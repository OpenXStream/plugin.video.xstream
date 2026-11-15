# -*- coding: utf-8 -*-
# Python 3
# Always pay attention to the translations in the menu!

import concurrent.futures
import re
import time
import xbmcgui
from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler, REQUEST_ERRORS
from resources.lib.logger import logger
from resources.lib.wrappers.meinecloud import resolveMeinecloud, resolveMeinecloudSerial, expandHosterList, buildHosterFromUrl, buildMergedHosters, MEINECLOUD_TRIGGER, platformImdbId, packSourceUrls
from resources.lib.tools import cParser
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui

SITE_IDENTIFIER = 'hdfilme'
SITE_NAME = 'HD Filme'
SITE_ICON = 'hdfilme.png'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'hd-filme.skin')  # seit dem 02.11.2026: .bond leitet mit 301 auf .skin um
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)

URL_MAIN = 'https://' + DOMAIN + '/'
URL_NEW = URL_MAIN + 'kinofilme-online/'
URL_KINO = URL_MAIN + 'aktuelle-kinofilme-im-kino/'
URL_SERIES = URL_MAIN + 'serienstream-deutsch/'

def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.hdfilme.lastSearchText')
    params = ParameterHandler()
    params.setParam('sUrl', URL_KINO)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30501), SITE_IDENTIFIER, 'showEntries'), params)  # Aktuelle Releases
    # Aufbau wie kkiste (gleiche Seitenfamilie), seit dem 10.09.2026: die Startseite ist die
    # gemischte Neu-Liste (rund 35 Eintraege, Filme und Serien, blaettert nicht), die
    # Filmliste /kinofilme-online/ (Navigation: „Kinofilme“) ist „Filme“ — vorher hing
    # „Neu auf der Seite“ an der Filmliste
    params.setParam('sUrl', URL_MAIN)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30500), SITE_IDENTIFIER, 'showEntries'), params)  # Neu auf der Seite
    params.setParam('sUrl', URL_NEW)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30502), SITE_IDENTIFIER, 'showEntries'), params)  # Filme
    params.setParam('sUrl', URL_SERIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30511), SITE_IDENTIFIER, 'showEntries'), params)  # Series
    params.setParam('sUrl', URL_MAIN)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30506), SITE_IDENTIFIER, 'showGenre'), params)  # Genre
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'), params)# Search
    cGui().setEndOfDirectory()


def showGenre(entryUrl=False):
    params = ParameterHandler()
    if not entryUrl: entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl)
    sHtmlContent = oRequest.request()
    # Neue Kopfleiste der Seite am 07.10.2026 (modern-nav, gegen 12:10): das Dropdown „KATEGORIE" traegt kein
    # title="Genre" mehr — Anker ist jetzt der Linktext, die Liste das <ul> direkt dahinter
    pattern = r'KATEGORIE\s*</a>\s*<ul[^>]*>(.*?)</ul>'
    isMatch, sHtmlContainer = cParser.parseSingleResult(sHtmlContent, pattern)
    if isMatch:
        isMatch, aResult = cParser.parse(sHtmlContainer, 'href="([^"]+)"[^>]*>([^<]+)</a>')
    if not isMatch:
        cGui().showInfo()
        return

    # Navigations-Einträge filtern (sind auch im Hauptmenü schon drin)
    nav_slugs = ['kinofilme-online', 'serienstream-deutsch', 'aktuelle-kinofilme-im-kino', 'demnachst',
                 'erotik', 'erotikfilme']
    for sUrl, sName in aResult:
        if sUrl.startswith('/'):
            sUrl = URL_MAIN + sUrl.lstrip('/')
        if any(nav in sUrl for nav in nav_slugs):
            continue
        params.setParam('sUrl', sUrl)
        cGui().addFolder(cGuiElement(sName.strip(), SITE_IDENTIFIER, 'showEntries'), params)
    cGui().setEndOfDirectory()


