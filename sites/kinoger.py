# -*- coding: utf-8 -*-
# Python 3
# Always pay attention to the translations in the menu!
# HTML LangzeitCache hinzugefügt
# showGenre:     48 Stunden
# showEntries:    6 Stunden
# showSeasons:    6 Stunden
# showEpisodes:   4 Stunden
#
# WAF: vor der Seite haengt seit 09/2026 der Fremd-WAF HostAdmin.online. Er
# beantwortet jeden Abruf ohne Freigabe mit einer Pruefseite (Status 200,
# Proof-of-Work). Alle Abrufe laufen deshalb ueber _requestGated(): Pruefseite
# erkennen, lokal rechnen (captcha/local_solver.py), einreichen, einmal neu
# holen. Die Freigabe haengt an zwei Cookies UND am User-Agent UND an der IP —
# daher der feste Sitzungs-UA (_sessionUA) und das Sichern der Cookies von Hand.

import concurrent.futures
import json
import re
import time
import xbmcgui

from http.cookiejar import LWPCookieJar
from urllib.request import Request

from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler, REQUEST_ERRORS
from resources.lib.logger import logger
from resources.lib.tools import cParser
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui
from resources.lib.captcha.local_solver import is_hostadmin_gate, solve_hostadmin, HOSTADMIN_VERIFY_PATH


SITE_IDENTIFIER = 'kinoger'
SITE_NAME = 'KinoGer'
SITE_ICON = 'kinoger.png'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'kinoger.com')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)

URL_MAIN = 'https://' + DOMAIN
URL_SERIES = URL_MAIN + '/stream/serie/'

# --- Hoster ---------------------------------------------------------------
# kinoger versteckt seine Hoster hinter eigenen Domains. Der Name des
# JavaScript-Blocks (pw./fsst./go./ollhd.) sagt NICHTS ueber den Hoster aus —
# auf derselben Seite lag schon fsst.online in pw.show() und kinoger.pw in
# fsst.show(). Der Hoster wird daher ausschliesslich an der URL erkannt.
# Es gibt keine Eigenaufloesung mehr, jede Domain laeuft ueber ResolveURL:
# kinoger.pw -> Streamix, kinoger.be -> FileLions, kinoger.ru -> VOE,
# kinoger.embed4me.vip/kinoger.seekplays.pro/kinoger.re -> KinoGer.
# Ohne passendes Plugin faellt die Domain ueber isBlockedHoster raus.

# kinoger.be ist domain-locked: ohne passenden Referer liefert der Embed nur
# "Video embed restricted for this domain", der Resolver findet dann keine Quelle.
# ResolveURL nimmt den Referer ueber die $$-Konvention entgegen (wie in filmpalast.py),
# der FileLions-Resolver wertet sie aus. Akzeptiert wird jede kinoger-Hauptdomain
# (.to und .com live geprueft), deshalb URL_MAIN statt fester Adresse — so folgt der
# Referer automatisch der Domain-Einstellung des Plugins.
HOST_REFERER_REQUIRED = ('kinoger.be',)


# --- WAF (HostAdmin.online) ------------------------------------------------
# Gemessen 19.09.2026: frei ist die Seite nur mit BEIDEN Cookies
# (ha-waf-ticket-secure von der Pruefseite, ha-waf-hash-secure aus der Antwort
# auf die Einreichung), mit demselben User-Agent wie beim Loesen und von
# derselben IP. Eine Freigabe gilt fuer alle Pfade, die Cookies nennen 30
# Minuten. Wie lange sie wirklich traegt, haengt vom Besucher ab (gemessen
# 21.09.2026): am Testgeraet trug EINE Loesung die ganze Sitzung (14 Minuten,
# Pausen bis 156 s), aus einem Rechenzentrum verfiel sie nach rund 15 s ohne
# Abruf und wurde beim naechsten Klick neu geloest. Das dritte Cookie
# ha-waf-hist (seit 21.09.2026, ein Verlaufs-Cookie) braucht die Freigabe nicht.
WAF_UA_PROPERTY = 'xstream.kinoger.sessionUA'


