# -*- coding: utf-8 -*-
# Python 3
# Always pay attention to the translations in the menu!
# Seite vollständig mit JSON erstellt (Next.js __NEXT_DATA__)
# Browse (Startseite/Neu/Highlights/Genres): __NEXT_DATA__ JSON der Website
# Suche: simplecache-API (liefert custom_fields mit Stream)
# Serien: GraphQL-Backend der Seite — Staffeln und Episoden inklusive Stream-Pfad
#         (das __NEXT_DATA__ der Serien-Detailseite fuehrt dort keine Quelle)
# HTML LangzeitCache:
# Browse (__NEXT_DATA__ ueber _getNextData): 6 Stunden
# Suche (capi, GET):     normaler HTML-Cache mit der globalen Cache-Dauer
# GraphQL (Serien, Suche): keiner — POST wird nicht gecacht


import json
import re
import time

import xbmcgui
from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger
from resources.lib.tools import cParser
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui

SITE_IDENTIFIER = 'netzkino'
SITE_NAME = 'NetzKino'
SITE_ICON = 'netzkino.png'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'netzkino.de')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)

URL_MAIN = 'https://' + DOMAIN + '/'
# Frontpage (featured Filme der Startseite)
URL_FRONTPAGE = URL_MAIN
# Kategorie-Listing nach Slug (Neu, Highlights, einzelne Genres ...)
URL_CATEGORY = URL_MAIN + 'kategorie/%s'
# Genre-Übersicht (liefert die einzelnen Genre-Kategorien)
URL_GENRE = URL_MAIN + 'genre'
# Film-Detailseite nach Slug (liefert MovieDetails mit videoSource.pmdUrl)
URL_DETAIL = URL_MAIN + 'details/%s'
# Suche über die simplecache-API (liefert custom_fields mit Stream)
URL_SEARCH = 'https://api.netzkino.de.simplecache.net/capi-2.0a/search?q=%s&d=www&l=de-DE'
# Stream-Host (pmdUrl wird angehängt)
URL_STREAM = 'https://pmd.netzkino-seite.netzkino.de/'
# GraphQL-Backend der Seite. Wird NUR fuer Serien gebraucht: die __NEXT_DATA__ der
# Serien-Detailseite liefert zwar Staffeln, aber keine Episoden mit Stream-Pfad
# (videoSource ist dort leer). Ueber diesen Endpunkt kommen Episodentitel und
# pmdUrl in EINER Abfrage je Serie. Filme brauchen ihn nicht.
URL_GRAPHQL = 'https://data.netzkino.de/netzkino/graphql'


def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.netzkino.lastSearchText')
    # Startseite (die Kategorie-Reihen der Seite)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30881), SITE_IDENTIFIER, 'showStart'))  # Startseite
    # Genres (dynamisch)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30506), SITE_IDENTIFIER, 'showGenres'))  # Genre (Hausstring, seit 2026.09.10 wie alle Sites)
    # Suche
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'))
    cGui().setEndOfDirectory()


def showStart():
    # Startseite: listet die Kategorie-Reihen der Frontpage (Neu, Highlights, Actionfilme ...)
    oGui = cGui()
    params = ParameterHandler()
    oNext = _getNextData(URL_FRONTPAGE)
    data = _findQuery(oNext, 'AllContent') if oNext else None
    nodes = []
    if data:
        try:
            nodes = data['parentCategory']['subcategories']['nodes']
        except (KeyError, TypeError):
            nodes = []
    if not nodes:
        oGui.showInfo()
        return
    for cat in nodes:
        sTitle = str(cat.get('title') or '')
        sSlug = cat.get('slug') or ''
        if not sTitle or not sSlug:
            continue
        params.setParam('sUrl', URL_CATEGORY % sSlug)
        oGui.addFolder(cGuiElement(sTitle, SITE_IDENTIFIER, 'showEntries'), params)
    oGui.setEndOfDirectory()


