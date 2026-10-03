# -*- coding: utf-8 -*-
# Python 3
#
# Always pay attention to the translations in the menu!
#
# API Seite: EIN Backend hinter vielen Spiegel-Domains (Stand 09/2026 dreizehn,
# alle mit demselben Katalog). Die Default-Domain steht unten; wer einen anderen
# Spiegel will, traegt ihn in den Einstellungen ein (plugin_api_sites.domain).
# Die Schnittstelle liefert JSON:
#   /data/browse/  Listen (type=movies|tvseries, order_by=releases) und die
#                  Titelsuche (keyword=...), beide mit pager.currentPage/totalPages
#   /data/watch/   die Streams eines Titels (Serien: Folgen ueber das Feld "e",
#                  Staffel ueber "s", Sprache der Serie ueber "lang")
#   /data/seasons/ alle Staffeln einer Serie (lang + original_title) — die Listen
#                  fuehren jede Staffel als eigenen Eintrag, der Staffelwaehler der
#                  Seite kommt von hier
# Nur die Standardliste (order_by=releases) ist bis zur letzten Seite gefuellt —
# jede andere Sortierung der API (name, updates, trending, views, rating) meldet
# tausende Seiten und liefert nur die ersten paar Dutzend (gemessen 11.09.2026).
# Deshalb gibt es hier genau die drei Punkte Filme, Serien und Suche.
# Sprache: die Seite laeuft hier NUR AUF DEUTSCH (Jack 13.09.2026) — Listen, Suche und
# Staffeln fragen die API fest mit lang=2 ab (LANG unten). Die Einstellung "Bevorzugte
# Sprache" wird hier nicht gelesen, das Menue ist bei jeder Einstellung dasselbe.
# Cache: Listen und Folgenlisten laufen ueber den normalen HTML-Cache aus den
# Einstellungen (Default 12 Stunden), die Hosterliste holt immer frisch.

import re
import xbmcgui
import resolveurl as resolver
from urllib.parse import quote
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger

SITE_IDENTIFIER = 'api_sites'
SITE_NAME = 'API Seite'
SITE_ICON = 'api_sites.png'
DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'megakino.to')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)
URL_MAIN = 'https://' + DOMAIN
URL_LIST = URL_MAIN + '/data/browse/?lang=%s&type=%s&order_by=releases&page=%s'
URL_SEARCH = URL_MAIN + '/data/browse/?lang=%s&keyword=%s&page=%s'
URL_WATCH = URL_MAIN + '/data/watch/?_id=%s'
URL_SEASONS = URL_MAIN + '/data/seasons/?lang=%s&original_title=%s'
URL_THUMBNAIL = 'https://image.tmdb.org/t/p/w300%s'
# Sprachfilter der API: 2 = Deutsch, 3 = Englisch, all = alles. Hier fest Deutsch —
# nur deutsche Titel, ohne Kopplung an "Bevorzugte Sprache" (Jack 13.09.2026).
LANG = '2'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

# Serien fuehrt die API je Staffel als eigenen Eintrag, die Staffel steht nur im
# Titel: "Name - Staffel 1", "Name  - Staffel 1", "Name - Season 3", "Name: Season 8".
# Dasselbe Muster nutzt das Frontend der Seite selbst, um den Serientitel zu bilden.
_RE_SEASON_SUFFIX = re.compile(r'\s*[-\u2013:]?\s*(?:Staffel|Season)\s*\d+\s*$')
# Qualitaet aus dem Release-Namen der Streams ("...GERMAN.DL.1080P.WEB.X264-WAYNE"):
# erst eine Aufloesung, sonst die Quelle. Ganze Token, sonst trifft TS auch YTS.
_RE_RESOLUTION = re.compile(r'\b(2160p|1440p|1080p|720p|480p|360p)\b', re.I)
_RE_SOURCE = re.compile(r'\b(BluRay|BDRip|BRRip|WEB-DL|WEBRip|WEB|HDTV|HDRip|DVDRip|HDCAM|CAM|TS|HD|SD)\b', re.I)


def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.%s.lastSearchText' % SITE_IDENTIFIER)
    params = ParameterHandler()
    params.setParam('sUrl', URL_LIST % (LANG, 'movies', 1))
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30502), SITE_IDENTIFIER, 'showEntries'), params)  # Filme
    params = ParameterHandler()
    params.setParam('sUrl', URL_LIST % (LANG, 'tvseries', 1))
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30511), SITE_IDENTIFIER, 'showEntries'), params)  # Serien
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'))  # Suche
    cGui().setEndOfDirectory()


