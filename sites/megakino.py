# -*- coding: utf-8 -*-
# Python 3
# Always pay attention to the translations in the menu!

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


SITE_IDENTIFIER = 'megakino'
SITE_NAME = 'Megakino'
SITE_ICON = 'megakino.png'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'megakino27.com')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)

URL_MAIN = 'https://' + DOMAIN + '/'
URL_KINO = URL_MAIN + 'kinofilme/'
URL_MOVIES = URL_MAIN + 'films/'
URL_SERIES = URL_MAIN + 'serials/'


def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.megakino.lastSearchText')
    params = ParameterHandler()
    params.setParam('sUrl', URL_KINO)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30501), SITE_IDENTIFIER, 'showEntries'), params)  # Aktuelle Releases
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30500), SITE_IDENTIFIER, 'showLatest'))  # Neu auf der Seite (Block „Zuletzt hinzugefuegt" der Startseite)
    params.setParam('sUrl', URL_MOVIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30502), SITE_IDENTIFIER, 'showEntries'), params)  # Filme
    params.setParam('sUrl', URL_SERIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30511), SITE_IDENTIFIER, 'showEntries'), params)  # Serien
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30506), SITE_IDENTIFIER, 'showGenre'))  # Genre
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30543), SITE_IDENTIFIER, 'showCollection'))  # Kollektionen (Sidebar „Sammlung" der Seite)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'))  # Suche
    cGui().setEndOfDirectory()


def getHtmlContent(url, bIgnoreErrors=False):
    """Hilfsfunktion zum Abrufen von HTML-Inhalten mit yg_token Cookie-Bypass.
    Megakino liefert bei erstem Hit ein JS-Stub das einen Token-Endpoint hittet.
    Token setzt Cookie, bei zweitem Request kommt echtes HTML.

    UA-Sticky: Alle 3 Requests im Token-Flow MUESSEN identischen UA nutzen
    (Cookie an UA gebunden, Anti-Bot prueft UA-Konsistenz zwischen Token+HTML).
    Drum einmal RandomUA() aufrufen und an alle 3 Requests weitergeben.

    bIgnoreErrors=True fuer die Folgeseiten der Suche: ein Fehler dort wird nicht
    als Fenster gemeldet, der Aufrufer zeigt seine normale Leer-Meldung.
    """
    sessionUA = cRequestHandler.RandomUA()
    oRequest = cRequestHandler(url, ignoreErrors=bIgnoreErrors)
    oRequest.cacheTime = 0
    oRequest.addHeaderEntry('User-Agent', sessionUA)
    oRequest.addHeaderEntry('Referer', URL_MAIN)
    sHtmlContent = oRequest.request()

    # Token-Stub erkannt -> Token holen + Original-URL retry
    if sHtmlContent and 'yg=token' in sHtmlContent and len(sHtmlContent) < 1000:
        logger.info('[megakino] Token-Stub erkannt, hole Token...')
        oTokenRequest = cRequestHandler(URL_MAIN + 'index.php?yg=token')
        oTokenRequest.cacheTime = 0
        oTokenRequest.addHeaderEntry('User-Agent', sessionUA)
        oTokenRequest.addHeaderEntry('Accept', '*/*')
        oTokenRequest.addHeaderEntry('Referer', url)
        oTokenRequest.addHeaderEntry('X-Requested-With', 'XMLHttpRequest')
        oTokenRequest.request()

        # Original-URL nochmal abrufen mit Cookie
        oRequest2 = cRequestHandler(url, ignoreErrors=bIgnoreErrors)
        oRequest2.cacheTime = 0
        oRequest2.addHeaderEntry('User-Agent', sessionUA)
        oRequest2.addHeaderEntry('Referer', URL_MAIN)
        sHtmlContent = oRequest2.request()

    return sHtmlContent if sHtmlContent and len(sHtmlContent) > 1000 else None