def _searchRequest(sSearchText, iPage=1, bFull=False, bIgnoreErrors=False):
    """Abruf einer Suchseite ueber das Suchformular der Seite: `<form method="post">`
    ohne action mit den versteckten Feldern do=search und subaction=search (Markup
    der Seite, 30.10.2026) — der Rumpf geht an die Startseite, so wie ihn der
    Browser eines Besuchers schickt. Die Suchadresse `index.php?do=search` (bis zum
    29.10.2026 als GET gebaut, wie kinoger sie noch nutzt) liegt bei HD Filme seit
    dem 30.10.2026 hinter einer Cloudflare-Pruefung, egal ob GET oder POST (am
    29.10. lief sie noch; gemessen 30.10.2026 am echten Handler: Suchadresse 403
    Cloudflare, Listen und Formularweg 200) — dieselbe Klasse wie kellerkino am
    02.10.2026 (Suchspam-Regel auf EINER Route, Pfad-Karte statt Kopfsatz). Die
    Felder liest die Seite aus der Anfrage, nicht aus der Adresse, deshalb kommt
    das Formular mit denselben Feldern durch wie vorher der GET. Der Begriff geht
    als Formularfeld so raus, wie ihn das Formular der Seite schickt (der GET
    kodierte ihn ueber quotePlus und urlEncode doppelt: `star%2Bwars`).

    Die Folgeseiten blaettern ueber `search_start` und `result_from` — genau das
    setzt das list_submit-JS der Seite (Mitschnitt 21.10.2026: `frm.result_from.value
    =(prm-1) * 10 + 1; frm.search_start.value=prm; frm.submit()`).

    Gesucht wird in den TITELN (`titleonly=3`, die Titelsuche der Seite — so
    sucht kinoger schon immer): die Volltextsuche der Seite liefert nach
    Einstelldatum sortierte Beschreibungstreffer mit einem 50er-Deckel, bei
    „der pate" standen die Pate-Filme dahinter und alle fuenf Seiten waren nach
    dem Titelfilter leer (gemessen 21.10.2026: Titelsuche 7 Treffer auf einer
    Seite statt 0 auf fuenf; „star wars" 44 = 44, „love" 50 statt 42; der
    Abruf ist sogar schneller, 0,8 statt 1,4 s). bFull=True ist die
    Volltextsuche als Rueckfall, wenn die Titelsuche nichts findet — sie trifft
    z.B. „koenig" fuer „König", die Titelsuche nicht.

    Gebaut wird IMMER aus dem rohen Suchbegriff, nie aus einer fertigen Adresse:
    der Weiter-Eintrag traegt nur Begriff, Seitenzahl und den Rueckfall-Marker
    (Regel: roh im Parameter, kodiert nur am Abruf; bis zum
    02.11.2026 loeste der Parameterweg jede Kodierung ohnehin wieder auf,
    unquote_plus). Der Rumpf kodiert den Begriff selbst (addParameters).
    """
    oRequest = cRequestHandler(URL_MAIN, ignoreErrors=bIgnoreErrors)
    oRequest.addParameters('do', 'search')
    oRequest.addParameters('subaction', 'search')
    oRequest.addParameters('story', sSearchText)
    if not bFull:
        oRequest.addParameters('titleonly', '3')
    if iPage > 1:
        oRequest.addParameters('search_start', str(iPage))
        oRequest.addParameters('result_from', str((iPage - 1) * 10 + 1))
    return oRequest


