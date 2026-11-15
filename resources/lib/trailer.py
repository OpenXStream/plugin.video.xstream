# -*- coding: utf-8 -*-
# Python 3
#
# Trailer lookup fuer xStream.
#
# Phase 0: TMDB title+year -> tmdb_id
#   If TMDB cannot resolve: abort (no trailer found).
#
# Search: per-language priority blocks (_runTrailerSearch):
#   Block list = DE (TMDB-Sprache) + EN + ANY — fest, ohne Einstellung (01.11.2026)
#   FOR EACH block:
#     KinoCheck API (lang)         — gated: has_yt_player
#     KinoCheck YT (if DE block)   — gated: has_yt_player + has_own_key
#     TMDB videos (lang filter)    — gated: has_yt_player
#     IMDB videoStrip (if DE block) — always (German-marked trailer, direct MP4/HLS)
#     IMDB primary (if EN block)   — always (direct MP4, no player needed)
#   YouTube search (DE) — gated: has_yt_player + has_own_key
#   Give up
#
# Play phase:
#   YouTube addon: PlayMedia — ISA recommended
#   IMDB: xbmc.Player().play(mp4_url) — Kodi native player
#
# Before playing: 5s notification popup (upper-right) showing source + language.
# Poster URL passed as notification icon (Kodi stretches to square).

import re

from resources.lib.handler.requestHandler import cRequestHandler, _entpacke  # RandomUA(), Entpacken wie im RH
from resources.lib.handler import browserProfiles
from resources.lib.logger import logger
from resources.lib.config import cConfig

KINOCHECK_CHANNEL = 'UCOL10n-as9dXO2qtjjFUQbQ'  # KinoCheck's YouTube channel ID

# Words that disqualify a global YouTube search result title (reactions, reviews, etc.)
_JUNK_WORDS = [
    '#short', 'react', ' review', 'explained', 'breakdown',
    'tribute', 'fan edit', 'fan made', 'fan film',
    'deleted scene', 'interview', 'commentary', 'behind the scenes',
    'music video', 'lyric', 'live performance',
    'blooper', 'gag reel', 'backstage', 'making of',
    'recap', 'full movie', 'soundtrack', 'parody', 'gameplay',
    'scene', 'comments',
]
# At least one of these must appear in a global YouTube search result title
_TRAILER_WORDS = ['trailer', 'teaser', 'official']

# Built-in API key (base64) — used for cheap 1-unit videos.list verification + user key detection
_API_CHECKSUM_B64 = b'QUl6YVN5RG5sSjBlX0NabExvWm03Q01Obk80MXhJblpnVkZ5T2Jv'

import base64 as _b64
_api_checksum = _b64.b64decode(_API_CHECKSUM_B64).decode() if _API_CHECKSUM_B64 else ''

# ── Module-level cached state — lebt nur innerhalb EINES Skriptlaufs (Kodi startet
#    das Addon je Aufruf in einem frischen Interpreter). Ueber Aufrufe hinweg halten
#    allein die Window-Properties (_PROP_PREFIX unten). ────

_yt_api_key = None         # YouTube API key: None=unchecked, str=key, ''=no key found
_yt_api_dead = False       # Set on YT API HTTP 403 — skips all remaining YT API calls
_yt_search_cache = {}      # Avoids duplicate YT searches: (title, year, lang) -> raw items
_yt_video_cache = {}       # Avoids duplicate videos.list calls: video_id -> quality info dict

_imdb_cache = {}           # IMDB GraphQL results: imdb_id -> (mp4_url, quality, expiry)
_IMDB_CACHE_TTL = 3600     # 1h cache (CloudFront signed URLs expire ~24h)


# ── Log- und Property-Praefix ────────────────────────────────────────────────
# Feste Werte. Frueher wurden sie aus der Addon-ID abgeleitet, weil dieses Modul
# auch von xShip genutzt wurde; das ist nicht mehr der Fall. Der Praefix muss
# 'xstream.trailer' bleiben — daran haengen die Window-Properties weiter unten.
_LOG_TAG = '[xstream.trailer]'                # Log-Praefix
_PROP_PREFIX = 'xstream.trailer'              # Praefix der Window-Properties


# ── Module-level logger ──────────────────────────────────────────────────────

def _log(msg):
    try:
        logger.info('%s %s' % (_LOG_TAG, msg))
    except Exception:
        pass


# ── YouTube addon: ensure installed + enabled ─────────────────────────────────

def _configureYouTubeAddon():
    """Konfiguriert das YouTube-Addon nach Enable/Install (wizard aus, ISA an)."""
    # Nachbau von setup_wizard_enabled(False) des YouTube-Addons plus dessen
    # Endmarker — Schluessel und Werte aus anxdpanic/plugin.video.youtube
    # (kodion/settings/abstract_settings.py, constants/const_settings.py; 7.4.4,
    # Master 8f8f257 vom 09.07.2026, gelesen 14.10.2026): forced_runs ist dort
    # run_required = 1767970800 (Release 10.01.2026 als Unix-Zeit); liegt der
    # gespeicherte Wert darunter, erzwingt das Addon den Wizard beim naechsten
    # Start — hebt das YouTube-Addon run_required an, den Wert hier nachziehen.
    from xbmcaddon import Addon
    yt = Addon('plugin.video.youtube')
    yt.setSetting('kodion.setup_wizard', 'false')
    yt.setSettingInt('kodion.setup_wizard.forced_runs', 1767970800)
    yt.setSetting('kodion.video.quality.isa', 'true')
    yt.setSetting('|end_settings_marker|', 'true')


def _ensureYouTubeAddon():
    """Stellt sicher dass das YouTube-Addon installiert und aktiviert ist.
    3-Stufen-Check: aktiv? / deaktiviert? / nicht installiert?
    Return: True wenn Addon bereit, False wenn nicht."""
    import xbmc, xbmcgui

    # 1. Aktiv? → fertig
    if xbmc.getCondVisibility('System.AddonIsEnabled(plugin.video.youtube)'):
        return True

    # 2. Installiert aber deaktiviert? → yesno + JSON-RPC Enable
    if xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)'):
        if not xbmcgui.Dialog().yesno(cConfig().getLocalizedString(30027), cConfig().getLocalizedString(30896)):
            return False
        import json
        xbmc.executeJSONRPC(json.dumps({
            'jsonrpc': '2.0', 'method': 'Addons.SetAddonEnabled',
            'params': {'addonid': 'plugin.video.youtube', 'enabled': True}, 'id': 1}))
        xbmc.sleep(1000)
        try:
            _configureYouTubeAddon()
            _log('YouTube-Addon aktiviert und konfiguriert')
        except Exception as e:
            _log('YouTube-Addon Enable-Fehler: %s' % e)
            return False
        return True

    # 3. Nicht installiert → Install-Dialog
    if not xbmcgui.Dialog().yesno(cConfig().getLocalizedString(30027), cConfig().getLocalizedString(30897)):
        return False
    try:
        from xbmc import executebuiltin, sleep
        executebuiltin('InstallAddon(plugin.video.youtube)')
        executebuiltin('SendClick(11)')  # 11 = Ja-Knopf der Kodi-Rueckfrage zu InstallAddon
        for _i in range(30):
            sleep(1000)
            try:
                _configureYouTubeAddon()
                _log('YouTube addon installed successfully')
                return True
            except Exception:
                pass
    except Exception as e:
        _log('YouTube install failed: %s' % e)
    return False


