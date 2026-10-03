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

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'megakino21.com')
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
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30500), SITE_IDENTIFIER, 'showLatest'))  # Neues / Zuletzt hinzugefuegt
    params.setParam('sUrl', URL_MOVIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30502), SITE_IDENTIFIER, 'showEntries'), params)  # Filme
    params.setParam('sUrl', URL_SERIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30511), SITE_IDENTIFIER, 'showEntries'), params)  # Serien
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30506), SITE_IDENTIFIER, 'showGenre'))  # Genre
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30543), SITE_IDENTIFIER, 'showCollection'))  # Sammlung
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'))  # Suche
    cGui().setEndOfDirectory()


def getHtmlContent(url):
    """Hilfsfunktion zum Abrufen von HTML-Inhalten mit yg_token Cookie-Bypass.
    Megakino liefert bei erstem Hit ein JS-Stub das einen Token-Endpoint hittet.
    Token setzt Cookie, bei zweitem Request kommt echtes HTML.

    UA-Sticky: Alle 3 Requests im Token-Flow MUESSEN identischen UA nutzen
    (Cookie an UA gebunden, Anti-Bot prueft UA-Konsistenz zwischen Token+HTML).
    Drum einmal RandomUA() aufrufen und an alle 3 Requests weitergeben.
    """
    sessionUA = cRequestHandler.RandomUA()
    oRequest = cRequestHandler(url)
    oRequest.cacheTime = 0
    oRequest.addHeaderEntry('User-Agent', sessionUA)
    oRequest.addHeaderEntry('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8')
    oRequest.addHeaderEntry('Accept-Language', 'de-DE,de;q=0.9,en;q=0.8')
    oRequest.addHeaderEntry('Referer', URL_MAIN)
    sHtmlContent = oRequest.request()

    # Token-Stub erkannt -> Token holen + Original-URL retry
    if sHtmlContent and 'yg=token' in sHtmlContent and len(sHtmlContent) < 1000:
        logger.info('[megakino] Token-Stub erkannt, hole Token...')
        oTokenRequest = cRequestHandler(URL_MAIN + 'index.php?yg=token')
        oTokenRequest.cacheTime = 0
        oTokenRequest.addHeaderEntry('User-Agent', sessionUA)
        oTokenRequest.addHeaderEntry('Accept', '*/*')
        oTokenRequest.addHeaderEntry('Accept-Language', 'de-DE,de;q=0.9,en;q=0.8')
        oTokenRequest.addHeaderEntry('Referer', url)
        oTokenRequest.addHeaderEntry('X-Requested-With', 'XMLHttpRequest')
        oTokenRequest.request()

        # Original-URL nochmal abrufen mit Cookie
        oRequest2 = cRequestHandler(url)
        oRequest2.cacheTime = 0
        oRequest2.addHeaderEntry('User-Agent', sessionUA)
        oRequest2.addHeaderEntry('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8')
        oRequest2.addHeaderEntry('Accept-Language', 'de-DE,de;q=0.9,en;q=0.8')
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


# Pause vor jedem Nachholversuch: gibt einem Rate-Limit Luft. Laenger kostet
# nur im Fehlerfall — im Normalfall laeuft keine einzige Pause.
RETRY_PAUSE = 0.6