def _sessionUA():
    """Ein User-Agent fuer die ganze Kodi-Sitzung.

    Der requestHandler wuerfelt je Abruf neu, und jeder Klick ist ein eigener
    Aufruf des Addons — die Freigabe des WAF gaelte damit nur bis zum naechsten
    Klick. Deshalb liegt der einmal gewaehlte UA als Window-Property vor (wie
    lastSearchText). Nach einem Kodi-Neustart oder dem Leeren des Caches wird
    neu gewaehlt; passt die alte Freigabe dann nicht mehr, kommt die Pruefseite
    und wird neu geloest.
    """
    win = xbmcgui.Window(10000)
    sUA = win.getProperty(WAF_UA_PROPERTY)
    if not sUA:
        sUA = cRequestHandler.RandomUA()
        win.setProperty(WAF_UA_PROPERTY, sUA)
    return sUA


class _HeaderResponse:
    """Minimal-Antwort fuer LWPCookieJar.make_cookies(): kennt nur info()."""

    def __init__(self, oHeaders):
        self._oHeaders = oHeaders

    def info(self):
        return self._oHeaders


def _saveResponseCookies(oRequest, sUrl):
    """Set-Cookie-Zeilen der letzten Antwort von Hand in die Cookie-Datei schreiben.

    Noetig, weil der requestHandler je Domain EINEN Opener wiederverwendet und
    dessen Cookie-Speicher der des ERSTEN Abrufs bleibt: Cookies spaeterer
    Antworten landen nur dort im Arbeitsspeicher, nicht in der Datei — und der
    naechste Abruf liest seine Cookies aus der Datei. Gemessen 19.09.2026: das
    hash-Cookie der Einreichung kam beim Folgeabruf nie an, die Pruefseite kam
    wieder. Das Parsen macht die Standardbibliothek (Max-Age, Domain, Secure).
    """
    oHeaders = oRequest.getResponseHeader()
    if not hasattr(oHeaders, 'get_all'):
        return
    try:
        for oCookie in LWPCookieJar().make_cookies(_HeaderResponse(oHeaders), Request(sUrl)):
            oRequest.setCookie(oCookie)
    except Exception as e:
        logger.error('%s: Cookies der Antwort nicht gesichert: %s' % (SITE_NAME, e))


def _passWaf(sGateHtml):
    """Pruefseite loesen und einreichen -> True, wenn der WAF die Loesung annimmt."""
    aBody = solve_hostadmin(sGateHtml)
    if not aBody:
        return False
    sVerifyUrl = URL_MAIN + HOSTADMIN_VERIFY_PATH
    # data als str = roher JSON-Rumpf; ohne eigenen Content-Type setzt der
    # Handler form-urlencoded. KOMPAKT serialisieren (keine Leerzeichen): der
    # WAF haelt den Datensatz `data` bytegleich gegen seinen Hash, mit den
    # Standard-Trennzeichen von json.dumps lehnt er ab (403, gemessen
    # 24.09.2026). ignoreErrors: eine Ablehnung (403) bekommt kein Fenster,
    # der Aufrufer meldet ueber die leere Liste.
    oVerify = cRequestHandler(sVerifyUrl, caching=False, ignoreErrors=True, method='POST',
                              data=json.dumps(aBody, separators=(',', ':')))
    oVerify.addHeaderEntry('User-Agent', _sessionUA())
    oVerify.addHeaderEntry('Content-Type', 'application/json')
    oVerify.addHeaderEntry('Accept', '*/*')
    oVerify.addHeaderEntry('Origin', URL_MAIN)
    oVerify.addHeaderEntry('Referer', URL_MAIN + '/')
    oVerify.request()
    # Nur der Statuscode zaehlt: die Antwort ist bei Erfolg leer, und ein
    # Fehler-Klartext des Handlers darf nie als Erfolg durchgehen.
    if str(oVerify.getStatus()) != '200':
        logger.error('%s: WAF hat die Loesung nicht angenommen (Status %s)' % (SITE_NAME, oVerify.getStatus()))
        return False
    _saveResponseCookies(oVerify, sVerifyUrl)
    return True