def _searchPages(sHtmlContent, iPage):
    """Seitenlage der Suche aus der Blaetterleiste: (hat Folgeseite, letzte Seite).

    Die Suchseite blaettert nicht ueber Links, sondern ueber `list_submit(N)` im
    onclick — die Leiste fuehrt jede andere Seite so, die aktive als <span>, und
    auf der letzten Seite steht keine hoehere Zahl mehr. Die hoechste Zahl ist
    die letzte Seite, eine hoehere Zahl als die aktive belegt die Folgeseite.
    Ohne Leiste gibt es nur diese eine Seite (gemessen 21.10.2026 ueber 15
    Begriffe, Ende 7 von 7 richtig). Der Vorwaerts-Link der Seite taugt dafuer
    NICHT — er verschwindet ab Seite 5, obwohl es weitergeht.
    """
    aPages = set(int(x) for x in re.findall(r'list_submit\((\d+)\)', sHtmlContent))
    iLast = max(aPages | {iPage})
    return iLast > iPage, iLast


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    isTvshow = False
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
    pattern = '<div class="box-product(.*?)<h3.*?href="([^"]+).*?">([^<]+).*?(.*?)</li>'
    while True:
        if sSearchText:
            # Suche ueber das Formular der Seite (_searchRequest). Eine Folgeseite der
            # Suche meldet Fehler nicht als Fenster: dort gilt wie beim Blaettern
            # „Kein Eintrag gefunden" (Seite 1 meldet wie bisher).
            oRequest = _searchRequest(sSearchText, iPage, bFull, sGui is not False or iPage > 1)
        else:
            # Adressen mit Leerzeichen oder Umlaut kommen aus dem Parameter-Durchlauf
            # unkodiert zurueck -> direkt vor dem Request kodieren (deckt auch die
            # Naechste-Seite-URL ab). Pfadstruktur bleibt erhalten.
            sRequestUrl = cParser.urlEncode(entryUrl, safe="/:?=&%#")
            oRequest = cRequestHandler(sRequestUrl, ignoreErrors=(sGui is not False))
        sHtmlContent = oRequest.request()
        isMatch, aResult = cParser.parse(sHtmlContent, pattern)
        if not sSearchText:
            break
        if not isMatch and iPage == 1 and not bFull and sHtmlContent and sHtmlContent not in REQUEST_ERRORS:
            # Die Titelsuche der Seite kennt den Begriff nicht: einmal die
            # Volltextsuche der Seite fragen (Umlaut-Schreibweisen, Begriffe nur
            # in der Beschreibung). Nur bei einer echten Antwort, nie nach einem
            # Fehler — sonst kaeme das Fenster zweimal.
            bFull = True
            continue
        if not isMatch:
            break
        # Titelfilter wie an allen Filterstellen (cParser.searchTitle, normalisiert)
        aResult = [row for row in aResult if cParser.searchTitle(sSearchText, row[2])]
        bNext, iLast = _searchPages(sHtmlContent, iPage)
        if aResult or sGui or not bNext:
            break
        # Seite nach dem Titelfilter leer, aber die Leiste fuehrt eine Folgeseite:
        # gleich weiterblaettern statt dem Nutzer leere Seiten zu zeigen (gefunden
        # 21.10.2026 an „der pate", fuenf leere Seiten). Nur in der Einzelsuche —
        # die globale Suche bleibt bei Seite 1.
        iPage += 1
    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    total = len(aResult)
    iShown = 0
    # Keine Sprachlogik mehr (seit dem 10.09.2026): die Seite ist deutsch, englische
    # Fassungen tragen den Zusatz „English*" im Titel und sind so erkennbar —
    # ein Filter danach blendete je Einstellung Eintraege aus, ohne dass die
    # Seite je Hoster eine Sprache nennt (Regel: Sprachlogik nur, wo das Label
    # der Seite sie hergibt, wie bei serienstream, aniworld, burningseries, filmo).
    for sInfo, sUrl, sName, sDummy in aResult:
        isThumbnail, sThumbnail = cParser.parseSingleResult(sInfo, 'data-src="([^"]+)')
        # Template-Wechsel der Seite am 07.10.2026 (gegen 11:50): das Jahr steht im movie-meta-Block hinter dem
        # Kalender-Symbol, die Qualitaet als Plakette im Cover (movie-quality) — die alten Muster (<p>-Jahr,
        # quality-product) fanden nichts mehr, Jahr und Qualitaet fehlten still in jedem Label
        isYear, sYear = cParser.parseSingleResult(sDummy, r'fa-calendar-o[^>]*></i>\s*(\d{4})\s*<')
        isQuality, sQuality = cParser.parseSingleResult(sInfo, r'movie-quality">\s*([^<]+?)\s*<')
        isTvshow = True if 'taffel' in sName else False
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons' if isTvshow else 'showHosters')
        oGuiElement.setMediaType('tvshow' if isTvshow else 'movie')
        if isThumbnail:
            # data-src ist ein Pfad mit fuehrendem Schraegstrich, URL_MAIN endet auf einen —
            # ohne lstrip entstand ".../" + "/uploads/…" (doppelter Schraegstrich in jedem Cover)
            if not sThumbnail.startswith('http'):
                sThumbnail = URL_MAIN + sThumbnail.lstrip('/')
            oGuiElement.setThumbnail(sThumbnail)
        if isYear:
            oGuiElement.setYear(sYear)
        if isQuality:
            oGuiElement.setQuality(sQuality)
        oGuiElement.setMediaType('tvshow' if isTvshow else 'movie')
        params.setParam('entryUrl', sUrl)
        params.setParam('sName', sName)
        params.setParam('sThumbnail', sThumbnail)
        oGui.addFolder(oGuiElement, params, isTvshow, total)
        iShown += 1
    if sGui:
        return
    if sSearchText:
        # Suche: eine Seite je Aufruf, die Folgeseite ueber den Weiter-Eintrag mit
        # Begriff, Seitenzahl und Rueckfall-Marker (Bauform wie bei den anderen
        # Seiten). Leere Seiten wurden oben uebersprungen; ohne Treffer und ohne
        # Folgeseite kommt die Meldung „Kein Eintrag gefunden".
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
        isMatchNextPage, sNextUrl = cParser.parseSingleResult(sHtmlContent, 'href="([^"]+)">›</a></div>')
        # Seitenlage fuer den Weiter-Eintrag: die hoechste Zahl der Blaetterleiste ist
        # das Listenende — bei langen Listen steht sie hinter der "…"-Auslassung, bei
        # kurzen sind ohnehin alle Zahlen da (gemessen 04.09.2026 gegen die bisektierten
        # Enden, kurz wie lang). Die aktive Seite steht als <span> in derselben Leiste.
        # Leerraum zwischen den beiden schliessenden div der Leiste erlaubt: die Seite liefert
        # Brotkrume und Blaetterleiste mit CRLF, den Rest mit LF (30.10.2026, 5 CR je Listenseite),
        # der requestHandler entfernt nur LF — ohne \s* lief das Muster bis zum naechsten Block weiter
        # und nahm die Sternwertung 0–5 als Seitenzahl mit (Biographie „(1/5)" statt „(1/2)").
        sPageInfo = ''
        isMatchSiteSearch, sHtmlContainer = cParser.parseSingleResult(sHtmlContent, r'class="pagination(.*?)</div>\s*</div>')
        if isMatchSiteSearch:
            isMatchCur, sCurrent = cParser.parseSingleResult(sHtmlContainer, r'<span[^>]*>(\d+)</span>')
            aPages = [int(x) for x in re.findall(r'>(\d{1,6})<', sHtmlContainer)]
            if isMatchCur and aPages:
                sPageInfo = cGui.pageInfo(sCurrent, max(aPages))
        if isMatchNextPage:
            params.setParam('sUrl', sNextUrl)
            oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', params, sPageInfo)
    oGui.setView('tvshows' if isTvshow else 'movies')
    oGui.setEndOfDirectory()


