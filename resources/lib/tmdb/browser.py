# -*- coding: utf-8 -*-
# Python 3

# TMDB-basierte Discovery mit Bridge zu xStream's searchAlter ('Weitere Quellen').
# User browst TMDB-Daten (Filme/Serien/Schauspieler), bei Klick auf einen
# Eintrag wird der Titel gecleant an xStream's searchAlter-System-Funktion
# weitergegeben — die sucht durch alle aktivierten Site-Plugins. Kein Hoster
# wird hier direkt aufgeloest — daher SITE_GLOBAL_SEARCH=False.
# Trailer + Erweiterte Info werden automatisch als Kontext-Menue von
# xStream's __createContextMenu hinzugefuegt sobald setMediaType gesetzt ist.

import datetime
import re
from urllib.parse import quote_plus

import xbmcgui

from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.logger import logger
from resources.lib.tmdb.api import cTMDB
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui


SITE_IDENTIFIER = 'tmdb_browser'
SITE_NAME = 'TMDB Browser'

SITE_GLOBAL_SEARCH = False
ACTIVE = True  # fester Bestandteil — kein User-Toggle mehr, immer aktiv

# Bewusst kein DOMAIN/URL_MAIN — die TMDB-API-Adresse steckt in cTMDB, ein
# Domain-Wechsel durch den Nutzer ist nicht noetig. Das Modul liegt nicht unter
# sites/: der Domain-Check und die Site-Schleife des Hauptmenues sehen es nicht,
# es gibt keine plugin_tmdb_browser.domain / _checkdomain Settings, und der
# Menuepunkt kommt fest aus tmdbBrowserGuiElement() in xstream.py.



# ═══════════════════════════════════════════════════════════════════
#   Top-Menue
# ═══════════════════════════════════════════════════════════════════

def load():
    """Top-Menue: Filme / Serien / Schauspieler.

    Kein Suche-Eintrag — die globale Suche existiert eine Ebene drueber im
    xStream-Hauptmenue.

    clearProperty fuer personQuery: beim Betreten des Menues den gemerkten
    Schauspieler-Suchbegriff verwerfen (showPersonsMenu setzt ihn), sonst
    zeigt der naechste 'Schauspieler'-Klick wortlos das alte Ergebnis statt
    die Tastatur — gleiche Mechanik wie lastSearchText in den Site-Files.
    """
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.tmdb_browser.personQuery')

    oGui = cGui()
    _addNavEntry(oGui, 'Filme', 'showMoviesMenu')
    _addNavEntry(oGui, 'Serien', 'showTVShowsMenu')
    _addNavEntry(oGui, 'Schauspieler', 'showPersonsMenu')

    oGui.setEndOfDirectory()


# ═══════════════════════════════════════════════════════════════════
#   Filme-Menue
# ═══════════════════════════════════════════════════════════════════

def showMoviesMenu():
    """10 Browse-Kategorien fuer Filme — analog xShip navigator.

    Reihenfolge: Pinned (Im Kino/Neu für Daheim) → Streaming-Anbieter → Aktuell-Tier
    (Heute im Trend/Beliebt) → Browse-Tier (Genres/Jahr) → Bestenlisten-Tier
    (Bestes Einspielergebnis/Am besten bewertet/Meiste Bewertungen).
    """
    logger.info('%s: showMoviesMenu' % SITE_NAME)
    oGui = cGui()

    # Pinned
    _addListingEntry(oGui, 'Im Kino', 'movie', 'kinotheater')
    _addListingEntry(oGui, 'Neu für Daheim', 'movie', 'kino')

    # Streaming-Anbieter Submenue (Position 3)
    params = ParameterHandler()
    params.setParam('media_type', 'movie')
    el = cGuiElement()
    el.setTitle('Streaming-Anbieter')
    el.setSiteName(SITE_IDENTIFIER)
    el.setFunction('showStreamingProviders')
    oGui.addFolder(el, params)

    # Aktuell-Tier
    _addListingEntry(oGui, 'Heute im Trend', 'movie', '__trending_day__')

    # Browse-Tier
    _addNavEntry(oGui, 'Genres', 'showGenresMovies')
    _addNavEntry(oGui, 'Jahr', 'showYearsMovies')

    # Bestenlisten-Tier — 'Beliebt' steht hier (nicht im Aktuell-Tier), weil es seit
    # dem Wegfall des Zeitfensters die dauerhaft beliebtesten Titel zeigt. Gleiche
    # Position wie im Serien-Menue.
    _addListingEntry(oGui, 'Beliebt', 'movie', 'popular')
    _addListingEntry(oGui, 'Bestes Einspielergebnis', 'movie', 'production_status=released&sort_by=revenue.desc')
    _addListingEntry(oGui, 'Am besten bewertet', 'movie', 'toprated')
    _addListingEntry(oGui, 'Meiste Bewertungen', 'movie', 'production_status=released&sort_by=vote_count.desc')

    oGui.setEndOfDirectory()