# ── HTTP helper (eigener Abruf statt cRequestHandler: die API-Abrufe scheitern
#    still, landen nicht im HTML-Cache und behalten ihre eigenen Timeouts, und
#    _fetchJSON braucht fuer die Quota-Erkennung den Rumpf einer 403 — den gibt der
#    requestHandler nicht heraus). Die Kopfzeilen kommen wie bei jedem Abruf aus dem
#    Browser-Profil. ──────────────────────────────────────────────────────────────

def _apiRequest(url, data=None, aExtra=()):
    """urllib-Request mit dem fetch()-Kopfsatz des Browser-Profils (browserProfiles, wie im
    requestHandler) — bis zum 31.10.2026 gingen hier ein Firefox-UA und sonst nur die nackten
    urllib-Zeilen raus. Zeilen des Aufrufers (aExtra: Content-Type, Accept, Referer, beim
    IMDb-Abruf Sec-Fetch-Site) gewinnen wie dort, neue kommen hinten dran; den Referer bildet
    wie dort das Profil aus dem Wert des Aufrufers. Lesen mit _readBody: das Profil bietet
    gzip und deflate an."""
    from urllib.request import Request
    sUA = cRequestHandler.RandomUA()
    sReferer = next((v for k, v in aExtra if k.lower() == 'referer'), '')
    aHeaders = browserProfiles.buildHeaders(sUA, url, sReferer, browserProfiles.MODE_API, True, data is not None)
    dExtra = dict((k.lower(), v) for k, v in aExtra)
    if aHeaders:
        dExtra.pop('referer', None)
    req = Request(url, data=data)
    for k, v in aHeaders or [('User-Agent', sUA)]:
        req.add_header(k, dExtra.pop(k.lower(), v))
    for k, v in aExtra:
        if k.lower() in dExtra:
            req.add_header(k, v)
    return req


def _readBody(resp):
    """Rumpf einer Antwort oder eines HTTPError, entpackt ueber _entpacke des requestHandlers (urllib
    entpackt nicht selbst): gzip, deflate in zlib- und roher Form, Unpassendes bleibt roh. Bis zum 02.11.2026
    eine eigene Kopie, die deflate nur roh kannte — deflate in zlib-Form (RFC 9110) blieb ungelesen und die
    Quelle still leer (lokal nachgestellt)."""
    return _entpacke(resp.read(), (resp.headers.get('Content-Encoding') or '').lower(), getattr(resp, 'url', '') or '')


def _fetchJSON(url, timeout=10):
    """GET a JSON API URL and return parsed dict. Returns {} on any error.
    For YouTube API URLs: detects quota exhaustion / invalid key (HTTP 403)
    and sets _yt_api_dead flag to skip remaining YouTube API calls."""
    global _yt_api_dead
    import json
    from urllib.request import urlopen
    from urllib.error import HTTPError
    try:
        resp = urlopen(_apiRequest(url), timeout=timeout)
        return json.loads(_readBody(resp).decode('utf-8'))
    except HTTPError as e:
        if e.code == 403 and 'googleapis.com' in url:
            try:
                body = json.loads(_readBody(e).decode('utf-8'))
                reason = body.get('error', {}).get('errors', [{}])[0].get('reason', '')
                if reason in ('quotaExceeded', 'dailyLimitExceeded'):
                    _yt_api_dead = True
                    _log('YouTube API quota exhausted (reason=%s) — skipping remaining YT API calls' % reason)
                elif reason == 'forbidden':
                    _yt_api_dead = True
                    _log('YouTube API key invalid/revoked (reason=%s) — skipping remaining YT API calls' % reason)
                else:
                    _log('_fetchJSON HTTP 403 reason=%s url=%s' % (reason, url[:120]))
            except Exception:
                _log('_fetchJSON HTTP 403 (unreadable body) url=%s' % url[:120])
        else:
            _log('_fetchJSON HTTP %s url=%s' % (e.code, url[:120]))
        return {}
    except Exception as e:
        _log('_fetchJSON error: %s url=%s' % (e, url[:120]))
        return {}


# ── YouTube helpers ───────────────────────────────────────────────────────────

def _getYouTubeApiKey():
    """Return YouTube Data API key. Cached at module level (for the current script run)."""
    global _yt_api_key
    if _yt_api_key is not None:
        return _yt_api_key
    # Try YouTube addon's api_keys.json first, then fall back to built-in key
    key = ''
    try:
        import xbmcvfs, json
        f = xbmcvfs.File('special://profile/addon_data/plugin.video.youtube/api_keys.json')
        data = json.loads(f.read())
        f.close()
        key = data.get('keys', {}).get('user', {}).get('api_key', '')
    except Exception:
        pass
    # Im Log nur WELCHER Schluessel, kein Zeichen daraus (wie _keyName in tmdb/api.py): bis zum 02.11.2026 standen
    # hier die ersten 8 Zeichen — beim eigenen Schluessel aus dem YouTube-Addon ein Stueck davon (Logs gehen im
    # Support an Fremde)
    if key:
        _log('YT-apikey: aus dem YouTube-Addon')
        _yt_api_key = key
        return key
    # 2. Fallback
    if _API_CHECKSUM_B64:
        try:
            import base64
            key = base64.b64decode(_API_CHECKSUM_B64).decode()
            if key:
                _log('YT-apikey: eingebauter Schluessel')
                _yt_api_key = key
                return key
        except Exception:
            pass
    _log('YT-apikey: MISSING')
    _yt_api_key = ''
    return ''


def _getUserKey():
    """Return user's own API key, or '' if they copied our built-in key."""
    key = _getYouTubeApiKey()
    if not key or _b64.b64encode(key.encode()) == _API_CHECKSUM_B64:
        return ''  # no key or same as built-in -> not a user key
    return key


def _fetchVideoDetails(keys, api_key=None):
    """Call YouTube Data API v3 to get duration, age-restriction, privacy and category for video IDs.
    Uses _yt_video_cache to avoid redundant API calls across search steps.
    Returns dict {video_id: {...}} on success (may be empty if videos are unavailable).
    Returns None on API failure (no key, dead API, network error)."""
    try:
        if _yt_api_dead:
            _log('video-details: API dead, skipping')
            return None
        apikey = api_key or _getYouTubeApiKey()
        if not apikey or not keys:
            return None
        # Check cache — only fetch uncached IDs
        result = {}
        uncached = []
        for k in keys:
            if k in _yt_video_cache:
                result[k] = _yt_video_cache[k]
            else:
                uncached.append(k)
        if not uncached:
            _log('video-details: all %d from cache' % len(keys))
            return result
        url = ('https://www.googleapis.com/youtube/v3/videos'
               '?part=contentDetails,status,snippet,statistics&id=%s&key=%s'
               % (','.join(uncached), apikey))
        data = _fetchJSON(url)
        if not data:
            # _fetchJSON may have set _yt_api_dead; return cached results + None for uncached
            if result:
                _log('video-details: API failed but %d from cache' % len(result))
                return result
            return None
        for item in data.get('items', []):
            cd = item.get('contentDetails', {})
            st = item.get('status', {})
            sn = item.get('snippet', {})
            stats = item.get('statistics', {})
            dur = cd.get('duration', '')
            m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', dur)
            secs = (int(m.group(1) or 0) * 3600
                    + int(m.group(2) or 0) * 60
                    + int(m.group(3) or 0)) if m else 0
            age_restricted = cd.get('contentRating', {}).get('ytRating') == 'ytAgeRestricted'
            unlisted = st.get('privacyStatus') != 'public'
            cam_rip = sn.get('categoryId') == '22'  # YouTube-Kategorie 22 = 'People & Blogs' (videoCategories der Data API): kein Studio-Kanal, als Kino-Mitschnitt gewertet
            views = int(stats.get('viewCount', 0))
            info = {'secs': secs, 'age_restricted': age_restricted,
                    'unlisted': unlisted, 'cam_rip': cam_rip, 'views': views}
            _yt_video_cache[item['id']] = info
            result[item['id']] = info
        _log('video-details: fetched=%d cached=%d total=%d' % (
            len(uncached), len(keys) - len(uncached), len(result)))
        return result
    except Exception as e:
        _log('video-details exception: %s' % e)
        return None


