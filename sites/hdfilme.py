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

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'hd-filme.blog')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)

URL_MAIN = 'https://' + DOMAIN + '/'
URL_NEW = URL_MAIN + 'kinofilme-online/'
URL_KINO = URL_MAIN + 'aktuelle-kinofilme-im-kino/'
URL_SERIES = URL_MAIN + 'serienstream-deutsch/'
URL_SEARCH = URL_MAIN + 'index.php?do=search&subaction=search&story=%s'

def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.hdfilme.lastSearchText')
    params = ParameterHandler()
    params.setParam('sUrl', URL_KINO)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30501), SITE_IDENTIFIER, 'showEntries'), params)  # Aktuelle Releases
    # Aufbau wie kkiste (gleiche Seitenfamilie), seit 2026.09.10: die Startseite ist die
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
    # Seiten-Update: Dropdown heißt jetzt "KATEGORIE", title="Genre"
    pattern = r'title="Genre">KATEGORIE.*?</ul>'
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


def _fetchSearchPage(entryUrl, iPage, pattern, bFrisch=False):
    """Eine Folgeseite der Suche holen.

    Rueckgabe ist (Rohtreffer, bErreicht). bErreicht=False heisst, der Abruf
    selbst ist gescheitert — Timeout, Sperre, 404 oder leere Antwort. Das darf
    NICHT als Ende der Ergebnisse gelten: request() liefert im Fehlerfall einen
    Klartext aus REQUEST_ERRORS, darin findet das Muster nichts, und eine leere
    Trefferliste sieht dann exakt wie die letzte Seite aus. Ein einzelner
    Aussetzer wuerde so die halbe Trefferliste abschneiden (nachgestellt:
    Fehler auf Seite 4 -> 24 statt 108 Rohtreffer).
    """
    sSep = '&' if '?' in entryUrl else '?'
    # Fehler ab Seite 2 werden nicht gemeldet: die Seite blaettert weiter, als sie
    # Ergebnisse hat, und ein 404 dort ist kein Fall fuer ein Fenster.
    # bFrisch=True zwingt am HTML-Cache vorbei: Nachhol- und Bestaetigungs-
    # abrufe muessen den SERVER fragen — der Cache liefert sonst exakt die
    # Antwort zurueck, die gerade geheilt oder bestaetigt werden soll
    # (Drosselseiten mit Status 200 werden wie normale Antworten gecacht).
    # cookies=not bFrisch: die Gruppenabrufe laufen OHNE Sitzungs-Cookie. Die
    # Seite sperrt die PHP-Sitzung je Anfrage, parallele Abrufe mit demselben
    # Cookie wurden serverseitig nacheinander abgearbeitet (vier Seiten 4,1 s
    # mit, 1,6 s ohne Cookie; "star wars" 12,8 s -> gemessen 02.09.2026).
    # Nachhol- und Bestaetigungsabrufe gehen einzeln und wieder MIT Cookie —
    # zugleich der Rueckfallweg, falls eine Sperre ohne Cookie greifen sollte.
    oRequest = cRequestHandler('%s%ssearch_start=%d' % (entryUrl, sSep, iPage), ignoreErrors=True, caching=not bFrisch, cookies=bFrisch)
    sHtmlContent = oRequest.request()
    if not sHtmlContent or sHtmlContent in REQUEST_ERRORS:
        return [], False
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    return (aResult if isMatch else []), True


# Pause vor jedem Nachholversuch: gibt einem Rate-Limit (429) Luft. Kuerzer
# heilt seltener, laenger kostet nur im Fehlerfall — im Normalfall laeuft
# keine einzige Pause.
RETRY_PAUSE = 0.6