def showGenre():
    params = ParameterHandler()
    sHtmlContent = getHtmlContent(URL_MAIN)
    if not sHtmlContent:
        cGui().showInfo()
        return

    # Sidebar: <div class="side-block__title">Genres</div>...<ul class="side-block__content side-block__menu">...</ul>
    pattern = r'<div class="side-block__title">Genres</div>.*?<ul class="side-block__content side-block__menu"(.*?)</ul>'
    isMatch, sContainer = cParser.parseSingleResult(sHtmlContent, pattern)
    if not isMatch:
        cGui().showInfo()
        return

    pattern = r'href="([^"]+)">([^<]+)</a>'
    isMatch, aResult = cParser.parse(sContainer, pattern)
    if not isMatch:
        cGui().showInfo()
        return

    for sUrl, sName in aResult:
        if sUrl.startswith('/'):
            sUrl = URL_MAIN.rstrip('/') + sUrl
        params.setParam('sUrl', sUrl)
        cGui().addFolder(cGuiElement(sName.strip(), SITE_IDENTIFIER, 'showEntries'), params)
    cGui().setEndOfDirectory()


def showCollection():
    params = ParameterHandler()
    sHtmlContent = getHtmlContent(URL_MAIN)
    if not sHtmlContent:
        cGui().showInfo()
        return

    # Sammlung-Sidebar mit collection-scroll
    pattern = r'<div class="side-block__title">Sammlung</div>.*?<div class="side-block__content collection-scroll">(.*?)</div>\s*</div>'
    isMatch, sContainer = cParser.parseSingleResult(sHtmlContent, pattern)
    if not isMatch:
        cGui().showInfo()
        return

    pattern = r'href="([^"]+)"[^>]*>.*?<div class="custom-collection-title">([^<]+)</div>'
    isMatch, aResult = cParser.parse(sContainer, pattern)
    if not isMatch:
        cGui().showInfo()
        return

    for sUrl, sName in aResult:
        if sUrl.startswith('/'):
            sUrl = URL_MAIN.rstrip('/') + sUrl
        params.setParam('sUrl', sUrl)
        cGui().addFolder(cGuiElement(sName.strip(), SITE_IDENTIFIER, 'showEntries'), params)
    cGui().setEndOfDirectory()


def showLatest():
    """Zeigt die 'Zuletzt hinzugefuegt' Sektion von der Megakino-Homepage.
    Andere HTML-Struktur als poster grid-item: 'listItem' Container ohne Cover-Bilder.
    Cover kommt nicht aus dem Megakino-HTML (gibts nicht in dieser Sektion) — TMDB
    handelt das via Title+Year automatisch.
    """
    params = ParameterHandler()
    sHtmlContent = getHtmlContent(URL_MAIN)
    if not sHtmlContent:
        cGui().showInfo()
        return

    # Section isolieren: <h2>Zuletzt hinzugefuegt</h2> bis zum naechsten <section>
    isMatch, sContainer = cParser.parseSingleResult(
        sHtmlContent,
        r'<h2 class="sect__title[^"]*"[^>]*>Zuletzt hinzugefügt</h2>(.*?)(?=<section class="|$)'
    )
    if not isMatch:
        cGui().showInfo()
        return

    # listItem Pattern: Quality + URL + Title + Genre
    pattern = r'<div class="listItem">\s*<div class="listItem-badges">\s*<div class="listItem-badge listItem-quality">([^<]+)</div>.*?<div class="listItem-title">\s*<a href="([^"]+)">([^<]+)</a>\s*</div>\s*<div class="listItem-genre">([^<]+)</div>'
    isMatch, aResult = cParser.parse(sContainer, pattern)
    if not isMatch:
        cGui().showInfo()
        return

    total = len(aResult)
    isTvshow = False
    for sQuality, sUrl, sTitle, sGenre in aResult:
        # Year aus Title extrahieren: "They Will Kill You (2026)"
        sYear = ''
        isYear, aYear = cParser.parseSingleResult(sTitle, r'\((\d{4})\)')
        if isYear:
            sYear = aYear

        # Title cleanen (Year-Suffix raus, Display-Name bleibt mit "- Staffel N")
        sName = re.sub(r'\s*\(\d{4}\)\s*$', '', sTitle).strip()
        sName = sName.replace('&amp;', '&').replace('&#039;', "'").replace('&quot;', '"').strip()

        # Movie vs TV-Show via URL-Pfad — oder ueber das Serien-Badge der Karte
        # (gleiche Klasse wie in showEntries, siehe _isSeriesBadge)
        isTvshow = sUrl.startswith('/serials/') or _isSeriesBadge(sQuality)
        if sUrl.startswith('/'):
            sUrl = URL_MAIN.rstrip('/') + sUrl

        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showEpisodes' if isTvshow else 'showHosters')
        oGuiElement.setMediaType('tvshow' if isTvshow else 'movie')
        if sQuality:
            oGuiElement.setQuality(sQuality.strip())
        if sYear:
            oGuiElement.setYear(sYear)
        # Genre als Description (besser als nichts ohne Cover)
        if sGenre:
            oGuiElement.setDescription(sGenre.strip())
        params.setParam('entryUrl', sUrl)
        params.setParam('sName', sName)
        params.setParam('sDesc', sGenre.strip() if sGenre else '')
        if sYear:
            params.setParam('sYear', sYear)
        cGui().addFolder(oGuiElement, params, isTvshow, total)

    cGui().setView('tvshows' if isTvshow else 'movies')
    cGui().setEndOfDirectory()