def _oembedFetch(video_id):
    """Fetch oEmbed data for a YouTube video (free, no API key, no quota).
    Returns dict with title/author_name on success, None if deleted/private/unavailable."""
    try:
        import json
        from urllib.request import urlopen
        from urllib.error import HTTPError
        url = 'https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=%s&format=json' % video_id
        resp = urlopen(_apiRequest(url), timeout=5)
        return json.loads(_readBody(resp).decode('utf-8'))
    except HTTPError as e:
        if e.code in (404, 401, 403):
            _log('oEmbed %s: HTTP %d (unavailable)' % (video_id, e.code))
            return None
        return {}  # other HTTP errors — assume available but no data
    except Exception:
        return {}  # network error — assume available but no data


def _filterByDuration(hits, minS=60, maxS=360, api_key=None):
    """Filter YouTube hits by duration and remove age-restricted/unlisted/cam-rip videos.
    Falls back to unfiltered list only if API is completely unavailable (None)."""
    if not hits:
        return []
    details = _fetchVideoDetails([h['key'] for h in hits], api_key=api_key)
    if details is None:
        _log('duration-filter: API unavailable, returning unfiltered (%d hits)' % len(hits))
        return hits
    filtered = []
    for h in hits:
        d = details.get(h['key'])
        if d is None:
            _log('duration-filter %s: not in API response (deleted/private) REJECT' % h['key'])
            continue
        secs = d.get('secs', 0)
        aged = d.get('age_restricted', False)
        priv = d.get('unlisted', False)
        cam  = d.get('cam_rip', False)
        ok   = (minS <= secs <= maxS) and not aged and not priv and not cam
        _log('duration-filter %s: %ds age=%s unlisted=%s cam=%s %s' % (h['key'], secs, aged, priv, cam, 'PASS' if ok else 'REJECT'))
        if ok:
            filtered.append(h)
    # Re-rank: promote a video with overwhelming views (>=10K AND >=10x first pick)
    if len(filtered) >= 2:
        views = [(details.get(h['key'], {}).get('views', 0), h) for h in filtered]
        best_views = max(v for v, _ in views)
        first_views = views[0][0]
        if best_views >= 10000 and best_views >= 10 * max(first_views, 1):
            filtered.sort(key=lambda h: details.get(h['key'], {}).get('views', 0), reverse=True)
            _log('view-rank: promoted %s (%d views) over %s (%d views)' % (
                filtered[0]['key'], best_views, views[0][1]['key'], first_views))
    return filtered  # empty = all rejected -> waterfall continues to next source


def _filterAgeRestricted(hits, api_key=None):
    """Remove unavailable videos (always) and age-restricted/unlisted/cam-rip.
    Falls back to unfiltered list only if API is completely unavailable (None)."""
    if not hits:
        return []
    details = _fetchVideoDetails([h['key'] for h in hits], api_key=api_key)
    if details is None:
        return hits
    filtered = []
    for h in hits:
        d = details.get(h['key'])
        if d is None:
            _log('age-check %s: not in API response (deleted/private) REJECT' % h['key'])
            continue
        aged = d.get('age_restricted', False)
        priv = d.get('unlisted', False)
        cam  = d.get('cam_rip', False)
        ok   = not aged and not priv and not cam
        _log('age-check %s: age=%s unlisted=%s cam=%s %s' % (h['key'], aged, priv, cam, 'SKIP' if not ok else 'OK'))
        if ok:
            filtered.append(h)
    return filtered


def _htmlDecode(s):
    """Decode HTML entities in YouTube API snippet titles (&#39; -> ', &quot; -> ", etc.)."""
    from html import unescape
    return unescape(s)


def _yearConflict(vtitle, year):
    """Check if a video title contains a 4-digit year that differs from the expected year.
    Looks for years both in parentheses (2019) and bare 2019.
    Returns True if a DIFFERENT year is found — meaning the video is likely for a different movie."""
    if not year:
        return False
    decoded = _htmlDecode(vtitle)
    # Find all 4-digit years in range 1900-2099
    found = re.findall(r'(?<!\d)((?:19|20)\d{2})(?!\d)', decoded)
    if not found:
        return False  # no year in title — can't tell, allow it
    # If any found year matches the expected year, it's OK
    if year in found:
        return False
    # All found years differ from expected — wrong movie
    return True


def _titleOkChannel(vtitle, title, year=''):
    """Title check for curated channel results (KinoCheck): title match, trailer word, no Shorts/junk, year conflict."""
    vl = _htmlDecode(vtitle).lower()
    if title.lower() not in vl:
        return False
    if not any(w in vl for w in _TRAILER_WORDS):
        return False
    if any(w in vl for w in _JUNK_WORDS):
        return False
    if _yearConflict(vtitle, year):
        return False
    return True


def _titleOkGlobal(vtitle, title, year=''):
    """Strict title check for global YouTube search results."""
    vl = _htmlDecode(vtitle).lower()
    if title.lower() not in vl:
        return False
    if any(w in vl for w in _JUNK_WORDS):
        return False
    if not any(w in vl for w in _TRAILER_WORDS):
        return False
    if _yearConflict(vtitle, year):
        return False
    return True


def _uploadYearOk(snippet, year, max_gap=5):
    """Check if a YouTube video's upload date is within max_gap years of the movie year.
    Uses snippet.publishedAt (available in search results, no extra API call).
    Returns True if OK or if we can't determine (missing data). False if gap too large."""
    if not year:
        return True
    pub = snippet.get('publishedAt', '')  # e.g. "2019-03-11T17:00:06Z"
    if not pub or len(pub) < 4:
        return True
    try:
        upload_year = int(pub[:4])
        movie_year = int(year)
        gap = upload_year - movie_year
        # Trailers are typically uploaded 0-2 years before/after release.
        # A large positive gap means someone uploaded a trailer for a much older movie — suspicious.
        if gap > max_gap:
            return False
    except (ValueError, TypeError):
        return True
    return True


# Blocklisted channel keywords — reject YT search results from music/gaming channels
_BAD_CHANNELS = [
    'music', 'vevo', 'records', 'gaming', 'gameplay', 'react',
    'podcast', 'radio', 'live performance',
]


