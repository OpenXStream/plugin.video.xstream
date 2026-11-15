# -*- coding: utf-8 -*-
# Python 3

import ast
import json
import re
import threading

from resources.lib.handler.requestHandler import cRequestHandler, REQUEST_ERRORS
from resources.lib.config import cConfig
from resources.lib.logger import logger
from urllib.parse import quote_plus
from resources.lib.tools import cParser, keyRejected


def _titleKey(sTitle):
    """Vergleichsschluessel fuer die Trefferwahl der Titelsuche: Kleinschreibung, nur
    Buchstaben und Ziffern. Schreibvarianten fallen so zusammen — "Dragon Ball Super: Broly"
    (aniworld) und "Dragonball Super: Broly" (TMDB) haben denselben Schluessel. Gemessen
    04.09.2026: der zeichengenaue Vergleich fand fuer die aniworld-Form keinen Treffer, und
    TMDB reiht davor einen Kurzfilm mit 0 Stimmen ein — der wurde genommen, kein Trailer."""
    return re.sub(r'[\W_]+', '', str(sTitle or '').lower())


def _ohneLeereKlammer(sName):
    """Suchbegriff ohne die Klammer, die vom herausgeloesten Jahr bleibt: der Titel eines Eintrags traegt das Jahr
    der Seite („Testfilm (2020)", getTitle), die Namenssuche loescht nur die Ziffern — bis zum 02.11.2026 ging
    „Testfilm ( )" an TMDB (TMDB fand den Film trotzdem, aber jede Form ein eigener Cache-Eintrag)."""
    return re.sub(' +', ' ', re.sub(r'\(\s*\)', ' ', sName)).strip()


def _pickByTitle(aResults, sName, sYear, aFields, sDateField):
    """Treffer mit gleichem Titelschluessel waehlen. Mit Jahr gewinnt der erste Namenstreffer
    (TMDB-Reihenfolge), dessen Datum hoechstens ZWEI Jahre abweicht — die Seiten fuehren oft das
    deutsche Start- oder Produktionsjahr, ein bis zwei Jahre neben dem TMDB-Datum (gemessen
    04.09.2026: bei ±2 keine andere Wahl als bei ±1 ueber 34 Listentitel, aber Namensvettern
    bleiben auch bei zwei Jahren Drift richtig: "Dune" 1986 -> Der Wuestenplanet 1984). Erst ueber
    den (deutschen) Titel, dann ueber den Originaltitel ("Giant" 1956 heisst hier "Giganten",
    Original "Giant"). Ohne Jahrestreffer oder ohne Jahr der erste Namenstreffer in
    TMDB-Reihenfolge, Titel vor Originaltitel — sonst gewinnt bei Namensvettern der aeltere Film
    ("Giant" 2026 gegen 1956). '' ohne Treffer."""
    nameKey = _titleKey(sName)
    aHitsByField = [[m for m in aResults if _titleKey(m.get(sField)) == nameKey] for sField in aFields]
    if sYear:
        for aHits in aHitsByField:
            for m in aHits:
                sDate = (m.get(sDateField) or '')[:4]
                if sDate.isdigit() and abs(int(sYear) - int(sDate)) <= 2:
                    return m
    for aHits in aHitsByField:
        if aHits:
            return aHits[0]
    return ''