def _fetchMoreSearchPages(entryUrl, pattern, iMaxPages=10, iBatch=4):
    """Folgeseiten einer Suche einsammeln — die Seite blaettert ueber `search_start`.

    Ohne das endete jede Suche nach Seite 1, und weil die Seite ihre Treffer
    NICHT nach Relevanz sortiert, standen die Titeltreffer oft gar nicht dort:
    gemessen lieferte "koenig" 0 von 7 und "herr" 0 von 7 Treffern.

    Abbruch ist eine Seite ohne Treffer. Der Vorwaerts-Link der Seite taugt
    dafuer NICHT — er verschwindet ab Seite 5, obwohl es weitergeht. Deshalb
    ist iMaxPages Pflicht und keine Vorsichtsmassnahme: manche Begriffe
    liefern praktisch endlos weiter (bis Seite 100 nachgemessen).

    Geholt wird in Gruppen parallel, weil die Seiten sonst nacheinander auf
    der Leitung liegen. Preis sind bis zu drei ueberzaehlige Abrufe je Suche,
    da die Seite ihre Gesamtseitenzahl nicht verraet — gleiches Muster wie
    _fetchAllSearchPages bei filmpalast.
    Fehlertoleranz in zwei Stufen (Anlass: unter der Parallellast fielen je
    Lauf zufaellig ganze Seiten aus und die Trefferzahl wuerfelte — still,
    ohne jede Meldung; gemessen 31.08. an streamcloud):
    - Ein GESCHEITERTER Abruf (Timeout, Sperre, 404) wird nach den Gruppen
      einmal sequenziell mit kurzer Pause nachgeholt statt still verworfen.
    - Eine ERREICHTE Seite ohne Treffer gilt erst als Listenende, wenn ein
      zweiter Abruf das bestaetigt — ein 200er mit leerem Body saehe sonst
      exakt wie das Ende aus. Kostet am echten Ende einen Zusatzabruf.
    Die Treffer werden je Seite gesammelt und in Seitenreihenfolge
    zurueckgegeben, damit Nachgeholtes an der richtigen Stelle landet.
    """
    dPages = {}
    aRetry = []
    iEnde = None
    iPage = 2
    while iPage <= iMaxPages:
        aBatch = list(range(iPage, min(iPage + iBatch, iMaxPages + 1)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(aBatch)) as oPool:
            aPages = list(oPool.map(lambda p: _fetchSearchPage(entryUrl, p, pattern), aBatch))
        for iNum, (aRows, bErreicht) in zip(aBatch, aPages):
            if not bErreicht:
                aRetry.append(iNum)
            elif aRows:
                dPages[iNum] = aRows
            else:
                # Ende-Kandidat: einmal bestaetigen, bevor abgebrochen wird.
                time.sleep(RETRY_PAUSE)
                aRows2, bErreicht2 = _fetchSearchPage(entryUrl, iNum, pattern, bFrisch=True)
                if bErreicht2 and not aRows2:
                    iEnde = iNum
                    break
                if aRows2:
                    # Hickser: beim zweiten Abruf war die Seite doch gefuellt.
                    logger.info('searchRetry %s: Seite %d nachgeholt, %d Treffer' % (SITE_NAME, iNum, len(aRows2)))
                    dPages[iNum] = aRows2
                else:
                    # Erst leer-erreicht, dann gescheitert: unklar, Seite fehlt.
                    logger.info('searchRetry %s: Seite %d nicht bestaetigt, Treffer dieser Seite fehlen' % (SITE_NAME, iNum))
        if iEnde is not None:
            break
        iPage += iBatch
    # Nachholrunde: gescheiterte Seiten einmal sequenziell holen. Seiten hinter
    # einem bestaetigten Ende liegen jenseits der Ergebnisse und bleiben weg.
    if iEnde is not None:
        aRetry = [p for p in aRetry if p < iEnde]
    for iNum in aRetry:
        time.sleep(RETRY_PAUSE)
        aRows, bErreicht = _fetchSearchPage(entryUrl, iNum, pattern, bFrisch=True)
        if aRows:
            logger.info('searchRetry %s: Seite %d nachgeholt, %d Treffer' % (SITE_NAME, iNum, len(aRows)))
            dPages[iNum] = aRows
        else:
            logger.info('searchRetry %s: Seite %d weiterhin nicht erreichbar, Treffer dieser Seite fehlen' % (SITE_NAME, iNum))
    aAll = []
    for iNum in sorted(dPages):
        aAll.extend(dPages[iNum])
    return aAll

def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    isTvshow = False
    if not entryUrl: entryUrl = params.getValue('sUrl')
    # Adressen mit Leerzeichen oder Umlaut kommen aus dem Parameter-Durchlauf
    # unkodiert zurueck -> direkt vor dem Request kodieren (deckt auch die
    # Naechste-Seite-URL ab). Pfadstruktur bleibt erhalten.
    entryUrl = cParser.urlEncode(entryUrl, safe="/:?=&%#")
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()
    pattern = '<div class="box-product(.*?)<h3.*?href="([^"]+).*?">([^<]+).*?(.*?)</li>'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if isMatch and sSearchText:
        # In der globalen Suche laufen alle Sites gleichzeitig, deshalb dort nur
        # fuenf Seiten je Site. Mit zehn dauerte eine breite Suche ueber Mobilfunk
        # 19 s ("koenig", 412 Treffer) — der Einzelaufruf der Site bleibt bei zehn,
        # dort laeuft nur eine Seite zur Zeit.
        aResult += _fetchMoreSearchPages(entryUrl, pattern, iMaxPages=5 if sGui else 10)
    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    total = len(aResult)
    iShown = 0
    # Keine Sprachlogik mehr (seit 2026.09.10): die Seite ist deutsch, englische
    # Fassungen tragen den Zusatz „English*" im Titel und sind so erkennbar —
    # ein Filter danach blendete je Einstellung Eintraege aus, ohne dass die
    # Seite je Hoster eine Sprache nennt (Regel: Sprachlogik nur, wo das Label
    # der Seite sie hergibt, wie bei serienstream, aniworld, burningseries, filmo).
    for sInfo, sUrl, sName, sDummy in aResult:
        if sSearchText and not cParser.searchTitle(sSearchText, sName):
            continue
        isThumbnail, sThumbnail = cParser.parseSingleResult(sInfo, 'data-src="([^"]+)')
        isYear, sYear = cParser.parseSingleResult(sDummy, r'([\d]+)\s</p>')
        isQuality, sQuality = cParser.parseSingleResult(sDummy, 'quality-product">([^<]+)')
        isTvshow = True if 'taffel' in sName else False
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons' if isTvshow else 'showHosters')
        oGuiElement.setMediaType('tvshow' if isTvshow else 'movie')
        if isThumbnail:
            sThumbnail = URL_MAIN + sThumbnail
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
    # Kamen Treffer an, wurden aber ALLE vom Titelfilter verworfen, stand
    # hier bisher ein leeres Verzeichnis ohne Hinweis (belegt mit "2019").
    # BEWUSST VOR dem Pagination-Block: dessen Bedingung schliesst die Suche
    # aus, die Meldung wuerde dort nie erreicht.
    if not sGui and not iShown:
        oGui.showInfo()

    if not sGui and not sSearchText:
        isMatchNextPage, sNextUrl = cParser.parseSingleResult(sHtmlContent, 'href="([^"]+)">›</a></div>')
        # Seitenlage fuer den Weiter-Eintrag: die hoechste Zahl der Blaetterleiste ist
        # das Listenende — bei langen Listen steht sie hinter der "…"-Auslassung, bei
        # kurzen sind ohnehin alle Zahlen da (gemessen 04.09.2026 gegen die bisektierten
        # Enden, kurz wie lang). Die aktive Seite steht als <span> in derselben Leiste.
        sPageInfo = ''
        isMatchSiteSearch, sHtmlContainer = cParser.parseSingleResult(sHtmlContent, 'class="pagination(.*?)</div></div>')
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
        if mcEp:
            sLabel = 'S%sE%s — %s' % (str(sStaffel).zfill(2), str(iEp).zfill(2), mcEp['title'])
        elif sTxt:
            sLabel = sTxt
        else:
            sLabel = 'S%sE%s' % (str(sStaffel).zfill(2), str(iEp).zfill(2))
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
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def _search(oGui, sSearchText):
    showEntries(URL_SEARCH % cParser.quotePlus(sSearchText), oGui, sSearchText)