def _isSeriesBadge(sBadge):
    """Serien-Badge der Karte: "Komplett" oder ein Folgenzaehler wie "+6 Episode"."""
    sBadge = (sBadge or '').strip()
    return sBadge == 'Komplett' or 'Episode' in sBadge


def _parsePage(sHtmlContent):
    """Parst eine einzelne Seite mit dem Full-Poster-Pattern und gibt (isMatch, aResult) zurueck.

    Das Quality-Badge (poster__label) ist OPTIONAL: nicht jede Karte traegt es
    (belegt: "Star Wars: The Bad Batch - Staffel 1" in der Suche). Als Pflichtfeld
    lief der Match sonst ueber die Kartengrenze bis zum Badge der NAECHSTEN Karte —
    die badge-lose Karte verschwand aus der Liste und der Nachbar bekam deren
    Adresse (Titel "Solo", Ziel Bad Batch). Ohne Badge bleibt die Quality leer.
    """
    pattern = r'<a class="poster grid-item[^>]*href="([^"]+)"[^>]*>.*?<img[^>]*data-src="([^"]+)"[^>]*alt="([^"]+)"[^>]*>.*?(?:<div class="poster__label">([^<]*)</div>.*?)?<h3 class="poster__title[^>]*>([^<]*)</h3>.*?<div class="poster__text[^>]*>([^<]*)</div>'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    return isMatch, aResult if isMatch else []


def _getNextPageUrl(sHtmlContent):
    """Extrahiert die Next-Page-URL aus pagination__btn-loader oder gibt False zurueck."""
    pattern = r'<div class="pagination__btn-loader[^>]*>\s*<a href="([^"]+)"'
    isMatch, sNextUrl = cParser.parseSingleResult(sHtmlContent, pattern)
    if isMatch:
        if sNextUrl.startswith('/'):
            sNextUrl = URL_MAIN.rstrip('/') + sNextUrl
        return sNextUrl
    return False