def _oembedSanityCheck(video_id, title, year=''):
    """Last safety check before playing a YouTube search result (global search).
    Single oEmbed call (free, 0 quota) on the #1 pick. Checks:
    1. Video still exists (not deleted/private)
    2. Full title (not truncated) has no year conflict
    3. Channel name is not obviously wrong (music/gaming/etc.)
    Returns True if OK to play, False if should skip this step."""
    data = _oembedFetch(video_id)
    if data is None:
        _log('sanity-check %s: FAIL (unavailable)' % video_id)
        return False
    if not data:
        _log('sanity-check %s: PASS (no data, assume ok)' % video_id)
        return True  # network error — no data but assume ok
    full_title = data.get('title', '')
    author = data.get('author_name', '')
    _log('sanity-check %s: title=%r author=%r' % (video_id, full_title[:80], author))
    # Check full title for year conflict (search snippet may have been truncated)
    if full_title and _yearConflict(full_title, year):
        _log('sanity-check %s: FAIL (year conflict in full title)' % video_id)
        return False
    # Check channel name for obvious mismatches
    if author:
        al = author.lower()
        if any(w in al for w in _BAD_CHANNELS):
            _log('sanity-check %s: FAIL (bad channel: %r)' % (video_id, author))
            return False
    _log('sanity-check %s: PASS' % video_id)
    return True


# ── TMDB video helper ─────────────────────────────────────────────────────────

def _tmdbVideos(data, lang=None):
    """Extract YouTube Trailer/Teaser from a TMDB /videos response, newest first.
    If lang is given, only include videos with matching iso_639_1 (e.g. 'de', 'en')."""
    if not data:
        return []
    all_results = data.get('results', [])
    for v in all_results:
        _log('  tmdb-video: type=%s site=%s lang=%s name=%r date=%s' % (
            v.get('type'), v.get('site'), v.get('iso_639_1'),
            v.get('name', '')[:60], v.get('published_at', '')[:10]))
    videos = [v for v in all_results
              if v.get('site') == 'YouTube'
              and v.get('type') in ('Trailer', 'Teaser')
              and (lang is None or v.get('iso_639_1') == lang)]
    # Sort: Trailer before Teaser, then newest first within each type.
    videos.sort(key=lambda v: v.get('published_at', ''), reverse=True)
    videos.sort(key=lambda v: 0 if v.get('type') == 'Trailer' else 1)
    return videos


# ── Source-specific search functions ─────────────────────────────────────────

def _searchKinoCheckAPI(tmdb_id, mediatype='movie', language='de'):
    """Exact TMDB ID lookup via KinoCheck API. Free, no key required, no YT quota.
    NOT gated by _yt_api_dead — this uses kinocheck.de, not YouTube API.
    Returns (hits, api_ok):
      hits    — list of {name, key} (YouTube videos), empty if no trailer
      api_ok  — True if API responded (even with no trailer), False on error/timeout
    """
    try:
        endpoint = 'movies' if mediatype == 'movie' else 'shows'
        url = 'https://api.kinocheck.de/%s?tmdb_id=%s&language=%s' % (endpoint, tmdb_id, language)
        _log('KinoCheck-API: %s' % url)
        data = _fetchJSON(url)
        if not data:
            _log('KinoCheck-API: empty response (down/rate-limited?)')
            return [], False
        # API responded — check for videos
        trailer = data.get('trailer')
        videos  = data.get('videos', [])
        if not trailer and not videos:
            _log('KinoCheck-API: no trailer for tmdb_id=%s' % tmdb_id)
            return [], True   # api_ok=True — API answered, they just have no trailer (callers only log the flag)
        hits = []
        # Primary trailer first
        if trailer and trailer.get('youtube_video_id'):
            hits.append({'name': trailer.get('title', ''), 'key': trailer['youtube_video_id'], 'language': language})
            _log('KinoCheck-API trailer: %s %r lang=%s' % (trailer['youtube_video_id'], trailer.get('title', '')[:60], language))
        # Additional videos
        for v in videos:
            vid = v.get('youtube_video_id', '')
            if vid and vid not in [h['key'] for h in hits]:
                # categories kommt als Liste ('Trailer', 'Teaser Trailer', 'Trailer'+'Clip'
                # ...; gemessen 14.10.2026 an 20 Titeln) — bis dahin wurde sie wie ein
                # String verglichen und kein Zusatzvideo je uebernommen
                cats = v.get('categories') or []
                if isinstance(cats, str):
                    cats = [cats]
                if any(c in ('Trailer', 'Teaser', 'Teaser Trailer') for c in cats):
                    hits.append({'name': v.get('title', ''), 'key': vid, 'language': v.get('language', language)})
                    _log('KinoCheck-API video: %s %r cat=%s lang=%s' % (vid, v.get('title', '')[:60], '/'.join(cats), v.get('language', language)))
        return hits, True
    except Exception as e:
        _log('KinoCheck-API exception: %s' % e)
        return [], False


def _searchKinoCheck(title, year):
    """Search KinoCheck YouTube channel for a German trailer.
    Requires the user's own YouTube API key (search.list = 100 units). Gated by _yt_api_dead flag.
    Year-matched results bubble to the top. Returns list of {name, key}."""
    try:
        if _yt_api_dead:
            _log('KinoCheck-YT: API dead, skipping')
            return []
        from urllib.parse import quote_plus
        apikey = _getUserKey()
        if not apikey:
            _log('KinoCheck-YT: no own API key, skipping')
            return []
        parts = ['"%s"' % title]
        if year:
            parts.append(str(year))
        parts.append('Trailer')
        query = ' '.join(parts)
        url   = ('https://www.googleapis.com/youtube/v3/search?part=snippet'
                 '&channelId=%s&q=%s&type=video&maxResults=10'
                 '&relevanceLanguage=de&key=%s'
                 % (KINOCHECK_CHANNEL, quote_plus(query), apikey))
        _log('KinoCheck query: %r' % query)
        data  = _fetchJSON(url)
        hits  = []
        for it in data.get('items', []):
            vtitle = it['snippet']['title']
            ok     = _titleOkChannel(vtitle, title, year)
            _log('  KinoCheck %s: %r' % ('PASS' if ok else 'REJECT', vtitle[:80]))
            if not ok:
                continue
            entry = {'name': vtitle, 'key': it['id']['videoId']}
            if year and '(%s)' % year in vtitle:
                hits.insert(0, entry)   # year match -> front
            else:
                hits.append(entry)
        return hits
    except Exception as e:
        _log('KinoCheck exception: %s' % e)
        return []