# Zentrale TMDB API Key Verwaltung — Reihenfolge = Probier-Reihenfolge.
# _call() rotiert automatisch zum naechsten bei status_code 7 (Invalid) /
# 10 (Suspended) / 25 (Rate-Limit) oder bei JSON-Parse-Fehler.
#
# User kann optional eigenen Key in den Settings hinterlegen
# (tmdb_user_api_key). Wenn gesetzt, wird der User-Key zuerst probiert.
# Bei leer/ungueltig fallen wir automatisch auf die Standard-Keys zurueck; lehnt TMDB den
# eigenen Key ab, meldet das eine Einblendung, und er faellt fuer den Rest des Aufrufs raus
# (_ownKeyRejected).
_TMDB_DEFAULT_KEYS = [
    '86dd18b04874d9c94afadde7993d94e3',  # primary
    '0b529d296545c2545a68db5cb903cd94',  # backup
]
_user_tmdb_key = (cConfig().getSetting('tmdb_user_api_key') or '').strip()
TMDB_API_KEYS = ([_user_tmdb_key] + _TMDB_DEFAULT_KEYS) if _user_tmdb_key else list(_TMDB_DEFAULT_KEYS)
if not TMDB_API_KEYS:
    # Gar kein Schluessel (Standard-Schluessel entfernt, keiner eingetragen): _call fragt TMDB dann
    # nicht und liefert {} wie bei lauter abgelehnten Schluesseln — TMDB Info und Browser melden
    # „Kein Eintrag", ein Trailer mit bekannter TMDB-ID kommt noch ueber KinoCheck, einer nur mit Titel
    # nicht (die ID kommt aus der TMDB-Suche). Bis zum 01.11.2026 brach cTMDB() hier mit IndexError ab
    # (Fehlerfenster bei TMDB Info und im Browser, am echten Code durchgespielt). Abgelaufene
    # Standard-Schluessel trotzdem austauschen, nicht ersatzlos loeschen.
    logger.warning('TMDB: kein API Key (keine Standard-Schluessel, kein eigener in den Einstellungen)')

# Schuetzt TMDB_API_KEYS beim Aussortieren: der TMDB-Vorlauf einer Liste hat bis zu 10 Threads
_keyLock = threading.Lock()


def _keyName(sKey):
    # Fuer das Log: WELCHER Schluessel, ohne ein Zeichen daraus — bis zum 01.11.2026 standen hier
    # die ersten 8 Zeichen, beim eigenen Schluessel also ein Stueck davon (Logs gehen im Support an
    # Fremde; 01.11.2026).
    if sKey == _user_tmdb_key:
        return 'eigener'
    if sKey in _TMDB_DEFAULT_KEYS:
        return 'Standard %d' % (_TMDB_DEFAULT_KEYS.index(sKey) + 1)
    return '?'


def _ownKeyRejected(sKey):
    """Lehnt TMDB den EIGENEN Schluessel ab (ungueltig oder gesperrt): Einblendung wie beim
    2Captcha-Schluessel (tools.keyRejected), und der Schluessel faellt fuer den Rest des Aufrufs aus
    TMDB_API_KEYS — sonst fragte jede weitere Abfrage zuerst ihn, kassierte eine Ablehnung und lief
    erst dann ueber die Standard-Schluessel (so entschieden am 01.11.2026). Abgelehnte Standard-Schluessel
    bleiben drin und nur im Log, die kann der Nutzer nicht tauschen; das Limit (429 bzw. Code 25)
    ist kein Schluesselfehler und kommt hier nicht an."""
    if not sKey or sKey != _user_tmdb_key:
        return
    with _keyLock:
        if sKey in TMDB_API_KEYS:
            TMDB_API_KEYS.remove(sKey)
    keyRejected('TMDB', 30917)


# Bildgroessen fest — die Einstellungen "Groesse des Posters/der Fanart" sind seit dem 25.10.2026
# ausgebaut (so entschieden), das hier sind ihre bisherigen Standardwerte. Gemessen 25.10.2026 an TMDB:
# w342 = 342x513, w1280 = 1280x720; Folgenbilder und Fotos der Besetzung laufen ueber dieselbe
# Posteradresse (TMDB liefert sie auch in w342). Der TMDB-Browser nimmt eigene Groessen.
IMAGE_URL = 'https://image.tmdb.org/t/p/'
POSTER_SIZE = 'w342'
FANART_SIZE = 'w1280'