def _searchUrl(sSearchText, iPage=1, bFull=False):
    """Adresse einer Suchseite. Seite 1 ist die DLE-Suchadresse, die Folgeseiten
    blaettern ueber `search_start` und `result_from` — genau das setzt das
    list_submit-JS der Seite (Mitschnitt 21.10.2026: `frm.result_from.value=(prm-1)
    * 20 + 1; frm.search_start.value=prm; frm.submit()`); der Loader-Link aus
    _getNextPageUrl steht nur auf den Kategorieseiten, die Suchergebnisse haben
    gar kein href. Der Begriff wird kodiert, weil er roh von der Tastatur kommt —
    ein Umlaut ('könig') bricht urllib sonst mit UnicodeEncodeError ab; quotePlus
    macht aus Leerzeichen das '+', das die DLE-Suche erwartet.

    Gesucht wird in den TITELN (`titleonly=3`, die Titelsuche der Seite — so
    sucht kinoger schon immer): die Volltextsuche der Seite liefert bis zu 400
    nach Einstelldatum sortierte Beschreibungstreffer auf 20 Seiten, bei
    „der pate" stand der erste Pate-Film auf Seite 3 (gemessen 21.10.2026:
    Titelsuche 3 Treffer auf einer Seite, „Der Pate" und „Der Pate - Teil II"
    dabei; „star wars" 25 = 25, „love" 54 statt 25). bFull=True ist die
    Volltextsuche als Rueckfall, wenn die Titelsuche nichts findet — sie trifft
    z.B. „koenig" fuer „König", die Titelsuche nicht.

    Gebaut wird IMMER aus dem rohen Suchbegriff, nie aus einer fertigen Adresse:
    der Weiter-Eintrag traegt nur Begriff, Seitenzahl und den Rueckfall-Marker
    (Regel: roh im Parameter, kodiert nur am Abruf; bis zum
    02.11.2026 loeste der Parameterweg jede Kodierung ohnehin wieder auf,
    unquote_plus).
    """
    sUrl = URL_MAIN + '?do=search&subaction=search&story=' + cParser.quotePlus(sSearchText)
    if not bFull:
        sUrl += '&titleonly=3'
    if iPage > 1:
        sUrl += '&search_start=%d&result_from=%d' % (iPage, (iPage - 1) * 20 + 1)
    return sUrl