# ═══════════════════════════════════════════════════════════════════
#   Serien-Menue
# ═══════════════════════════════════════════════════════════════════

def showTVShowsMenu():
    """10 Browse-Kategorien fuer Serien — analog xShip navigator.

    Reihenfolge: Pinned (Neu/Laufend/Abgeschlossen) → Streaming-Anbieter →
    Aktuell-Tier (Heute im Trend) → Browse-Tier (Genres/Jahr) → Bestenlisten-Tier
    (Beliebt/Am besten bewertet/Meiste Bewertungen).
    """
    logger.info('%s: showTVShowsMenu' % SITE_NAME)
    oGui = cGui()

    # Pinned
    _addListingEntry(oGui, 'Neu', 'tv', 'tvneu')
    _addListingEntry(oGui, 'Laufend', 'tv', 'with_status=0&sort_by=popularity.desc')
    _addListingEntry(oGui, 'Abgeschlossen', 'tv', 'with_status=3&sort_by=vote_count.desc')

    # Streaming-Anbieter Submenue (Position 4)
    params = ParameterHandler()
    params.setParam('media_type', 'tv')
    el = cGuiElement()
    el.setTitle('Streaming-Anbieter')
    el.setSiteName(SITE_IDENTIFIER)
    el.setFunction('showStreamingProviders')
    oGui.addFolder(el, params)

    # Aktuell-Tier
    _addListingEntry(oGui, 'Heute im Trend', 'tv', '__trending_day__')

    # Browse-Tier
    _addNavEntry(oGui, 'Genres', 'showGenresTV')
    _addNavEntry(oGui, 'Jahr', 'showYearsTV')

    # Bestenlisten-Tier
    _addListingEntry(oGui, 'Beliebt', 'tv', 'sort_by=popularity.desc')
    _addListingEntry(oGui, 'Am besten bewertet', 'tv', 'sort_by=vote_average.desc')
    _addListingEntry(oGui, 'Meiste Bewertungen', 'tv', 'sort_by=vote_count.desc')

    oGui.setEndOfDirectory()


# ═══════════════════════════════════════════════════════════════════
#   Genre-Untermenues (TMDB-API)
# ═══════════════════════════════════════════════════════════════════

def showGenresMovies():
    """Genre-Liste fuer Filme — TMDB-API."""
    logger.info('%s: showGenresMovies' % SITE_NAME)
    _renderGenres('movie')


def showGenresTV():
    """Genre-Liste fuer Serien — TMDB-API."""
    logger.info('%s: showGenresTV' % SITE_NAME)
    _renderGenres('tv')


def _renderGenres(media_type):
    oGui = cGui()
    genres = _getGenres(media_type)
    for g in genres:
        _addListingEntry(oGui, g['name'], media_type,
                         'with_genres=%s&sort_by=popularity.desc' % g['id'])
    oGui.setEndOfDirectory()


def _getGenres(media_type):
    """TMDB-Genre-Liste via API.

    media_type: 'movie' oder 'tv'
    Returns: list[dict] mit 'id' + 'name'

    Bei API-Fehler/Outage: leere Liste (User sieht leeres Menue statt
    eines kuratierten Fallback der beim Klick eh wieder API braucht).
    """
    action = 'genre/%s/list' % media_type
    try:
        data = cTMDB()._call(action)
        if data and 'genres' in data and data['genres']:
            return data['genres']
    except Exception as e:
        logger.warning('%s: Genre-API fehlgeschlagen: %s' % (SITE_NAME, e))
    return []


# ═══════════════════════════════════════════════════════════════════
#   Streaming-Anbieter Submenu (TMDB-API)
# ═══════════════════════════════════════════════════════════════════