# TMDB-Genre-ID "Dokumentarfilm" (genre/movie/list, gelesen 28.10.2026): die Filmsuche waehlt
# zuerst unter Treffern mit Genre und ohne Doku. Eine ID bleibt fest, sie ist TMDBs Schluessel
# (der TMDB-Browser filtert genauso ueber with_genres=<id>); die NAMEN kommen aus getGenreList.
_GENRE_DOKU = 99

class cTMDB:
    URL = 'https://api.themoviedb.org/3/'
    URL_TRAILER = 'plugin://plugin.video.youtube/play/?video_id=%s'
    # Fest Deutsch: die Einstellung "TMDB Sprache" ist seit dem 25.10.2026 ausgebaut (so entschieden).
    # Ohne Sprache liefert TMDB Englisch (Beschreibung, Genres) — deshalb ein fester Wert
    # statt einer leeren Einstellung. trailer.py sucht zusaetzlich Englisch ueber lang='en'.
    TMDB_LANGUAGE = 'de'
    # Listen von TMDB (Genres je Typ, Sprachnamen) je (Sprache, Abfrage), hoechstens einmal je
    # Kodi-Aufruf geholt (_tmdbList): jeder Plugin-Aufruf ist ein frischer Interpreter, das
    # Klassenattribut lebt also einen Klick. Der Lock, weil der TMDB-Vorlauf einer Liste bis zu
    # 10 Threads hat — ohne ihn schickten bei leerem Cache alle dieselbe Abfrage los.
    _lists = {}
    _listLock = threading.Lock()

    def __init__(self, api_key='', lang=TMDB_LANGUAGE):
        # api_key Parameter wird ignoriert — Backwards-Compat-Signatur.
        # Key-Verwaltung laeuft zentral ueber TMDB_API_KEYS + Auto-Rotation in _call().
        aKeys = list(TMDB_API_KEYS)   # Kopie: ein Thread kann den eigenen Schluessel gerade aussortieren
        self.api_key = aKeys[0] if aKeys else ''  # leer = kein Schluessel (siehe oben)
        self.lang = lang
        self.poster = IMAGE_URL + POSTER_SIZE
        self.fanart = IMAGE_URL + FANART_SIZE


    def search_movie_name(self, name, year='', page=1, advanced='false'):
        name = re.sub(' +', ' ', name)
        # Zusaetze der Seite entfernen („... Ger Sub", „(Unrated)", „*Subbed*", „(US)" ...) —
        # mit Zusatz findet TMDB den Film nicht (Trailer, TMDB-Info, Metadaten). Die Regeln stehen
        # EINMAL in cParser.stripTitleNotes, Weitere Quellen nutzt dieselben.
        name = cParser.stripTitleNotes(name)
        if year:
            name = re.sub(year, ' ', name) #Wenn das Jahr im Namen auftaucht dann das Jahr löschen
        term = quote_plus(_ohneLeereKlammer(name))
        meta = self._call('search/movie', 'query=' + term + '&page=' + str(page))
        if 'errors' not in meta and 'status_code' not in meta:
            if 'total_results' in meta and meta['total_results'] != 0:
                movie = ''
                if meta['total_results'] == 1:
                    movie = meta['results'][0]
                else:
                    # Exception Handling notwendig da TMDb in seltenen Fällen keine genre_ids mitliefert
                    try:
                        aCandidates = [m for m in meta['results'] if m['genre_ids'] and _GENRE_DOKU not in m['genre_ids']]
                    except Exception:
                        aCandidates = []
                    movie = _pickByTitle(aCandidates, name, year, ('title', 'original_title'), 'release_date')
                    if not movie:
                        for searchMovie in meta['results']:
                            if searchMovie['genre_ids'] and _GENRE_DOKU not in searchMovie['genre_ids']:
                                if year:
                                    if 'release_date' in searchMovie and searchMovie['release_date']:
                                        release_date = searchMovie['release_date']
                                        yy = release_date[:4]
                                        if int(year) - int(yy) > 1:
                                            continue
                                movie = searchMovie
                                break
                    if not movie:
                        movie = meta['results'][0]
                if advanced == 'true':
                    tmdb_id = movie['id']
                    meta = self.search_movie_id(tmdb_id)
                else:
                    meta = movie
        else:
            meta = {}
        return meta

    def search_movie_id(self, movie_id, append_to_response='append_to_response=trailers,credits'):
        result = self._call('movie/' + str(movie_id), append_to_response)
        # Leer bleibt leer (Netzfehler, unbekannte ID): mit nur der ID darin galt die Antwort als
        # Treffer, und das Fenster "TMDB Info" oeffnete ohne Inhalt statt zu melden (25.10.2026).
        if result:
            result['tmdb_id'] = movie_id
        return result

    def search_tvshow_name(self, name, year='', page=1, advanced='false'):
        # Zusaetze der Seite und die englischen Staffelformen samt S01E02 („Kaiju No. 8 2nd Season
        # Ger Sub", „Sandokan S01 E01 (DE)") — VOR dem Kleinschreiben, die Kuerzel-Regel „(US)" braucht
        # die Grossbuchstaben. Regeln in cParser, Weitere Quellen nutzt dieselben.
        name = cParser.stripTitleNotes(cParser.stripSeasonForms(name))
        name = name.lower()
        if '- staffel' in name:
            name = re.sub(r'\s-\s\wtaffel[^>]([1-9\-]+)', '', name)
        elif re.search(r'-\s*\d+\s+staffel', name):
            # Format B (z.B. Megakino): "show - 1 staffel" / "show - 12 staffel" — bis zum
            # Zeilenende schneiden, nicht nur bis "staffel": hinter der Staffel steht oft noch
            # das Jahr ("lanterns - 1 staffel (2026)"), und mit dem Anker am Zeilenende blieb
            # "lanterns - 1 staffel ( )" stehen, TMDB fand nichts (02.10.2026, 5 megakino-Titel)
            name = re.sub(r'\s*-\s*\d+\s+staffel\b.*$', '', name)
        elif 'staffel' in name:
            name = re.sub(r'\s\wtaffel[^>]([1-9\-]+)', '', name)
        if year:
            name = re.sub(year, ' ', name) #Wenn das Jahr im Namen auftaucht dann das Jahr löschen
        term = quote_plus(_ohneLeereKlammer(name))
        meta = self._call('search/tv', 'query=' + term + '&page=' + str(page))
        if 'errors' not in meta and 'status_code' not in meta:
            if 'total_results' in meta and meta['total_results'] != 0:
                movie = ''
                if meta['total_results'] == 1:
                    movie = meta['results'][0]
                else:
                    movie = _pickByTitle(meta['results'], name, year, ('name', 'original_name'), 'first_air_date')
                    if not movie:
                        movie = meta['results'][0]
                if advanced == 'true':
                    tmdb_id = movie['id']
                    meta = self.search_tvshow_id(tmdb_id)
                else:
                    meta = movie
        else:
            meta = {}
        return meta

    def search_tvshow_id(self, show_id, append_to_response='append_to_response=external_ids,videos,credits'):
        result = self._call('tv/' + str(show_id), append_to_response)
        if result:   # wie search_movie_id: leer bleibt leer
            result['tmdb_id'] = show_id
        return result

    def get_meta(self, media_type, name, imdb_id='', tmdb_id='', year='', season='', episode='', advanced='false'):
        name = re.sub(' +', ' ', name)
        meta = {}
        if media_type == 'movie':
            if tmdb_id:
                meta = self.search_movie_id(tmdb_id)
            elif name:
                meta = self.search_movie_name(name, year, advanced=advanced)
        elif media_type == 'tvshow':
            if tmdb_id:
                meta = self.search_tvshow_id(tmdb_id)
            elif name:
                meta = self.search_tvshow_name(name, year, advanced=advanced)
        # Ohne id ist es kein Treffer: die Namenssuche gibt bei 0 Treffern TMDBs rohe Antwort zurueck
        # (page, results, total_pages, total_results) — die kam hier durch und stand mit "TMDB Infos
        # laden" als vier Werte am Listeneintrag (25.10.2026). Leer bleibt leer, wie bei der ID-Suche.
        if not meta or 'id' not in meta:
            return {}
        return self._format(meta, name, 'tv' if media_type == 'tvshow' else 'movie')

    def getUrl(self, url, page=1, term=''):
        try:
            if term:
                term = term + '&page=' + str(page)
            else:
                term = 'page=' + str(page)
            result = self._call(url, term)
        except Exception:
            return False
        return result

    def _call(self, action, append_to_response=''):
        # Alle Keys probieren: aktueller zuerst, dann die anderen.
        # Rotation greift bei HTTP 401 (ungueltiger/gesperrter Schluessel) und 429 (Limit),
        # bei status_code 7/10/25 in einer 200er-Antwort oder wenn die Response kein
        # parseable JSON liefert (z.B. eine HTML-Fehlerseite); jeder andere Netzfehler-Sentinel
        # beendet den Aufruf, siehe unten.
        aKeys = list(TMDB_API_KEYS)   # Kopie wie in __init__
        if self.api_key not in aKeys:
            # Der eigene Schluessel wurde in diesem Aufruf abgelehnt und aussortiert (_ownKeyRejected)
            self.api_key = aKeys[0] if aKeys else ''
        if not self.api_key:
            return {}  # kein Schluessel: keine Anfrage (Logzeile einmal beim Laden des Moduls)
        keys_to_try = [self.api_key] + [k for k in aKeys if k != self.api_key]
        for key in keys_to_try:
            url = '%s%s?language=%s&api_key=%s' % (self.URL, action, self.lang, key)
            if append_to_response:
                url += '&%s' % append_to_response
            oRequestHandler = cRequestHandler(url, ignoreErrors=True)
            response = oRequestHandler.request()
            if response in REQUEST_ERRORS:
                # Einen ungueltigen oder gesperrten Schluessel (TMDB-Code 7/10) meldet TMDB als
                # HTTP 401, das Limit (Code 25) als 429 — beide kommen hier als Sentinel an, weil
                # der requestHandler jeden HTTP-Fehler so zurueckgibt (gemessen 25.10.2026: Body
                # {"status_code":7} hinter einem 401). Am Status erkannt, naechster Schluessel —
                # sonst legte ein falscher eigener Schluessel TMDB lahm, und der Ersatzschluessel
                # sprang bei einer Sperre des ersten nie ein.
                sStatus = str(oRequestHandler.getStatus())
                if sStatus in ('401', '429'):
                    logger.warning('TMDB API Key %s abgelehnt (HTTP %s)' % (_keyName(key), sStatus))
                    if sStatus == '401':
                        _ownKeyRejected(key)   # nur der eigene Schluessel wird gemeldet und aussortiert
                    continue
                # Timeout, Verbindung zu, Sperre: ein Netzfehler ist kein Schluesselproblem.
                # Mit dem zweiten Schluessel lief dieselbe Anfrage in dasselbe Timeout —
                # gemessen 21 s statt 10 fuer eine Antwort, die ohnehin leer bleibt.
                logger.warning('TMDB: %s (%s)' % (response, action))
                return {}
            try:
                data = json.loads(response)
            except (ValueError, TypeError):
                logger.warning('TMDB API Key %s fehlgeschlagen (kein JSON)' % _keyName(key))
                continue
            # status_code 7 = Invalid API key, 10 = Suspended API key, 25 = Rate-Limit
            if 'status_code' in data and data['status_code'] in (7, 10, 25):
                logger.warning('TMDB API Key %s abgelehnt (status %s)' % (_keyName(key), data['status_code']))
                if data['status_code'] != 25:
                    _ownKeyRejected(key)   # wie beim HTTP 401 oben
                continue
            # Funktionierender Key — fuer naechste Requests dieser Instanz merken
            if key != self.api_key:
                self.api_key = key
                logger.info('TMDB API Key gewechselt auf: %s' % _keyName(key))
            # status_code 34 = Resource not found (kein Key-Issue, normaler Fall)
            if 'status_code' in data and data['status_code'] == 34:
                return {}
            return data
        logger.error('TMDB: Alle API Keys fehlgeschlagen!')
        return {}

    def _tmdbList(self, action, field=''):
        """Eine Liste von TMDB — Eintraege als Dicts, aus dem Antwortfeld `field` oder (leer) der Antwort
        selbst — hoechstens einmal je Kodi-Aufruf holen; leer, wenn TMDB nicht liefert (Logzeile), und
        auch dieser Fehlschlag gilt fuer den Rest des Aufrufs (kein zweiter Versuch). Der requestHandler
        cacht die Antwort selbst (cacheTime). Nutzer: getGenreList, getLanguage."""
        key = (self.lang, action)
        with cTMDB._listLock:
            if key not in cTMDB._lists:
                data = self._call(action)
                items = data if not field else (data.get(field) if isinstance(data, dict) else None)
                items = [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []
                if not items:
                    logger.warning('TMDB: keine Liste %s (%s)' % (action, self.lang))
                cTMDB._lists[key] = items
            return cTMDB._lists[key]

    def getGenreList(self, media_type):
        """Genre-Liste von TMDB fuer media_type 'movie' oder 'tv' — [{'id': .., 'name': ..}, ...] in der
        Sprache dieser Instanz. Die EINE Quelle fuer Genre-Namen: das Genre-Menue des TMDB-Browsers und
        getGenresFromIDs (TMDB-Infos der Listen) lesen hier. Bis zum 28.10.2026 stand fuer die Suchtreffer
        eine feste Tabelle im Code, die bei einer Aenderung bei TMDB still veraltet waere, waehrend der
        Browser schon live las."""
        return self._tmdbList('genre/%s/list' % media_type, 'genres')

    def getGenresFromIDs(self, genresID, media_type):
        # Suchtreffer tragen nur die IDs; die Namen kommen aus der Genre-Liste desselben Typs.
        # Eine ID, die die Liste nicht kennt, faellt weg.
        names = dict((g.get('id'), g.get('name')) for g in self.getGenreList(media_type))
        return [names[gid] for gid in genresID if names.get(gid)]

    def getLanguage(self, Language):
        # Englischer Name zu TMDBs Sprachcode (original_language: ISO 639-1 plus TMDB-eigene wie cn)
        # aus configuration/languages — der Liste, aus der die Codes der Treffer stammen (28.10.2026:
        # 187 Codes; TMDB fuehrt die Namen nur englisch oder nativ, deshalb english_name). Bis zum
        # 28.10.2026 eine feste Tabelle mit 43 Codes, andere Codes erschienen roh. Ohne Liste bleibt
        # der Code wie bisher stehen.
        names = dict((x.get('iso_639_1'), x.get('english_name')) for x in self._tmdbList('configuration/languages'))
        return names.get(Language) or Language

    def get_meta_episodes(self, media_type, name, tmdb_id='', season='', episode='', advanced='false'):
        # Seit 14.10.2026 ueber _call wie jede andere TMDB-Abfrage: Sprache aus
        # cTMDB (TMDB_LANGUAGE, fest Deutsch), Schluesselwechsel bei 7/10/25,
        # Netzfehler-Sentinel wird geloggt und liefert {} — vorher ein eigener
        # Abruf, dessen Sentinel still im json-except endete. Einziger Aufrufer
        # guiElement.getMeta (TMDB-Infos je Folge, Einstellung TMDBMETA, Default aus).
        if media_type != 'episode' or not (tmdb_id and season and episode):
            return {}
        meta = self._call('tv/%s/season/%s' % (tmdb_id, season))
        for e in meta.get('episodes', []) or []:
            if e.get('episode_number') == int(episode):
                return self._format_episodes(e, name)
        return {}

    def _format_episodes(self, meta, name):
        _meta = {}
        if 'air_date' in meta and meta['air_date']:
            _meta['aired'] = meta['air_date']
        if 'episode_number' in meta and meta['episode_number']:
            _meta['episode'] = meta['episode_number']
        if 'name' in meta and meta['name']:
            _meta['title'] = meta['name']
        if 'overview' in meta and meta['overview']:
            _meta['plot'] = meta['overview']
        if 'production_code' in meta and meta['production_code']:
            _meta['code'] = str(meta['production_code'])
        if 'season_number' in meta and meta['season_number']:
            _meta['season'] = meta['season_number']
        if 'still_path' in meta and meta['still_path']:
            _meta['cover_url'] = self.poster + meta['still_path']
        if 'vote_average' in meta and meta['vote_average']:
            _meta['rating'] = meta['vote_average']
        if 'vote_count' in meta and meta['vote_count']:
            _meta['votes'] = meta['vote_count']
        if 'crew' in meta and meta['crew']:
            _meta['writer'] = ''
            _meta['director'] = ''

            for crew in meta['crew']:
                if crew['department'] == 'Directing':
                    if _meta['director'] != '':
                        _meta['director'] += ' / '
                    _meta['director'] += '%s: %s' % (crew['job'], crew['name'])
                elif crew['department'] == 'Writing':
                    if _meta['writer'] != '':
                        _meta['writer'] += ' / '
                    _meta['writer'] += '%s: %s' % (crew['job'], crew['name'])
        if 'guest_stars' in meta and meta['guest_stars']:
            licast = []
            for c in meta['guest_stars']:
                licast.append((c['name'], c['character'], self.poster + str(c['profile_path'])))
            _meta['cast'] = licast
        return _meta

    def _format(self, meta, name, media_type):
        # media_type = TMDB-Typ 'movie' oder 'tv' (fuer die Genre-Liste, falls nur genre_ids da sind)
        _meta = {}
        _meta['genre'] = ''
        if 'id' in meta:
            _meta['tmdb_id'] = meta['id']
        if 'backdrop_path' in meta and meta['backdrop_path']:
            _meta['backdrop_url'] = self.fanart + str(meta['backdrop_path'])
        if 'original_language' in meta and meta['original_language']:
            _meta['country'] = self.getLanguage(meta['original_language'])
        if 'original_title' in meta and meta['original_title']:
            _meta['originaltitle'] = meta['original_title']
        elif 'original_name' in meta and meta['original_name']:
            _meta['originaltitle'] = meta['original_name']
        if 'overview' in meta and meta['overview']:
            _meta['plot'] = meta['overview']
        if 'poster_path' in meta and meta['poster_path']:
            _meta['cover_url'] = self.poster + str(meta['poster_path'])
        if 'release_date' in meta and meta['release_date']:
            _meta['premiered'] = meta['release_date']
        elif 'first_air_date' in meta and meta['first_air_date']:
            _meta['premiered'] = meta['first_air_date']
        if 'premiered' in _meta and _meta['premiered'] and len(_meta['premiered']) == 10:
            _meta['year'] = int(_meta['premiered'][:4])
        # Budget und Einnahmen roh (Dollar); die Anzeigeform baut das Info-Fenster nach der Oberflaechensprache
        # (info.py, seit dem 03.11.2026 — vorher hier fest „160,000,000 $")
        if 'budget' in meta and meta['budget']:
            _meta['budget'] = meta['budget']
        if 'revenue' in meta and meta['revenue']:
            _meta['revenue'] = meta['revenue']
        if 'status' in meta and meta['status']:
            _meta['status'] = meta['status']
        duration = 0
        if 'runtime' in meta and meta['runtime']:
            duration = int(meta['runtime'])
        elif 'episode_run_time' in meta and meta['episode_run_time']:
            duration = int(meta['episode_run_time'][0])
        if duration > 1:
            _meta['duration'] = duration
        if 'tagline' in meta and meta['tagline']:
            _meta['tagline'] = meta['tagline']
        if 'vote_average' in meta and meta['vote_average']:
            _meta['rating'] = meta['vote_average']
        if 'vote_count' in meta and meta['vote_count']:
            _meta['votes'] = meta['vote_count']
        if 'genres' in meta and meta['genres']:
            for genre in meta['genres']:
                if _meta['genre'] == '':
                    _meta['genre'] += genre['name']
                else:
                    _meta['genre'] += ' / ' + genre['name']
        elif 'genre_ids' in meta and meta['genre_ids']:
            genres = self.getGenresFromIDs(meta['genre_ids'], media_type)
            for genre in genres:
                if _meta['genre'] == '':
                    _meta['genre'] += genre
                else:
                    _meta['genre'] += ' / ' + genre
        if 'production_companies' in meta and meta['production_companies']:
            _meta['studio'] = ''
            for studio in meta['production_companies']:
                if _meta['studio'] == '':
                    _meta['studio'] += studio['name']
                else:
                    _meta['studio'] += ' / ' + studio['name']
        if 'credits' in meta and meta['credits']:
            strmeta = str(meta['credits'])
            listCredits = ast.literal_eval(strmeta)
            casts = listCredits['cast']
            crews = []
            if len(casts) > 0:
                licast = []
                if 'crew' in listCredits:
                    crews = listCredits['crew']
                if len(crews) > 0:
                    _meta['credits'] = "{'cast': " + str(casts) + ", 'crew': " + str(crews) + "}"
                    for cast in casts:
                        licast.append((cast['name'], cast['character'], self.poster + str(cast['profile_path']), str(cast['id'])))
                    _meta['cast'] = licast
                else:
                    _meta['credits'] = "{'cast': " + str(casts) + '}'
            if len(crews) > 0:
                # Nur Namen mit Kodis Trenner " / ": TMDB nennt die Jobs nur englisch, "Writer: Name"
                # stand so im Fenster TMDB Info (30.10.2026). Regie = jeder mit Job Director (vorher
                # blieb nur der letzte stehen), Drehbuch = die Abteilung Writing, eine Person mit zwei
                # Drehbuch-Jobs (Screenplay und Story) einmal; Produzenten standen bis dahin mit im
                # Drehbuch und sind raus.
                aDirectors = []
                aWriters = []
                for crew in crews:
                    if crew['job'] == 'Director':
                        if crew['name'] not in aDirectors:
                            aDirectors.append(crew['name'])
                    elif crew['department'] == 'Writing' and crew['name'] not in aWriters:
                        aWriters.append(crew['name'])
                if aDirectors:
                    _meta['director'] = ' / '.join(aDirectors)
                _meta['writer'] = ' / '.join(aWriters)
        if 'trailers' in meta and meta['trailers']:
            if 'youtube' in meta['trailers']:
                trailers = ''
                for t in meta['trailers']['youtube']:
                    if t['type'] == 'Trailer':
                        trailers = self.URL_TRAILER % t['source']
                if trailers:
                    _meta['trailer'] = trailers
        elif 'videos' in meta and meta['videos']:
            if 'results' in meta['videos']:
                trailers = ''
                for t in meta['videos']['results']:
                    if t['type'] == 'Trailer' and t['site'] == 'YouTube':
                        trailers = self.URL_TRAILER % t['key']
                if trailers:
                    _meta['trailer'] = trailers
        return _meta