def _searchPages(sHtmlContent, iPage):
    """Seitenlage der Suche aus der Blaetterleiste: (hat Folgeseite, letzte Seite).

    Die Suchseite blaettert nicht ueber Links, sondern ueber `list_submit(N)` im
    onclick — die Leiste fuehrt jede andere Seite so, die aktive als <span>, und
    auf der letzten Seite steht keine hoehere Zahl mehr. Die hoechste Zahl ist
    die letzte Seite (die Leiste zeigt sie auch hinter der Auslassung: "love"
    2..10 und 20), eine hoehere Zahl als die aktive belegt die Folgeseite. Ohne
    Leiste gibt es nur diese eine Seite (gemessen 21.10.2026 ueber 15 Begriffe,
    Ende 4 von 4 richtig).
    """
    aPages = set(int(x) for x in re.findall(r'list_submit\((\d+)\)', sHtmlContent))
    iLast = max(aPages | {iPage})
    return iLast > iPage, iLast


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not sSearchText:
        # Weiter-Seite der Suche: Kodi ruft die Funktion neu auf, Begriff und
        # Seitenzahl stehen dann nur noch im Parameter. Ohne den Begriff liefe die
        # Folgeseite ungefiltert und zeigte die Beschreibungstreffer der Seite.
        sSearchText = params.getValue('sSearchText') or False
    iPage = 1
    bFull = False
    bNext, iLast = False, 1
    if sSearchText:
        iPage = int(params.getValue('page') or 1)
        bFull = params.getValue('full') == '1'
    elif not entryUrl:
        entryUrl = params.getValue('sUrl')

    while True:
        if sSearchText:
            entryUrl = _searchUrl(sSearchText, iPage, bFull)
        # Eine Folgeseite der Suche meldet Fehler nicht als Fenster: dort gilt wie
        # beim Blaettern „Kein Eintrag gefunden" (Seite 1 meldet wie bisher).
        sHtmlContent = getHtmlContent(entryUrl, bIgnoreErrors=(sGui is not False or iPage > 1))
        isMatch, aResult = _parsePage(sHtmlContent) if sHtmlContent else (False, [])
        if not sSearchText:
            break
        if not isMatch and iPage == 1 and not bFull and sHtmlContent:
            # Die Titelsuche der Seite kennt den Begriff nicht: einmal die
            # Volltextsuche der Seite fragen (Umlaut-Schreibweisen, Begriffe nur
            # in der Beschreibung). Nur bei einer echten Antwort (getHtmlContent
            # liefert bei Fehlern None), sonst kaeme das Fenster zweimal.
            bFull = True
            continue
        if not isMatch:
            break
        # Titelfilter wie an allen Filterstellen (cParser.searchTitle, normalisiert);
        # der Name ist der Kartentitel, ersatzweise das alt-Attribut des Covers
        aResult = [row for row in aResult if cParser.searchTitle(sSearchText, row[4] if row[4] else row[2])]
        bNext, iLast = _searchPages(sHtmlContent, iPage)
        if aResult or sGui or not bNext:
            break
        # Seite nach dem Titelfilter leer, aber die Leiste fuehrt eine Folgeseite:
        # gleich weiterblaettern statt dem Nutzer leere Seiten zu zeigen (gefunden
        # 21.10.2026 an hdfilme „der pate", fuenf leere Seiten). Nur in der
        # Einzelsuche — die globale Suche bleibt bei Seite 1.
        iPage += 1
    if not isMatch:
        if not sGui:
            oGui.showInfo()
        return

    total = len(aResult)
    isTvshow = True if 'serials' in entryUrl else False  # default basierend auf URL
    iShown = 0
    for sUrl, sThumb, sAlt, sQuality, sTitle, sDesc in aResult:
        sName = sTitle if sTitle else sAlt
        # Serien-Erkennung: URL hat /serials/ ODER "Staffel" im Titel ODER die
        # Karte traegt das Serien-Badge der Seite. Das Badge (poster__label) ist
        # bei Filmen die Qualitaet (HD, TS/MD, CAM/MIC ...), bei Serien der Stand
        # der Folgen ("Komplett", "+6 Episode"). Gemessen 01.09.2026 ueber 22
        # Listen: 345 Filmkarten mit Qualitaet, 94 Serienkarten mit Folgenstand -
        # und genau eine Serie, die die Seite als Film-Beitrag unter /drama/
        # fuehrt ("Band of Brothers", Badge "Komplett", zehn Folgen auf der
        # Detailseite). Ohne das Badge landete sie auf der Hoster-Ebene und lief
        # ins Leere; ein Detailabruf je Karte kostete 1,5 s pro Liste.
        isTvshow = True if 'serials' in sUrl or 'Staffel' in sName or _isSeriesBadge(sQuality) else False
        if sUrl.startswith('/'):
            sUrl = URL_MAIN.rstrip('/') + sUrl
        if sThumb.startswith('/'):
            sThumb = URL_MAIN.rstrip('/') + sThumb
        sName = sName.replace('&amp;', '&').replace('&#039;', "'").replace('&quot;', '"').strip()
        sDesc = sDesc.replace('&amp;', '&').replace('&#039;', "'").replace('&quot;', '"').strip()

        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showEpisodes' if isTvshow else 'showHosters')
        oGuiElement.setMediaType('tvshow' if isTvshow else 'movie')
        oGuiElement.setThumbnail(sThumb)
        if sQuality:
            oGuiElement.setQuality(sQuality.strip())
        if sDesc:
            oGuiElement.setDescription(sDesc[:500])
        params.setParam('entryUrl', sUrl)
        params.setParam('sThumbnail', sThumb)
        params.setParam('sName', sName)
        params.setParam('sDesc', sDesc)
        oGui.addFolder(oGuiElement, params, isTvshow, total)
        iShown += 1

    if not sGui:
        if sSearchText:
            # Suche: eine Seite je Aufruf, die Folgeseite ueber den Weiter-Eintrag mit
            # Begriff, Seitenzahl und Rueckfall-Marker (Bauform wie bei den anderen
            # Seiten). Leere Seiten wurden oben uebersprungen; ohne Treffer und ohne
            # Folgeseite kommt die Meldung „Kein Eintrag gefunden" (vorher Klasse (H),
            # stumme leere Liste, belegt mit "2019").
            if not iShown:
                oGui.showInfo()
            if bNext:
                nextParams = ParameterHandler()
                nextParams.setParam('sSearchText', sSearchText)
                nextParams.setParam('page', iPage + 1)
                if bFull:
                    nextParams.setParam('full', 1)
                oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', nextParams, cGui.pageInfo(iPage, iLast))
        else:
            # Seitenlage fuer den Weiter-Eintrag: die hoechste Zahl der Blaetterleiste ist
            # das Listenende — bei langen Listen steht sie hinter der "…"-Auslassung, bei
            # kurzen sind ohnehin alle Zahlen da (gemessen 04.09.2026 gegen die bisektierten
            # Enden, kurz wie lang). Die aktive Seite steht als <span> in derselben Leiste.
            sPageInfo = ''
            isMatchNav, sNav = cParser.parseSingleResult(sHtmlContent, r'class=\"pagination__pages[^\"]*\"[^>]*>(.*?)</div>')
            if isMatchNav:
                isMatchCur, sCurrent = cParser.parseSingleResult(sNav, r'<span[^>]*>(\d+)</span>')
                aPages = [int(x) for x in re.findall(r'>(\d{1,6})<', sNav)]
                if isMatchCur and aPages:
                    sPageInfo = cGui.pageInfo(sCurrent, max(aPages))
            sNextUrl = _getNextPageUrl(sHtmlContent)
            if sNextUrl:
                params.setParam('sUrl', sNextUrl)
                oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', params, sPageInfo)
        oGui.setView('tvshows' if isTvshow else 'movies')
        oGui.setEndOfDirectory()


