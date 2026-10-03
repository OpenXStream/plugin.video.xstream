# -*- coding: utf-8 -*-
# Python 3
"""
vavoo.py - Vavoo live TV for xStream.

Ported from the Oracle 3.6 addon (vjlive/vjackson) into xStream:
  - HTTP via xStream's cRequestHandler (no 'requests' dependency)
  - Playback via Kodi's native player (no inputstream.ffmpegdirect):
    ListItem(path) + HLS mime type + header pipe, exactly like hoster.py
  - Backend/auth lives in auth.py (switch backend there only)
  - No favorites system (intentionally dropped)

Menu flow:
  vavootv (main-menu entry)  ->  show_countries  ->  show_channels  ->  play

Caching (kept from Oracle):
  - country/group list: permanent, also serves as fallback (see get_available_countries)
  - per-group channel list: 20 min TTL
"""

import os
import re
import sys
import shutil
import json
import time

import xbmc
import xbmcgui
import xbmcplugin
import xbmcvfs

from urllib.parse import urlencode, quote_plus

from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.config import cConfig
from resources.lib.logger import logger
from resources.lib.vavoo import auth


# =============================================================================
# CONSTANTS
# =============================================================================

SITE_NAME = 'vavootv'

REQUEST_TIMEOUT = 10
API_BASE_URL = auth.CATALOG_BASE

# Country/group list, stored permanently. Doubles as the fallback when the
# catalog answers without its filter description (see get_available_countries).
GROUPS_CACHE_KEY = "group_list"

# Prefix der Window-Properties (RAM-Ebene des Caches), Namensraum wie der Rest
# des Addons: xstream.<Bereich>.<Schluessel>. Fenster 10000 teilen sich alle
# Addons; die Datei-Ebene unter <profile>/vavoo/ bleibt davon unberuehrt.
PROP_PREFIX = "xstream.vavoo."

# Status, bei denen ein zweiter Versuch mit frischer Signatur sinnvoll ist. Alles
# andere (400 Validation error, 5xx Ueberlast, Timeout -1) liegt am Server und
# wird von einem neuen Ping nicht besser. Als Strings, weil getStatus() je nach
# Zweig einen String liefert.
AUTH_RETRY_STATUS = ('401', '403', '500')

# Kein zweiter Versuch nach einem Lese-Timeout: der erste hat schon
# REQUEST_TIMEOUT Sekunden gekostet, ein zweiter verdoppelt nur die Wartezeit,
# bevor der Nutzer die Meldung sieht.
NO_RETRY_STATUS = ('-1',)

# Kurze Pause vor dem Wiederholungsversuch. Gemessen am 31.08.2026 gegen den
# echten Katalog: 5 Fehlschlaege in 25 Abrufen, davon 4 durch einen sofortigen
# zweiten Versuch OHNE neuen Ping gerettet.
RETRY_DELAY_MS = 500

home = xbmcgui.Window(10000)

# Global per-invocation channel cache (name -> [urls]) for playback lookups.
_channels_cache = None


# Zwei Fehlerarten, die frueher beide als ConnectionError herauskamen und deshalb
# nicht zu unterscheiden waren. Beide erben von ConnectionError, damit bestehende
# Aufrufer unveraendert weiterlaufen.
#   VavooAuthError    - der Ping ist gescheitert. get_signature() hat dem Nutzer
#                       bereits einen Dialog gezeigt (30845/30846 bzw. 30847/30848),
#                       der Aufrufer darf also NICHT nochmal melden.
#   VavooRequestError - der Ping lief, der Katalog/Resolve hat abgelehnt. Hier hat
#                       noch niemand etwas gesagt, der Aufrufer MUSS melden.
class VavooAuthError(ConnectionError):
    """Auth ping failed — a dialog has already been shown."""


class VavooRequestError(ConnectionError):
    """Catalog/resolve request failed — nobody has told the user yet."""


# =============================================================================
# PLUGIN / URL HELPERS
# =============================================================================

def _handle():
    try:
        return int(sys.argv[1])
    except Exception:
        return -1


def _base():
    try:
        return sys.argv[0]
    except Exception:
        return ''


