# -*- coding: utf-8 -*-
# Python 3
"""
vavoo.py - Vavoo Live-TV fuer xStream.

Seit dem 04.11.2026 auf Vavoos eigener Live-Schnittstelle (mhub, zwei
GET-Abrufe, siehe auth.py). Aufbau:
  - HTTP ueber xStreams cRequestHandler (keine Abhaengigkeit von 'requests')
  - Wiedergabe wie in hoster.py: ListItem(path) + HLS-MIME-Typ + Header-Pipe;
    HLS laeuft ueber InputStream Adaptive, wenn dieses Addon aktiv ist
    (player.applyIsa), sonst ueber Kodis nativen Player (kein ffmpegdirect)
  - Das Backend steht in auth.py (Backend-Wechsel nur dort)
  - Kein Favoriten-System (bewusst weggelassen)

Menueablauf:
  vavootv (Hauptmenuepunkt)  ->  show_channels (die Sender von GROUP)  ->  play

Cache:
  - Senderliste von GROUP: 20 min gueltig
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

from resources.lib.handler.requestHandler import cRequestHandler, ERR_TIMEOUT, ERR_URL, REQUEST_ERRORS
from resources.lib.config import cConfig
from resources.lib.logger import logger
from resources.lib.player import cPlayer, applyIsa
from resources.lib.vavoo import auth


# =============================================================================
# KONSTANTEN
# =============================================================================

SITE_NAME = 'vavootv'

API_BASE_URL = auth.BASE_URL

# Die eine Sendergruppe, die das Addon zeigt (seit dem 04.10.2026 nur deutsches
# Fernsehen, die Laenderliste davor ist raus). Begruendete Ausnahme von der Regel
# "nichts hartkodieren": der Wert ist die exakte Schreibweise des Gruppenfilters
# im Katalog des Anbieters, und der Filter achtet auf Gross-/Kleinschreibung ("germany",
# "GERMANY" und "Deutschland" liefern 0 Sender, gemessen 04.10.2026). Benennt
# der Anbieter die Gruppe um, kommt beim Klick genau ein Fenster "Keine Sender
# gefunden", bis dieser Wert nachgezogen ist.
GROUP = "Germany"

# Praefix der Window-Properties (RAM-Ebene des Caches), Namensraum wie der Rest
# des Addons: xstream.<Bereich>.<Schluessel>. Fenster 10000 teilen sich alle
# Addons; die Datei-Ebene unter <profile>/vavoo/ bleibt davon unberuehrt.
PROP_PREFIX = "xstream.vavoo."

# Kein zweiter Versuch nach einem Lese-Timeout (der erste hat schon den
# Abruf-Timeout des requestHandlers gekostet, Einstellung requestTimeout — ein
# zweiter verdoppelt nur die Wartezeit, bevor der Nutzer die Meldung sieht) und
# nicht nach 404/410 (unbekannte Senderkennung bzw. Schnittstelle weg, gemessen
# 04.11.2026: ein unbekannter Resolve antwortet 404 — da hilft keine Wiederholung).
# Als Strings, weil getStatus() einen String liefert (seit dem 02.11.2026 in jedem Zweig).
NO_RETRY_STATUS = ('-1', '404', '410')

# Kurze Pause vor dem Wiederholungsversuch. Gemessen am 31.08.2026 gegen den
# Katalog der alten Schnittstelle: 5 Fehlschlaege in 25 Abrufen, davon 4 durch
# einen sofortigen zweiten Versuch gerettet.
RETRY_DELAY_MS = 500

home = xbmcgui.Window(10000)

# Globaler Sender-Cache je Aufruf (Name -> [urls]) zum Nachschlagen beim Abspielen.
_channels_cache = None


# Katalog oder Resolve haben nicht geliefert (Status im Text). Erbt von
# ConnectionError wie frueher, die Aufrufer melden es dem Nutzer selbst — der
# requestHandler laeuft hier still (ignoreErrors), bis dahin hat niemand geredet.
class VavooRequestError(ConnectionError):
    """Katalog- oder Resolve-Abruf gescheitert — dem Nutzer noch nicht gemeldet."""


# =============================================================================
# PLUGIN- UND ADRESS-HELFER
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
    """Plugin-Adresse fuer den Rueckruf an den vavootv-Verteiler bauen."""
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
# DATEI-/RAM-CACHE  (Window-Properties + JSON-Dateien im Addon-Profil)
# =============================================================================

_legacy_cache_checked = False


def _drop_legacy_cache_dir(profile):
    """Den alten vavoo_cache/-Ordner einmalig entfernen.

    Inhalt ist reiner Cache und wird beim naechsten Abruf in vavoo/ neu
    angelegt — es geht nichts verloren. Ein Fehler beim Loeschen wird nur geloggt.
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
    """<profile>/vavoo — der Ordner des Moduls (Senderlisten-Cache; bis zum 04.11.2026 lag hier auch die
    Geraete-Identity device.json des alten Backends, die bleibt bei Bestandsinstallationen liegen)."""
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

    Der Schluessel traegt den Gruppennamen in der Schreibweise des Anbieters
    (heute die Konstante GROUP) und landet direkt im Dateinamen; ein
    Schraegstrich oder eine Punktfolge darin wuerde die Datei ausserhalb des
    Cache-Ordners ablegen. Auf Windows sind Doppelpunkte und Sternchen als
    Dateiname ohnehin unzulaessig.
    """
    return re.sub(r'[^A-Za-z0-9._-]', '_', str(key))


def _set_cache(key, value, timeout=False):
    """Wert ablegen. timeout=False -> dauerhaft; sonst Sekunden bis zum Ablauf."""
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
    """Gecachten Wert liefern, wenn vorhanden und nicht abgelaufen, sonst None."""
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
# HTTP  (alles ueber cRequestHandler)
# =============================================================================

def _api_get(url, params, _retry=True):
    """Katalog- oder Resolve-Endpunkt des Backends (auth.py) per GET abrufen und
    das JSON auswerten; hoechstens ein Wiederholungsversuch nach kurzer Pause
    (keiner nach einem Lese-Timeout oder einem 404/410, siehe NO_RETRY_STATUS).

    Gibt das ausgewertete JSON-Objekt zurueck. Wirft VavooRequestError
    (ConnectionError), wenn das Backend keine brauchbare Antwort liefert.
    """
    oRequest = auth.apply(cRequestHandler(url + '?' + urlencode(params), caching=False, ignoreErrors=True))
    result = oRequest.requestJson()   # fetch()-Modus des Browser-Profils; None bei Fehler oder ohne JSON
    status = oRequest.getStatus()

    if not isinstance(result, dict):
        if _retry and str(status) not in NO_RETRY_STATUS:
            # Aussetzer auf Serverseite (5xx, 400) oder eine Antwort ohne JSON: ein
            # zweiter Anlauf lohnt (gemessen 31.08.2026 an der alten Schnittstelle:
            # 5 Fehlschlaege in 25 Abrufen, 4 davon beim sofortigen zweiten Versuch
            # durchgekommen); nach einem Timeout nicht (NO_RETRY_STATUS).
            logger.info("[vavoo] catalog/resolve failed (status=%s) — retrying once" % status)
            xbmc.sleep(RETRY_DELAY_MS)
            return _api_get(url, params, _retry=False)
        logger.error("[vavoo] catalog/resolve failed (status=%s), giving up" % status)
        raise VavooRequestError("Request failed (status=%s)" % status)

    return result


# =============================================================================
# SENDERNAMEN VEREINHEITLICHEN
# =============================================================================

def _normalize_channel_name(name):
    """Endungen der Stream-Varianten abschneiden, damit Dubletten zusammenfallen.

    Katalog: "RTL .b" / "RTL .c" / "RTL .s" -> "RTL" (14.10.2026, Seite 1: .b 168,
    .c 99, .s 33)   |   aeltere Form: "RTL (1)" -> "RTL"
    """
    normalized = name.strip()
    normalized = re.sub(r'\s+\.[a-zA-Z]+$', '', normalized)
    normalized = re.sub(r'\s+\(\d+\)$', '', normalized)
    return normalized


# =============================================================================
# SENDER ABRUFEN
# =============================================================================

def _fetch_channels_page(group, cursor=None):
    """Eine einzelne Seite Sender einer Gruppe abrufen (Katalog-API)."""
    # Eine Seite = 300 Eintraege, weiter geht es ueber nextCursor (Text '300',
    # '600', ...; die letzte Seite kommt ohne) — gemessen 22.10. und 04.11.2026.
    params = {auth.GROUP_PARAM: group}
    if cursor is not None:
        params[auth.CURSOR_PARAM] = cursor
    return _api_get(auth.CATALOG_URL, params)


def _collect_channels(group, channels):
    """Alle Sender einer Gruppe ueber die Katalog-API sammeln (seitenweise)."""
    cursor = None
    page_num = 0
    max_pages = 100
    seen_cursors = set()

    while page_num < max_pages:
        page_num += 1
        response = _fetch_channels_page(group, cursor)
        items = response.get("items")
        if not isinstance(items, list):
            items = []
        next_cursor = response.get("nextCursor")
        logger.debug("[vavoo] catalog page %d: %d items, nextCursor=%s (group=%s)" % (
            page_num, len(items), next_cursor, group))
        if not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            raw_name = str(item.get("name") or "").strip()
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
    """Sender einer Gruppe. Nutzt den 20-min-Datei-Cache und fuellt den globalen Cache."""
    global _channels_cache

    cache_key = "channels_live_%s" % group
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

    # Nur nicht-leere Ergebnisse cachen: eine leere Liste ist ein Fehlschlag
    # (unbekannter Gruppenname — 200 mit 0 Eintraegen, gemessen 04.11.2026 mit
    # "germany"), keine echte leere Gruppe.
    if channels:
        _set_cache(cache_key, channels, 1200)   # 20 min

    if _channels_cache is None:
        _channels_cache = {}
    _channels_cache.update(channels)
    return channels


def refresh_group_cache(group):
    """Sender-Cache einer Gruppe leeren, damit neu abgerufen wird."""
    global _channels_cache
    _clear_cache("channels_live_%s" % group)
    _channels_cache = None


# =============================================================================
# STREAM AUFLOESEN
# =============================================================================

def _follow_stream_url(url):
    """Einer aufgeloesten Adresse ueber Weiterleitungen bis zur endgueltigen
    Stream-Adresse folgen.

    Einfache Zwischen- und Werbeseiten (HTML) werden uebersprungen: ist die
    Antwort HTML, wird daraus eine .m3u8 gezogen. Nach bestem Bemuehen: sonst
    bleibt es bei der urspruenglichen Adresse. Gibt (None, headers) zurueck,
    wenn die Adresse gar nicht antwortet (Timeout, keine Verbindung) oder mit
    einem Serverfehler (5xx) — siehe den Kommentar an diesem Zweig.
    """
    # Der Abspiel-Kopfsatz: die Browser-Kennung des Profils wie bei den API-Abrufen
    # (Vorabruf hier, Player ueber die Pipe bzw. die ISA-Properties)
    stream_headers = {
        'User-Agent': cRequestHandler.RandomUA(),
        'Accept': '*/*',
    }
    try:
        oRequest = cRequestHandler(url, caching=False, ignoreErrors=True)
        oRequest.addHeaderEntry('Accept', '*/*')
        started = time.time()
        content = oRequest.request()
        status = str(oRequest.getStatus())
        # Eine Zeile je Vorabruf mit Status und Dauer: das Verhalten der Edge-Server
        # wechselt stuendlich (ARD auf 193.47.62.157 antwortete am 26.10.2026 fast
        # den ganzen Vormittag mit 500, zwischendurch mit 200), und nur das Log
        # zeigt hinterher, ob die Adresse oder der Player gescheitert ist.
        logger.info("[vavoo] stream pre-check: status %s after %.1f s" % (status, time.time() - started))
        if content in (ERR_TIMEOUT, ERR_URL) or (content in REQUEST_ERRORS and status.startswith('5')):
            # Gar keine Antwort (Timeout, keine Verbindung) oder ein Serverfehler:
            # der Player wuerde an derselben Adresse nur scheitern — mit
            # InputStream Adaptive bis zu einer halben Minute bei schwarzem Bild,
            # und ein Stopp in dieser Wartezeit hing bei neueren Kodi-Versionen.
            # Gemessen 20.10.2026: ein Edge-Server hielt den Abruf 30 s fest und
            # antwortete dann mit 502, waehrend andere Sender auf demselben
            # Edge-Server sofort antworteten. Gemessen 26.10.2026: derselbe
            # Edge-Server antwortete fuer einen Sender stundenlang sofort mit 500
            # — der Player zeigte dann nur Kodis eigenes Fenster, und nichts sagte,
            # welchen Stream man nehmen soll. Deshalb zaehlt ein 5xx als keine
            # Antwort, mit unserer Meldung (30855/30856). 4xx bleibt wie bisher
            # beim Player, der scheitert daran schnell. Der requestHandler hat
            # die Adresse schon geloggt.
            logger.error("[vavoo] stream address gave no answer (status %s), not starting the player" % status)
            return None, stream_headers
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


def resolve_link(link):
    """Sender-Link zu einem abspielbaren Paar (url, headers) aufloesen; url ist
    None, wenn die Stream-Adresse nicht antwortet (_follow_stream_url)."""
    # Die Antwort ist ein Objekt {format, live, name, url} (gemessen 22.10. und
    # 04.11.2026), die Adresse fuehrt per _follow_stream_url zur .m3u8. Referer und
    # Origin auf die Seite des Backends wie bei einem Browser, der von dort spielt.
    result = _api_get(auth.RESOLVE_URL, {auth.RESOLVE_PARAM: link})
    resolved_url = result.get("url")
    if not isinstance(resolved_url, str) or not resolved_url.strip():
        logger.error("[vavoo] resolve without stream address (keys=%s)" % sorted(result))
        raise VavooRequestError("Resolve without url")
    resolve_headers = result.get("headers")

    final_url, stream_headers = _follow_stream_url(resolved_url)

    if isinstance(resolve_headers, dict):
        stream_headers.update(resolve_headers)
    stream_headers["Referer"] = API_BASE_URL + "/"
    stream_headers["Origin"] = API_BASE_URL

    return final_url, stream_headers


# =============================================================================
# STREAM-AUSWAHL (OBERFLAECHE)
# =============================================================================

def _select_stream(name, urls):
    """Stream waehlen. Gibt (index, title) zurueck; index -1 == abgebrochen."""
    stream_count = len(urls)
    if stream_count <= 1:
        return 0, name
    options = [_L(30866) % i for i in range(1, stream_count + 1)]
    dialog_index = xbmcgui.Dialog().select(name, options)
    if dialog_index < 0:
        return -1, None
    return dialog_index, "%s (%s/%s)" % (name, dialog_index + 1, stream_count)


# =============================================================================
# VERZEICHNISLISTEN
# =============================================================================

def _add_dir(label, isFolder=True, **params):
    """Ordner- bzw. Menueeintrag zum Verzeichnis dieses Aufrufs hinzufuegen."""
    listitem = xbmcgui.ListItem(label)
    listitem.setArt({'icon': 'DefaultFolder.png'})
    try:
        listitem.getVideoInfoTag().setPlot(' ')
    except Exception:
        pass
    xbmcplugin.addDirectoryItem(_handle(), _url(**params), listitem, isFolder)


def show_channels(params):
    """Oberste Ebene von Vavoo TV: die Sender von GROUP. Oben steht der rote
    Eintrag zum Aktualisieren."""
    group = GROUP
    xbmcplugin.setContent(_handle(), "videos")

    try:
        results = getchannels_by_group(group)
    except Exception as e:
        # Noch hat niemand gemeldet (der requestHandler laeuft still): ohne das
        # Fenster klickte der Nutzer, und es passierte sichtbar gar nichts
        # (31.08.2026, Katalog antwortete 400).
        logger.error("[vavoo] failed to load channels for %s: %s" % (group, e))
        _error_dialog(_L(30851), _L(30852) % group)
        xbmcplugin.endOfDirectory(_handle(), succeeded=False)
        return

    if not results:
        _error_dialog(_L(30851), _L(30852) % group)
        xbmcplugin.endOfDirectory(_handle(), succeeded=False)
        return

    # Roter Aktualisieren-Eintrag (nur, wenn die Sender geladen wurden).
    _add_dir("[COLOR red]%s[/COLOR]" % _L(30865), isFolder=True,
             function="refresh_channels")

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
    """Senderliste von GROUP mit Fortschrittsanzeige frisch abrufen, dann neu laden."""
    group = GROUP

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
# WIEDERGABE  (Kodi-Player; HLS ueber InputStream Adaptive, wenn dieses Addon
#              aktiv ist — player.applyIsa —, sonst nativ, kein ffmpegdirect)
# =============================================================================

def _build_play_path(url, headers):
    """Kopfzeilen in Kodis Pipe-Schreibweise an die Stream-Adresse haengen."""
    if not headers:
        return url
    return url + '|' + urlencode(headers)


def play(params):
    """Sender aufloesen und abspielen (InputStream Adaptive, wenn aktiv, sonst nativ)."""
    name = params.getValue('name')
    if name:
        from urllib.parse import unquote_plus
        name = unquote_plus(name)
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
        _error_dialog(_L(30855), _L(30856))
        return

    progress.close()

    # None: die Stream-Adresse hat nicht geantwortet (_follow_stream_url) — kein
    # Playerstart, die Meldung sagt, einen anderen Stream zu nehmen oder die
    # Liste zu aktualisieren.
    if not resolved_url:
        _error_dialog(_L(30855), _L(30856))
        return

    play_path = _build_play_path(resolved_url, resolved_headers)
    display_title = "%s (%s/%s)" % (name, stream_index + 1, total) if total > 1 else name

    listitem = xbmcgui.ListItem(display_title, path=play_path)
    # Nativer Kodi-Player: Kodi das Format nennen, damit es HLS direkt demuxt.
    if '.m3u8' in resolved_url:
        listitem.setMimeType('application/vnd.apple.mpegurl')
        listitem.setContentLookup(False)
    # HLS ueber InputStream Adaptive, wenn es aktiv ist; die Kopfzeilen wandern
    # dann aus der Pipe in die ListItem-Properties.
    _path, use_isa = applyIsa(listitem, play_path)
    try:
        vtag = listitem.getVideoInfoTag()
        vtag.setMediaType('video')
        vtag.setTitle(display_title)
        vtag.setPlot('[B]%s[/B] - %s' % (name, _L(30867) % (stream_index + 1, total)))
    except Exception:
        pass
    listitem.setProperty("IsPlayable", "true")

    xbmcplugin.setResolvedUrl(_handle(), True, listitem)
    if use_isa:
        # Neueres ISA zeigt ein eigenes, blockierendes Fehlerfenster, solange der
        # Player noch oeffnet (toter Sender); startPlayer schliesst es. Nur bis
        # zum ersten Bild warten: ein Warten bis zum Ende der Wiedergabe hielte
        # beim Umschalten jedes Skript am Leben (gemessen 15.10.2026). Die native
        # Wiedergabe bleibt wie bisher, ohne Warten.
        cPlayer().startPlayer(isa=True, untilAv=True)


# =============================================================================
# AUFRUFE VERTEILEN
# =============================================================================

def dispatch(function, params):
    """Einen vavootv-Rueckruf an die passende Funktion weiterleiten.

    Alles ohne eigenen Zweig landet in der Senderliste: der Hauptmenuepunkt
    ('load'), alte Favoriten auf 'channelsbycategory' und die frueheren
    Laender-Funktionen.
    """
    if function == 'refresh_channels':
        refresh_channels(params)
    elif function == 'play':
        play(params)
    else:
        show_channels(params)