def showEpisodes():
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    sName = params.getValue('sName')
    # Serienname ohne den Staffel-Zusatz der Seite ("Name - 2 Staffel" / "Name - Staffel 3")
    sShowName = re.sub(r'\s*-\s*(?:\d+\s*Staffel|Staffel\s*\d+).*$', '', sName or '').strip()
    # Staffelnummer aus demselben Zusatz — fuer Label und Staffel-Info; ohne Zusatz bleibt das Label der Seite ("Episode 5")
    mSeason = re.search(r'\s*-\s*(?:(\d+)\s*Staffel|Staffel\s*(\d+))', sName or '')
    sSeason = (mSeason.group(1) or mSeason.group(2)) if mSeason else ''
    sThumb = params.getValue('sThumbnail') if params.exist('sThumbnail') else ''
    sDesc = params.getValue('sDesc') if params.exist('sDesc') else ''
    sYear = params.getValue('sYear') if params.exist('sYear') else ''
    sHtmlContent = getHtmlContent(sUrl)
    if not sHtmlContent:
        cGui().showInfo()
        return

    # Pattern: <option value="epN">Episode-Name</option>
    pattern = r'<option\s+value="ep(\d+)"[^>]*>([^<]+)</option>'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        cGui().showInfo()
        return

    # Falls kein Parent-Thumbnail uebergeben (z.B. aus showLatest): aus Movie-Detail-Page extrahieren
    if not sThumb:
        isMatchOg, sOgImage = cParser.parseSingleResult(sHtmlContent, r'<meta property="og:image" content="([^"]+)"')
        if isMatchOg and sOgImage:
            sThumb = sOgImage
            if sThumb.startswith('/'):
                sThumb = URL_MAIN.rstrip('/') + sThumb

    total = len(aResult)
    for sEpisode, sEpName in aResult:
        # Eine Form auf allen Sites ("S02E05", cParser.episodeLabel); der Text der Seite ist dort ein Platzhalter
        oGuiElement = cGuiElement(cParser.episodeLabel(sSeason, sEpisode, sEpName, sEpName.strip()), SITE_IDENTIFIER, 'showEpisodeHosters')
        oGuiElement.setMediaType('episode')
        oGuiElement.setEpisode(sEpisode)
        if sSeason:
            oGuiElement.setSeason(sSeason)   # Staffel-Info fuer Kodi und Trakt wie auf den anderen Sites
        if sShowName: oGuiElement.setTVShowTitle(sShowName)
        if sThumb:
            oGuiElement.setThumbnail(sThumb)
        if sDesc:
            oGuiElement.setDescription(sDesc[:500])
        if sYear:
            # Jahr nur als Info (Info-Ansicht, Trakt), nicht ans Label: setYear haengt es an den Titel
            # ("S01E05 (2026)") — die anderen Sites geben das Jahr ebenso per addItemValue mit
            oGuiElement.addItemValue('year', sYear)
        params.setParam('episodeId', sEpisode)
        params.setParam('entryUrl', sUrl)
        cGui().addFolder(oGuiElement, params, False, total)
    cGui().setView('episodes')
    cGui().setEndOfDirectory()


