# -*- coding: utf-8 -*-
# Python 3

#Always pay attention to the translations in the menu!
# Sprachauswahl für Hoster enthalten.
# 2022-12-06 Heptamer - Suchfunktion überarbeitet

import ast
import re
import xbmcgui

from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger
from resources.lib.tools import cParser, cUtil
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui

SITE_IDENTIFIER = 'aniworld'
SITE_NAME = 'AniWorld'
SITE_ICON = 'aniworld.png'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'aniworld.to')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)

URL_MAIN = 'https://' + DOMAIN
URL_SERIES = URL_MAIN + '/animes'
URL_POPULAR = URL_MAIN + '/beliebte-animes'
URL_NEW_EPISODES = URL_MAIN + '/neue-episoden'
URL_NEW_ANIMES = URL_MAIN          # "Neue Animes" Sektion liegt auf der Startseite
URL_LOGIN = URL_MAIN + '/login'
REFERER = 'https://' + DOMAIN


def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.aniworld.lastSearchText')
    xbmcgui.Window(10000).clearProperty('xstream.aniworld.lastYear')
    params = ParameterHandler()
    # Login ist optional — Settings 'aniworld.user' / 'aniworld.pass' bleiben
    # in settings.xml verfuegbar. Bei gesetzten Credentials wird in
    # getHosterUrl() ein Login-POST gemacht (Cookie-basiert), sonst direkt
    # Hoster geholt — Backend funktioniert auch ohne Login.

    # Neues  (Animes + Episoden)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30813), SITE_IDENTIFIER, 'showNeues'), params)
    # Beliebte Animes
    params.setParam('sUrl', URL_POPULAR)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30519), SITE_IDENTIFIER, 'showEntries'), params)
    # Genres (lädt direkt die Genre-Liste)
    params.setParam('sUrl', URL_MAIN)
    params.setParam('sCont', 'homeContentGenresList')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30815), SITE_IDENTIFIER, 'showValue'), params)
    # Aki: Jahr-Suche (User gibt Jahr ein, /animes/jahr/YYYY)
    params = ParameterHandler()
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30564), SITE_IDENTIFIER, 'showYearSearch'), params)
    # A-Z (direkt in die Buchstaben-Auswahl)
    params = ParameterHandler()
    params.setParam('sUrl', URL_MAIN)
    params.setParam('sCont', 'catalogNav')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30814), SITE_IDENTIFIER, 'showValue'), params)
    # Suche
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'), params)
    cGui().setEndOfDirectory()


def showNeues():
    """Submenu: Animes + Episoden"""
    params = ParameterHandler()
    # Animes
    params.setParam('sUrl', URL_NEW_ANIMES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30561), SITE_IDENTIFIER, 'showNewAnimes'), params)  # Animes
    # Episoden
    params.setParam('sUrl', URL_NEW_EPISODES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30557), SITE_IDENTIFIER, 'showNewEpisodes'), params)  # Episoden (30557 wie SerienStream und Burningseries)
    cGui().setEndOfDirectory()


def showAZMenu():
    """Submenu: Alle Serien + A-Z"""
    params = ParameterHandler()
    # Alle Serien
    params.setParam('sUrl', URL_SERIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30518), SITE_IDENTIFIER, 'showAllSeries'), params)
    # A-Z
    params.setParam('sUrl', URL_MAIN)
    params.setParam('sCont', 'catalogNav')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30814), SITE_IDENTIFIER, 'showValue'), params)
    cGui().setEndOfDirectory()