def _requestGated(oRequest, bSolve=True):
    """request() mit WAF-Behandlung. EIN Anlauf je Aufruf, keine Schleife.

    Ablauf bei einer Pruefseite: Cache-Eintrag verwerfen (sie kommt mit Status
    200 und wurde wie Inhalt gecacht), loesen, einreichen, EINMAL neu holen —
    drei Netzabrufe, mehr nicht: die Gegenseite kippt unter Last in
    Zeitueberschreitungen. Scheitert etwas, kommt '' zurueck und der Aufrufer
    zeigt seine normale Leer-Meldung; der naechste Klick ist der naechste Versuch.
    bSolve=False fuer parallele Abrufe (Such-Folgeseiten): dort wird nicht
    geloest, eine Pruefseite zaehlt als nicht erreicht.
    """
    oRequest.addHeaderEntry('User-Agent', _sessionUA())
    sHtmlContent = oRequest.request()
    if not sHtmlContent or sHtmlContent in REQUEST_ERRORS or not is_hostadmin_gate(sHtmlContent):
        return sHtmlContent
    oRequest.dropCacheEntry()
    if not bSolve:
        return ''
    logger.info('%s: WAF-Pruefseite erkannt, loese lokal' % SITE_NAME)
    _saveResponseCookies(oRequest, URL_MAIN + '/')
    if not _passWaf(sHtmlContent):
        return ''
    sHtmlContent = oRequest.request()
    if not sHtmlContent or sHtmlContent in REQUEST_ERRORS:
        return sHtmlContent
    if is_hostadmin_gate(sHtmlContent):
        oRequest.dropCacheEntry()
        logger.error('%s: WAF zeigt nach der Freigabe wieder die Pruefseite' % SITE_NAME)
        return ''
    logger.info('%s: WAF-Pruefung bestanden' % SITE_NAME)
    return sHtmlContent


def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.kinoger.lastSearchText')
    params = ParameterHandler()
    params.setParam('sUrl', URL_MAIN + '/')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30500), SITE_IDENTIFIER, 'showEntries'), params)  # Neu auf der Seite
    params.setParam('sUrl', URL_SERIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30511), SITE_IDENTIFIER, 'showEntries'), params)  # Serien
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30506), SITE_IDENTIFIER, 'showGenre'))  # Genre
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'))  # Suche
    cGui().setEndOfDirectory()


def showGenre():
    params = ParameterHandler()
    oRequest = cRequestHandler(URL_MAIN)
    if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'true':
        oRequest.cacheTime = 60 * 60 * 48  # 48 Stunden
    sHtmlContent = _requestGated(oRequest)
    # Markup: <li class="links"><a href="/main/action/"><img ... /> Action</a></li>
    # Der erste Eintrag ("Alle Filme") nutzt zusaetzlich <b>...</b> — daher beide Formen.
    # WICHTIG: kein .*?/>-Pattern verwenden. Der requestHandler entfernt Zeilenumbrueche,
    # dadurch laeuft ein solches Pattern in das naechste <li> und paart die URL von
    # Eintrag N mit dem Namen von Eintrag N+1 (jeder Genre-Link zeigt dann falsch).
    pattern = r'<li class="links"><a href="([^"]+)"><img[^>]*/>\s*(?:<b>)?([^<]+?)(?:</b>)?</a>'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        cGui().showInfo()
        return

    # Die Sidebar der Seite IST das Menue: "Alle Filme" (= Startseite) + 32 Genres.
    # Raus fliegen: "Alle Filme" (steht schon als "Neu auf der Seite" im Hauptmenue),
    # "Serie" (/main/serie/ liefert identisch dasselbe wie URL_SERIES, eigener Punkt)
    # und "Erwachsene" (Erotik — wie bei den anderen Sites in xStream ausgeblendet).
    skip = ('/main/serie/', '/main/erwachsene/')
    for sUrl, sName in aResult:
        if not sUrl.startswith('/main/') or sUrl in skip:
            continue
        params.setParam('sUrl', URL_MAIN + sUrl)
        cGui().addFolder(cGuiElement(sName.strip(), SITE_IDENTIFIER, 'showEntries'), params)
    cGui().setEndOfDirectory()