def showHosters():
    """Movie-Hoster: <iframe data-src OR src="HOSTER_URL">"""
    hosters = []
    sUrl = ParameterHandler().getValue('entryUrl')
    sHtmlContent = getHtmlContent(sUrl)
    if not sHtmlContent:
        return hosters

    # data-src (lazy-load) UND src matchen — Megakino nutzt beide Varianten
    pattern = r'<iframe[^>]*(?:data-src|src)="(https?://[^"]+)"'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if isMatch:
        for sHosterUrl in aResult:
            if 'youtube' in sHosterUrl:
                continue  # YouTube-Trailer skippen
            sName = cParser.urlparse(sHosterUrl).split('.')[0].replace('https://', '').replace('http://', '').strip()
            if cConfig().isBlockedHoster(sName)[0]:
                continue
            sQuality = '720'
            hoster = {'link': sHosterUrl, 'name': sName, 'displayedName': '%s [I][%sp][/I]' % (sName, sQuality), 'quality': sQuality}
            hosters.append(hoster)
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def showEpisodeHosters():
    """Episode-Hoster: <select id="epN">...<option value="HOSTER_URL">Name</option>...</select>"""
    hosters = []
    sUrl = ParameterHandler().getValue('entryUrl')
    sEpisodeId = 'ep' + ParameterHandler().getValue('episodeId')
    sHtmlContent = getHtmlContent(sUrl)
    if not sHtmlContent:
        return hosters

    pattern = r'<select[^>]*id="%s"[^>]*>(.*?)</select>' % sEpisodeId
    isMatch, sContainer = cParser.parseSingleResult(sHtmlContent, pattern)
    if not isMatch:
        return hosters

    pattern = r'<option[^>]*value="(https?://[^"]+)"[^>]*>([^<]+)</option>'
    isMatch, aResult = cParser.parse(sContainer, pattern)
    if not isMatch:
        # Fallback: nur value=
        isMatch, urls = cParser.parse(sContainer, r'value="(https?://[^"]+)"')
        if isMatch:
            aResult = [(u, '') for u in urls]

    if isMatch:
        for sHosterUrl, sHosterName in aResult:
            if 'youtube' in sHosterUrl:
                continue
            sName = sHosterName.strip() if sHosterName.strip() else cParser.urlparse(sHosterUrl).split('.')[0]
            sName = sName.replace('https://', '').replace('http://', '').strip()
            if cConfig().isBlockedHoster(sName)[0]:
                continue
            sQuality = '720'
            hoster = {'link': sHosterUrl, 'name': sName, 'displayedName': '%s [I][%sp][/I]' % (sName, sQuality), 'quality': sQuality}
            hosters.append(hoster)
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def getHosterUrl(sUrl=False):
    return [{'streamUrl': sUrl, 'resolved': False}]


def showSearch():
    win = xbmcgui.Window(10000)
    sSearchText = win.getProperty('xstream.megakino.lastSearchText')
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30281))
        if not sSearchText:
            return
        win.setProperty('xstream.megakino.lastSearchText', sSearchText)
    # Das Verzeichnis schliesst showEntries selbst ab — so wie bei jeder
    # Weiter-Seite der Suche, die Kodi direkt dort aufruft.
    _search(False, sSearchText)


def _search(oGui, sSearchText):
    showEntries(False, oGui, sSearchText)