def _url(**params):
    """Build a plugin callback URL for the vavootv dispatcher."""
    params['site'] = SITE_NAME
    return _base() + '?' + urlencode(params)


def _L(string_id):
    """Lokalisierten String holen (Kurzform fuer cConfig().getLocalizedString)."""
    return cConfig().getLocalizedString(string_id)


def _notify(message, heading=None, error=False):
    if heading is None:
        heading = _L(30842)
    icon = xbmcgui.NOTIFICATION_ERROR if error else xbmcgui.NOTIFICATION_INFO
    xbmcgui.Dialog().notification(heading, message, icon)


def _error_dialog(heading, message):
    xbmcgui.Dialog().ok(heading, message)


# =============================================================================
# FILE/MEMORY CACHE  (window props + JSON files under the addon profile)
# =============================================================================

_legacy_cache_checked = False


def _drop_legacy_cache_dir(profile):
    """Den alten vavoo_cache/-Ordner einmalig entfernen.

    Inhalt ist reiner Cache und wird beim naechsten Abruf in vavoo/ neu
    angelegt — es geht nichts verloren. Fail-soft.
    """
    global _legacy_cache_checked
    if _legacy_cache_checked:
        return
    _legacy_cache_checked = True
    old = os.path.join(profile, 'vavoo_cache')
    if not os.path.isdir(old):
        return
    try:
        shutil.rmtree(old)
        logger.info("[vavoo] removed legacy cache dir vavoo_cache")
    except OSError as e:
        logger.error("[vavoo] could not remove legacy cache dir: %s" % e)


def _cache_dir():
    """<profile>/vavoo — derselbe Ordner, in dem auth.py die device.json ablegt."""
    profile = xbmcvfs.translatePath(cConfig().getAddonInfo('profile'))
    path = os.path.join(profile, 'vavoo')
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except OSError:
            pass
    _drop_legacy_cache_dir(profile)
    return path


def _safe_key(key):
    """Cache-Schluessel auf unbedenkliche Zeichen reduzieren.

    Der Schluessel enthaelt bei Sendergruppen den Gruppennamen aus dem Katalog
    des Anbieters — also Fremddaten. Er landet direkt im Dateinamen, und ein
    Schraegstrich oder Punktfolge darin wuerde die Datei ausserhalb des
    Cache-Ordners ablegen. Auf Windows sind Doppelpunkte und Sternchen als
    Dateiname ohnehin unzulaessig.
    """
    return re.sub(r'[^A-Za-z0-9._-]', '_', str(key))


def _set_cache(key, value, timeout=False):
    """Store a value. timeout=False -> permanent; else seconds until expiry."""
    expiry = False if timeout is False else int(time.time()) + timeout
    payload = json.dumps({"exp": expiry, "value": value})
    home.setProperty(PROP_PREFIX + key, payload)
    filepath = os.path.join(_cache_dir(), _safe_key(key) + ".json")
    tmp = filepath + ".tmp"
    try:
        with open(tmp, "w") as f:
            f.write(payload)
        os.replace(tmp, filepath)
    except Exception as e:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        logger.error("[vavoo] failed to write cache %s: %s" % (key, e))


def _get_cache(key):
    """Return a cached value if present and unexpired, else None."""
    now = int(time.time())

    cached = home.getProperty(PROP_PREFIX + key)
    if cached:
        try:
            data = json.loads(cached)
            exp = data.get("exp", 0)
            if exp is False or exp > now:
                return data.get("value")
            home.clearProperty(PROP_PREFIX + key)
        except (ValueError, TypeError):
            home.clearProperty(PROP_PREFIX + key)

    filepath = os.path.join(_cache_dir(), _safe_key(key) + ".json")
    try:
        with open(filepath) as f:
            data = json.load(f)
        exp = data.get("exp", 0)
        if exp is False or exp > now:
            value = data.get("value")
            home.setProperty(PROP_PREFIX + key, json.dumps({"exp": exp, "value": value}))
            return value
        os.remove(filepath)
    except (FileNotFoundError, json.JSONDecodeError, IOError, OSError):
        pass
    return None


def _clear_cache(key):
    home.clearProperty(PROP_PREFIX + key)
    try:
        filepath = os.path.join(_cache_dir(), _safe_key(key) + ".json")
        if os.path.exists(filepath):
            os.remove(filepath)
    except OSError:
        pass