def _getWatchProviders(media_type):
    """TMDB-Watch-Provider-Liste fuer DE-Region via API.

    media_type: 'movie' oder 'tv'
    Returns: list[dict] mit 'provider_id', 'provider_name', 'display_priority'
             sortiert nach display_priority (TMDBs eigene Reihenfolge)

    Bei API-Fehler/Outage: leere Liste.
    """
    action = 'watch/providers/%s' % media_type
    try:
        data = cTMDB()._call(action, append_to_response='watch_region=DE')
        if data and 'results' in data and data['results']:
            # TMDB liefert unsortiert — wir sortieren nach display_priority (DE)
            providers = data['results']
            providers.sort(key=lambda p: p.get('display_priorities', {}).get('DE', 999))
            return providers
    except Exception as e:
        logger.warning('%s: Watch-Provider-API fehlgeschlagen: %s' % (SITE_NAME, e))
    return []


def showStreamingProviders():
    """Submenu mit DE-Watch-Providern via TMDB-API.

    Klick auf einen Provider fuehrt zu Listings mit
    with_watch_providers=<id>&watch_region=DE.
    """
    p = ParameterHandler()
    media_type = p.getValue('media_type')
    if not media_type:
        logger.warning('%s: showStreamingProviders ohne media_type' % SITE_NAME)
        cGui().setEndOfDirectory()
        return
    logger.info('%s: showStreamingProviders (%s)' % (SITE_NAME, media_type))
    oGui = cGui()
    for prov in _getWatchProviders(media_type):
        url = 'with_watch_providers=%d&watch_region=DE&sort_by=popularity.desc' % prov['provider_id']
        _addListingEntry(oGui, prov['provider_name'], media_type, url)
    oGui.setEndOfDirectory()


# ═══════════════════════════════════════════════════════════════════
#   Jahr-Untermenues
# ═══════════════════════════════════════════════════════════════════

def showYearsMovies():
    """Jahr-Liste fuer Filme — aktuelles Jahr bis 1910."""
    logger.info('%s: showYearsMovies' % SITE_NAME)
    _renderYears('movie')


def showYearsTV():
    """Jahr-Liste fuer Serien — aktuelles Jahr bis 1950."""
    logger.info('%s: showYearsTV' % SITE_NAME)
    _renderYears('tv')


def _renderYears(media_type):
    oGui = cGui()
    current_year = datetime.datetime.today().year
    if media_type == 'movie':
        param = 'primary_release_year=%s&sort_by=vote_count.desc'
        start_year = 1910
    else:
        param = 'first_air_date_year=%s&sort_by=vote_count.desc'
        start_year = 1950
    for year in range(current_year, start_year - 1, -1):
        _addListingEntry(oGui, str(year), media_type, param % year)
    oGui.setEndOfDirectory()


# ═══════════════════════════════════════════════════════════════════
#   Generic Listings-Renderer (Discover-Endpoint)
# ═══════════════════════════════════════════════════════════════════

def showListings():
    """Generischer TMDB-discover-Renderer.

    URL-Params (via ParameterHandler):
        media_type: 'movie' oder 'tv'
        url: TMDB-discover-Parameter ODER Keyword (kino/kinotheater/popular/toprated/tvneu)
        page: Seitenzahl (default '1')
    """
    p = ParameterHandler()
    media_type = p.getValue('media_type')
    raw_url = p.getValue('tmdb_url')
    page = int(p.getValue('tmdb_page') or '1')

    if not media_type or not raw_url:
        logger.warning('%s: showListings ohne media_type/tmdb_url' % SITE_NAME)
        cGui().setEndOfDirectory()
        return

    # Trending-Sentinel: anderer Endpoint (trending/{type}/day) statt discover
    if raw_url == '__trending_day__':
        action = 'trending/%s/day' % media_type
        data = cTMDB().getUrl(action, page=page, term='')
    else:
        discover_url = _resolveListingUrl(raw_url, media_type)
        action = 'discover/%s' % media_type
        data = cTMDB().getUrl(action, page=page, term=discover_url)

    if not data or 'results' not in data or not data['results']:
        logger.info('%s: keine Treffer fuer %s/%s page %d' % (SITE_NAME, media_type, raw_url, page))
        cGui().showInfo()   # leere Liste (oder TMDB nicht erreichbar) melden statt stumm
        cGui().setEndOfDirectory()
        return

    oGui = cGui()
    for item in data['results']:
        _renderListingItem(oGui, item, media_type)

    # Pagination
    total_pages = int(data.get('total_pages', 1))
    if page < total_pages and page < 500:  # TMDB-Limit ist 500 Pages
        _addPaginationEntry(oGui, media_type, raw_url, page + 1, total_pages)

    oGui.setEndOfDirectory()


