# -*- coding: utf-8 -*-
# Python 3


# Always pay attention to the translations in the menu!

import re
import xbmcgui
from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger
from resources.lib.tools import cParser
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui

SITE_IDENTIFIER = 'einschalten'
SITE_NAME = 'Einschalten'
SITE_ICON = 'einschalten.png'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'einschalten.in')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)

URL_MAIN = 'https://' + DOMAIN
URL_NEW_MOVIES = URL_MAIN + '/movies/new'
URL_LAST_MOVIES = URL_MAIN + '/movies/recently-added'
URL_ALL_MOVIES = URL_MAIN + '/movies'           # „Alle Filme“ der Seite
URL_GENRES = URL_MAIN + '/genres'                # Genre-Uebersicht der Seite, Listen unter /genres/<id>
URL_COLLECTIONS = URL_MAIN + '/collections'
URL_SEARCH = URL_MAIN + '/search?query=%s'
URL_THUMBNAIL = URL_MAIN + '/api/image/poster'


def _hasNextPage(sHtmlContent, iPage):
    """Bietet die Seite selbst eine Folgeseite an?

    Die Blaetter-Leiste der Seite laesst den "Weiter"-Link auf der letzten Seite weg
    (gemessen: Sammlungen Seite 27 verlinkt 26 und 28, Seite 28 nur noch 27). Ohne
    diese Pruefung stand am Listenende ein Weiter-Eintrag, der nur zu "Es wurde kein
    Eintrag gefunden" fuehrte. Kostet keinen Zusatzabruf — der Link steht in der
    Antwort, die ohnehin schon geladen ist.
    """
    if not sHtmlContent:
        return False
    # Anker auf href, damit nur echte Blaetter-Links zaehlen und nicht irgendein
    # "page=29" aus einem Datenattribut. Das schliessende Anfuehrungszeichen gehoert
    # ins Muster, sonst trifft page=2 auch auf page=20.
    return bool(re.search(r'href="[^"]*[?&]page=%d"' % (iPage + 1), sHtmlContent))


def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.einschalten.lastSearchText')
    params = ParameterHandler()
    params.setParam('sUrl', URL_NEW_MOVIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30501), SITE_IDENTIFIER, 'showEntries'), params)  # Aktuelle Releases
    params.setParam('sUrl', URL_LAST_MOVIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30500), SITE_IDENTIFIER, 'showEntriesLast'), params)  # Neues
    # Seit 2026.09.10 (Kategorien-Durchgang): die zwei Bereiche der Seiten-Navigation,
    # die noch fehlten — „Alle Filme“ und „Genres“; beide nutzen das Karten-Markup
    # der uebrigen Listen, showEntries liest sie unveraendert
    params.setParam('sUrl', URL_ALL_MOVIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30502), SITE_IDENTIFIER, 'showEntries'), params)  # Filme
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30506), SITE_IDENTIFIER, 'showGenres'), params)  # Genre
    params.setParam('sUrl', URL_COLLECTIONS)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30543), SITE_IDENTIFIER, 'showCollections'), params)  # Collections
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'), params)   # Search
    cGui().setEndOfDirectory()