def showNewAnimes(entryUrl=False, sGui=False):
    """
    Parst die "Neue Animes"-Sektion vom AniWorld Startseiten-Karussell.
    HTML-Struktur:
        <h2>Neue Animes</h2>
        <div class="previews">
            <div class="coverListItem">
                <a href="/anime/stream/...">
                    <img data-src="/public/img/cover/...">
                    <h3>Titel <span ...></h3>
                    <small>Genre</small>
                </a>
            </div>
            ...
        </div>
        <div class="cf">   ← Ende der Sektion
    """
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl:
        entryUrl = params.getValue('sUrl')

    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))

    sHtmlContent = oRequest.request()
    if not sHtmlContent:
        if not sGui: oGui.showInfo()
        return

    # --- Sektion isolieren: alles zwischen "Neue Animes" Heading und <div class="cf"> ---
    isMatch, sContainer = cParser.parseSingleResult(
        sHtmlContent,
        r'Neue Animes<\/h2>.*?<div class="previews">(.*?)<\/div>\s*<\/div>\s*<div class="cf">'
    )
    if not isMatch:
        logger.info('[%s] showNewAnimes: Neue-Animes-Sektion nicht gefunden.' % SITE_NAME)
        if not sGui: oGui.showInfo()
        return

    # --- Jedes coverListItem parsen: URL + Thumbnail (data-src) + Titel + Genre ---
    # Beispiel-Item:
    #   <div class="coverListItem"><a href="/anime/stream/rooster-fighter" title="...">
    #       ...
    #       <img data-src="/public/img/cover/rooster-fighter-stream-cover-xxx_150x225.png" ...>
    #       ...
    #       <h3>Rooster Fighter <span class="paragraph-end black"></span></h3>
    #       <small>Action</small>
    #   </a></div>
    pattern = (
        r'<div class="coverListItem"><a href="(/anime/stream/[^"]+)"[^>]*>'  # URL
        r'.*?data-src="([^"]+)"[^>]*>'                                        # Thumbnail
        r'.*?<h3>([^<]+)<span'                                                # Titel
        r'.*?<small>([^<]*)<\/small>'                                         # Genre
    )
    isMatch, aResult = cParser.parse(sContainer, pattern)
    if not isMatch:
        logger.info('[%s] showNewAnimes: Keine Items im Container gefunden.' % SITE_NAME)
        if not sGui: oGui.showInfo()
        return

    total = len(aResult)
    for sUrl, sThumbnail, sName, sGenre in aResult:
        sName = sName.strip()
        sGenre = sGenre.strip()
        if not sName:
            continue
        sThumbnail = sThumbnail if sThumbnail.startswith('http') else URL_MAIN + sThumbnail
        sFullUrl = URL_MAIN + sUrl

        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        oGuiElement.setTVShowTitle(sName)
        oGuiElement.setThumbnail(sThumbnail)
        if sGenre:
            oGuiElement.setDescription('[B]Genre:[/B] ' + sGenre)

        params.setParam('sUrl', sFullUrl)
        params.setParam('TVShowTitle', sName)
        oGui.addFolder(oGuiElement, params, True, total)

    if not sGui:
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()


PAGE_WINDOW = 15


def _pageInfo(sHtmlContent):
    """Seitenlage fuer den Weiter-Eintrag: (aktuelle Seite, letzte Seite) aus der
    Blaetterleiste. Letzte Seite ist 0, wenn die Leiste abgeschnitten ist."""
    isMatch, sNav = cParser.parseSingleResult(sHtmlContent, r'(<div class="hosterSiteDirectNav pagination">.*?</ul>)')
    if not isMatch:
        return 0, 0
    isMatch, sActive = cParser.parseSingleResult(sNav, r'class="active"[^>]*>(\d+)')
    iCurrent = int(sActive) if isMatch else 1
    aNums = [int(x) for x in re.findall(r'>(\d{1,5})<', sNav)]
    if not aNums:
        return iCurrent, 0
    iLast = max(aNums)
    if iLast >= iCurrent + PAGE_WINDOW:      # Leiste abgeschnitten, Ende unbekannt
        iLast = 0
    return iCurrent, iLast


def showValue():
    params = ParameterHandler()
    sUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(sUrl)
    sHtmlContent = oRequest.request()
    isMatch, sContainer = cParser.parseSingleResult(sHtmlContent, '<ul[^>]*class="%s"[^>]*>(.*?)<\\/ul>' % params.getValue('sCont'))
    if isMatch:
        isMatch, aResult = cParser.parse(sContainer, r'<li>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>\s*<\/li>')
    if not isMatch:
        cGui().showInfo()
        return

    for sUrl, sName in aResult:
        sUrl = sUrl if sUrl.startswith('http') else URL_MAIN + sUrl
        params.setParam('sUrl', sUrl)
        cGui().addFolder(cGuiElement(sName, SITE_IDENTIFIER, 'showEntries'), params)
    cGui().setEndOfDirectory()