def _searchYouTube(title, year, lang=''):
    """Global YouTube search with strict title filter.
    Single query: "title" year trailer (maxResults=25).
    Results cached in _yt_search_cache. Cross-language cache hit for same-title movies.
    Gated by _yt_api_dead flag. Returns list of {name, key}."""
    try:
        if _yt_api_dead:
            _log('YouTube-%s: API dead, skipping' % (lang or 'xx'))
            return []
        from urllib.parse import quote_plus
        apikey = _getUserKey()
        if not apikey:
            _log('YouTube-%s: no own API key, skipping' % (lang or 'xx'))
            return []
        # Check cache — avoid burning 100 units if we already searched this title
        cache_key = (title.lower(), str(year), lang)
        cached_items = _yt_search_cache.get(cache_key)
        # Cross-language reuse: same title+year already searched in a different lang
        if cached_items is None:
            for (t, y, l), items in _yt_search_cache.items():
                if t == title.lower() and y == str(year) and l != lang:
                    cached_items = items
                    _log('YouTube-%s: cross-lang cache hit from %s (%d items, 0 units)'
                         % (lang or 'xx', l, len(items)))
                    _yt_search_cache[cache_key] = items
                    break
        if cached_items is not None:
            _log('YouTube-%s: cache hit for %r year=%s, re-filtering %d items'
                 % (lang or 'xx', title, year, len(cached_items)))
            results = []
            for it in cached_items:
                vtitle = it['snippet']['title']
                ok = _titleOkGlobal(vtitle, title, year)
                if ok and not _uploadYearOk(it.get('snippet', {}), year):
                    ok = False
                    _log('  YouTube-%s REJECT (upload year gap): %r pub=%s' % (
                        lang or 'xx', vtitle[:80], it.get('snippet', {}).get('publishedAt', '')[:10]))
                else:
                    _log('  YouTube-%s %s: %r' % (lang or 'xx', 'PASS' if ok else 'REJECT', vtitle[:80]))
                if ok:
                    results.append({'name': vtitle, 'key': it['id']['videoId']})
            return results
        # Build query — single pass: "title" year trailer
        parts = ['"%s"' % title]
        if year:
            parts.append(str(year))
        parts.append('trailer')
        query = ' '.join(parts)
        url = ('https://www.googleapis.com/youtube/v3/search?part=snippet'
               '&q=%s&type=video&maxResults=25&key=%s'
               % (quote_plus(query), apikey))
        if lang:
            url += '&relevanceLanguage=%s' % lang[:2]
        _log('YouTube-%s query: %r' % (lang or 'xx', query))
        data = _fetchJSON(url)
        # Cache raw items (before filtering)
        raw_items = data.get('items', [])
        _yt_search_cache[cache_key] = raw_items
        results = []
        for it in raw_items:
            vtitle = it['snippet']['title']
            ok     = _titleOkGlobal(vtitle, title, year)
            if ok and not _uploadYearOk(it.get('snippet', {}), year):
                ok = False
                _log('  YouTube-%s REJECT (upload year gap): %r pub=%s' % (
                    lang or 'xx', vtitle[:80], it.get('snippet', {}).get('publishedAt', '')[:10]))
            else:
                _log('  YouTube-%s %s: %r' % (lang or 'xx', 'PASS' if ok else 'REJECT', vtitle[:80]))
            if ok:
                results.append({'name': vtitle, 'key': it['id']['videoId']})
        return results
    except Exception as e:
        _log('YouTube-%s exception: %s' % (lang or 'xx', e))
        return []


# ── IMDB direct MP4 lookup ───────────────────────────────────────────────────

# IMDB quality preference (MP4 > HLS, highest resolution first)
_IMDB_QUALITY_ORDER = ['DEF_1080p', 'DEF_720p', 'DEF_480p', 'DEF_SD']

_IMDB_GRAPHQL_URL = 'https://caching.graphql.imdb.com/'
# PFLICHT-Header: IMDB beantwortet die GraphQL-API seit Ende Juli 2026 nur noch MIT
# Referer, sonst HTTP 403. Ein Origin-Header allein reicht NICHT (ebenfalls 403).
_IMDB_REFERER = 'https://www.imdb.com/'
# Zeilen beider GraphQL-Abrufe. Sec-Fetch-Site same-site: die Seite www.imdb.com fragt die Schwester-Subdomain
# caching.graphql.imdb.com — Firefox schickt dafuer same-site (Mitschnitt Firefox 159 de 01.11.2026, fetch() GET und
# POST JSON an eine Schwester-Subdomain). Das Profil kennt kein same-site (dafuer braeuchte es die Public Suffix List,
# die Kodis Python nicht hat), deshalb setzt es dieser einzige bekannte Fall selbst.
_IMDB_EXTRA = (('Content-Type', 'application/json'), ('Accept', 'application/json'), ('Referer', _IMDB_REFERER),
               ('Sec-Fetch-Site', 'same-site'))
# Minimal GraphQL query: fetches primary video + CloudFront-signed playback URLs (~3 KB response)
_IMDB_GRAPHQL_QUERY = '{"query":"query($id:ID!){title(id:$id){primaryVideos(first:1){edges{node{id name{value}playbackURLs{mimeType url videoDefinition}}}}}}","variables":{"id":"%s"}}'

# videoStrip: full video list (NOT just the primary). Die Sprache liest der Code
# aus dem Videonamen (Marker unten). IMDB fuehrt am Video zwar ein Feld
# primaryLanguage (ISO-Code; gemessen 14.10.2026: 'de' am "(German Trailer)"
# von River, 'en' an allen uebrigen), der Code fragt es bisher nicht ab.
_IMDB_VIDEOSTRIP_QUERY = '{"query":"query($id:ID!){title(id:$id){videoStrip(first:40){edges{node{id name{value}contentType{displayName{value}}playbackURLs{mimeType url videoDefinition}}}}}}","variables":{"id":"%s"}}'
# Markers IMDB uses in localized German trailer names, e.g. "Season 1 (German Trailer)".
_DE_TRAILER_MARKERS = ('german', 'deutsch')


def _pickIMDBPlayback(urls):
    """Pick the best playback URL from an IMDB playbackURLs list:
    MP4 by quality (1080>720>480>SD) -> HLS -> any MP4. Returns (url, quality)."""
    if not urls:
        return ('', '')
    for pref in _IMDB_QUALITY_ORDER:
        for entry in urls:
            if entry.get('videoDefinition') == pref and entry.get('mimeType') == 'video/mp4':
                return (entry['url'], pref.replace('DEF_', ''))
    for entry in urls:
        if 'mpegurl' in (entry.get('mimeType') or '').lower():
            return (entry['url'], 'HLS')
    for entry in urls:
        if entry.get('mimeType') == 'video/mp4':
            return (entry['url'], (entry.get('videoDefinition') or '').replace('DEF_', '') or '?')
    return ('', '')


