# -*- coding: utf-8 -*-
# Python 3

import ast
import json
import re

from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.config import cConfig
from resources.lib.logger import logger
from urllib.parse import quote_plus
from resources.lib.tools import cParser


def _titleKey(sTitle):
    """Vergleichsschluessel fuer die Trefferwahl der Titelsuche: Kleinschreibung, nur
    Buchstaben und Ziffern. Schreibvarianten fallen so zusammen — "Dragon Ball Super: Broly"
    (aniworld) und "Dragonball Super: Broly" (TMDB) haben denselben Schluessel. Gemessen
    04.09.2026: der zeichengenaue Vergleich fand fuer die aniworld-Form keinen Treffer, und
    TMDB reiht davor einen Kurzfilm mit 0 Stimmen ein — der wurde genommen, kein Trailer."""
    return re.sub(r'[\W_]+', '', str(sTitle or '').lower())


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
# Aki: User kann optional eigenen Key in den Settings hinterlegen
# (tmdb_user_api_key). Wenn gesetzt, wird der User-Key zuerst probiert.
# Bei leer/ungueltig fallen wir automatisch auf die Standard-Keys zurueck.
_TMDB_DEFAULT_KEYS = [
    '86dd18b04874d9c94afadde7993d94e3',  # primary
    '0b529d296545c2545a68db5cb903cd94',  # backup
]
_user_tmdb_key = (cConfig().getSetting('tmdb_user_api_key') or '').strip()
TMDB_API_KEYS = ([_user_tmdb_key] + _TMDB_DEFAULT_KEYS) if _user_tmdb_key else list(_TMDB_DEFAULT_KEYS)