def showAllSeries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl: entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()
    pattern = '<a[^>]*href="(\\/anime\\/[^"]*)"[^>]*>(.*?)</a>'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    total = len(aResult)
    for sUrl, sName in aResult:
        if sSearchText and not cParser.searchTitle(sSearchText, sName):
            continue
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        params.setParam('sUrl', URL_MAIN + sUrl)
        params.setParam('TVShowTitle', sName)
        oGui.addFolder(oGuiElement, params, True, total)
    if not sGui:
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()


def showNewEpisodes(entryUrl=False, sGui=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl:
        entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()
    # Flag-Icon hinter dem </a> optional mitnehmen (german/japanese-german/japanese-english.svg, teils lazy via data-src);
    # (?!<strong>) verhindert bei flagloser Zeile den Überlauf in die nächste Zeile
    pattern = r'<div[^>]*class="col-md-[^"]*"[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>\s*<strong>([^<]+)</strong>\s*<span[^>]*>([^<]+)</span>(?:(?:(?!<strong>).)*?class="flag"[^>]*(?:data-src|src)="[^"]*?([\w-]+)\.svg")?'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    total = len(aResult)
    for sUrl, sName, sInfo, sFlag in aResult:
        sMovieTitle = sName + ' ' + sInfo
        sDisplayTitle = sMovieTitle
        if sFlag:  # exaktes Mapping, kein Substring-Check ('german' steckt auch in 'japanese-german')
            sDisplayTitle += ' [' + {'german': 'DE', 'japanese-german': 'JP-DE', 'japanese-english': 'JP-EN'}.get(sFlag, sFlag.upper()) + ']'
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        oGuiElement.setTitle(sDisplayTitle)
        params.setParam('sUrl', URL_MAIN + sUrl)
        params.setParam('TVShowTitle', sMovieTitle)

        oGui.addFolder(oGuiElement, params, True, total)
    if not sGui:
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()


def showEntries(entryUrl=False, sGui=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl:
        entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()
    #Aufbau pattern
    #'<div[^>]*class="col-md-[^"]*"[^>]*>.*?'  # start element
    #'<a[^>]*href="([^"]*)"[^>]*>.*?'  # url
    #'<img[^>]*src="([^"]*)"[^>]*>.*?'  # thumbnail
    #'<h3>(.*?)<span[^>]*class="paragraph-end">.*?'  # title
    #'<\\/div>'  # end element
    pattern = '<div[^>]*class="col-md-[^"]*"[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>.*?<img[^>]*src="([^"]*)"[^>]*>.*?<h3>(.*?)<span[^>]*class="paragraph-end">.*?</div>'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    total = len(aResult)
    for sUrl, sThumbnail, sName in aResult:
        if sThumbnail.startswith('/'):
            sThumbnail = URL_MAIN + sThumbnail
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setThumbnail(sThumbnail)
        oGuiElement.setMediaType('tvshow')
        params.setParam('sUrl', URL_MAIN + sUrl)
        params.setParam('TVShowTitle', sName)
        oGui.addFolder(oGuiElement, params, True, total)
    if not sGui:
        pattern = 'pagination">.*?<a href="([^"]+)">&gt;</a>.*?</a></div>'
        isMatchNextPage, sNextUrl = cParser.parseSingleResult(sHtmlContent, pattern)
        if isMatchNextPage:
            params.setParam('sUrl', sNextUrl)
            oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', params, cGui.pageInfo(*_pageInfo(sHtmlContent)))
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()


def showSeasons():
    params = ParameterHandler()
    sUrl = params.getValue('sUrl')
    sTVShowTitle = params.getValue('TVShowTitle')
    sTmdbID = params.getValue('tmdbID') or ''
    oRequest = cRequestHandler(sUrl)
    sHtmlContent = oRequest.request()
    pattern = '<div[^>]*class="hosterSiteDirectNav"[^>]*>.*?<ul>(.*?)</ul>'
    isMatch, sContainer = cParser.parseSingleResult(sHtmlContent, pattern)
    if isMatch:
        pattern = '<a[^>]*href="([^"]*)"[^>]*title="([^"]*)"[^>]*>(.*?)</a>.*?'
        isMatch, aResult = cParser.parse(sContainer, pattern)
    if not isMatch:
        cGui().showInfo()
        return

    isDesc, sDesc = cParser.parseSingleResult(sHtmlContent, '<p[^>]*data-full-description="(.*?)"[^>]*>')
    isThumbnail, sThumbnail = cParser.parseSingleResult(sHtmlContent, '<div[^>]*class="seriesCoverBox"[^>]*>.*?<img[^>]*src="([^"]*)"[^>]*>')
    if isThumbnail:
        if sThumbnail.startswith('/'):
            sThumbnail = URL_MAIN + sThumbnail

    # Aki: Year aus Detail-Seite extrahieren (itemprop="startDate")
    sYear = ''
    year_match = re.search(r'itemprop="startDate"[^>]*>\s*<a[^>]*>(\d{4})</a>', sHtmlContent)
    if year_match:
        sYear = year_match.group(1)

    total = len(aResult)
    for sUrl, sName, sNr in aResult:
        isMovie = sUrl.endswith('filme')
        if 'Alle Filme' in sName:
            sName = cConfig().getLocalizedString(30559)
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showEpisodes')
        # Der Filme-Ordner ist die Staffel 0 der Serie, kein Film: Serienname fuer InfoTag und
        # Weitere Quellen, kein Trailer-Eintrag und kein TMDB-Lookup auf das Wort "Filme"
        oGuiElement.setMediaType('season')
        if isThumbnail:
            oGuiElement.setThumbnail(sThumbnail)
        if isDesc:
            oGuiElement.setDescription(sDesc)
        oGuiElement.setTVShowTitle(sTVShowTitle)
        if not isMovie:
            oGuiElement.setSeason(sNr)
            if sTmdbID:
                oGuiElement.addItemValue('tmdb_id', sTmdbID)
            params.setParam('sSeason', sNr)
        else:
            oGuiElement.setSeason('0')
        if sYear:
            oGuiElement.addItemValue('year', sYear)
            params.setParam('sYear', sYear)
        params.setParam('sThumbnail', sThumbnail)
        params.setParam('sUrl', URL_MAIN + sUrl)
        cGui().addFolder(oGuiElement, params, True, total)
    cGui().setView('seasons')
    cGui().setEndOfDirectory()


def showEpisodes():
    params = ParameterHandler()
    sUrl = params.getValue('sUrl')
    sTVShowTitle = params.getValue('TVShowTitle')
    sSeason = params.getValue('sSeason')
    sThumbnail = params.getValue('sThumbnail')
    if not sSeason:
        sSeason = '0'
    isMovieList = sUrl.endswith('filme')
    oRequest = cRequestHandler(sUrl)
    sHtmlContent = oRequest.request()
    pattern = '<table[^>]*class="seasonEpisodesList"[^>]*>(.*?)</table>'
    isMatch, sContainer = cParser.parseSingleResult(sHtmlContent, pattern)
    if isMatch:
        if isMovieList == True:
            pattern = r'<tr[^>]*data-episode-season-id="(\d+).*?<a href="([^"]+)">\s([^<]+).*?<strong>([^<]+)'
            isMatch, aResult = cParser.parse(sContainer, pattern)
            if not isMatch:
                pattern = r'<tr[^>]*data-episode-season-id="(\d+).*?<a href="([^"]+)">\s([^<]+).*?<span>([^<]+)'
                isMatch, aResult = cParser.parse(sContainer, pattern)
        else:
            pattern = r'<tr[^>]*data-episode-season-id="(\d+).*?<a href="([^"]+).*?(?:<strong>(.*?)</strong>.*?)?(?:<span>(.*?)</span>.*?)?<'
            isMatch, aResult = cParser.parse(sContainer, pattern)
    if not isMatch:
        cGui().showInfo()
        return

    isDesc, sDesc = cParser.parseSingleResult(sHtmlContent, '<p[^>]*data-full-description="(.*?)"[^>]*>')
    total = len(aResult)
    for sID, sUrl2, sNameGer, sNameEng in aResult:
        sName = '%d - ' % int(sID)
        if isMovieList == True:
            sName += sNameGer + '- ' + sNameEng
        else:
            sName += sNameGer if sNameGer else sNameEng
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setMediaType('episode' if not isMovieList else 'movie')
        if isMovieList == True:
            # Aki: Clean Title fuer Trailer-Match (Display-Label hat Episode-Prefix)
            cleanTitle = (sNameEng or sNameGer or '').strip(' -')
            if cleanTitle:
                oGuiElement.addItemValue('originaltitle', cleanTitle)
        oGuiElement.setThumbnail(sThumbnail)
        if isDesc:
            oGuiElement.setDescription(sDesc)
        if not isMovieList:
            oGuiElement.setSeason(sSeason)
            oGuiElement.setEpisode(int(sID))
            oGuiElement.setTVShowTitle(sTVShowTitle)
        params.setParam('sUrl', URL_MAIN + sUrl2)
        params.setParam('entryUrl', sUrl)
        cGui().addFolder(oGuiElement, params, False, total)
    cGui().setView('episodes' if not isMovieList else 'movies')
    cGui().setEndOfDirectory()


def showHosters():
    hosters = []
    sUrl = ParameterHandler().getValue('sUrl')
    sHtmlContent = cRequestHandler(sUrl, caching=False).request()
    if cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain') == 'www.aniworld.info':
        pattern = r'<li[^>]*episodeLink([^"]+)"\sdata-lang-key="([^"]+).*?data-link-target="([^"]+).*?<h4>([^<]+)<([^>]+)'
        pattern2 = r'itemprop="keywords".content=".*?Season...([^"]+).S.*?'  # HD Kennzeichen
        # data-lang-key="1" Deutsch
        # data-lang-key="2" Japanisch mit englischen Untertitel
        # data-lang-key="3" Japanisch mit deutschen Untertitel
        isMatch, aResult = cParser.parse(sHtmlContent, pattern)
        aResult2 = cParser.parse(sHtmlContent, pattern2)
        if isMatch:
            for sID, sLang, sUrl, sName, sQuality in aResult:
                sUrl = sUrl.replace('/dl/2010', '/redirect/' + sID)
                if cConfig().isBlockedHoster(sName)[0]: continue # Hoster aus settings.xml oder deaktivierten Resolver ausschließen
                sLanguage = cConfig().getSetting('prefLanguage')
                if sLanguage == '1':        # Voreingestellte Sprache Deutsch in settings.xml
                    if '2' in sLang:        # data-lang-key="2" Japanisch mit englischen Untertitel
                        continue
                    elif '3' in sLang:        # data-lang-key="3" Japanisch mit deutschen Untertitel
                        continue
                    elif sLang == '1':        # data-lang-key="1" Deutsch
                        sLang = '(DE)'
                if sLanguage == '2':        # Voreingestellte Sprache Englisch in settings.xml
                    continue                # AniWorld hat kein reines Englisch — der Hinweis
                                            # kommt unten ueber 'if not hosters', sonst poppte
                                            # der Dialog einmal PRO Hoster-Eintrag
                if sLanguage == '3':        # Voreingestellte Sprache Japanisch in settings.xml
                    if '1' in sLang:        # data-lang-key="1" Deutsch
                        continue
                    elif sLang == '3':        # data-lang-key="3" Japanisch mit deutschen Untertitel
                        sLang = '(JPN) Sub: (DE)'
                    elif sLang == '2':       # data-lang-key="2" Japanisch mit englischen Untertitel
                        sLang = '(JPN) Sub: (EN)'
                if sLanguage == '0':        # Alle Sprachen
                    if sLang == '1':    # data-lang-key="1"
                        sLang = '(DE)'
                    elif sLang == '3':  # data-lang-key="3"
                        sLang = '(JPN) Sub: (DE)'
                    elif sLang == '2':    # data-lang-key="2"
                        sLang = '(JPN) Sub: (EN)'
                if 'HD' in aResult2[1]:
                    sQuality = '720'
                else:
                    sQuality = '480'
                    # link = [url, name]: der Name wird in gui/hoster.py mit ausgewertet
                    # (Beispiel aus dem Log: ['/redirect/12286260', 'VOE']).
                hoster = {'link': [sUrl, sName], 'name': sName, 'displayedName': '%s [I]%s [%sp][/I]' % (sName, sLang, sQuality), 'quality': sQuality, 'languageCode': sLang} # Language Code für hoster.py Sprache Prio
                hosters.append(hoster)
            if hosters:
                hosters.append('getHosterUrl')
            if not hosters:
                cGui().showLanguage()
            return hosters
    else:
        pattern = '<li[^>]*data-lang-key="([^"]+).*?data-link-target="([^"]+).*?<h4>([^<]+)<([^>]+)'
        pattern2 = 'itemprop="keywords".content=".*?Season...([^"]+).S.*?'  # HD Kennzeichen
        # data-lang-key="1" Deutsch
        # data-lang-key="2" Japanisch mit englischen Untertitel
        # data-lang-key="3" Japanisch mit deutschen Untertitel
        isMatch, aResult = cParser.parse(sHtmlContent, pattern)
        aResult2 = cParser.parse(sHtmlContent, pattern2)
        if isMatch:
            for sLang, sUrl, sName, sQuality in aResult:
                if cConfig().isBlockedHoster(sName)[0]: continue # Hoster aus settings.xml oder deaktivierten Resolver ausschließen
                sLanguage = cConfig().getSetting('prefLanguage')
                if sLanguage == '1':  # Voreingestellte Sprache Deutsch in settings.xml
                    if '2' in sLang:  # data-lang-key="2" Japanisch mit englischen Untertitel
                        continue
                    elif '3' in sLang:  # data-lang-key="3" Japanisch mit deutschen Untertitel
                        continue
                    elif sLang == '1':  # data-lang-key="1" Deutsch
                        sLang = '(DE)'
                if sLanguage == '2':  # Voreingestellte Sprache Englisch in settings.xml
                    continue              # AniWorld hat kein reines Englisch — der Hinweis
                                          # kommt unten ueber 'if not hosters', sonst poppte
                                          # der Dialog einmal PRO Hoster-Eintrag
                if sLanguage == '3':  # Voreingestellte Sprache Japanisch in settings.xml
                    if '1' in sLang:  # data-lang-key="1" Deutsch
                        continue
                    elif sLang == '3':  # data-lang-key="3" Japanisch mit deutschen Untertitel
                        sLang = '(JPN) Sub: (DE)'
                    elif sLang == '2':  # data-lang-key="2" Japanisch mit englischen Untertitel
                        sLang = '(JPN) Sub: (EN)'
                if sLanguage == '0':  # Alle Sprachen
                    if sLang == '1':  # data-lang-key="1"
                        sLang = '(DE)'
                    elif sLang == '3':  # data-lang-key="3"
                        sLang = '(JPN) Sub: (DE)'
                    elif sLang == '2':  # data-lang-key="2"
                        sLang = '(JPN) Sub: (EN)'
                if 'HD' in aResult2[1]:
                    sQuality = '720'
                else:
                    sQuality = '480'
                    # link = [url, name]: der Name wird in gui/hoster.py mit ausgewertet
                    # (Beispiel aus dem Log: ['/redirect/12286260', 'VOE']).
                hoster = {'link': [sUrl, sName], 'name': sName, 'displayedName': '%s [I]%s [%sp][/I]' % (sName, sLang, sQuality), 'quality': sQuality, 'languageCode': sLang} # Language Code für hoster.py Sprache Prio
                hosters.append(hoster)
            if hosters:
                hosters.append('getHosterUrl')
            if not hosters:
                cGui().showLanguage()
            return hosters


def getHosterUrl(hUrl):
    if type(hUrl) == str: hUrl = ast.literal_eval(hUrl)
    username = cConfig().getSetting('aniworld.user')
    password = cConfig().getSetting('aniworld.pass')

    # Login ist optional: mit gesetzten Zugangsdaten wird vorher ein
    # Cookie-Login gemacht. Er hat keinen Einfluss auf Hoster oder Qualitaet —
    # ohne Zugangsdaten geht es direkt zur Hoster-URL, die Seite liefert dasselbe.
    if username and password:
        Handler = cRequestHandler(URL_LOGIN, caching=False)
        Handler.addHeaderEntry('Upgrade-Insecure-Requests', '1')
        Handler.addHeaderEntry('Referer', ParameterHandler().getValue('entryUrl'))
        Handler.addParameters('email', username)
        Handler.addParameters('password', password)
        Handler.request()

    # DoodStream: haengt hinter Cloudflare.
    # Embed-Seite selbst zu laden triggert den CF-Block ("CLOUDFLARE-SCHUTZ AKTIV").
    # Wir reichen daher nur das Redirect-Ziel an ResolveURL weiter (wie einschalten),
    # das die Seite selbst aufloest — byparr wird dafuer nicht mehr benoetigt.
    if 'dood' in hUrl[1].lower():
        Request = cRequestHandler(URL_MAIN + hUrl[0], caching=False)
        Request.addHeaderEntry('Referer', ParameterHandler().getValue('entryUrl'))
        Request.addHeaderEntry('Upgrade-Insecure-Requests', '1')
        return [{'streamUrl': Request.getRedirectUrl(), 'resolved': False}]

    Request = cRequestHandler(URL_MAIN + hUrl[0], caching=False)
    Request.addHeaderEntry('Referer', ParameterHandler().getValue('entryUrl'))
    Request.addHeaderEntry('Upgrade-Insecure-Requests', '1')
    Request.request()
    sUrl = Request.getRealUrl()
    if not sUrl:
        # Der Abruf der Weiterleitung ist gescheitert (Timeout, Fehler — der
        # requestHandler hat schon gemeldet). Ohne diese Zeile prueft der
        # VOE-Zweig eine LEERE Adresse, ResolveURL kennt sie nicht, und aus
        # ''.replace('', 'voe.sx') wird die Phantasie-Adresse 'voe.sx' — der
        # Nutzer sah dann noch „Kein unterstuetzter Hoster" obendrauf (Jacks
        # Log 10.09.2026 ueber eine langsame VPN-Route).
        return [{'streamUrl': '', 'resolved': False}]

    if 'voe' in hUrl[1].lower():
        isBlocked, sDomain = cConfig().isBlockedHoster(sUrl)
        if isBlocked:  # Voe Pseudo sDomain nicht bekannt in resolveUrl
            sUrl = sUrl.replace(sDomain, 'voe.sx')
            return [{'streamUrl': sUrl, 'resolved': False}]

    return [{'streamUrl': sUrl, 'resolved': False}]


def showSearch():
    win = xbmcgui.Window(10000)
    sSearchText = win.getProperty('xstream.aniworld.lastSearchText')
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30281))
        if not sSearchText: return
        win.setProperty('xstream.aniworld.lastSearchText', sSearchText)
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def showYearSearch():
    """Aki: Jahr-Suche — User gibt Jahr ein, oeffnet /animes/jahr/YYYY."""
    win = xbmcgui.Window(10000)
    sYear = win.getProperty('xstream.aniworld.lastYear')
    if not sYear:
        # Zahlenfeld statt Freitext: die Aufforderung nennt ein Jahr, Buchstaben
        # sind dort nicht eingebbar. Eine verworfene Eingabe wird gemeldet — bis
        # zum 01.09.2026 brach die Funktion stumm ab und der Nutzer stand vor
        # einer leeren Liste ohne Grund.
        sYear = str(cGui().showNumpad(numPadTitle=cConfig().getLocalizedString(30563)) or '').strip()
        if not sYear:
            return
        if not sYear.isdigit() or len(sYear) != 4 or int(sYear) < 1970:
            cGui().showInfo('xStream', cConfig().getLocalizedString(30563))
            return
        win.setProperty('xstream.aniworld.lastYear', sYear)
    searchUrl = URL_MAIN + '/animes/jahr/' + sYear
    showYearEntries(searchUrl, sYear)