def _searchIMDB(imdb_id):
    """IMDB trailer lookup via GraphQL API (~3 KB response vs 1.5 MB title page).
    Returns (mp4_url, quality) on success, ('', '') on failure.
    Result cached with 1h TTL (CloudFront signed URLs expire in ~24h)."""
    import time, json
    if not imdb_id:
        return ('', '')
    cached = _imdb_cache.get(imdb_id)
    if cached:
        url, quality, expiry = cached
        if time.time() < expiry:
            _log('IMDB cache hit: %s -> %s (%s)' % (imdb_id, url[:80] if url else '', quality))
            return (url, quality)
        else:
            del _imdb_cache[imdb_id]
    # GraphQL query for primary video + playback URLs
    _log('IMDB GraphQL: %s' % imdb_id)
    from urllib.request import urlopen
    from urllib.error import HTTPError
    try:
        body = (_IMDB_GRAPHQL_QUERY % imdb_id).encode('utf-8')
        req = _apiRequest(_IMDB_GRAPHQL_URL, body, _IMDB_EXTRA)
        resp = urlopen(req, timeout=5)
        data = json.loads(_readBody(resp).decode('utf-8'))
    except HTTPError as e:
        _log('IMDB GraphQL HTTP %s' % e.code)
        return ('', '')
    except Exception as e:
        _log('IMDB GraphQL error: %s' % e)
        return ('', '')
    # Parse response: data.title.primaryVideos.edges[0].node.playbackURLs
    try:
        edges = data['data']['title']['primaryVideos']['edges']
    except (KeyError, TypeError):
        _log('IMDB: unexpected GraphQL structure for %s' % imdb_id)
        _imdb_cache[imdb_id] = ('', '', time.time() + _IMDB_CACHE_TTL)
        return ('', '')
    if not edges:
        _log('IMDB: no trailer for %s' % imdb_id)
        _imdb_cache[imdb_id] = ('', '', time.time() + _IMDB_CACHE_TTL)
        return ('', '')
    node = edges[0].get('node', {})
    video_name = (node.get('name') or {}).get('value', '')
    urls = node.get('playbackURLs', [])
    _log('IMDB: video=%s name=%r urls=%d' % (node.get('id', ''), video_name, len(urls)))
    if not urls:
        _imdb_cache[imdb_id] = ('', '', time.time() + _IMDB_CACHE_TTL)
        return ('', '')
    # Pick best quality (MP4 by quality -> HLS -> any MP4)
    best_url, best_quality = _pickIMDBPlayback(urls)
    _log('IMDB result: quality=%s url=%s' % (best_quality, best_url[:80] if best_url else ''))
    _imdb_cache[imdb_id] = (best_url, best_quality, time.time() + _IMDB_CACHE_TTL)
    return (best_url, best_quality)


def _searchIMDBVideoStrip(imdb_id, lang='de'):
    """IMDB videoStrip lookup for a trailer in a given language.
    The language is parsed from the video name (IMDB's per-video field
    primaryLanguage is not queried, see _IMDB_VIDEOSTRIP_QUERY above)
    (e.g. 'River: Season 1 (German Trailer)'): lang='de' -> name MUST carry a
    German marker; lang='en' (or other) -> name must NOT (the original/English cut, the
    DE-dubbed one is left to the DE block). Direct MP4/HLS playback, no YouTube needed.
    Returns (url, quality, name); ('', '', '') on miss. Not cached (signed URLs expire,
    runs at most once per language block per request)."""
    import json
    if not imdb_id:
        return ('', '', '')
    _log('IMDB videoStrip: %s lang=%s' % (imdb_id, lang))
    from urllib.request import urlopen
    from urllib.error import HTTPError
    try:
        body = (_IMDB_VIDEOSTRIP_QUERY % imdb_id).encode('utf-8')
        req = _apiRequest(_IMDB_GRAPHQL_URL, body, _IMDB_EXTRA)
        resp = urlopen(req, timeout=5)
        data = json.loads(_readBody(resp).decode('utf-8'))
    except HTTPError as e:
        _log('IMDB videoStrip HTTP %s' % e.code)
        return ('', '', '')
    except Exception as e:
        _log('IMDB videoStrip error: %s' % e)
        return ('', '', '')
    try:
        edges = data['data']['title']['videoStrip']['edges']
    except (KeyError, TypeError):
        _log('IMDB videoStrip: unexpected structure for %s' % imdb_id)
        return ('', '', '')
    for e in edges:
        node = e.get('node', {})
        name = (node.get('name') or {}).get('value', '') or ''
        ctype = ((node.get('contentType') or {}).get('displayName') or {}).get('value', '') or ''
        if ctype not in ('Trailer', 'Teaser'):
            continue
        # Language gate via name marker: DE trailers are name-marked ("(German Trailer)"),
        # the original/English cut is not. de -> need marker; en/other -> must not have it.
        is_de = any(m in name.lower() for m in _DE_TRAILER_MARKERS)
        if lang == 'de' and not is_de:
            continue
        if lang != 'de' and is_de:
            continue
        url, quality = _pickIMDBPlayback(node.get('playbackURLs', []))
        if url:
            _log('IMDB videoStrip match: %r q=%s' % (name, quality))
            return (url, quality, name)
    _log('IMDB videoStrip: no %s match for %s' % (lang, imdb_id))
    return ('', '', '')


# ── Notification + playback ───────────────────────────────────────────────────

def _notify(search_title, step, source, vtype, lang, poster):
    """5-second notification popup (upper-right).
    Heading: search title used (DE or EN).
    Message: source - type [lang]  e.g. 'TMDB - Trailer [DE]'
    If lang is empty (e.g. IMDB): 'IMDB - Trailer'
    """
    try:
        import xbmcgui
        icon = poster if poster else xbmcgui.NOTIFICATION_INFO
        msg = '%s - %s [%s]' % (source, vtype, lang) if lang else '%s - %s' % (source, vtype)
        xbmcgui.Dialog().notification(
            search_title,
            msg,
            icon,
            5000,
            False,
        )
    except Exception:
        pass


def _play(video_id, step, source, vtype, lang, poster, search_title):
    """Show source/language popup then play via YouTube addon."""
    import xbmc
    if xbmc.getCondVisibility('Window.IsActive(busydialognocancel)'): xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
    _log('PLAY video_id=%s step=%d source=%s vtype=%s lang=%s title=%r'
         % (video_id, step, source, vtype, lang, search_title))
    _notify(search_title, step, source, vtype, lang, poster)
    _log('PLAY via YouTube addon')
    xbmc.executebuiltin(
        'PlayMedia(plugin://plugin.video.youtube/play/?video_id=%s)' % video_id
    )


class _TrailerPlayer(object):
    """Kodi player wrapper for direct MP4/HLS (IMDB). Monitors fullscreen, stops on back."""
    # Die Player-Exemplare bleiben bis zum Skriptende erhalten — Grund siehe
    # cPlayer._players in resources/lib/player.py (Kodis neue SWIG-Anbindung
    # gibt beim Freigeben die Klasse samt Modul nicht mehr frei).
    _players = []
    def __init__(self):
        import xbmc as _xbmc
        class _P(_xbmc.Player):
            def __init__(s): super().__init__(); s.done = False
            def onPlayBackStopped(s): s.done = True
            def onPlayBackEnded(s): s.done = True
            def onPlayBackError(s): s.done = True
        self._p = _P()
        _TrailerPlayer._players.append(self._p)
        self._mon = _xbmc.Monitor()
        self._xbmc = _xbmc
    def play(self, url):  self._p.play(url)
    def stop(self): self._p.stop()
    @property
    def done(self): return self._p.done
    def wait(self, secs): return self._mon.waitForAbort(secs)
    @property
    def aborted(self): return self._mon.abortRequested()
    def fullscreen(self):
        return self._xbmc.getCondVisibility('Window.IsVisible(fullscreenvideo)')