def _fetchJson(sUrl, sHost, caching, ignoreErrors):
    # Adressen kommen ROH an (der Parameterweg dekodiert alles) und werden erst hier
    # kodiert: Leerzeichen und Umlaute im Suchbegriff, '#' als %23 (sonst kappt urllib
    # ab dem Fragment). '+' bleibt ein Pluszeichen im Begriff, kein Leerzeichen; '%'
    # bleibt stehen, damit ein schon kodierter Wert (Serientitel bei /data/seasons/)
    # nicht doppelt kodiert wird.
    oRequest = cRequestHandler(quote(sUrl, safe=':/?&=%'), caching=caching, ignoreErrors=ignoreErrors)
    oRequest.addHeaderEntry('Referer', 'https://' + sHost + '/')
    oRequest.addHeaderEntry('Origin', 'https://' + sHost)
    return oRequest.requestJson(), oRequest.getStatus()


def _apiRequest(sUrl, caching=True, ignoreErrors=False):
    # Ein Abruf ueber die eingestellte Domain, der requestHandler meldet wie ueberall —
    # auf dem Nutzerweg mit Fenster bzw. Einblendung, in der globalen Suche still
    # (ignoreErrors kommt vom Aufrufer). Keine zweite Stufe: ein Cache-Buster gegen
    # einen von Cloudflare festgehaltenen Origin-404 wuerde eine Adresse mit unbekanntem
    # Parameter schicken, und die laesst das Backend haengen (gemessen 24.09.2026) —
    # er kostete nur einen weiteren Timeout.
    return _fetchJson(sUrl, DOMAIN, caching, ignoreErrors)[0]


def _isSeries(sTitle):
    return bool(_RE_SEASON_SUFFIX.search(sTitle))


def _seriesTitle(sTitle):
    # Serienname ohne den Staffel-Zusatz — fuer TVShowTitle (Weitere Quellen,
    # Trailer, TMDB-Info suchen damit die Serie statt "Folge 8").
    return _RE_SEASON_SUFFIX.sub('', sTitle).strip()


def _thumbnail(movie):
    for sKey in ('poster_path_season', 'poster_path', 'backdrop_path'):
        if movie.get(sKey):
            return URL_THUMBNAIL % str(movie[sKey])
    return ''


def _pageUrl(sUrl, iPage):
    return re.sub(r'([?&]page=)\d+', r'\g<1>%d' % iPage, sUrl)


def _getQuality(sRelease):
    isMatch = _RE_RESOLUTION.search(sRelease) or _RE_SOURCE.search(sRelease)
    return isMatch.group(1) if isMatch else ''