# =============================================================================
# HTTP  (all via cRequestHandler)
# =============================================================================

def _catalog_post(url, data_dict, _retry=True):
    """POST JSON to an auth-signed catalog/resolve endpoint; one auth-retry.

    Returns parsed JSON. Raises ConnectionError on unrecoverable failure.
    """
    signature = auth.get_signature()
    if not signature:
        raise VavooAuthError("Authentication failed")

    oRequest = cRequestHandler(url, caching=False, ignoreErrors=True,
                               method='POST', data=json.dumps(data_dict))
    oRequest.addHeaderEntry('User-Agent', auth.CATALOG_UA)
    oRequest.addHeaderEntry('Accept', 'application/json')
    oRequest.addHeaderEntry('Accept-Language', 'de')
    oRequest.addHeaderEntry('Content-Type', 'application/json; charset=utf-8')
    oRequest.addHeaderEntry(auth.SIG_HEADER, signature)

    content = oRequest.request()
    status = oRequest.getStatus()

    try:
        result = json.loads(content)
    except Exception:
        result = None

    if result is None:
        if _retry:
            if str(status) in AUTH_RETRY_STATUS:
                # Eine frische Signatur hilft nur, wenn der Server die alte
                # beanstandet hat. Gemessen am 31.08.2026 gegen vavoo.to: eine
                # kaputte Signatur wird mit HTTP 500 ("Malformed MediaHubMX
                # signature") abgelehnt. Vorher lief der Ping bei JEDEM Fehler
                # mit und hat im Log vom 31.08. jeden Aufruf verdoppelt, ohne
                # dass ein einziger Versuch dadurch durchkam.
                logger.info("[vavoo] catalog/resolve failed (status=%s) — refreshing auth and retrying" % status)
                if auth.refresh():
                    return _catalog_post(url, data_dict, _retry=False)
            elif str(status) not in NO_RETRY_STATUS:
                # Aussetzer auf Serverseite (400 Validation error, 503 Ueberlast).
                # Da hilft kein neuer Ping, aber sehr wohl ein zweiter Anlauf:
                # gemessen 31.08.2026, 5 Fehlschlaege in 25 Abrufen, 4 davon beim
                # sofortigen zweiten Versuch durchgekommen.
                logger.info("[vavoo] catalog/resolve failed (status=%s) — retrying once without a new ping" % status)
                xbmc.sleep(RETRY_DELAY_MS)
                return _catalog_post(url, data_dict, _retry=False)
        logger.error("[vavoo] catalog/resolve failed (status=%s), giving up" % status)
        raise VavooRequestError("Request failed (status=%s)" % status)

    return result


# =============================================================================
# CHANNEL NAME NORMALIZATION
# =============================================================================

def _normalize_channel_name(name):
    """Strip stream-variant suffixes so duplicates merge.

    Catalog: "RTL .s" / "RTL .b" -> "RTL"   |   older form: "RTL (1)" -> "RTL"
    """
    normalized = name.strip()
    normalized = re.sub(r'\s+\.[a-zA-Z]+$', '', normalized)
    normalized = re.sub(r'\s+\(\d+\)$', '', normalized)
    return normalized


# =============================================================================
# COUNTRIES
# =============================================================================

def _extract_groups(response):
    """Read the group filter's own value list out of a catalog response.

    The catalog describes the filters it accepts under features.filter; the
    entry with id "group" carries the exact spellings its group filter matches.
    That list is what we want, because the filter is case-SENSITIVE: a name
    taken from channel data instead (a stray "GERMANY" next to the real
    "Germany") yields a country entry that resolves to nothing at all.

    Returns a list of names, or [] when the field is absent.
    """
    features = response.get("features")
    if not isinstance(features, dict):
        return []
    for entry in features.get("filter") or []:
        if not isinstance(entry, dict) or entry.get("id") != "group":
            continue
        values = entry.get("values") or []
        return [v.strip() for v in values if isinstance(v, str) and v.strip()]
    return []