def showYearEntries(entryUrl=False, sYear=''):
    """Aki: Parser fuer /animes/jahr/YYYY Seite (mit Pagination).
    HTML-Struktur: <a href="/anime/stream/..."> <img data-src="..."> <h3>Titel<span></span></h3> <small>Genre</small> </a>
    """
    oGui = cGui()
    params = ParameterHandler()
    # Bei Pagination-Call kommt entryUrl aus Params
    if not entryUrl:
        entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl)
    sHtmlContent = oRequest.request()
    if not sHtmlContent:
        oGui.showInfo()
        return

    # Pattern: URL + Thumbnail + Titel (ohne Genre im Title!)
    pattern = (
        r'href="(/anime/stream/[^"]+)"[^>]*>'
        r'.*?data-src="([^"]+)"'
        r'.*?<h3>([^<]+)<span[^>]*></span></h3>'
        r'\s*<small>([^<]*)</small>'
    )
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        logger.info('[%s] showYearEntries: Keine Animes fuer Jahr %s gefunden.' % (SITE_NAME, sYear))
        oGui.showInfo()
        return

    total = len(aResult)
    for sUrl, sThumb, sName, sGenre in aResult:
        sName = sName.strip()
        sFullThumb = sThumb if sThumb.startswith('http') else URL_MAIN + sThumb
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        oGuiElement.setThumbnail(sFullThumb)
        if sGenre:
            oGuiElement.setDescription('[B]Genre:[/B] ' + sGenre.strip())
        params.setParam('sUrl', URL_MAIN + sUrl)
        params.setParam('TVShowTitle', sName)
        oGui.addFolder(oGuiElement, params, True, total)

    # Aki: Pagination — analog zu showEntries
    pag_pattern = 'pagination">.*?<a href="([^"]+)">&gt;</a>.*?</a></div>'
    isMatchNextPage, sNextUrl = cParser.parseSingleResult(sHtmlContent, pag_pattern)
    if isMatchNextPage:
        params.setParam('sUrl', sNextUrl)
        oGui.addNextPage(SITE_IDENTIFIER, 'showYearEntries', params, cGui.pageInfo(*_pageInfo(sHtmlContent)))
    oGui.setView('tvshows')
    oGui.setEndOfDirectory()