def showSeasons():
    """Staffel-Ebene. hdfilme legt pro Staffel eine eigene Seite an (intern immer
    "serie-1_N", echte Staffel im Titel); meinecloud liefert die komplette Serie.
    Hat mc mehr Staffeln, nehmen wir mc als Rueckgrat (alle Staffeln sichtbar) und
    mergen die nativen Hoster in die passende Staffel (siehe showEpisodes)."""
    params = ParameterHandler()
    entryUrl = params.getValue('entryUrl')
    sName = params.getValue('sName') if params.exist('sName') else ''
    sThumbnail = params.getValue('sThumbnail') if params.exist('sThumbnail') else ''
    # Serienname ohne " - Staffel N" (die Seite fuehrt je Staffel einen eigenen Eintrag)
    sShowName = re.sub(r'\s*-\s*Staffel\s+\d+.*$', '', sName or '').strip()
    sHtmlContent = cRequestHandler(entryUrl).request()

    _, aNativeInternal = cParser.parse(sHtmlContent, r'<li id="serie-(\d+)_\d+">')
    nativeInternal = sorted(set(aNativeInternal), key=int) if aNativeInternal else []

    sImdbId = platformImdbId(sHtmlContent)
    aMc = resolveMeinecloudSerial(sImdbId, referer=entryUrl, siteHtml=sHtmlContent) if sImdbId else []
    mcSeasons = sorted(set(ep['season'] for ep in aMc))

    if mcSeasons and len(mcSeasons) > len(nativeInternal):
        seasons = [str(s) for s in mcSeasons]
    elif nativeInternal:
        isTitleSeason, sTitleSeason = cParser.parseSingleResult(sName, r'[Ss]taffel\s*(\d+)')
        if len(nativeInternal) == 1 and isTitleSeason:
            seasons = [sTitleSeason]
        else:
            seasons = nativeInternal
    elif mcSeasons:
        seasons = [str(s) for s in mcSeasons]
    else:
        seasons = []

    if not seasons:
        cGui().showInfo()
        return

    if len(seasons) == 1:
        showEpisodes(staffel=seasons[0], htmlContent=sHtmlContent, mcEpisodes=aMc)
        return

    for sStaffel in seasons:
        oGuiElement = cGuiElement(cConfig().getLocalizedString(30512) + ' %s' % sStaffel, SITE_IDENTIFIER, 'showEpisodes')
        oGuiElement.setMediaType('season')
        oGuiElement.setSeason(sStaffel)
        if sShowName: oGuiElement.setTVShowTitle(sShowName)
        if sThumbnail:
            oGuiElement.setThumbnail(sThumbnail)
        params.setParam('entryUrl', entryUrl)
        params.setParam('sName', sName)
        params.setParam('staffel', sStaffel)
        cGui().addFolder(oGuiElement, params, True)
    cGui().setView('seasons')
    cGui().setEndOfDirectory()