def _getNextData(sUrl, sGui=False):
    # Holt das __NEXT_DATA__-JSON einer Netzkino-Seite und gibt das geparste dict zurück (oder None).
    # URL absichern: Slugs können Nicht-ASCII enthalten (z.B. "Teenie-Komödien-frontpage" mit ö).
    # Der ParameterHandler dekodiert eingehende sUrl via parse_qsl wieder zu rohem ö -> hier am
    # Request-Rand percent-encoden, sonst crasht http.client beim request.encode('ascii').
    sUrl = cParser.urlEncode(sUrl, "%:/?#[]@!$&'()*+,;=~")  # nur Nicht-ASCII kodieren, %XX/Struktur unberührt
    oRequest = cRequestHandler(sUrl, ignoreErrors=(sGui is not False))
    oRequest.cacheTime = 60 * 60 * 6  # 6 Stunden
    sHtmlContent = oRequest.request()
    isMatch, sJson = cParser.parseSingleResult(sHtmlContent, r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>')
    if not isMatch:
        return None
    try:
        return json.loads(sJson)
    except ValueError:
        return None


def _findQuery(oNext, sQueryName):
    # Sucht in __dehydratedState.queries nach der ersten Query mit passendem Namen und gibt deren state.data.data zurück.
    try:
        queries = oNext['props']['__dehydratedState']['queries']
    except (KeyError, TypeError):
        return None
    for q in queries:
        key = q.get('queryKey') or []
        if key and key[0] == sQueryName:
            try:
                return q['state']['data']['data']
            except (KeyError, TypeError):
                return None
    return None


def _getMovieNodes(oNext):
    # Liefert die Film-Nodes einer Seite, egal ob Frontpage (AllContent.featured.content)
    # oder Kategorie (CategoryDataBySlug.category.content).
    data = _findQuery(oNext, 'CategoryDataBySlug')
    if data:
        try:
            return data['category']['content']['nodes']
        except (KeyError, TypeError):
            pass
    data = _findQuery(oNext, 'AllContent')
    if data:
        try:
            return data['featured']['content']['nodes']
        except (KeyError, TypeError):
            pass
    return []


def _getSubcategoryNodes(oNext):
    # Liefert die Unterkategorien einer Kategorie-Seite. Beide Query-Formen
    # abdecken: CategoryDataBySlug (Kategorie-Seiten) traegt sie unter
    # category.subcategories, AllContent (Frontpage/Genre) unter
    # parentCategory.subcategories.
    data = _findQuery(oNext, 'CategoryDataBySlug')
    if data:
        try:
            nodes = data['category']['subcategories']['nodes']
            if nodes:
                return nodes
        except (KeyError, TypeError):
            pass
    data = _findQuery(oNext, 'AllContent')
    if data:
        try:
            return data['parentCategory']['subcategories']['nodes']
        except (KeyError, TypeError):
            pass
    return []


def _imageUrl(oMovie, *keys):
    # Gibt die masterUrl des ersten vorhandenen Bild-Feldes zurück.
    for k in keys:
        img = oMovie.get(k)
        if isinstance(img, dict) and img.get('masterUrl'):
            return img['masterUrl']
    return ''


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl:
        entryUrl = params.getValue('sUrl')
    oNext = _getNextData(entryUrl, sGui)
    if not oNext:
        if not sGui: oGui.showInfo()
        return
    nodes = _getMovieNodes(oNext)
    # Die Unterbereiche einer Kategorie (Dokus: History, Wissen, Terragonia ...)
    # kommen IMMER als Ordner vor die Filme, nicht nur wenn die Filmliste leer
    # ist. Gemessen 01.09.2026: die Unterbereiche sind KEINE Teilmenge der
    # Kategorieliste — Actionkino zeigt 285 Filme, seine zwoelf Unterbereiche
    # fuehren 1.463, davon 972 nirgends sonst; Dokus fuehrte nach einem
    # einzelnen direkten Film nur noch diesen einen Eintrag und versteckte
    # 657 Titel. Nur die 13 Genre-Kategorien haben Unterbereiche, die Reihen
    # der Hauptseite nicht; tiefer als eine Ebene geht die Seite nicht.
    # Bei der Suche (sGui/sSearchText) werden keine Ordner ausgegeben.
    subs = [] if (sGui or sSearchText) else _getSubcategoryNodes(oNext)
    if not nodes and not subs:
        if not sGui: oGui.showInfo()
        return
    for cat in subs:
        sTitle = str(cat.get('title') or '')
        sSlug = cat.get('slug') or ''
        if not sTitle or not sSlug:
            continue
        # frischer Handler je Ordner, sonst erben die Filme darunter sUrl/sMode
        subParams = ParameterHandler()
        subParams.setParam('sUrl', URL_CATEGORY % sSlug)
        subParams.setParam('sMode', 'category')
        oGui.addFolder(cGuiElement(sTitle, SITE_IDENTIFIER, 'showEntries'), subParams)

    total = len(nodes)
    for node in nodes:
        try:
            movie = node.get('contentMovie')
            if not movie:
                # Serien-Knoten: eigene Ebene ueber das GraphQL-Backend (Staffeln/Episoden)
                _addSeriesFolder(oGui, node, sSearchText, total)
                continue
            sSlug = movie.get('slug') or ''
            if not sSlug:
                continue  # ohne Slug keine Detailseite abrufbar
            sTitle = str(movie.get('title') or '')
            if sSearchText and not cParser.searchTitle(sSearchText, sTitle):
                continue
            oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showHosters')
            oGuiElement.setMediaType('movie')
            sThumb = _imageUrl(movie, 'coverImage', 'widescreenImage', 'headerImage')
            if sThumb:
                oGuiElement.setThumbnail(sThumb)
            sFanart = _imageUrl(movie, 'widescreenImage', 'headerImage', 'coverImage')
            if sFanart:
                oGuiElement.setFanart(sFanart)
            if movie.get('longSynopsis') or movie.get('shortSynopsis'):
                oGuiElement.setDescription(str(movie.get('longSynopsis') or movie.get('shortSynopsis')))
            if movie.get('productionYear'):
                oGuiElement.setYear(str(movie.get('productionYear')))
            # Slug an showHosters -> dort wird die Detailseite fuer die pmdUrl geladen
            params.setParam('sSlug', sSlug)
            params.setParam('mediaType', 'movie')
            oGui.addFolder(oGuiElement, params, False, total)
        except Exception:
            continue

    if not sGui:
        if nodes:
            oGui.setView('movies')
        oGui.setEndOfDirectory()


def showGenres():
    oGui = cGui()
    params = ParameterHandler()
    oNext = _getNextData(URL_GENRE)
    data = _findQuery(oNext, 'AllContent') if oNext else None
    nodes = []
    if data:
        try:
            nodes = data['parentCategory']['subcategories']['nodes']
        except (KeyError, TypeError):
            nodes = []
    if not nodes:
        oGui.showInfo()
        return
    for cat in nodes:
        sTitle = str(cat.get('title') or '')
        sSlug = cat.get('slug') or ''
        if not sTitle or not sSlug:
            continue
        params.setParam('sUrl', URL_CATEGORY % sSlug)
        params.setParam('sMode', 'category')
        oGui.addFolder(cGuiElement(sTitle, SITE_IDENTIFIER, 'showEntries'), params)
    oGui.setEndOfDirectory()


def _addSeriesFolder(oGui, node, sSearchText, total):
    # Legt fuer einen contentSeries-Knoten einen Ordner an, der in die Staffelauswahl fuehrt.
    series = node.get('contentSeries') or {}
    sSlug = series.get('slug') or ''
    sTitle = str(series.get('title') or '')
    if not sSlug or not sTitle:
        return
    if sSearchText and not cParser.searchTitle(sSearchText, sTitle):
        return
    params = ParameterHandler()
    oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showSeasons')
    oGuiElement.setMediaType('tvshow')
    sThumb = _imageUrl(series, 'coverImage', 'widescreenImage', 'headerImage24By9')
    if sThumb:
        oGuiElement.setThumbnail(sThumb)
    sFanart = _imageUrl(series, 'widescreenImage', 'headerImage24By9', 'coverImage')
    if sFanart:
        oGuiElement.setFanart(sFanart)
    if series.get('longSynopsis') or series.get('shortSynopsis'):
        oGuiElement.setDescription(str(series.get('longSynopsis') or series.get('shortSynopsis')))
    if series.get('productionYear'):
        oGuiElement.setYear(str(series.get('productionYear')))
    params.setParam('sSlug', sSlug)
    params.setParam('TVShowTitle', sTitle)
    if sThumb:
        params.setParam('sThumbnail', sThumb)
    oGui.addFolder(oGuiElement, params, True, total)


def _graphql(sQuery):
    # Fragt das GraphQL-Backend ab und gibt den 'data'-Teil zurueck (oder None).
    # POST mit JSON-Body: addParameters waere hier wirkungslos, der Handler liest
    # bei POST ausschliesslich data. Der Content-Type-Header muss gesetzt sein,
    # sonst schickt der Handler form-urlencoded und die Gegenstelle antwortet mit
    # einem Parse-Fehler.
    oRequest = cRequestHandler(URL_GRAPHQL, caching=False, method='POST',
                               data=json.dumps({'query': sQuery}))
    oRequest.addHeaderEntry('Content-Type', 'application/json')
    sResponse = oRequest.request()
    if not sResponse:
        return None
    try:
        jResponse = json.loads(sResponse)
    except ValueError:
        logger.info('[%s] GraphQL: Antwort ist kein JSON.' % SITE_NAME)
        return None
    if jResponse.get('errors'):
        logger.info('[%s] GraphQL meldet Fehler: %s' % (SITE_NAME, jResponse['errors']))
    return jResponse.get('data')


def _seasonNumber(season, iIndex):
    # Die API liefert seasonInSeries haeufig als null (bei mehrstaffligen Serien sogar
    # durchgehend). Ohne Nummer landen alle Folgen in einem Topf und die Folgennummern
    # kollidieren, weil jede Staffel wieder bei 1 beginnt. Deshalb der Reihe nach:
    # gemeldete Nummer -> Zahl aus dem Staffeltitel der Seite -> Position in der Liste.
    iSeason = season.get('seasonInSeries')
    if iSeason:
        return int(iSeason)
    isMatch, sNumber = cParser.parseSingleResult(str(season.get('title') or ''), r'(?:Staffel|Season)\s*(\d+)')
    if isMatch:
        return int(sNumber)
    return iIndex + 1


def _getSeriesEpisodes(sSlug):
    # Liefert alle Episoden einer Serie als flache Liste, sortiert nach Staffel und
    # Folge. Eine Abfrage je Serie — Staffeln und Episoden kommen zusammen zurueck.
    sQuery = ('{allCmsSeries(condition:{slug:"%s"}){nodes{title '
              'cmsSeasonsBySeriesId{nodes{seasonInSeries title '
              'cmsEpisodesBySeasonId{nodes{title episodeInSeason hasVideoSource '
              'videoSource{pmdUrl}}}}}}}}' % sSlug.replace('"', ''))
    data = _graphql(sQuery)
    if not data:
        return []
    try:
        seriesNodes = data['allCmsSeries']['nodes']
    except (KeyError, TypeError):
        return []
    episodes = []
    for series in seriesNodes:
        seasonNodes = (series.get('cmsSeasonsBySeriesId') or {}).get('nodes') or []
        for iIndex, season in enumerate(seasonNodes):
            iSeason = _seasonNumber(season, iIndex)
            for episode in ((season.get('cmsEpisodesBySeasonId') or {}).get('nodes') or []):
                sPmd = ((episode.get('videoSource') or {}).get('pmdUrl') or '').strip()
                if not sPmd:
                    continue  # ohne Stream-Pfad nicht abspielbar -> nicht anzeigen
                episodes.append({
                    'season': int(iSeason) if iSeason else 0,
                    'episode': int(episode.get('episodeInSeason') or 0),
                    'title': str(episode.get('title') or ''),
                    'pmdUrl': sPmd,
                })
    episodes.sort(key=lambda e: (e['season'], e['episode']))
    return episodes


def showSeasons():
    # Staffelauswahl einer Serie. Bei nur einer Staffel wird die Ebene uebersprungen
    # und direkt die Folgenliste gezeigt — die Episoden liegen ohnehin schon vor.
    oGui = cGui()
    params = ParameterHandler()
    sSlug = params.getValue('sSlug')
    if not sSlug:
        oGui.showInfo()
        return
    episodes = _getSeriesEpisodes(sSlug)
    if not episodes:
        oGui.showInfo()
        return
    seasons = sorted(set(e['season'] for e in episodes))
    if len(seasons) == 1:
        _listEpisodes(oGui, episodes, params)
        oGui.setView('episodes')
        oGui.setEndOfDirectory()
        return
    sName = params.getValue('TVShowTitle') or ''
    sThumbnail = params.getValue('sThumbnail') or ''
    total = len(seasons)
    for iSeason in seasons:
        oGuiElement = cGuiElement('%s %d' % (cConfig().getLocalizedString(30512), iSeason),
                                  SITE_IDENTIFIER, 'showEpisodes')
        oGuiElement.setMediaType('season')
        if sThumbnail:
            oGuiElement.setThumbnail(sThumbnail)
        if sName:
            oGuiElement.setTVShowTitle(sName)
        oGuiElement.setSeason(iSeason)
        p = ParameterHandler()
        p.setParam('sSlug', sSlug)
        p.setParam('season', iSeason)
        if sName:
            p.setParam('TVShowTitle', sName)
        if sThumbnail:
            p.setParam('sThumbnail', sThumbnail)
        oGui.addFolder(oGuiElement, p, True, total)
    oGui.setView('seasons')
    oGui.setEndOfDirectory()


def showEpisodes():
    # Folgen einer einzelnen Staffel.
    oGui = cGui()
    params = ParameterHandler()
    sSlug = params.getValue('sSlug')
    sSeason = params.getValue('season')
    if not sSlug:
        oGui.showInfo()
        return
    episodes = _getSeriesEpisodes(sSlug)
    if sSeason:
        episodes = [e for e in episodes if str(e['season']) == str(sSeason)]
    if not episodes:
        oGui.showInfo()
        return
    _listEpisodes(oGui, episodes, params)
    oGui.setView('episodes')
    oGui.setEndOfDirectory()


def _listEpisodes(oGui, episodes, params):
    # Gemeinsame Ausgabe fuer beide Wege (uebersprungene Staffelebene und Staffelordner).
    sName = params.getValue('TVShowTitle') or ''
    sThumbnail = params.getValue('sThumbnail') or ''
    total = len(episodes)
    for e in episodes:
        oGuiElement = cGuiElement(e['title'], SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setMediaType('episode')
        if sThumbnail:
            oGuiElement.setThumbnail(sThumbnail)
        if sName:
            oGuiElement.setTVShowTitle(sName)
        if e['season']:
            oGuiElement.setSeason(e['season'])
        if e['episode']:
            oGuiElement.setEpisode(e['episode'])
        p = ParameterHandler()
        # Stream-Pfad direkt mitgeben: showHosters hat dafuer bereits den entryUrl-Zweig.
        # pmdUrl bringt die Dateiendung mit, Pfade koennen Leerzeichen enthalten -> kodieren,
        # / behalten.
        p.setParam('entryUrl', URL_STREAM + cParser.urlEncode(e['pmdUrl'], safe='/'))
        p.setParam('mediaType', 'episode')
        if sName:
            p.setParam('TVShowTitle', sName)
        oGui.addFolder(oGuiElement, p, False, total)


def showHosters():
    hosters = []
    params = ParameterHandler()
    sSlug = params.getValue('sSlug')
    # Direkter Stream (z.B. aus der Suche) hat Vorrang
    sDirect = params.getValue('entryUrl')
    if sDirect:
        for sUrl in sDirect.split('#'):
            if not sUrl:
                continue
            sName = 'Netzkino' if 'netzkino' in sUrl else 'Youtube'
            hosters.append({'link': sUrl, 'name': sName, 'resolveable': True})
        if hosters:
            hosters.append('getHosterUrl')
        return hosters
    # Sonst: Detailseite per Slug laden und pmdUrl ziehen
    if sSlug:
        oNext = _getNextData(URL_DETAIL % sSlug)
        data = _findQuery(oNext, 'MovieDetails') if oNext else None
        if data:
            movie = data.get('movie') or {}
            vs = movie.get('videoSource') or {}
            pmdUrl = vs.get('pmdUrl') or ''
            if pmdUrl:
                # Next.js-pmdUrl enthaelt bereits die Dateiendung -> direkt anhaengen
                # Pfad kann Leerzeichen enthalten (z.B. "OneGate Media/...") -> kodieren, / behalten
                hosters.append({'link': URL_STREAM + cParser.urlEncode(pmdUrl, safe='/'), 'name': 'Netzkino', 'resolveable': True})
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def getHosterUrl(sUrl=False):
    return [{'streamUrl': sUrl, 'resolved': True}]


def showSearch():
    win = xbmcgui.Window(10000)
    sSearchText = win.getProperty('xstream.netzkino.lastSearchText')
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30287))
        if not sSearchText:
            return
        win.setProperty('xstream.netzkino.lastSearchText', sSearchText)
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def _titleKey(sTitle):
    """Vergleichsschluessel zum Entdoppeln zwischen capi und GraphQL.

    Beide Quellen schreiben denselben Film leicht unterschiedlich (Bindestriche,
    Gross-/Kleinschreibung, Sonderzeichen), deshalb wird auf Buchstaben und
    Ziffern reduziert.
    """
    return re.sub(r'[^0-9a-z]+', '', (sTitle or '').lower())