def _streamKey(sLink):
    # Vergleichsschluessel fuer den Dubletten-Schnitt in showHosters: die API fuehrt denselben
    # Link dutzendfach mit Tracking-Anhang (?zzz1, ?hh2, /fme3, Zufallsstring) und auf
    # Spiegel-Domains desselben Hosters — gemessen 13.09.2026: 741 Streams, 142 Dateien.
    # Ob es dieselbe Datei ist, entscheidet ResolveURL selbst: Resolver plus Media-ID aus
    # dessen Muster. Kein eigenes Suffix-Wissen — aendert die API den Anhang, aendert sich
    # hier nichts. Liefert ResolveURL keine ID, ist der Link selbst der Schluessel, der
    # Eintrag bleibt dann in jedem Fall stehen.
    try:
        oMediaFile = resolver.HostedMediaFile(url=sLink)
        if oMediaFile.valid_url():
            oResolver = oMediaFile.get_resolvers(validated=True)[0]
            aHostId = oResolver.get_host_and_id(sLink)
            if aHostId and aHostId[1]:
                return (oResolver.name, aHostId[1])
    except Exception:
        pass
    return sLink


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl:
        entryUrl = params.getValue('sUrl')
    aJson = _apiRequest(entryUrl, ignoreErrors=(sGui is not False))
    # Hinter dem Listenende antwortet die API mit movies=0 (Zahl statt Liste)
    aMovies = aJson.get('movies') if isinstance(aJson, dict) else None
    if not isinstance(aMovies, list) or not aMovies:
        if not sGui:
            oGui.showInfo()
        return

    total = len(aMovies)
    iSeries = 0
    for movie in aMovies:
        if '_id' not in movie:
            continue
        sTitle = ' '.join(str(movie.get('title', '')).split())   # doppelte und randstaendige Leerzeichen der API
        if not sTitle:
            continue
        isTvshow = _isSeries(sTitle)
        oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showSeasons' if isTvshow else 'showHosters')
        sThumbnail = _thumbnail(movie)
        if sThumbnail:
            oGuiElement.setThumbnail(sThumbnail)
        sYear = str(movie.get('year', ''))
        if len(sYear) == 4:
            oGuiElement.setYear(sYear)
        try:
            if float(movie.get('rating') or 0) > 0:
                oGuiElement.addItemValue('rating', movie['rating'])
        except (TypeError, ValueError):
            pass
        # Genre liefert die API je Eintrag mit (Text oder Liste), kein Abruf noetig
        aGenres = movie.get('genres')
        if isinstance(aGenres, list):
            aGenres = ', '.join(str(g).strip() for g in aGenres if str(g).strip())
        if aGenres:
            oGuiElement.addItemValue('genre', str(aGenres).strip())
        oGuiElement.setMediaType('tvshow' if isTvshow else 'movie')
        if isTvshow:
            iSeries += 1
            oGuiElement.setTVShowTitle(_seriesTitle(sTitle))
        params.setParam('entryUrl', URL_WATCH % str(movie['_id']))
        params.setParam('sName', sTitle)
        params.setParam('sThumbnail', sThumbnail)
        oGui.addFolder(oGuiElement, params, isTvshow, total)

    if not sGui:
        # Beleg fuer die Folgeseite ist der pager der Antwort, daraus auch die Seitenlage
        pager = aJson.get('pager') or {}
        try:
            iPage, iLast = int(pager.get('currentPage') or 0), int(pager.get('totalPages') or 0)
        except (TypeError, ValueError):
            iPage, iLast = 0, 0
        if iPage and iPage < iLast:
            params = ParameterHandler()
            params.setParam('sUrl', _pageUrl(entryUrl, iPage + 1))
            oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', params, cGui.pageInfo(iPage, iLast))
        oGui.setView('tvshows' if iSeries == total else 'movies')
        oGui.setEndOfDirectory()


def showSeasons():
    # Staffelebene wie auf der Seite: die Liste fuehrt jede Staffel als eigenen Eintrag,
    # /data/seasons/ liefert alle Staffeln der Serie. Dafuer braucht die API die Sprache
    # der Serie (steht in der watch-Antwort, die fuer die Folgen ohnehin faellig ist;
    # fehlt sie, gilt Deutsch wie fuer die Listen).
    # Nur eine Staffel oder keine Antwort: direkt die Folgen des angeklickten Eintrags.
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    sThumbnail = params.getValue('sThumbnail')
    sName = params.getValue('sName') or ''
    aJson = _apiRequest(sUrl)
    if not isinstance(aJson, dict):
        cGui().showInfo()
        return
    sLang = str(aJson.get('lang') or '')
    if sLang not in ('2', '3'):
        sLang = LANG
    sShowName = str(aJson.get('original_title') or '').strip() or _seriesTitle(sName)
    aSeasons = None
    if sLang in ('2', '3') and sShowName:
        aSeasons = _apiRequest(URL_SEASONS % (sLang, quote(sShowName, safe='')))
    aSeasons = [x for x in aSeasons if isinstance(x, dict) and x.get('_id')] if isinstance(aSeasons, list) else []
    if len(aSeasons) < 2:
        _showEpisodes(sUrl, sName, sThumbnail, aJson)
        return
    aSeasons.sort(key=lambda x: int(x.get('s') or 0))
    total = len(aSeasons)
    for season in aSeasons:
        sSeason = str(season.get('s') or '')
        sSeasonTitle = ' '.join(str(season.get('title', '')).split())
        oGuiElement = cGuiElement('%s %s' % (cConfig().getLocalizedString(30512), sSeason), SITE_IDENTIFIER, 'showEpisodes')
        sSeasonThumb = _thumbnail(season) or sThumbnail
        oGuiElement.setThumbnail(sSeasonThumb)
        if sSeason:
            oGuiElement.setSeason(sSeason)
        oGuiElement.setTVShowTitle(sShowName)
        oGuiElement.setMediaType('season')
        params.setParam('entryUrl', URL_WATCH % str(season['_id']))
        params.setParam('sName', sSeasonTitle or sName)
        params.setParam('sThumbnail', sSeasonThumb)
        cGui().addFolder(oGuiElement, params, True, total)
    cGui().setView('seasons')
    cGui().setEndOfDirectory()