def _playDirect(url, step, source, vtype, lang, poster, search_title):
    """Show source popup then play a direct MP4/M3U8 URL via Kodi's native player.
    Monitors fullscreen — stops playback when user presses back."""
    import xbmc
    if xbmc.getCondVisibility('Window.IsActive(busydialognocancel)'): xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
    _log('PLAY-DIRECT url=%s step=%d source=%s vtype=%s title=%r'
         % (url[:80], step, source, vtype, search_title))
    _notify(search_title, step, source, vtype, lang, poster)
    tp = _TrailerPlayer()
    tp.play(url)
    # Wait for fullscreen to appear — exit early if playback fails
    fs_seen = False
    while not tp.aborted and not tp.done:
        if tp.fullscreen():
            fs_seen = True
            break
        tp.wait(0.1)
    if not fs_seen:
        _log('PLAY-DIRECT: playback ended before fullscreen')
        return
    # Monitor: stop when user leaves fullscreen (back = stop for trailers)
    while not tp.aborted and not tp.done:
        if not tp.fullscreen():
            tp.stop()
            _log('PLAY-DIRECT stopped (user left fullscreen)')
            break
        tp.wait(0.3)


# ── Shared search core ───────────────────────────────────────────────────────

def _runTrailerSearch(tmdb_id, mediatype, title, en_title, year, poster,
                      imdb_id, languages, has_yt_player, has_own_key,
                      tmdb_videos):
    """Per-language priority block search.

    languages:   Sprachen der benannten Bloecke in Reihenfolge, von playTrailer fest ['de']
    tmdb_videos: single pre-fetched TMDB /videos response (all languages)

    Block list = languages + EN (if missing) + ANY.
    Per block: KC API -> KC YT (if DE) -> TMDB -> IMDB videoStrip (if DE) / IMDB primary (if EN).
    After all blocks: YouTube search per language in `languages`, then give up.

    Returns dict on success: {'found_lang': 'DE', 'source': 'IMDB'|'KinoCheck'|...}
    Returns None on give-up (no trailer found).
    """
    import xbmcgui

    _vf = _api_checksum  # built-in key for cheap 1-unit verification (age/duration filter)

    # Build block list: caller languages + EN (ensures IMDB) + ANY (catches remaining)
    blocks = list(languages)
    if 'en' not in blocks:
        blocks.append('en')       # EN auto-added so IMDB always gets its own block
    blocks.append(None)           # None = ANY block (TMDB videos in unlisted languages)
    all_explicit = [b for b in blocks if b]  # named languages to exclude from ANY block

    _log('SEARCH languages=%s blocks=%s' % (languages, [b or 'ANY' for b in blocks]))

    step = 0

    # Walk each block in priority order — first trailer found wins
    for lang in blocks:
        is_any = (lang is None)
        lang_label = lang.upper() if lang else 'ANY'
        lang_title = en_title if (lang == 'en' or is_any) else title  # EN title for EN/ANY

        # ── Sources that return YouTube video IDs (need a player) ─────
        if has_yt_player:
            # KinoCheck API: free, no key, ID-based (only supports de/en)
            # ANY block: try KC-API(de) only if DE wasn't already an explicit block
            do_kc = not is_any or (is_any and 'de' not in languages)
            if do_kc:
                kc_lang = 'de' if is_any else lang
                step += 1
                _log('--- [%s] KinoCheck API (lang=%s) ---' % (lang_label, kc_lang))
                kc_hits, kc_ok = _searchKinoCheckAPI(tmdb_id, mediatype, language=kc_lang)
                _log('[%s] KC-API: hits=%d ok=%s' % (lang_label, len(kc_hits), kc_ok))
                if kc_hits:
                    non_rb = [h for h in kc_hits if 'red band' not in h.get('name', '').lower()]
                    if non_rb:
                        kc_hits = non_rb
                    else:
                        _log('[%s] KC-API: only Red Band, running age-check' % lang_label)
                        kc_hits = _filterAgeRestricted(kc_hits, api_key=_vf)
                    if kc_hits:
                        _play(kc_hits[0]['key'], step, 'KinoCheck', 'Trailer',
                              kc_lang.upper(), poster, lang_title)
                        return {'found_lang': kc_lang.upper(), 'source': 'KinoCheck'}
                    _log('[%s] KC-API: all results unavailable' % lang_label)

            # KinoCheck YT channel search: DE only, needs user's own key (100 units)
            if (lang == 'de' or (is_any and 'de' not in languages)) and has_own_key:
                step += 1
                _log('--- [%s] KinoCheck YT channel ---' % lang_label)
                kc_raw = _searchKinoCheck(lang_title, year)
                kc_hit = _filterByDuration(kc_raw, api_key=_vf)
                _log('[%s] KC-YT: raw=%d filtered=%d' % (lang_label, len(kc_raw), len(kc_hit)))
                if kc_hit:
                    _play(kc_hit[0]['key'], step, 'KinoCheck', 'Trailer',
                          'DE', poster, lang_title)
                    return {'found_lang': 'DE', 'source': 'KinoCheck'}

            # TMDB videos: filter pre-fetched results by language (0 TMDB calls; the age check costs 1 YT unit)
            step += 1
            _log('--- [%s] TMDB videos ---' % lang_label)
            if is_any:
                videos = _tmdbVideos(tmdb_videos)
                videos = [v for v in videos if v.get('iso_639_1') not in all_explicit]  # exclude already-tried langs
            else:
                videos = _tmdbVideos(tmdb_videos, lang=lang)
            videos = _filterAgeRestricted(videos, api_key=_vf)
            _log('[%s] TMDB: filtered=%d' % (lang_label, len(videos)))
            if videos:
                vlang = (videos[0].get('iso_639_1') or lang or '??').upper()
                _play(videos[0]['key'], step, 'TMDB', videos[0].get('type', 'Trailer'),
                      vlang, poster, lang_title)
                return {'found_lang': vlang, 'source': 'TMDB'}

        # IMDB German trailer (DE block): videoStrip, name-filtered German.
        # No YT player/key needed (direct MP4/HLS). primaryVideos is EN,
        # so the German case goes through videoStrip.
        if lang == 'de' and imdb_id:
            step += 1
            _log('--- [DE] IMDB videoStrip ---')
            imdb_url, imdb_quality, imdb_name = _searchIMDBVideoStrip(imdb_id, lang='de')
            _log('[DE] IMDB-strip: url=%s quality=%s name=%r' % (
                imdb_url[:80] if imdb_url else '', imdb_quality, imdb_name))
            if imdb_url:
                _playDirect(imdb_url, step, 'IMDB', 'Trailer', 'DE', poster, imdb_name or title)
                return {'found_lang': 'DE', 'source': 'IMDB'}

        # IMDB direct MP4 (EN block): no player/key needed, ID-based (primaryVideos).
        if lang == 'en' and imdb_id:
            step += 1
            _log('--- [EN] IMDB ---')
            imdb_url, imdb_quality = _searchIMDB(imdb_id)
            _log('[EN] IMDB: url=%s quality=%s' % (imdb_url[:80] if imdb_url else '', imdb_quality))
            play_title = en_title or title
            if imdb_url:
                _playDirect(imdb_url, step, 'IMDB', 'Trailer', '', poster, play_title)
                return {'found_lang': 'EN', 'source': 'IMDB'}

    # YouTube global search (last resort, expensive: 101 units per language —
    # search.list 100 + videos.list 1; a cache hit costs 0-1)
    if has_yt_player and has_own_key:
        user_key = _getUserKey()  # search uses user's own key (not built-in)
        for yt_lang in languages:
            step += 1
            yt_title = en_title if yt_lang == 'en' else title
            yt_upper = yt_lang.upper()
            _log('--- YouTube-%s search ---' % yt_upper)
            yt_raw = _searchYouTube(yt_title, year, lang=yt_lang)
            yt_hit = _filterByDuration(yt_raw, api_key=user_key)
            _log('YouTube-%s: raw=%d filtered=%d' % (yt_upper, len(yt_raw), len(yt_hit)))
            if yt_hit and _oembedSanityCheck(yt_hit[0]['key'], yt_title, year):
                _play(yt_hit[0]['key'], step, 'YouTube', 'Trailer',
                      yt_upper, poster, yt_title)
                return {'found_lang': yt_upper, 'source': 'YouTube'}

    # ── Give up ───────────────────────────────────────────────────
    _log('Give up — languages=%s has_yt_player=%s has_own_key=%s' % (languages, has_yt_player, has_own_key))
    return None