def showEpisodes(staffel=None, htmlContent=None, mcEpisodes=None):
    params = ParameterHandler()
    entryUrl = params.getValue('entryUrl')
    sName = params.getValue('sName') if params.exist('sName') else ''
    sShowName = re.sub(r'\s*-\s*Staffel\s+\d+.*$', '', sName or '').strip()   # Serienname ohne " - Staffel N"
    sThumbnail = params.getValue('sThumbnail') if params.exist('sThumbnail') else ''
    sStaffel = staffel if staffel is not None else params.getValue('staffel')
    if htmlContent is not None:
        sHtmlContent = htmlContent
    else:
        sHtmlContent = cRequestHandler(entryUrl).request()

    # Native Episoden-Map {episode:int -> (linktext, hosterBlock)} (serie-INTERN_N).
    nativeMap = {}
    _, aInternal = cParser.parse(sHtmlContent, r'<li id="serie-(\d+)_\d+">')
    internalSeasons = sorted(set(aInternal), key=int) if aInternal else []
    isTitleSeason, sTitleSeason = cParser.parseSingleResult(sName, r'[Ss]taffel\s*(\d+)')
    sInternalForThis = None
    if len(internalSeasons) == 1:
        sRealOfPage = sTitleSeason if isTitleSeason else internalSeasons[0]
        if str(sRealOfPage) == str(sStaffel):
            sInternalForThis = internalSeasons[0]
    elif str(sStaffel) in internalSeasons:
        sInternalForThis = str(sStaffel)
    if sInternalForThis is not None:
        pattern = r'<li id="serie-' + re.escape(sInternalForThis) + r'_(\d+)"><a href="#">([^<]+)</a>\s*<ul[^>]*>(.*?)</ul>\s*</li>'
        isNat, aNat = cParser.parse(sHtmlContent, pattern)
        if isNat:
            for sEp, sTxt, sBlock in aNat:
                nativeMap[int(sEp)] = (sTxt.strip(), sBlock)

    # meinecloud Episoden dieser Staffel: von showSeasons durchgereicht (Einstaffel-
    # Sprung, ausdruecklich auch eine LEERE Liste — sonst fragt ein Klick die
    # Plattform zweimal und zahlt bei einem Ausfall zweimal den Timeout), beim
    # Klick auf einen Staffel-Ordner selbst laden.
    if mcEpisodes is not None:
        aMc = list(mcEpisodes)
    else:
        sImdbId = platformImdbId(sHtmlContent)
        aMc = resolveMeinecloudSerial(sImdbId, referer=entryUrl, siteHtml=sHtmlContent) if sImdbId else []
    mcMap = {ep['episode']: ep for ep in aMc if str(ep['season']) == str(sStaffel)}

    if not nativeMap and not mcMap:
        cGui().showInfo()
        return

    isDesc, sDesc = cParser.parseSingleResult(sHtmlContent, '"description"[^>]content="([^"]+)')
    allEps = sorted(set(mcMap.keys()) | set(nativeMap.keys()))
    total = len(allEps)
    for iEp in allEps:
        mcEp = mcMap.get(iEp)
        sTxt, sBlock = nativeMap.get(iEp, ('', ''))
        # Eine Form auf allen Sites ("S01E05 - Titel", cParser.episodeLabel): der Titel kommt von der Plattform,
        # sonst der Linktext der Seite — der ist ein Platzhalter ("Episoden 5") und faellt dort weg
        sLabel = cParser.episodeLabel(sStaffel, iEp, mcEp['title'] if mcEp else sTxt)
        oGuiElement = cGuiElement(sLabel, SITE_IDENTIFIER, 'showHosters')
        if sThumbnail:
            oGuiElement.setThumbnail(sThumbnail)
        if isDesc:
            oGuiElement.setDescription(sDesc)
        oGuiElement.setMediaType('episode')
        oGuiElement.setSeason(str(sStaffel))
        oGuiElement.setEpisode(str(iEp))
        if sShowName: oGuiElement.setTVShowTitle(sShowName)
        params.setParam('entryUrl', entryUrl)
        params.setParam('hosterBlock', sBlock)
        params.setParam('meinecloud_url', packSourceUrls(mcEp['urls']) if mcEp else '')
        cGui().addFolder(oGuiElement, params, False, total)
    cGui().setView('episodes')
    cGui().setEndOfDirectory()