def showEpisodes():
    params = ParameterHandler()
    _showEpisodes(params.getValue('entryUrl'), params.getValue('sName') or '', params.getValue('sThumbnail'))


def _showEpisodes(sUrl, sName, sThumbnail, aJson=None):
    params = ParameterHandler()
    params.setParam('entryUrl', sUrl)
    params.setParam('sName', sName)
    params.setParam('sThumbnail', sThumbnail)
    sShowName = _seriesTitle(sName)
    if aJson is None:
        aJson = _apiRequest(sUrl)
    aStreams = aJson.get('streams') if isinstance(aJson, dict) else None
    if not isinstance(aStreams, list) or not aStreams:
        cGui().showInfo()
        return
    # jede Folge einmal, aufsteigend — die Streams liegen unsortiert und mehrfach je Folge vor
    aEpisodes = sorted(set(int(stream['e']) for stream in aStreams if str(stream.get('e', '')).isdigit()))
    if not aEpisodes:
        cGui().showInfo()
        return
    sSeason = str(aJson.get('s') or '')
    total = len(aEpisodes)
    for iEpisode in aEpisodes:
        oGuiElement = cGuiElement('%s %d' % (cConfig().getLocalizedString(30513), iEpisode), SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setThumbnail(sThumbnail)
        if sSeason:
            oGuiElement.setSeason(sSeason)
        oGuiElement.setEpisode(iEpisode)
        if sShowName:
            oGuiElement.setTVShowTitle(sShowName)
        oGuiElement.setMediaType('episode')
        cGui().addFolder(oGuiElement, params, False, total)
    cGui().setView('episodes')
    cGui().setEndOfDirectory()


def showHosters():
    hosters = []
    seen = set()
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    sEpisode = params.getValue('episode')
    aJson = _apiRequest(sUrl, caching=False)
    aStreams = aJson.get('streams') if isinstance(aJson, dict) else None
    if not isinstance(aStreams, list):
        return hosters
    for stream in aStreams:
        sLink = str(stream.get('stream', '')).strip()
        if not sLink.startswith('http'):
            continue
        # Folgen: nur die Streams dieser Folge; Streams ohne Folgennummer gehoeren dem Film
        if 'e' in stream and str(stream['e']) != str(sEpisode):
            continue
        # Geprueft wird die ADRESSE, nicht ein Namensfetzen: nur was ResolveURL
        # tatsaechlich kennt, kommt in die Liste (Kurzlinks und fremde Hosts nicht)
        isBlocked, sHostName = cConfig().isBlockedHoster(sLink)
        if isBlocked:
            continue
        # Dieselbe Datei nur einmal, der erste Eintrag gewinnt (Schluessel: _streamKey).
        # Ohne den Schnitt probiert der Auto-Modus eine tote Datei so oft, wie die API
        # sie listet — bis zu 85x dieselbe ID hintereinander.
        sKey = _streamKey(sLink)
        if sKey in seen:
            continue
        seen.add(sKey)
        sName = sHostName.split('.')[0]
        sQuality = _getQuality(str(stream.get('release', '')).strip())
        if sQuality:
            sName += ' [%s]' % sQuality
        hosters.append({'link': sLink, 'name': sName})
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def getHosterUrl(sUrl=False):
    return [{'streamUrl': sUrl, 'resolved': False}]


def showSearch():
    win = xbmcgui.Window(10000)
    sKey = 'xstream.%s.lastSearchText' % SITE_IDENTIFIER
    sSearchText = win.getProperty(sKey)
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30281))
        if not sSearchText:
            return
        win.setProperty(sKey, sSearchText)
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def _search(oGui, sSearchText):
    # Titelsuche der API, serverseitig mit Blaettern; Filme und Serien gemischt wie auf
    # der Seite. Kein eigener Titelfilter: die Schnittstelle sucht selbst nur im Titel.
    # Der Begriff bleibt roh in der Adresse — kodiert wird in _apiRequest, damit die
    # Folgeseite (Adresse aus dem Parameter, dort dekodiert) genauso laeuft wie Seite 1.
    showEntries(URL_SEARCH % (LANG, sSearchText, 1), oGui, sSearchText)