def _resolveListingUrl(raw_url, media_type):
    """Keyword (kino/kinotheater/popular/toprated/tvneu) zu echter Discover-URL.
    Andere URLs sind direkte TMDB-discover-Parameter und werden durchgereicht.

    Plus: ergaenzt fehlende Quality-Filter (Muster aus xShip) damit
    keine russischen No-Name-Filme oder Adult-Content auftauchen:
      - region=DE (nur wenn tmdb_lang=de)
      - include_adult=false
      - include_video=false (movie only)
      - vote_count.gte=20 (mindestens 20 Bewertungen)
      - release_date.lte=heute (movie + with_release_type)
    """
    today = datetime.datetime.today()
    today_str = today.strftime('%Y-%m-%d')

    # Keyword-Resolver
    if raw_url == 'kino':
        # 90 Tage: sortiert wird nach release_date.desc, das Fenster bestimmt also nur
        # die Tiefe der Liste, nie was oben steht. 30 Tage lieferten oft nur ~60 Titel.
        ago = (today - datetime.timedelta(days=90)).strftime('%Y-%m-%d')
        base = 'release_date.gte=%s&release_date.lte=%s&with_release_type=4|5|6&sort_by=release_date.desc' % (ago, today_str)
    elif raw_url == 'kinotheater':
        ago = (today - datetime.timedelta(days=60)).strftime('%Y-%m-%d')
        base = 'release_date.gte=%s&release_date.lte=%s&with_release_type=2|3&sort_by=popularity.desc' % (ago, today_str)
    elif raw_url == 'popular':
        # Kein Zeitfenster — wie bei den Serien. release_date.lte=heute wird unten
        # automatisch ergaenzt, damit keine unveroeffentlichten Titel auftauchen.
        base = 'with_release_type=4|5|6&sort_by=popularity.desc'
    elif raw_url == 'toprated':
        base = 'with_release_type=4|5|6&vote_count.gte=250&sort_by=vote_average.desc'
    elif raw_url == 'tvneu':
        # 90 Tage, gleiche Begruendung wie bei 'kino' — 30 Tage gaben oft unter
        # 20 Treffer, also nicht mal eine volle Seite.
        ago = (today - datetime.timedelta(days=90)).strftime('%Y-%m-%d')
        base = 'first_air_date.gte=%s&first_air_date.lte=%s&sort_by=first_air_date.desc' % (ago, today_str)
    else:
        base = raw_url

    # Quality-Filter ergaenzen wo noch nicht vorhanden
    extras = []
    # region=DE: nur bei Discover-URLs, nicht bei Streaming-Anbieter-Listings
    # (watch_region=DE filtert dort schon — region=DE waere Doppel-Filter und
    #  wuerde non-DE-Release-Filme wie Squid Game etc. rausfiltern)
    if cConfig().getSetting('tmdb_lang') == 'de' and 'watch_region=' not in base and 'region=' not in base:
        extras.append('region=DE')
    if 'include_adult=' not in base:
        extras.append('include_adult=false')
    if media_type == 'movie' and 'include_video=' not in base:
        extras.append('include_video=false')
    if 'vote_count.gte=' not in base:
        extras.append('vote_count.gte=20')
    if media_type == 'movie' and 'with_release_type' in base and 'release_date.lte' not in base:
        extras.append('release_date.lte=%s' % today_str)

    if extras:
        return base + '&' + '&'.join(extras)
    return base