# ── Entry point ──────────────────────────────────────────────────────────────

def playTrailer(tmdb_id, mediatype='movie', title='', year='', poster=''):
    """Trailer wrapper — detects capabilities, pre-fetches TMDB data,
    then calls _runTrailerSearch().

    Args:
        tmdb_id:   TMDB numeric ID (string), or empty for Phase 0 resolution
        mediatype: 'movie' or 'tv' ('tvshow' wird auf 'tv' gemappt)
        title:     display title (for YouTube fallback searches)
        year:      release year string
        poster:    poster image URL (shown as notification icon)

    Sprache fuer Kontextmenue und TMDB-Dialog gleich: zuerst Deutsch, dann Englisch, dann was
    TMDB sonst fuehrt (_runTrailerSearch), ohne Einstellung (so entschieden am 01.11.2026).
    """
    import xbmc, xbmcgui
    from resources.lib.tmdb.api import cTMDB

    if mediatype == 'tvshow':
        mediatype = 'tv'

    url_type  = 'movie' if mediatype == 'movie' else 'tv'
    title_key = 'title' if mediatype == 'movie' else 'name'

    # ── Sprachen ────────────────────────────────────────────────────────
    # Fest die TMDB-Sprache (Deutsch); Englisch und den Block "alle uebrigen" haengt
    # _runTrailerSearch an. Bis zum 01.11.2026 kamen die bevorzugte Sprache der Hoster-Einstellungen
    # (bei "Alle Sprachen" Kodis Sprache) und Kodis Sprache dazu — die Einstellung gehoert den Hostern.
    languages = [cTMDB.TMDB_LANGUAGE]
    _log('Languages: %s' % languages)

    # ── Phase 0: resolve TMDB ID from title search ──────────────────────
    if not tmdb_id:
        _log('Phase 0: resolving TMDB ID for title=%r year=%s mediatype=%s' % (title, year, mediatype))
        search_title = re.sub(r'\s*\(\d{4}\)\s*$', '', title).strip() if title else ''
        if search_title:
            try:
                tmdb_search = cTMDB()
                if mediatype == 'movie':
                    result = tmdb_search.search_movie_name(search_title, year)
                else:
                    result = tmdb_search.search_tvshow_name(search_title, year)
                if result and 'id' in result:
                    tmdb_id = str(result['id'])
                    _log('Phase 0: resolved tmdb_id=%s' % tmdb_id)
            except Exception as e:
                _log('Phase 0: search failed: %s' % e)
        if not tmdb_id:
            _log('Phase 0: could not resolve TMDB ID, aborting')
            xbmcgui.Dialog().notification(
                cConfig().getLocalizedString(30027), cConfig().getLocalizedString(30899),
                xbmcgui.NOTIFICATION_WARNING, 5000,
            )
            return

    _log('START tmdb_id=%s title=%r year=%s mediatype=%s languages=%s' % (tmdb_id, title, year, mediatype, languages))

    # ── Capability detection ───────────────────────────────────────
    has_yt_addon = xbmc.getCondVisibility('System.AddonIsEnabled(plugin.video.youtube)')
    has_own_key = bool(_getUserKey())                # user has own key for expensive searches

    # ── Pre-check: offer YouTube install/enable if no player (1x per session) ──
    if not has_yt_addon:
        _yt_asked = _PROP_PREFIX + '.yt_install_asked'
        _win = xbmcgui.Window(10000)
        if not _win.getProperty(_yt_asked):
            _win.setProperty(_yt_asked, '1')
            if _ensureYouTubeAddon():
                has_yt_addon = True

    has_yt_player = has_yt_addon
    _log('YT addon: %s | has_yt_player: %s | has_own_key: %s' % (has_yt_addon, has_yt_player, has_own_key))

    # ── ISA pre-flight: warn if YouTube addon's InputStream Adaptive is off ──
    if has_yt_addon:
        _ISA_WARNED = _PROP_PREFIX + '.isa_warned'
        try:
            import xbmcaddon
            _win = xbmcgui.Window(10000)
            yt = xbmcaddon.Addon('plugin.video.youtube')
            if yt.getSetting('kodion.video.quality.isa') != 'true':
                if not _win.getProperty(_ISA_WARNED):
                    _win.setProperty(_ISA_WARNED, '1')
                    if xbmcgui.Dialog().yesno(cConfig().getLocalizedString(30027), cConfig().getLocalizedString(30898)):
                        yt.setSetting('kodion.video.quality.isa', 'true')
                        _log('ISA enabled via pre-flight check')
        except Exception:
            pass

    # ── Single TMDB call: EN details + all videos + IMDB ID (1 API call) ──
    tmdb_en = cTMDB(lang='en')  # EN for English title + IMDB ID
    en_data = None
    try:
        if url_type == 'tv':
            term = 'append_to_response=videos,external_ids&include_video_language=de,en,null'
        else:
            term = 'append_to_response=videos&include_video_language=de,en,null'
        en_data = tmdb_en.getUrl('%s/%s' % (url_type, tmdb_id), term=term)
        en_title = (en_data or {}).get(title_key, '') or title
    except Exception:
        en_title = title
    imdb_id = (en_data or {}).get('imdb_id', '')  # movies have imdb_id at top level
    if not imdb_id and url_type == 'tv':
        imdb_id = (en_data or {}).get('external_ids', {}).get('imdb_id', '') or ''  # TV shows need external_ids
    tmdb_videos = (en_data or {}).get('videos', {})  # all videos regardless of language
    _log('EN title: %r imdb_id: %s tmdb_videos: %d results' % (
        en_title, imdb_id, len((tmdb_videos or {}).get('results', []))))

    # ── Run per-language block search ────────────────────────────────
    result = _runTrailerSearch(
        tmdb_id=tmdb_id, mediatype=mediatype,
        title=title, en_title=en_title, year=year, poster=poster,
        imdb_id=imdb_id, languages=languages,
        has_yt_player=has_yt_player, has_own_key=has_own_key,
        tmdb_videos=tmdb_videos,
    )

    # ── Post-search handling ─────────────────────────────────────────
    if not result:
        xbmcgui.Dialog().notification(
                cConfig().getLocalizedString(30027), cConfig().getLocalizedString(30899),
                xbmcgui.NOTIFICATION_WARNING, 5000,
            )