# Pause vor jedem Nachholversuch: gibt einem Rate-Limit Luft. Laenger kostet
# nur im Fehlerfall — im Normalfall laeuft keine einzige Pause.
RETRY_PAUSE = 0.6


def _graphqlMovieSearch(sSearchText, iLimit=50):
    """Filme ueber das GraphQL-Backend suchen.

    Ergaenzung zur capi-Suche, die eigene Katalogtitel nicht findet. Sucht im
    TITEL (includesInsensitive) — deshalb ersetzt sie die capi nicht, sondern
    kommt dazu: die capi durchsucht auch Beschreibungen und liefert bei
    allgemeinen Begriffen mehr.
    """
    if not sSearchText:
        return []
    # Der GraphQL-Weg ist eine ERGAENZUNG. Faellt er aus — egal wie —, muss die
    # capi-Suche trotzdem ihre Treffer zeigen. Ohne dieses Netz reisst eine
    # Exception hier die ganze Suchliste mit (nachgestellt: 0 statt 26 Treffer).
    try:
        sSafe = str(sSearchText).replace('\\', '').replace('"', '')
        sQuery = ('{allCmsMovies(filter:{title:{includesInsensitive:"%s"}} first:%d)'
                  '{nodes{title slug productionYear videoSource{pmdUrl} coverImage{masterUrl}}}}'
                  % (sSafe, iLimit))
        jData = _graphql(sQuery)
        if not jData:
            # Der Arm fiel bei einem Aussetzer bisher STILL aus — die Suche
            # zeigte dann nur die capi-Treffer (sichtbar als 26 statt 27 bei
            # "Joe"). Einmal mit Pause nachfassen.
            time.sleep(RETRY_PAUSE)
            jData = _graphql(sQuery)
            if not jData:
                logger.info('searchRetry %s: GraphQL-Arm nicht erreichbar, Suche zeigt nur capi-Treffer' % SITE_NAME)
                return []
            logger.info('searchRetry %s: GraphQL-Arm nachgeholt' % SITE_NAME)
        return jData['allCmsMovies']['nodes'] or []
    except Exception:
        logger.info('[%s] GraphQL-Suche uebersprungen, capi-Treffer bleiben.' % SITE_NAME)
        return []