def _renderListingItem(oGui, item, media_type):
    """TMDB-Result als GuiElement rendern.

    Klick fuehrt direkt zu xStream's 'searchAlter' (Weitere Quellen) — das ist
    die existierende System-Funktion die durch alle aktivierten Plugins sucht.
    searchAlter cuttet selbst Klammer-Jahr + S0/E0/Staffel-Tokens. Wir ersetzen
    vorher den Em-Dash (das macht searchAlter nicht, siehe _cleanTitleForSearch).

    setMediaType triggert xStream's __createContextMenu fuer Trailer + Erweiterte Info.
    """
    if media_type == 'movie':
        title = item.get('title', '')
        date = item.get('release_date', '')
        gui_media_type = 'movie'
    else:
        title = item.get('name', '')
        date = item.get('first_air_date', '')
        gui_media_type = 'tvshow'

    if not title:
        return

    year = date[:4] if date else ''

    # Title fuer searchAlter cleanen (Em-Dash ersetzen, Rest macht searchAlter)
    sCleanTitle = _cleanTitleForSearch(title)
    if not sCleanTitle:
        return

    el = cGuiElement()
    el.setTitle('%s (%s)' % (title, year) if year else title)
    el.setSiteName(SITE_IDENTIFIER)
    el.setFunction('searchAlter')  # xStream-System-Funktion (Weitere Quellen)
    el.setMediaType(gui_media_type)
    if year:
        el.setYear(year)

    overview = item.get('overview', '')
    if overview:
        el.setDescription(overview)

    if item.get('poster_path'):
        el.setThumbnail('https://image.tmdb.org/t/p/w500%s' % item['poster_path'])
    if item.get('backdrop_path'):
        el.setFanart('https://image.tmdb.org/t/p/w1280%s' % item['backdrop_path'])

    # ItemValues damit Kontext-Menue Trailer-Aufruf den TMDB-ID kennt
    itemValues = {
        'title': title,
        'tmdb_id': str(item.get('id', '')),
        'year': year,
    }
    el.setItemValues(itemValues)

    # Params fuer searchAlter (System-Funktion erwartet 'searchTitle')
    p = ParameterHandler()
    p.setParam('searchTitle', sCleanTitle)

    oGui.addFolder(el, p, bIsFolder=True)


def _addPaginationEntry(oGui, media_type, raw_url, next_page, total_pages):
    """Naechste-Seite-Eintrag am Listenende — gleicher Text und gleiche
    Seitenlage wie in den Site-Files (Anzeigetext 30279, "(x von y)" ueber
    cGui.pageInfo); vorher stand hier ein fest deutscher Titel."""
    p = ParameterHandler()
    p.setParam('media_type', media_type)
    p.setParam('tmdb_url', raw_url)
    p.setParam('tmdb_page', str(next_page))
    # pageInfo zeigt die AKTUELLE Seite, wie in den Site-Files — der Helfer bekommt
    # hier die naechste, also eine zurueck.
    oGui.addNextPage(SITE_IDENTIFIER, 'showListings', p,
                     cGui.pageInfo(next_page - 1, total_pages))


# ═══════════════════════════════════════════════════════════════════
#   Schauspieler-Pfad
# ═══════════════════════════════════════════════════════════════════

def showPersonsMenu():
    """Schauspieler-Suche -> Personen-Liste -> Filmography -> searchAlter.

    Pagination via URL-Param 'query' (Naechste-Seite-Eintrag traegt das mit).
    Direkter Klick auf 'Schauspieler' im Top-Menue: Cache pruefen — wenn
    vorhanden, cached Begriff nutzen (Detail-Zurueck zeigt direkt Treffer).
    Sonst Tastatur.
    """
    p = ParameterHandler()
    sQuery = p.getValue('query')  # Pagination-Variante: query in URL-Param
    page = int(p.getValue('tmdb_page') or '1')

    win = xbmcgui.Window(10000)

    # Bei Pagination: query ist im URL-Param, kein Cache-Check noetig
    if not sQuery:
        # Cache pruefen — Detail-Zurueck zeigt direkt Treffer
        cached = win.getProperty('xstream.tmdb_browser.personQuery')
        if cached:
            sQuery = cached
            logger.info('%s: showPersonsMenu Cache-Treffer "%s"' % (SITE_NAME, sQuery))
        else:
            sQuery = cGui().showKeyBoard(sHeading='Schauspieler-Suche')
            if not sQuery:
                # Abbruch: KEIN endOfDirectory, sonst leeres Verzeichnis -
                # Kodi bleibt so in der aktuellen Liste
                return
            win.setProperty('xstream.tmdb_browser.personQuery', sQuery)

    logger.info('%s: showPersonsMenu query="%s" page=%d' % (SITE_NAME, sQuery, page))
    data = cTMDB()._call('search/person', 'query=%s&page=%d' % (quote_plus(sQuery), page))

    if not data or 'results' not in data or not data['results']:
        logger.info('%s: keine Personen-Treffer fuer "%s"' % (SITE_NAME, sQuery))
        # Cache leeren, damit der naechste Klick wieder das Keyboard oeffnet
        win.clearProperty('xstream.tmdb_browser.personQuery')
        # Nulltreffer MELDEN statt stumm ein leeres Verzeichnis zu zeigen — die
        # globale Suche und alle Site-Suchen melden seit dem 01.09.2026, nur dieser
        # Weg blieb stumm (Full-Audit 02.09.2026).
        cGui().showInfo()
        cGui().setEndOfDirectory()
        return

    oGui = cGui()
    rendered = 0
    for person in data['results']:
        # Nur Schauspieler — Regisseure/Producer/etc. rausfiltern (xShip-Pattern)
        if person.get('known_for_department') != 'Acting':
            continue
        _renderPersonItem(oGui, person)
        rendered += 1

    # Treffer kamen an, aber keiner davon ist Schauspieler: gleiche Meldung,
    # sonst steht auch hier ein leeres Verzeichnis ohne Hinweis.
    if not rendered:
        win.clearProperty('xstream.tmdb_browser.personQuery')
        oGui.showInfo()

    # Pagination
    total_pages = int(data.get('total_pages', 1))
    if page < total_pages and page < 500:
        _addPersonPaginationEntry(oGui, sQuery, page + 1, total_pages)

    oGui.setEndOfDirectory()