def _fetch_groups():
    """Ask the catalog for the values its group filter accepts.

    Any catalog response carries the filter description, so this is the same
    request the channel list makes, only without a group. Returns [] on failure.
    """
    data = {
        "language": "de",
        "region": "AT",
        "catalogId": auth.CATALOG_ID,
        "id": auth.CATALOG_ID,
        "adult": False,
        "search": "",
        "sort": "name",
        "filter": {},
        "cursor": 0,
        "count": 9999,
        "clientVersion": auth.CLIENT_VERSION,
    }
    url = "%s/%s" % (API_BASE_URL, auth.CATALOG_ENDPOINT)
    try:
        return _extract_groups(_catalog_post(url, data))
    except Exception as e:
        logger.error("[vavoo] failed to fetch group list: %s" % e)
        return []


def _store_groups(countries):
    """Sort a freshly fetched group list and keep it permanently."""
    countries.sort()
    _set_cache(GROUPS_CACHE_KEY, countries, False)   # permanent
    logger.debug("[vavoo] %s countries from catalog filter" % len(countries))


def get_available_countries(use_cache=True):
    """Country/region list, taken from the catalog's own group filter."""
    if use_cache:
        cached = _get_cache(GROUPS_CACHE_KEY)
        if cached:
            logger.debug("[vavoo] returning cached country list (%s)" % len(cached))
            return cached

    countries = _fetch_groups()
    if countries:
        _store_groups(countries)
        return countries

    # Request failed, or the catalog answered without describing its filters.
    # The last known list is a far better answer than an empty menu, so it is
    # deliberately NOT cleared before a refresh — a fresh list overwrites it.
    previous = _get_cache(GROUPS_CACHE_KEY)
    if previous:
        logger.info("[vavoo] no group filter in catalog reply, keeping known country list")
        return previous

    _error_dialog(_L(30849), _L(30850))
    return []


# =============================================================================
# CHANNEL FETCHING
# =============================================================================

def _fetch_channels_page(group, cursor=0):
    """Fetch a single page of channels for a group (catalog API)."""
    data = {
        "language": "de",
        "region": "AT",
        "catalogId": auth.CATALOG_ID,
        "id": auth.CATALOG_ID,
        "adult": False,
        "search": "",
        "sort": "name",
        "filter": {"group": group},
        "cursor": cursor,
        "count": 9999,
        "clientVersion": auth.CLIENT_VERSION,
    }
    url = "%s/%s" % (API_BASE_URL, auth.CATALOG_ENDPOINT)
    return _catalog_post(url, data)


def _collect_channels(group, channels):
    """Collect all channels for a group via the catalog API (paginated)."""
    cursor = 0
    page_num = 0
    max_pages = 100
    seen_cursors = set()

    while page_num < max_pages:
        page_num += 1
        response = _fetch_channels_page(group, cursor)
        items = response.get("items", [])
        next_cursor = response.get("nextCursor")
        logger.debug("[vavoo] catalog page %d: %d items, nextCursor=%s (group=%s)" % (
            page_num, len(items), next_cursor, group))
        if not items:
            break

        for item in items:
            raw_name = item.get("name", "").strip()
            item_url = item.get("url")
            if not item_url or not raw_name:
                continue
            normalized_name = _normalize_channel_name(raw_name)
            if normalized_name not in channels:
                channels[normalized_name] = []
            if item_url not in channels[normalized_name]:
                channels[normalized_name].append(item_url)

        if next_cursor is None or next_cursor in ("", 0, "null"):
            break
        cursor_key = str(next_cursor)
        if cursor_key in seen_cursors:
            break
        seen_cursors.add(cursor_key)
        cursor = next_cursor

    if page_num >= max_pages:
        logger.info("[vavoo] hit max pages limit for group '%s'" % group)