def _fetchSearchPage(entryUrl, sSearchText, iPage, pattern, bFrisch=False):
    """Eine Folgeseite der Suche holen -> (Rohtreffer, bErreicht)."""
    # bFrisch=True zwingt am HTML-Cache vorbei: Nachhol- und Bestaetigungs-
    # abrufe muessen den SERVER fragen — der Cache liefert sonst exakt die
    # Antwort zurueck, die gerade geheilt oder bestaetigt werden soll
    # (Drosselseiten mit Status 200 werden wie normale Antworten gecacht).
    oRequest = cRequestHandler(entryUrl, ignoreErrors=True, caching=not bFrisch)
    oRequest.addParameters('do', 'search')
    oRequest.addParameters('subaction', 'search')
    oRequest.addParameters('story', sSearchText)
    oRequest.addParameters('titleonly', '3')
    oRequest.addParameters('submit', 'submit')
    # Die Blaetterung der Seite steckt in ihrem eigenen list_submit-JS:
    # search_start ist die Seitennummer, result_from der Versatz in 20er-Schritten.
    oRequest.addParameters('search_start', str(iPage))
    oRequest.addParameters('result_from', str((iPage - 1) * 20 + 1))
    # bSolve=False: laeuft parallel — geloest wird nur im Hauptabruf (Seite 1).
    sHtmlContent = _requestGated(oRequest, bSolve=False)
    # Ein gescheiterter Abruf (Timeout, Sperre, 404) liefert einen Klartext aus
    # REQUEST_ERRORS. Ohne diese Unterscheidung saehe er wie die letzte Seite
    # aus und wuerde die Sammlung vorzeitig beenden.
    if not sHtmlContent or sHtmlContent in REQUEST_ERRORS:
        return [], False
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    return (aResult if isMatch else []), True


# Pause vor jedem Nachholversuch: gibt einem Rate-Limit (429) Luft. Kuerzer
# heilt seltener, laenger kostet nur im Fehlerfall — im Normalfall laeuft
# keine einzige Pause.
RETRY_PAUSE = 0.6