def _renderPersonItem(oGui, person):
    """TMDB-Person als GuiElement — Klick fuehrt zu Filmography."""
    name = person.get('name', '')
    if not name:
        return

    el = cGuiElement()
    el.setTitle(name)
    el.setSiteName(SITE_IDENTIFIER)
    el.setFunction('showPersonCredits')

    # Bekannt fuer (knownFor) als Beschreibung
    known_for = person.get('known_for', [])
    if known_for:
        titles = []
        for kf in known_for[:3]:  # Top 3 als Hint
            t = kf.get('title') or kf.get('name')
            if t:
                titles.append(t)
        if titles:
            el.setDescription('Bekannt für: ' + ', '.join(titles))

    if person.get('profile_path'):
        el.setThumbnail('https://image.tmdb.org/t/p/w500%s' % person['profile_path'])

    p = ParameterHandler()
    p.setParam('person_id', str(person.get('id', '')))
    p.setParam('person_name', name)
    p.setParam('offset', '0')

    oGui.addFolder(el, p, bIsFolder=True)


def _addPersonPaginationEntry(oGui, sQuery, next_page, total_pages):
    """Naechste-Seite-Eintrag fuer die Schauspieler-Suche."""
    p = ParameterHandler()
    p.setParam('query', sQuery)
    p.setParam('tmdb_page', str(next_page))
    oGui.addNextPage(SITE_IDENTIFIER, 'showPersonsMenu', p,
                     cGui.pageInfo(next_page - 1, total_pages))


def showPersonCredits():
    """Filmography einer Person — Movies + TV combined.

    TMDB liefert oft 50-200+ Eintraege auf einen Schlag — wir paginieren
    client-seitig in 30er-Bloecken (combined_credits hat keine Server-Pagination).
    """
    p = ParameterHandler()
    person_id = p.getValue('person_id')
    person_name = p.getValue('person_name') or ''
    offset = int(p.getValue('offset') or '0')
    PAGE_SIZE = 30

    if not person_id:
        logger.warning('%s: showPersonCredits ohne person_id' % SITE_NAME)
        cGui().setEndOfDirectory()
        return

    logger.info('%s: showPersonCredits person_id=%s offset=%d' % (SITE_NAME, person_id, offset))
    data = cTMDB()._call('person/%s/combined_credits' % person_id)

    if not data or 'cast' not in data or not data['cast']:
        logger.info('%s: keine Credits fuer person_id=%s' % (SITE_NAME, person_id))
        cGui().setEndOfDirectory()
        return

    # Filtern + Sortieren
    cast = []
    for c in data['cast']:
        # Voice/uncredited/rumored Rollen rausfiltern (xShip-Pattern)
        character = c.get('character', '') or ''
        if any(tag in character.lower() for tag in ('voice', 'rumored', 'uncredited')):
            continue
        cast.append(c)
    # Sortieren: vote_average desc, dann popularity desc
    cast.sort(key=lambda x: (
        x.get('vote_average') or 0,
        x.get('popularity') or 0,
    ), reverse=True)

    if not cast:
        logger.info('%s: nach Filter keine Credits mehr fuer person_id=%s' % (SITE_NAME, person_id))
        cGui().setEndOfDirectory()
        return

    total = len(cast)
    end = min(offset + PAGE_SIZE, total)
    chunk = cast[offset:end]

    oGui = cGui()
    for credit in chunk:
        # media_type kommt direkt aus combined_credits ('movie' oder 'tv')
        item_media_type = credit.get('media_type', '')
        if item_media_type not in ('movie', 'tv'):
            continue
        _renderListingItem(oGui, credit, item_media_type)

    # Client-seitige Pagination
    if end < total:
        _addCreditsPaginationEntry(oGui, person_id, person_name, end, total)

    oGui.setEndOfDirectory()