def _search(oGui, sSearchText):
    SSsearch(oGui, sSearchText)


def SSsearch(sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    params.getValue('sSearchText')
    oRequest = cRequestHandler(URL_SERIES, caching=True, ignoreErrors=(sGui is not False))
    oRequest.addHeaderEntry('X-Requested-With', 'XMLHttpRequest')
    oRequest.addHeaderEntry('Referer', REFERER  + '/animes')
    oRequest.addHeaderEntry('Origin', REFERER)
    oRequest.addHeaderEntry('Content-Type', 'application/x-www-form-urlencoded; charset=UTF-8')
    oRequest.addHeaderEntry('Upgrade-Insecure-Requests', '1')
    sHtmlContent = oRequest.request()

    if not sHtmlContent:
            return

    sst = sSearchText.lower()

    pattern = r'<li><a data.+?href="([^"]+)".+?">(.*?)\<\/a><\/l' #link - title

    aResult = cParser.parse(sHtmlContent, pattern)

    if not aResult[0]:
        oGui.showInfo()
        return

    total = len(aResult[1])
    for link, title in aResult[1]:
        titleLow = title.lower()
        if not sst in titleLow and not cUtil.isSimilarByToken(sst, titleLow):
            continue
        else:
            #get images thumb / descr pro call. (optional)
            try:
                sThumbnail, sDescription = getMetaInfo(link, title)
                oGuiElement = cGuiElement(title, SITE_IDENTIFIER, 'showSeasons')
                oGuiElement.setThumbnail(URL_MAIN + sThumbnail)
                oGuiElement.setDescription(sDescription)
                oGuiElement.setTVShowTitle(title)
                oGuiElement.setMediaType('tvshow')
                params.setParam('sUrl', URL_MAIN + link)
                params.setParam('sName', title)
                oGui.addFolder(oGuiElement, params, True, total)
            except Exception:
                oGuiElement = cGuiElement(title, SITE_IDENTIFIER, 'showSeasons')
                oGuiElement.setTVShowTitle(title)
                oGuiElement.setMediaType('tvshow')
                params.setParam('sUrl', URL_MAIN + link)
                params.setParam('sName', title)
                oGui.addFolder(oGuiElement, params, True, total)

        if not sGui:
            oGui.setView('tvshows')


def getMetaInfo(link, title):
    oGui = cGui()
    oRequest = cRequestHandler(URL_MAIN + link, caching=False)
    oRequest.addHeaderEntry('X-Requested-With', 'XMLHttpRequest')
    oRequest.addHeaderEntry('Referer', REFERER + '/animes')
    oRequest.addHeaderEntry('Origin', REFERER)

    sHtmlContent = oRequest.request()
    if not sHtmlContent:
        return

    pattern = r'seriesCoverBox">.*?<img src="([^"]+)"\ al.+?data-full-description="([^"]+)"' #img , descr

    aResult = cParser.parse(sHtmlContent, pattern)

    if not aResult[0]:
        return

    for sImg, sDescr in aResult[1]:
        return sImg, sDescr