def showGenres():
    """Genre-Uebersicht der Seite: Kacheln mit `title="<Genre>" href="/genres/<id>"`.

    Die Namen kommen von der Seite (TMDb-Schema, deutsch), nichts steht fest im
    Code. Jede Genreliste blaettert wie die anderen ueber ?page=N.
    """
    oGui = cGui()
    params = ParameterHandler()
    sHtmlContent = cRequestHandler(URL_GENRES).request()
    isMatch, aResult = cParser.parse(sHtmlContent, r'title="([^"]+)"\s+href="(/genres/\d+)"')
    if not isMatch:
        oGui.showInfo()
        return
    seen = set()
    for sName, sPath in aResult:
        if sPath in seen:
            continue
        seen.add(sPath)
        params.setParam('sUrl', URL_MAIN + sPath)
        oGui.addFolder(cGuiElement(sName.strip(), SITE_IDENTIFIER, 'showEntries'), params)
    oGui.setEndOfDirectory()


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl: entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    iPage = int(params.getValue('page'))
    
    separator = '&' if '?' in entryUrl else '?'
    sUrl = entryUrl + separator + 'page=' + str(iPage) if iPage > 0 else entryUrl
    
    oRequest = cRequestHandler(sUrl, ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()
    # Der Match darf die Objektgrenze nicht ueberschreiten ([^{}] statt .*?): im
    # ng-state steht vor den Filmen oft das Kollektionsobjekt mit seinem Genre-Array
    # ({"id":27,"name":"Horror"}), und ein offenes .*? lief von dessen id bis zum
    # Titel des ersten Films - der bekam dann die Genre-ID und endete in einem
    # 404 auf /api/movies/27/watch (20 von 31 Kollektionen, Audit 01.09.2026).
    pattern = '{"id":([^,"]+)[^{}]*?"title":"([^"]+)[^{}]*?Date":"([^-]+)[^{}]*?"posterPath":"([^"]+)[^{}]*?collectionId":([^}]+)'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    total = len(aResult)
    iShown = 0
    for sUrl, sName, sYear, sThumbnail, sDummy in aResult:
        if sSearchText and not cParser.searchTitle(sSearchText, sName):
            continue
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setYear(sYear)
        oGuiElement.setThumbnail(URL_THUMBNAIL + sThumbnail)
        oGuiElement.setMediaType('movie')
        params.setParam('sName', sName)
        params.setParam('sThumbnail', sThumbnail)
        params.setParam('entryUrl', sUrl)
        oGui.addFolder(oGuiElement, params, False, total)
        iShown += 1
    # Kamen Treffer an, wurden aber ALLE vom Titelfilter verworfen, stand
    # hier bisher ein leeres Verzeichnis ohne Hinweis (belegt mit "2019").
    # BEWUSST VOR dem Pagination-Block: dessen Bedingung schliesst die Suche
    # aus, die Meldung wuerde dort nie erreicht.
    if not sGui and not iShown:
        oGui.showInfo()
    if not sGui and not sSearchText:
        sPageNr = int(params.getValue('page'))
        if sPageNr == 0:
            sPageNr = 2
        else:
            sPageNr += 1
        if _hasNextPage(sHtmlContent, sPageNr - 1):
            params.setParam('page', int(sPageNr))
            params.setParam('sUrl', entryUrl)
            oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', params)
        oGui.setView('movies')
        oGui.setEndOfDirectory()


def showCollections(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl: entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    iPage = int(params.getValue('page'))
    
    separator = '&' if '?' in entryUrl else '?'
    sUrl = entryUrl + separator + 'page=' + str(iPage) if iPage > 0 else entryUrl
    
    oRequest = cRequestHandler(sUrl, ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()
    # Gleiche Objektgrenze wie bei den Filmlisten: ein Genre-Objekt ({"id":27,"name":"Horror"})
    # traegt kein posterPath, mit [^{}] kann der Match dort nicht haengenbleiben.
    pattern = '{"id":([^,"]+)[^{}]*?"name":"([^"]+)[^{}]*?"posterPath":"([^"]+)'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    total = len(aResult)
    for sUrl, sName, sThumbnail in aResult:
        if sSearchText and not cParser.searchTitle(sSearchText, sName):
            continue
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER,'showCollectionEntries')
        oGuiElement.setThumbnail(URL_THUMBNAIL + sThumbnail)
        oGuiElement.setMediaType('movie')
        params.setParam('sName', sName)
        params.setParam('sThumbnail', sThumbnail)
        params.setParam('entryUrl', sUrl)
        oGui.addFolder(oGuiElement, params, total)
    if not sGui and not sSearchText:
        sPageNr = int(params.getValue('page'))
        if sPageNr == 0:
            sPageNr = 2
        else:
            sPageNr += 1
        if _hasNextPage(sHtmlContent, sPageNr - 1):
            params.setParam('page', int(sPageNr))
            params.setParam('sUrl', entryUrl)
            oGui.addNextPage(SITE_IDENTIFIER, 'showCollections', params)
        oGui.setView('movies')
        oGui.setEndOfDirectory()


def showCollectionEntries(sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    entryUrl = URL_COLLECTIONS + '/' + params.getValue('entryUrl')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()
    # Objektgrenze [^{}] statt .*? — Begruendung am Muster in showEntries.
    pattern = '{"id":([^,"]+)[^{}]*?"title":"([^"]+)[^{}]*?Date":"([^-]+)[^{}]*?"posterPath":"([^"]+)[^{}]*?collectionId":([^}]+)'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        if not sGui: oGui.showInfo()
        return
    total = len(aResult)
    for sUrl, sName, sYear, sThumbnail, sDummy in aResult:
        if sSearchText and not cParser.searchTitle(sSearchText, sName):
            continue
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setYear(sYear)
        oGuiElement.setThumbnail(URL_THUMBNAIL + sThumbnail)
        oGuiElement.setMediaType('movie')
        params.setParam('sName', sName)
        params.setParam('sThumbnail', sThumbnail)
        params.setParam('entryUrl', sUrl)
        oGui.addFolder(oGuiElement, params, False, total)
    if not sGui and not sSearchText:
        params.setParam('sUrl', entryUrl)
        oGui.setView('movies')
        oGui.setEndOfDirectory()


def showEntriesLast(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl: entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    iPage = int(params.getValue('page'))
    
    separator = '&' if '?' in entryUrl else '?'
    sUrl = entryUrl + separator + 'page=' + str(iPage) if iPage > 0 else entryUrl
    
    oRequest = cRequestHandler(sUrl, ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()
    # Objektgrenze [^{}] statt .*? — Begruendung am Muster in showEntries.
    pattern = '{"id":([^,"]+)[^{}]*?"title":"([^"]+)[^{}]*?Date":"([^-]+)[^{}]*?"posterPath":"([^"]+)[^{}]*?collectionId":([^}]+)'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    total = len(aResult)
    for sUrl, sName, sYear, sThumbnail, sDummy in aResult:
        if sSearchText and not cParser.searchTitle(sSearchText, sName):
            continue
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setYear(sYear)
        oGuiElement.setThumbnail(URL_THUMBNAIL + sThumbnail)
        oGuiElement.setMediaType('movie')
        params.setParam('sName', sName)
        params.setParam('sThumbnail', sThumbnail)
        params.setParam('entryUrl', sUrl)
        oGui.addFolder(oGuiElement, params, False, total)
    if not sGui and not sSearchText:
        sPageNr = int(params.getValue('page'))
        if sPageNr == 0:
            sPageNr = 2
        else:
            sPageNr += 1
        if _hasNextPage(sHtmlContent, sPageNr - 1):
            params.setParam('page', int(sPageNr))
            params.setParam('sUrl', entryUrl)
            oGui.addNextPage(SITE_IDENTIFIER, 'showEntriesLast', params)
        oGui.setView('movies')
        oGui.setEndOfDirectory()


def showHosters():
    params = ParameterHandler()
    entryUrl = params.getValue('entryUrl')
    hosters = []
    sUrl = URL_MAIN + '/api/movies/' + entryUrl + '/watch'
    sHtmlContent = cRequestHandler(sUrl, caching=False).request()
    pattern = 'streamUrl":"([^"]+)'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch: return
    sQuality = '720'
    for sUrl in aResult:
        sName = cParser.urlparse(sUrl)
        if cConfig().isBlockedHoster(sName)[0]: continue # Hoster aus settings.xml oder deaktivierten Resolver ausschließen
        hoster = {'link': sUrl, 'name': sName, 'displayedName': '%s [I][%sp][/I]' % (sName, sQuality), 'quality': sQuality}
        hosters.append(hoster)
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def getHosterUrl(sUrl=False):
    return [{'streamUrl': sUrl, 'resolved': False}]


def showSearch():
    win = xbmcgui.Window(10000)
    sSearchText = win.getProperty('xstream.einschalten.lastSearchText')
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30287))
        if not sSearchText: return
        win.setProperty('xstream.einschalten.lastSearchText', sSearchText)
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def _search(oGui, sSearchText):
    showEntries(URL_SEARCH % cParser.quotePlus(sSearchText), oGui, sSearchText)