def _addCreditsPaginationEntry(oGui, person_id, person_name, next_offset, total):
    """Naechste-Seite-Eintrag fuer die Filmografie (das Addon schneidet die
    vollstaendige Liste selbst in 30er-Bloecke, die Seitenzahl ist also bekannt)."""
    p = ParameterHandler()
    p.setParam('person_id', person_id)
    p.setParam('person_name', person_name)
    p.setParam('offset', str(next_offset))
    # next_offset ist der Beginn der naechsten 30er-Seite; die aktuelle ist die davor.
    oGui.addNextPage(SITE_IDENTIFIER, 'showPersonCredits', p,
                     cGui.pageInfo(next_offset // 30, (total + 29) // 30))


# ═══════════════════════════════════════════════════════════════════
#   Title-Cleanup fuer searchAlter
# ═══════════════════════════════════════════════════════════════════

def _cleanTitleForSearch(sTitle):
    """TMDB-Titel fuer xStream's searchAlter bereinigen.

    Cuttet was searchAlter NICHT cuttet:
      - Em-Dash '—' zu normalem Bindestrich '-'
        (Streaming-Sites haben quasi nie Em-Dash, fast immer normalen Bindestrich)

    Behaelt:
      - Doppelpunkt ':' (z.B. 'Star Wars: Maul - Shadow Lord' bleibt komplett)

    searchAlter cuttet selbst:
      - Klammer-Jahr '(2025)'
      - Season/Episode-Tokens (' S0', ' E0', ' - Staffel', ' Staffel')
    """
    if not sTitle:
        return ''
    sClean = sTitle.replace('—', '-')
    sClean = re.sub(r'\s+', ' ', sClean).strip()
    return sClean


# ═══════════════════════════════════════════════════════════════════
#   Helper
# ═══════════════════════════════════════════════════════════════════

def _addNavEntry(oGui, title, function):
    """Helper: einfacher Folder-Eintrag (kein media_type, navigations-only)."""
    el = cGuiElement()
    el.setTitle(title)
    el.setSiteName(SITE_IDENTIFIER)
    el.setFunction(function)
    oGui.addFolder(el, ParameterHandler())


def _addListingEntry(oGui, title, media_type, url):
    """Helper: Folder-Eintrag fuer showListings().

    Param-Name 'tmdb_url' (nicht 'url') vermeidet Kollision mit xStream's
    Konvention wo 'url' fuer Hoster-URLs steht. Wuerde sonst durch
    ParameterHandler-init aus sys.argv[2] in Plugin-Search-Calls polluten
    und showHosters(url) crashen lassen.
    """
    el = cGuiElement()
    el.setTitle(title)
    el.setSiteName(SITE_IDENTIFIER)
    el.setFunction('showListings')
    p = ParameterHandler()
    p.setParam('media_type', media_type)
    p.setParam('tmdb_url', url)
    p.setParam('tmdb_page', '1')
    oGui.addFolder(el, p)


# ═══════════════════════════════════════════════════════════════════
#   Pflicht-Stub fuer Plugin-Architektur (kein Hoster — leer)
# ═══════════════════════════════════════════════════════════════════

def getHosterUrl(sUrl=False):
    """Plugin liefert keine Hoster — alle Klicks rufen xStream's searchAlter direkt auf."""
    return []