def getchannels_by_group(group):
    """Channels for a group. Uses 20-min file cache + populates global cache."""
    global _channels_cache

    cache_key = "channels_group_%s" % group
    cached = _get_cache(cache_key)
    if cached:
        logger.debug("[vavoo] cached channels for '%s' (%s)" % (group, len(cached)))
        if _channels_cache is None:
            _channels_cache = {}
        _channels_cache.update(cached)
        return cached

    channels = {}
    _collect_channels(group, channels)
    logger.info("[vavoo] group=%s collected=%d distinct channels" % (group, len(channels)))

    # Empty-result fallback: 0 channels likely = expired/cold signature (200 + empty items).
    if not channels:
        logger.info("[vavoo] 0 channels — refreshing auth and retrying once")
        if auth.refresh():
            _collect_channels(group, channels)
            logger.info("[vavoo] retry after auth refresh: %s channels" % len(channels))

    # Only cache non-empty results (empty == likely auth failure, not a real empty group).
    if channels:
        _set_cache(cache_key, channels, 1200)   # 20 min

    if _channels_cache is None:
        _channels_cache = {}
    _channels_cache.update(channels)
    return channels


def refresh_group_cache(group):
    """Clear channel cache for a group so it re-fetches."""
    global _channels_cache
    _clear_cache("channels_group_%s" % group)
    _channels_cache = None


# =============================================================================
# STREAM RESOLUTION
# =============================================================================