def _fetchMoreSearchPages(entryUrl, sSearchText, pattern, iMaxPages=10, iBatch=4):
    """Folgeseiten der Suche einsammeln.

    Ohne das endete die Suche nach Seite 1: gemessen "star wars" 12 statt 31,
    "koenig" 12 statt ueber 48. Abbruch ist eine Seite ohne Treffer — bei
    "walking dead" ist schon Seite 2 leer, dort entstehen also keine
    ueberzaehligen Abrufe. Geholt wird in Gruppen parallel, weil die Seiten
    sonst nacheinander auf der Leitung liegen.
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
            aPages = list(oPool.map(lambda p: _fetchSearchPage(entryUrl, sSearchText, p, pattern), aBatch))
        for iNum, (aRows, bErreicht) in zip(aBatch, aPages):
            if not bErreicht:
                aRetry.append(iNum)
            elif aRows:
                dPages[iNum] = aRows
            else:
                # Ende-Kandidat: einmal bestaetigen, bevor abgebrochen wird.
                time.sleep(RETRY_PAUSE)
                aRows2, bErreicht2 = _fetchSearchPage(entryUrl, sSearchText, iNum, pattern, bFrisch=True)
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
        aRows, bErreicht = _fetchSearchPage(entryUrl, sSearchText, iNum, pattern, bFrisch=True)
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
    if not entryUrl:
        entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'true':
        oRequest.cacheTime = 60 * 60 * 6  # 6 Stunden
    if sSearchText:
        oRequest.addParameters('do', 'search')
        oRequest.addParameters('subaction', 'search')
        oRequest.addParameters('story', sSearchText)
        oRequest.addParameters('titleonly', '3')
        oRequest.addParameters('submit', 'submit')
    sHtmlContent = _requestGated(oRequest)
    pattern = 'class="title".*?href="([^"]+)">([^<]+).*?src="([^"]+)(.*?)</a> </span>'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if isMatch and sSearchText:
        # In der globalen Suche laufen alle Sites gleichzeitig, deshalb dort nur
        # fuenf Seiten je Site. Mit zehn dauerte eine breite Suche ueber Mobilfunk
        # 19 s ("koenig", 412 Treffer) — der Einzelaufruf der Site bleibt bei zehn,
        # dort laeuft nur eine Seite zur Zeit.
        aResult += _fetchMoreSearchPages(entryUrl, sSearchText, pattern, iMaxPages=5 if sGui else 10)
    if not isMatch:
        if not sGui:
            oGui.showInfo()
        return

    total = len(aResult)
    iShown = 0
    isTvshow = False
    for sUrl, sName, sThumbnail, sDummy in aResult:
        if sSearchText and not cParser.searchTitle(sSearchText, sName):
            continue
        # Serie erkennen: Staffel im Titel, Serien-Kategorie oder der Staffel-Marker
        # (<div style="text-align:right;">S01-03E...) im Eintrag.
        # Serien-Marker der Site steht rechts oben im Eintrag ("S01-03E01-06"). Die Site
        # setzt das <b> mal VOR, mal HINTER das <div> — beide Formen muessen greifen,
        # sonst gelten die meisten Serien als Film (getestet: 5/12 vs 12/12).
        isTvshow = bool(re.search(r'text-align:right;">(?:<b>)?S\d', sDummy)) \
            or 'staffel' in sName.lower() or '/serie/' in entryUrl
        sName = sName.strip()
        # Jahr aus dem Namen trennen: "The Odyssey (2026)"
        sYear = ''
        isYear, aYear = cParser.parse(sName, r'(.*?)\s+\((\d{4})\)')
        if isYear and aYear:
            sName, sYear = aYear[0]
            sName = sName.strip()
        if sThumbnail.startswith('/'):
            sThumbnail = URL_MAIN + sThumbnail
        isDesc, sDesc = cParser.parseSingleResult(sDummy, '(?:</b></div>|</div></b>|</b>)([^<]+)')
        isDuration, sDuration = cParser.parseSingleResult(sDummy, r'(?:Laufzeit|Spielzeit).*?([\d]+)')

        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons' if isTvshow else 'showHosters')
        oGuiElement.setMediaType('tvshow' if isTvshow else 'movie')
        oGuiElement.setThumbnail(sThumbnail)
        if sYear:
            oGuiElement.setYear(sYear)
        if isDesc:
            oGuiElement.setDescription(sDesc.strip())
        if isDuration:
            oGuiElement.addItemValue('duration', sDuration)
        params.setParam('entryUrl', sUrl)
        params.setParam('sThumbnail', sThumbnail)
        params.setParam('searchTitle', sName)
        oGui.addFolder(oGuiElement, params, isTvshow, total)
        iShown += 1
    # Kamen Treffer an, wurden aber ALLE vom Titelfilter verworfen, stand hier
    # ein leeres Verzeichnis ohne Hinweis (belegt mit "koenig", Audit 01.09.2026).
    # BEWUSST VOR dem Pagination-Block: dessen Bedingung schliesst die Suche aus,
    # die Meldung wuerde dort nie erreicht. Gleiches Muster wie in hdfilme.
    if not sGui and not iShown:
        oGui.showInfo()

    if not sGui and not sSearchText:
        # Seitenlage fuer den Weiter-Eintrag: die hoechste Zahl der Blaetterleiste ist
        # das Listenende — bei langen Listen steht sie hinter der "…"-Auslassung, bei
        # kurzen sind ohnehin alle Zahlen da (gemessen 04.09.2026 gegen die bisektierten
        # Enden, kurz wie lang). Die aktive Seite steht als <span> in derselben Leiste.
        sPageInfo = ''
        isMatchNav, sNav = cParser.parseSingleResult(sHtmlContent, r'class=\"navigation\"[^>]*>(.*?)</div>')
        if isMatchNav:
            isMatchCur, sCurrent = cParser.parseSingleResult(sNav, r'<span[^>]*>(\d+)</span>')
            aPages = [int(x) for x in re.findall(r'>(\d{1,6})<', sNav)]
            if isMatchCur and aPages:
                sPageInfo = cGui.pageInfo(sCurrent, max(aPages))
        isMatchNextPage, sNextUrl = cParser.parseSingleResult(sHtmlContent, r'<a[^>]href="([^"]+)">vorw')
        if isMatchNextPage:
            params.setParam('sUrl', sNextUrl)
            oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', params, sPageInfo)
    if not sGui:
        oGui.setView('tvshows' if isTvshow else 'movies')
        oGui.setEndOfDirectory()


def _parseProviderMatrix(sHtmlContent):
    """Alle Player-Bloecke der Seite als Matrix {jsName: [[Staffel1-URLs], [Staffel2-URLs], ...]}.

    Seiten-Markup: <script>pw.init(); pw.show(3,[['S1E1','S1E2'],['S2E1'],['S3E1']])</script>
    Bei Filmen ist es derselbe Aufbau mit genau einer "Staffel" und einer "Episode".
    Die inneren Listen enthalten teils Platzhalter statt Links (z.B. 'ссылка') — es
    werden nur echte http-URLs uebernommen, sonst stimmt die Episodenzaehlung nicht.
    """
    matrix = {}
    for sProvider, sData in re.findall(r"(\w+)\.show\(\s*\d+\s*,\s*(\[\[.*?\]\])\s*[,)]", sHtmlContent):
        aSeasons = []
        for sSeason in re.findall(r'\[([^\[\]]*)\]', sData):
            aEpisodes = [u.strip() for u in re.findall(r"'([^']*)'", sSeason) if u.strip().startswith('http')]
            aSeasons.append(aEpisodes)
        if aSeasons:
            matrix[sProvider] = aSeasons
    return matrix


def _episodeUrls(matrix, iSeasonIdx, iEpisodeIdx):
    """Alle Hoster-URLs einer Episode ueber alle Player-Bloecke hinweg."""
    aUrls = []
    for aSeasons in matrix.values():
        if iSeasonIdx < len(aSeasons) and iEpisodeIdx < len(aSeasons[iSeasonIdx]):
            aUrls.append(aSeasons[iSeasonIdx][iEpisodeIdx])
    return aUrls


def showSeasons():
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    sThumbnail = params.getValue('sThumbnail') if params.exist('sThumbnail') else ''
    sName = params.getValue('searchTitle')
    oRequest = cRequestHandler(sUrl)
    if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'true':
        oRequest.cacheTime = 60 * 60 * 6  # 6 Stunden
    sHtmlContent = _requestGated(oRequest)
    matrix = _parseProviderMatrix(sHtmlContent)
    if not matrix:
        cGui().showInfo()
        return

    # Staffelzahl = Maximum ueber alle Bloecke. Die Bloecke sind NICHT gleich lang:
    # live hatte ein Block 0 Episoden in Staffel 2, ein anderer 8.
    total = max(len(aSeasons) for aSeasons in matrix.values())
    if total == 1:  # nur eine Staffel -> Ordner-Ebene sparen, HTML weiterreichen
        showEpisodes(staffel='1', htmlContent=sHtmlContent)
        return

    for iSeason in range(1, total + 1):
        oGuiElement = cGuiElement(cConfig().getLocalizedString(30512) + ' %d' % iSeason, SITE_IDENTIFIER, 'showEpisodes')
        oGuiElement.setMediaType('season')
        oGuiElement.setTVShowTitle(sName)
        oGuiElement.setSeason(iSeason)
        if sThumbnail:
            oGuiElement.setThumbnail(sThumbnail)
        params.setParam('staffel', str(iSeason))
        cGui().addFolder(oGuiElement, params, True, total)
    cGui().setView('seasons')
    cGui().setEndOfDirectory()


def showEpisodes(staffel=None, htmlContent=None):
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    sName = params.getValue('searchTitle')
    sThumbnail = params.getValue('sThumbnail') if params.exist('sThumbnail') else ''
    # staffel/htmlContent kommen von showSeasons (Single-Staffel-Skip), sonst aus den Parametern.
    sStaffel = staffel if staffel is not None else params.getValue('staffel')
    if htmlContent is not None:
        sHtmlContent = htmlContent
    else:
        oRequest = cRequestHandler(sUrl)
        if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'true':
            oRequest.cacheTime = 60 * 60 * 4  # 4 Stunden
        sHtmlContent = _requestGated(oRequest)
    matrix = _parseProviderMatrix(sHtmlContent)
    if not matrix:
        cGui().showInfo()
        return

    iSeasonIdx = int(sStaffel) - 1
    total = max((len(a[iSeasonIdx]) if iSeasonIdx < len(a) else 0) for a in matrix.values())
    if not total:
        cGui().showInfo()
        return

    for iEpisode in range(1, total + 1):
        aUrls = _episodeUrls(matrix, iSeasonIdx, iEpisode - 1)
        if not aUrls:
            continue
        sTitle = '%s - S%sE%s' % (sName, str(sStaffel).zfill(2), str(iEpisode).zfill(2))
        oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setMediaType('episode')
        oGuiElement.setTVShowTitle(sName)
        oGuiElement.setSeason(sStaffel)
        oGuiElement.setEpisode(iEpisode)
        if sThumbnail:
            oGuiElement.setThumbnail(sThumbnail)
        params.setParam('sLinks', '|'.join(aUrls))
        cGui().addFolder(oGuiElement, params, False, total)
    cGui().setView('episodes')
    cGui().setEndOfDirectory()


def _buildHosters(aUrls):
    """Hoster-Dicts aus den Player-URLs. Erkennung ausschliesslich ueber die Domain.

    Alle Domains gehen denselben Weg: hat ResolveURL einen Resolver, wird durchgereicht,
    sonst faellt der Eintrag ueber isBlockedHoster raus, damit nichts in der Liste steht,
    was nicht abspielt. kinoger.pw, kinoger.re, kinoger.be, kinoger.ru, firestream.to,
    voe.sx, veev.* und dsvplay.com sind damit abgedeckt, ohne sie hier einzeln zu pflegen.
    Eine Ausnahme betrifft kinoger.be: der Referer (HOST_REFERER_REQUIRED), oben begruendet.

    WICHTIG: fuer den Blocked-Check den VOLLEN Hostnamen nehmen, nicht wie sonst
    ueblich nur den ersten Namensteil. kinoger versteckt seine Hoster hinter
    eigenen Subdomains (kinoger.pw, kinoger.embed4me.vip, kinoger.seekplays.pro,
    kinoger.ru) — mit 'Kinoger' als Suchbegriff wuerden die alle faelschlich auf den
    kinoger.re-Resolver passen und als spielbar gelistet, obwohl sie es nicht sind.
    """
    hosters = []
    for sUrl in aUrls:
        sUrl = sUrl.strip()
        if not sUrl.startswith('http'):
            continue
        if 'youtube.com' in sUrl or 'youtu.be' in sUrl:
            continue  # Trailer im Player-Block — ResolveURL wuerde ihn als Hoster aufloesen
        sName = cParser.urlparse(sUrl)  # voller Hostname, siehe Docstring
        if cConfig().isBlockedHoster(sName)[0]:  # Hoster aus settings.xml oder ohne Resolver ausschliessen
            logger.info('kinoger: kein Resolver oder geblockt: %s' % sUrl)
            continue
        sLink = sUrl
        # sName kommt aus cParser.urlparse und ist Title-Case ('Kinoger.Be'), daher .lower()
        if sName.lower() in HOST_REFERER_REQUIRED:
            sLink = '%s$$%s/' % (sUrl, URL_MAIN)  # Referer fuer ResolveURL, siehe oben
        hosters.append({'link': sLink, 'name': sName, 'displayedName': '%s [I][720p][/I]' % sName,
                        'quality': '720'})
    return hosters


def showHosters():
    params = ParameterHandler()
    if params.exist('sLinks'):  # Serie: Episoden-URLs kommen aus showEpisodes
        aUrls = [u for u in params.getValue('sLinks').split('|') if u]
    else:  # Film: Player-Bloecke von der Filmseite holen
        sUrl = params.getValue('entryUrl')
        sHtmlContent = _requestGated(cRequestHandler(sUrl, caching=False))
        matrix = _parseProviderMatrix(sHtmlContent)
        aUrls = []
        for aSeasons in matrix.values():
            for aEpisodes in aSeasons:
                aUrls.extend(aEpisodes)
    hosters = _buildHosters(aUrls)
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def getHosterUrl(sUrl=False):
    return [{'streamUrl': sUrl, 'resolved': False}]


def showSearch():
    win = xbmcgui.Window(10000)
    sSearchText = win.getProperty('xstream.kinoger.lastSearchText')
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30281))
        if not sSearchText:
            return
        win.setProperty('xstream.kinoger.lastSearchText', sSearchText)
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def _search(oGui, sSearchText):
    showEntries(URL_MAIN + '/index.php?do=search', oGui, sSearchText)