def showHosters():
    hosters = []
    params = ParameterHandler()
    # Serie: showEpisodes hat hosterBlock (nativ) und/oder meinecloud_url gesetzt.
    # Movie: keiner der beiden -> Movie-Page laden.
    sHosterBlock = params.getValue('hosterBlock') if params.exist('hosterBlock') else ''
    sMcUrl = params.getValue('meinecloud_url') if params.exist('meinecloud_url') else ''

    if sHosterBlock or sMcUrl:
        # Merge-Pfad: native data-link Hoster + meinecloud-Adressen (alle Quellen der
        # Folge, gepackter Parameter) zusammenlegen.
        aNativeRaw = []
        if sHosterBlock:
            isMatch, aNativeRaw = cParser.parse(sHosterBlock, r'data-link="([^"]+)"')
            if not isMatch:
                aNativeRaw = []
        hosters = buildMergedHosters(aNativeRaw, sMcUrl, referer=URL_MAIN)
        if hosters:
            hosters.append('getHosterUrl')
        return hosters

    # Movie-Pfad: Hoster direkt von der Movie-Page.
    sHtmlContent = cRequestHandler(params.getValue('entryUrl'), caching=False).request()
    isMatch, aResult = cParser.parse(sHtmlContent, 'link="([^"]+)')
    if isMatch:
        sQuality = '720'
        aResult = expandHosterList(aResult, referer=URL_MAIN)
        for sUrl in aResult:
            hoster = buildHosterFromUrl(sUrl, sQuality=sQuality, includeQualitySuffix=True)
            if hoster:
                hosters.append(hoster)
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def getHosterUrl(sUrl=False):
    return [{'streamUrl': sUrl, 'resolved': False}]


def showSearch():
    win = xbmcgui.Window(10000)
    sSearchText = win.getProperty('xstream.hdfilme.lastSearchText')
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30281))
        if not sSearchText: return
        win.setProperty('xstream.hdfilme.lastSearchText', sSearchText)
    # Das Verzeichnis schliesst showEntries selbst ab — so wie bei jeder
    # Weiter-Seite der Suche, die Kodi direkt dort aufruft.
    _search(False, sSearchText)


def _search(oGui, sSearchText):
    showEntries(False, oGui, sSearchText)