def _follow_stream_url(url, timeout=REQUEST_TIMEOUT):
    """Follow a resolved URL through redirects to the final stream URL.

    Bypasses simple interstitial/ad HTML pages by extracting an .m3u8 if the
    response turns out to be HTML. Best-effort: falls back to the original URL.
    """
    stream_headers = {
        'User-Agent': auth.CATALOG_UA,
        'Accept': '*/*',
    }
    try:
        oRequest = cRequestHandler(url, caching=False, ignoreErrors=True)
        oRequest.addHeaderEntry('User-Agent', auth.CATALOG_UA)
        oRequest.addHeaderEntry('Accept', '*/*')
        content = oRequest.request()
        final_url = oRequest.getRealUrl() or url

        head = (content or "")[:2000].lower()
        if '<html' in head or '<!doctype html' in head:
            m3u8_matches = re.findall(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', content)
            if m3u8_matches:
                final_url = m3u8_matches[0]
            else:
                stream_matches = re.findall(
                    r'(https?://[^\s"\'<>]+(?:\.ts|/live/|/stream/|/playlist|/index)[^\s"\'<>]*)', content)
                if stream_matches:
                    final_url = stream_matches[0]

        return final_url, stream_headers
    except Exception as e:
        logger.error("[vavoo] follow stream URL failed, using original: %s" % e)
        return url, stream_headers


def resolve_link(link, timeout=REQUEST_TIMEOUT):
    """Resolve a channel link to a playable (url, headers) pair."""
    url = "%s/%s" % (API_BASE_URL, auth.RESOLVE_ENDPOINT)
    data = {
        "language": "de",
        "region": "AT",
        "url": link,
        "clientVersion": auth.CLIENT_VERSION,
    }

    result = _catalog_post(url, data)
    resolved_url = result[0]["url"]
    resolve_headers = result[0].get("headers", {})

    signature = auth.get_signature()

    final_url, stream_headers = _follow_stream_url(resolved_url, timeout=timeout)

    if resolve_headers:
        stream_headers.update(resolve_headers)
    if signature:
        stream_headers[auth.SIG_HEADER] = signature
    stream_headers["Referer"] = API_BASE_URL + "/"
    stream_headers["Origin"] = API_BASE_URL

    return final_url, stream_headers


# =============================================================================
# STREAM SELECTION UI
# =============================================================================

def _select_stream(name, urls):
    """Pick a stream. Returns (index, title); index -1 == cancelled."""
    stream_count = len(urls)
    if stream_count <= 1:
        return 0, name
    options = [_L(30866) % i for i in range(1, stream_count + 1)]
    dialog_index = xbmcgui.Dialog().select(name, options)
    if dialog_index < 0:
        return -1, None
    return dialog_index, "%s (%s/%s)" % (name, dialog_index + 1, stream_count)


# =============================================================================
# DIRECTORY LISTINGS
# =============================================================================

def _add_dir(label, isFolder=True, **params):
    """Add a folder/menu entry to the current listing."""
    listitem = xbmcgui.ListItem(label)
    listitem.setArt({'icon': 'DefaultFolder.png'})
    try:
        listitem.getVideoInfoTag().setPlot(' ')
    except Exception:
        pass
    xbmcplugin.addDirectoryItem(_handle(), _url(**params), listitem, isFolder)


def show_countries(params=None):
    """Top level of Vavoo TV: list of countries/regions (loaded directly)."""
    xbmcplugin.setContent(_handle(), "files")

    countries = get_available_countries()
    if not countries:
        xbmcplugin.endOfDirectory(_handle(), succeeded=False)
        return

    # Red refresh entry on top.
    _add_dir("[COLOR red]%s[/COLOR]" % _L(30864), isFolder=True, function="refresh_countries")

    for country in countries:
        _add_dir(country, isFolder=True, function="channelsbycategory", group=country)

    xbmcplugin.endOfDirectory(_handle(), cacheToDisc=False)


def refresh_countries(params=None):
    """Force-refresh the country list with progress, then reload cleanly."""
    progress = xbmcgui.DialogProgress()
    progress.create(_L(30842), _L(30860))
    progress.update(30)

    # No pre-clear: a successful fetch overwrites the cache. Clearing first
    # would throw away the entry that serves as fallback for show_countries
    # exactly when the refresh fails.
    progress.update(70, _L(30862))
    # Ask the catalog directly instead of get_available_countries(): that
    # reader keeps the last known list when the catalog fails, and a refresh
    # must not report success for a list that did not come from the catalog.
    try:
        countries = _fetch_groups()
        success = bool(countries)
        if success:
            _store_groups(countries)
    except Exception:
        success = False

    progress.update(100)
    progress.close()

    xbmcplugin.endOfDirectory(_handle(), succeeded=False)
    xbmc.executebuiltin("Action(ParentDir)")
    xbmc.sleep(300)

    if success:
        _notify(_L(30857))
        xbmc.executebuiltin("Container.Refresh")
    else:
        _notify(_L(30859), error=True)


def show_channels(params):
    """List channels for a group/country. Red refresh entry on top."""
    group = params.getValue('group') or "Germany"
    xbmcplugin.setContent(_handle(), "videos")

    try:
        results = getchannels_by_group(group)
    except VavooAuthError as e:
        # Der Ping ist gescheitert, get_signature() hat den Dialog schon gezeigt.
        # Hier NICHT nochmal melden, sonst stehen zwei Fenster uebereinander.
        logger.error("[vavoo] failed to load channels for %s: %s" % (group, e))
        xbmcplugin.endOfDirectory(_handle(), succeeded=False)
        return
    except Exception as e:
        # Alles andere hat noch niemand gemeldet. Frueher lief dieser Zweig stumm,
        # weil der Kommentar hier annahm, get_signature() habe bereits geredet -
        # das gilt aber nur fuer den Ping. Am 31.08.2026 lief der Ping sauber
        # durch und der Katalog antwortete mit 400: der Nutzer klickte auf ein
        # Land und es passierte sichtbar gar nichts.
        logger.error("[vavoo] failed to load channels for %s: %s" % (group, e))
        _error_dialog(_L(30851), _L(30852) % group)
        xbmcplugin.endOfDirectory(_handle(), succeeded=False)
        return

    if not results:
        _error_dialog(_L(30851), _L(30852) % group)
        xbmcplugin.endOfDirectory(_handle(), succeeded=False)
        return

    # Red refresh entry (only when channels loaded successfully).
    _add_dir("[COLOR red]%s[/COLOR]" % _L(30865), isFolder=True,
             function="refresh_channels", group=group)

    entries = []
    for name, urls in results.items():
        name = name.strip()
        count = len(urls)
        title = "%s  (%s)" % (name, count) if count > 1 else name
        listitem = xbmcgui.ListItem(title)
        listitem.setArt({'icon': 'DefaultTVShows.png'})
        try:
            vtag = listitem.getVideoInfoTag()
            vtag.setMediaType('video')
            vtag.setTitle(title)
            vtag.setPlot(' ')
        except Exception:
            pass
        listitem.setProperty("IsPlayable", "true")
        callback = _url(function="play", name=quote_plus(name), urls=quote_plus(json.dumps(urls)))
        entries.append((callback, listitem, False))

    xbmcplugin.addDirectoryItems(_handle(), entries, len(entries))
    xbmcplugin.addSortMethod(_handle(), xbmcplugin.SORT_METHOD_VIDEO_TITLE)
    xbmcplugin.endOfDirectory(_handle())


def refresh_channels(params):
    """Force-refresh a group's channel list with progress, then reload."""
    group = params.getValue('group') or "Germany"

    progress = xbmcgui.DialogProgress()
    progress.create(_L(30842), _L(30861) % group)
    progress.update(30)

    refresh_group_cache(group)

    progress.update(70, _L(30862))
    try:
        channels = getchannels_by_group(group)
        success = bool(channels)
    except Exception:
        success = False

    progress.update(100)
    progress.close()

    xbmcplugin.endOfDirectory(_handle(), succeeded=False)
    xbmc.executebuiltin("Action(ParentDir)")
    xbmc.sleep(300)

    if success:
        _notify(_L(30858) % group)
        xbmc.executebuiltin("Container.Refresh")
    else:
        _notify(_L(30859), error=True)


# =============================================================================
# PLAYBACK  (native Kodi player — no inputstream.ffmpegdirect)
# =============================================================================

def _build_play_path(url, headers):
    """Append request headers to the stream URL using Kodi's pipe syntax."""
    if not headers:
        return url
    return url + '|' + urlencode(headers)


def play(params):
    """Resolve and play a channel via Kodi's native player."""
    name = params.getValue('name')
    if name:
        from urllib.parse import unquote_plus
        name = unquote_plus(name)
    group = params.getValue('group')
    group = group if group else None

    urls = None
    urls_param = params.getValue('urls')
    if urls_param:
        try:
            from urllib.parse import unquote_plus
            urls = json.loads(unquote_plus(urls_param))
        except (json.JSONDecodeError, TypeError, ValueError):
            urls = None

    if urls is None:
        if _channels_cache is not None and name in _channels_cache:
            urls = _channels_cache[name]
        elif group:
            try:
                group_channels = getchannels_by_group(group)
                urls = group_channels.get(name)
            except Exception as e:
                logger.error("[vavoo] failed to fetch group %s: %s" % (group, e))
                return
        if not urls:
            _error_dialog(_L(30853), _L(30854) % name)
            return

    stream_index, _title = _select_stream(name, urls)
    if stream_index == -1:
        return

    total = len(urls)

    progress = xbmcgui.DialogProgress()
    progress.create(_L(30842), _L(30863) % name)
    progress.update(50)

    try:
        resolved_url, resolved_headers = resolve_link(urls[stream_index])
    except Exception as e:
        progress.close()
        logger.error("[vavoo] failed to resolve stream %s: %s" % (stream_index + 1, e))
        if "Authentication failed" not in str(e):
            _error_dialog(_L(30855), _L(30856))
        return

    progress.close()

    if not resolved_url:
        _error_dialog(_L(30855), _L(30856))
        return

    play_path = _build_play_path(resolved_url, resolved_headers)
    display_title = "%s (%s/%s)" % (name, stream_index + 1, total) if total > 1 else name

    listitem = xbmcgui.ListItem(display_title, path=play_path)
    # Native Kodi player: tell Kodi the format so it demuxes HLS directly.
    if '.m3u8' in resolved_url:
        listitem.setMimeType('application/vnd.apple.mpegurl')
        listitem.setContentLookup(False)
    try:
        vtag = listitem.getVideoInfoTag()
        vtag.setMediaType('video')
        vtag.setTitle(display_title)
        vtag.setPlot('[B]%s[/B] - %s' % (name, _L(30867) % (stream_index + 1, total)))
    except Exception:
        pass
    listitem.setProperty("IsPlayable", "true")

    xbmcplugin.setResolvedUrl(_handle(), True, listitem)


# =============================================================================
# DISPATCH
# =============================================================================

def dispatch(function, params):
    """Route a vavootv callback to the right handler."""
    if function in ('load', 'show_countries', '', False, None):
        show_countries(params)
    elif function == 'refresh_countries':
        refresh_countries(params)
    elif function == 'channelsbycategory':
        show_channels(params)
    elif function == 'refresh_channels':
        refresh_channels(params)
    elif function == 'play':
        play(params)
    else:
        show_countries(params)


# Entry point used by the main-menu element (site=vavootv&function=load).
def load():
    from resources.lib.handler.parameterHandler import ParameterHandler
    show_countries(ParameterHandler())