class cTMDB:
    TMDB_GENRES = {12: 'Abenteuer', 14: 'Fantasy', 16: 'Animation', 18: 'Drama', 27: 'Horror', 28: 'Action', 35: 'Komödie', 36: 'Historie', 37: 'Western', 53: 'Thriller', 80: 'Krimi', 99: 'Dokumentarfilm', 878: 'Science Fiction', 9648: 'Mystery', 10402: 'Musik', 10749: 'Liebesfilm', 10751: 'Familie', 10752: 'Kriegsfilm', 10759: 'Action & Adventure', 10762: 'Kids', 10763: 'News', 10764: 'Reality', 10765: 'Sci-Fi & Fantasy', 10766: 'Soap', 10767: 'Talk', 10768: 'War & Politics', 10770: 'TV-Film'}
    URL = 'https://api.themoviedb.org/3/'
    URL_TRAILER = 'plugin://plugin.video.youtube/play/?video_id=%s'
    TMDB_LANGUAGE = cConfig().getSetting('tmdb_lang')
    
    def __init__(self, api_key='', lang=TMDB_LANGUAGE):
        # api_key Parameter wird ignoriert — Backwards-Compat-Signatur.
        # Key-Verwaltung laeuft zentral ueber TMDB_API_KEYS + Auto-Rotation in _call().
        self.api_key = TMDB_API_KEYS[0]
        self.lang = lang
        self.poster = 'https://image.tmdb.org/t/p/%s' % cConfig().getSetting('poster_tmdb')
        self.fanart = 'https://image.tmdb.org/t/p/%s' % cConfig().getSetting('backdrop_tmdb')
        

    def search_movie_name(self, name, year='', page=1, advanced='false'):
        name = re.sub(' +', ' ', name)
        # Aki: Zusaetze der Seite entfernen („... Ger Sub", „(Unrated)", „*Subbed*", „(US)" ...) —
        # mit Zusatz findet TMDB den Film nicht (Trailer, TMDB-Info, Metadaten). Die Regeln stehen
        # EINMAL in cParser.stripTitleNotes, Weitere Quellen nutzt dieselben.
        name = cParser.stripTitleNotes(name)
        if year:
            name = re.sub(year, ' ', name) #Wenn das Jahr im Namen auftaucht dann das Jahr löschen
        term = quote_plus(name)
        meta = self._call('search/movie', 'query=' + term + '&page=' + str(page))
        if 'errors' not in meta and 'status_code' not in meta:
            if 'total_results' in meta and meta['total_results'] != 0:
                movie = ''
                if meta['total_results'] == 1:
                    movie = meta['results'][0]
                else:
                    # Exception Handling notwendig da TMDb in seltenen Fällen keine genre_ids mitliefert
                    try:
                        aCandidates = [m for m in meta['results'] if m['genre_ids'] and 99 not in m['genre_ids']]
                    except Exception:
                        aCandidates = []
                    movie = _pickByTitle(aCandidates, name, year, ('title', 'original_title'), 'release_date')
                    if not movie:
                        for searchMovie in meta['results']:
                            if searchMovie['genre_ids'] and 99 not in searchMovie['genre_ids']:
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
        result['tmdb_id'] = movie_id
        return result

    def search_tvshow_name(self, name, year='', page=1, genre='', advanced='false'):
        # Aki: Zusaetze der Seite und die englischen Staffelformen samt S01E02 („Kaiju No. 8 2nd Season
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
            # "lanterns - 1 staffel ( )" stehen, TMDB fand nichts (Audit 02.10.2026, 5 megakino-Titel)
            name = re.sub(r'\s*-\s*\d+\s+staffel\b.*$', '', name)
        elif 'staffel' in name:
            name = re.sub(r'\s\wtaffel[^>]([1-9\-]+)', '', name)
        if year:
            name = re.sub(year, ' ', name) #Wenn das Jahr im Namen auftaucht dann das Jahr löschen
        term = quote_plus(name)
        meta = self._call('search/tv', 'query=' + term + '&page=' + str(page))
        if 'errors' not in meta and 'status_code' not in meta:
            if 'total_results' in meta and meta['total_results'] != 0:
                movie = ''
                if meta['total_results'] == 1:
                    movie = meta['results'][0]
                else:
                    aCandidates = [m for m in meta['results'] if genre == '' or genre in m['genre_ids']]
                    movie = _pickByTitle(aCandidates, name, year, ('name', 'original_name'), 'first_air_date')
                    if not movie:
                        for searchMovie in meta['results']:
                            if genre and genre in searchMovie['genre_ids']:
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
                    meta = self.search_tvshow_id(tmdb_id)
                else:
                    meta = movie
        else:
            meta = {}
        return meta

    def search_tvshow_id(self, show_id, append_to_response='append_to_response=external_ids,videos,credits'):
        result = self._call('tv/' + str(show_id), append_to_response)
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
        if meta and 'id' in meta:
            meta = self._format(meta, name)
        return meta

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
        # Rotation greift bei status_code 7 (Invalid Key) oder 10 (Suspended Key)
        # oder wenn die Response kein parseable JSON liefert (Network/CDN-Issue).
        keys_to_try = [self.api_key] + [k for k in TMDB_API_KEYS if k != self.api_key]
        for key in keys_to_try:
            url = '%s%s?language=%s&api_key=%s' % (self.URL, action, self.lang, key)
            if append_to_response:
                url += '&%s' % append_to_response
            oRequestHandler = cRequestHandler(url, ignoreErrors=True)
            response = oRequestHandler.request()
            try:
                data = json.loads(response)
            except (ValueError, TypeError):
                logger.warning('TMDB API Key %s... fehlgeschlagen (kein JSON)' % key[:8])
                continue
            # status_code 7 = Invalid API key, 10 = Suspended API key, 25 = Rate-Limit
            if 'status_code' in data and data['status_code'] in (7, 10, 25):
                logger.warning('TMDB API Key %s... abgelehnt (status %s)' % (key[:8], data['status_code']))
                continue
            # Funktionierender Key — fuer naechste Requests dieser Instanz merken
            if key != self.api_key:
                self.api_key = key
                logger.info('TMDB API Key gewechselt auf: %s...' % key[:8])
            # status_code 34 = Resource not found (kein Key-Issue, normaler Fall)
            if 'status_code' in data and data['status_code'] == 34:
                return {}
            return data
        logger.error('TMDB: Alle API Keys fehlgeschlagen!')
        return {}

    def getGenresFromIDs(self, genresID):
        sGenres = []
        for gid in genresID:
            genre = self.TMDB_GENRES.get(gid)
            if genre:
                sGenres.append(genre)
        return sGenres

    def getLanguage(self, Language):
        iso_639 = {'en': 'English', 'de': 'German', 'fr': 'French', 'it': 'Italian', 'nl': 'Nederlands', 'sv': 'Swedish', 'cs': 'Czech', 'da': 'Danish', 'fi': 'Finnish', 'pl': 'Polish', 'es': 'Spanish', 'el': 'Greek', 'tr': 'Turkish', 'uk': 'Ukrainian', 'ru': 'Russian', 'kn': 'Kannada', 'ga': 'Irish', 'hr': 'Croatian', 'hu': 'Hungarian', 'ja': 'Japanese', 'no': 'Norwegian', 'id': 'Indonesian', 'ko': 'Korean', 'pt': 'Portuguese', 'lv': 'Latvian', 'lt': 'Lithuanian', 'ro': 'Romanian', 'sk': 'Slovak', 'sl': 'Slovenian', 'sq': 'Albanian', 'sr': 'Serbian', 'th': 'Thai', 'vi': 'Vietnamese', 'bg': 'Bulgarian', 'fa': 'Persian', 'hy': 'Armenian', 'ka': 'Georgian', 'ar': 'Arabic', 'af': 'Afrikaans', 'bs': 'Bosnian', 'zh': 'Chinese', 'cn': 'Chinese', 'hi': 'Hindi'}
        if Language in iso_639:
            return iso_639[Language]
        else:
            return Language

    def get_meta_episodes(self, media_type, name, tmdb_id='', season='', episode='', advanced='false'):
        meta = {}
        if media_type == 'episode' and tmdb_id and season and episode:
            url = '%stv/%s/season/%s?api_key=%s&language=de' % (self.URL, tmdb_id, season, self.api_key)
            Data = cRequestHandler(url, ignoreErrors=True).request()
            if Data:
                try:
                    meta = json.loads(Data)
                    if 'status_code' in meta and meta['status_code'] == 34:
                        meta = {}
                except Exception:
                    meta = {}
        if 'episodes' in meta:
            for e in meta['episodes']:
                if 'episode_number' in e:
                    if e['episode_number'] == int(episode):
                        return self._format_episodes(e, name)
        else:
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

    def _format(self, meta, name):
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
        if 'budget' in meta and meta['budget']:
            _meta['budget'] = '{:,} $'.format(meta['budget'])
        if 'revenue' in meta and meta['revenue']:
            _meta['revenue'] = '{:,} $'.format(meta['revenue'])
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
            genres = self.getGenresFromIDs(meta['genre_ids'])
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
                _meta['writer'] = ''
                for crew in crews:
                    if crew['job'] == 'Director':
                        _meta['director'] = crew['name']
                    elif crew['department'] == 'Writing':
                        if _meta['writer'] != '':
                            _meta['writer'] += ' / '
                        _meta['writer'] += '%s: %s' % (crew['job'], crew['name'])
                    elif crew['department'] == 'Production' and 'Producer' in crew['job']:
                        if _meta['writer'] != '':
                            _meta['writer'] += ' / '
                        _meta['writer'] += '%s: %s' % (crew['job'], crew['name'])
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