def _fetchAllSearchPages(startUrl, sGui=False):
    """Holt ALLE Seiten einer Suche und gibt kombinierte Ergebnisse zurueck.
    Megakino-Suche zeigt bei vielen Treffern mehrere Seiten — Kodi-User soll alle sehen.

    Geblaettert wird ueber `search_start`, NICHT ueber _getNextPageUrl: der dort
    gesuchte Loader-Link steht nur auf den Kategorieseiten, die Suchergebnisse
    blaettern per list_submit-JS und haben gar kein href. Deshalb brach die
    Suche vorher immer nach Seite 1 ab — "star wars" lieferte 14 statt 23
    Treffer, die Hauptfilme (Episode IV bis VI, Rogue One) standen auf Seite 2.
    `result_from` ist der Versatz in 20er-Schritten, so gibt es das JS der Seite vor.

    Abbruch ist eine Seite ohne Treffer. Das Limit bleibt, weil breite Begriffe
    weiterblaettern, solange die Volltextsuche noch irgendetwas findet.

    Fehlertoleranz in zwei Stufen (Anlass: unter Last fielen bei den
    Schwester-Sites zufaellig ganze Seiten still aus, gemessen 31.08. an
    streamcloud) — je Seite laufen hoechstens zwei Versuche:
    - Ein GESCHEITERTER Abruf wird einmal mit kurzer Pause nachgefasst
      statt still verworfen.
    - Eine ERREICHTE Seite ohne Treffer gilt erst als Listenende, wenn ein
      zweiter Abruf das bestaetigt. Kostet am echten Ende einen Zusatzabruf
      (samt Token-Gate).
    """
    allResults = []
    # In der globalen Suche laufen alle Sites gleichzeitig, deshalb dort nur
    # fuenf Seiten. Der Einzelaufruf der Site bleibt bei zehn.
    maxPages = 5 if sGui else 10  # Sicherheitslimit
    sSep = '&' if '?' in startUrl else '?'

    for page in range(1, maxPages + 1):
        sUrl = startUrl if page == 1 else '%s%ssearch_start=%d&result_from=%d' % (
            startUrl, sSep, page, (page - 1) * 20 + 1)
        sHtmlContent = getHtmlContent(sUrl)
        if not sHtmlContent:
            # Gescheitert (Timeout, Sperre, 404): einmal mit Pause nachfassen
            # statt die Seite still zu verwerfen. Je Seite laufen hoechstens
            # zwei Versuche; jeder kann das Token-Gate durchlaufen.
            time.sleep(RETRY_PAUSE)
            sHtmlContent = getHtmlContent(sUrl)
            if not sHtmlContent:
                logger.info('searchRetry %s: Seite %d weiterhin nicht erreichbar, Treffer dieser Seite fehlen' % (SITE_NAME, page))
                continue
            isMatch, aResult = _parsePage(sHtmlContent)
            if not isMatch or not aResult:
                # Erst tot, dann leer erreicht: mehr als zwei Versuche je Seite
                # gibt es nicht — die leere Antwort gilt als Listenende.
                break
            logger.info('searchRetry %s: Seite %d nachgeholt, %d Treffer' % (SITE_NAME, page, len(aResult)))
            allResults.extend(aResult)
            continue

        isMatch, aResult = _parsePage(sHtmlContent)
        if not isMatch or not aResult:
            # Ende-Kandidat: einmal bestaetigen, bevor abgebrochen wird — ein
            # 200er-Hickser (Fehlerseite mit Inhalt, leere Antwort unter Last)
            # saehe sonst exakt wie das Listenende aus.
            time.sleep(RETRY_PAUSE)
            sHtmlContent2 = getHtmlContent(sUrl)
            if sHtmlContent2:
                isMatch2, aResult2 = _parsePage(sHtmlContent2)
                if isMatch2 and aResult2:
                    logger.info('searchRetry %s: Seite %d nachgeholt, %d Treffer' % (SITE_NAME, page, len(aResult2)))
                    allResults.extend(aResult2)
                    continue
                break
            logger.info('searchRetry %s: Seite %d nicht bestaetigt, Treffer dieser Seite fehlen' % (SITE_NAME, page))
            continue
        allResults.extend(aResult)

    return allResults


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl:
        entryUrl = params.getValue('sUrl')

    # Search nutzt DLE-URL Format. Der Begriff wird kodiert, weil er roh von
    # der Tastatur kommt — ein Umlaut ('könig') bricht urllib sonst mit
    # UnicodeEncodeError ab. quotePlus macht aus Leerzeichen das '+', das die
    # DLE-Suche erwartet.
    if sSearchText:
        entryUrl = URL_MAIN + '?do=search&subaction=search&story=' + cParser.quotePlus(sSearchText)

    # Bei Suche: ALLE Seiten auf einmal holen + zusammenfuehren
    if sSearchText:
        aResult = _fetchAllSearchPages(entryUrl, sGui)
        isMatch = len(aResult) > 0
        sHtmlContent = None  # nicht mehr noetig fuer Pagination
    else:
        sHtmlContent = getHtmlContent(entryUrl)
        if not sHtmlContent:
            if not sGui:
                oGui.showInfo()
            return
        isMatch, aResult = _parsePage(sHtmlContent)

    if not isMatch:
        if not sGui:
            oGui.showInfo()
        return

    total = len(aResult)
    isTvshow = True if 'serials' in entryUrl else False  # default basierend auf URL
    iShown = 0
    for sUrl, sThumb, sAlt, sQuality, sTitle, sDesc in aResult:
        sName = sTitle if sTitle else sAlt
        if sSearchText and not cParser.searchTitle(sSearchText, sName):
            continue
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
        # Pagination nur bei normalen Listen — Search holt schon alle Seiten via _fetchAllSearchPages
        if not sSearchText and sHtmlContent:
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
        # Kamen Treffer an, wurden aber ALLE vom Titelfilter verworfen,
        # stand hier bisher ein leeres Verzeichnis ohne jeden Hinweis
        # (belegt mit dem Suchbegriff "2019"). Klasse (H): lieber die
        # normale Kein-Inhalt-Meldung als eine stumme leere Liste.
        if not iShown:
            oGui.showInfo()
        oGui.setEndOfDirectory()


def showEpisodes():
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    sName = params.getValue('sName')
    # Serienname ohne den Staffel-Zusatz der Seite ("Name - 2 Staffel" / "Name - Staffel 3")
    sShowName = re.sub(r'\s*-\s*(?:\d+\s*Staffel|Staffel\s*\d+).*$', '', sName or '').strip()
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
        oGuiElement = cGuiElement(sEpName.strip(), SITE_IDENTIFIER, 'showEpisodeHosters')
        oGuiElement.setMediaType('episode')
        oGuiElement.setEpisode(sEpisode)
        if sShowName: oGuiElement.setTVShowTitle(sShowName)
        if sThumb:
            oGuiElement.setThumbnail(sThumb)
        if sDesc:
            oGuiElement.setDescription(sDesc[:500])
        if sYear:
            oGuiElement.setYear(sYear)
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
            # GXPlayer-Mapping (URL ist watch.gxplayer.xyz)
            if sName.lower() == 'watch':
                sName = 'GXPlayer'
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
            if sName.lower() == 'watch':
                sName = 'GXPlayer'
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
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def _search(oGui, sSearchText):
    showEntries(URL_MAIN, oGui, sSearchText)