def _search(oGui, sSearchText):
    _showSearchEntries(URL_SEARCH % cParser.quotePlus(sSearchText), oGui, sSearchText)


def _showSearchEntries(entryUrl, sGui=False, sSearchText=False):
    # Suche läuft über die simplecache-API (anderes JSON-Format als die Website).
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    sResponse = oRequest.request()
    aPosts = []
    if sResponse:
        try:
            jSearch = json.loads(sResponse)
            if isinstance(jSearch, dict):
                aPosts = jSearch.get('posts') or []
        except ValueError:
            aPosts = []

    # Die capi-Suche hat Luecken: eigene Katalogtitel wie "Crypto",
    # "Ultimate Justice" oder "Beyond the Sky" liefert sie mit NULL Treffern,
    # obwohl sie in "Neu bei Netzkino" stehen. Das GraphQL-Backend — dasselbe,
    # ueber das die Serien laufen — findet sie. Umgekehrt durchsucht die capi
    # auch Beschreibungen und findet dort mehr ("Joe" 26 gegen 3). Keiner der
    # beiden Wege ist vollstaendig, deshalb werden BEIDE abgefragt und
    # zusammengefuehrt statt getauscht (gemessen 31.08.2026).
    aExtra = _graphqlMovieSearch(sSearchText) if sSearchText else []

    if not aPosts and not aExtra:
        if not sGui: oGui.showInfo()
        return

    total = len(aPosts) + len(aExtra)
    seen = set()
    for item in aPosts:
        try:
            sTitle = str(item['title'])
            cf = item.get('custom_fields') or {}
            sStreaming = ''
            if cf.get('Streaming') and cf['Streaming'][0]:
                sStreaming = cf['Streaming'][0]
            sYoutube = ''
            if cf.get('Youtube_Delivery_Id') and cf['Youtube_Delivery_Id'][0]:
                sYoutube = cf['Youtube_Delivery_Id'][0]
            if not sStreaming and not sYoutube:
                continue
            oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showHosters')
            oGuiElement.setMediaType('movie')
            if item.get('thumbnail'):
                oGuiElement.setThumbnail(str(item['thumbnail']))
            if item.get('content'):
                oGuiElement.setDescription(str(item['content']))
            if cf.get('featured_img_all') and cf['featured_img_all'][0]:
                oGuiElement.setFanart(str(cf['featured_img_all'][0]))
            if cf.get('Jahr') and cf['Jahr'][0]:
                oGuiElement.setYear(str(cf['Jahr'][0]))
            if cf.get('Adaptives_Streaming') and cf['Adaptives_Streaming'][0]:
                oGuiElement.setQuality(str(cf['Adaptives_Streaming'][0]))
            urls = ''
            if sStreaming:
                # Alte API liefert pmdUrl OHNE .mp4 -> hier anhängen
                # Pfad kann Leerzeichen enthalten -> kodieren, / behalten, .mp4 danach
                urls += URL_STREAM + cParser.urlEncode(sStreaming, safe='/') + '.mp4'
            if sYoutube:
                urls += ('#' if urls else '') + 'plugin://plugin.video.youtube/play/?video_id=%s' % sYoutube
            params.setParam('entryUrl', urls)
            params.setParam('mediaType', 'movie')
            oGui.addFolder(oGuiElement, params, False, total)
            seen.add(_titleKey(sTitle))
        except Exception:
            continue

    # GraphQL-Treffer anhaengen, die die capi nicht geliefert hat. Aufgeloest
    # wird ueber sSlug — den Weg kann showHosters bereits, es braucht also
    # keinen zweiten Auflösungspfad.
    for m in aExtra:
        try:
            sTitle = str(m.get('title') or '')
            sSlug = str(m.get('slug') or '')
            if not sTitle or not sSlug or _titleKey(sTitle) in seen:
                continue
            seen.add(_titleKey(sTitle))
            oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showHosters')
            oGuiElement.setMediaType('movie')
            oCover = m.get('coverImage') or {}
            if oCover.get('masterUrl'):
                oGuiElement.setThumbnail(str(oCover['masterUrl']))
            if m.get('productionYear'):
                oGuiElement.setYear(str(m['productionYear']))
            oParams = ParameterHandler()
            oVideo = m.get('videoSource') or {}
            sPmd = str(oVideo.get('pmdUrl') or '')
            if sPmd:
                # ACHTUNG: die pmdUrl aus GraphQL traegt das .mp4 bereits, die
                # der capi NICHT. Hier also nichts anhaengen, sonst entsteht
                # ".mp4.mp4" und der Titel laesst sich nicht abspielen.
                oParams.setParam('entryUrl', URL_STREAM + cParser.urlEncode(sPmd, safe='/'))
            else:
                oParams.setParam('sSlug', sSlug)
            oParams.setParam('mediaType', 'movie')
            oGui.addFolder(oGuiElement, oParams, False, total)
        except Exception:
            continue

    if not sGui:
        oGui.setView('movies')
        oGui.setEndOfDirectory()
