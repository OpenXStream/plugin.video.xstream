# -*- coding: utf-8 -*-
# Python 3
# Always pay attention to the translations in the menu!
# WAF: vor der Seite haengt seit 09/2026 der Fremd-WAF HostAdmin.online. Er
# beantwortet jeden Abruf ohne Freigabe mit einer Pruefseite (Status 200,
# Proof-of-Work). Alle Abrufe laufen deshalb ueber _requestGated(): Pruefseite
# erkennen, lokal rechnen (captcha/local/), einreichen, einmal neu
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
from resources.lib.captcha.local import is_hostadmin_background, is_hostadmin_gate, solve_hostadmin, HOSTADMIN_VERIFY_PATH


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
# Die Suche geht als Formular an die Startadresse, nicht an /index.php?do=search: seit dem 05.11.2026
# legt die Seite auf jede Adresse mit do=search in der Zeile eine Cloudflare-Pruefung (403 mit
# cf-mitigated, auf .com und .to gleich), die Kodi nicht loesen kann — mit do, subaction und story nur
# im Rumpf antwortet dieselbe Seite normal mit der Trefferliste (gemessen 05.11.2026, beide Domains,
# auch die Folgeseiten ueber search_start)
URL_SEARCH = URL_MAIN + '/'

# --- Hoster ---------------------------------------------------------------
# kinoger versteckt seine Hoster hinter eigenen Domains. Der Name des
# JavaScript-Blocks (pw./fsst./go./ollhd.) sagt NICHTS ueber den Hoster aus —
# auf derselben Seite lag schon die fsst-Domain im pw-Block und die pw-Domain
# im fsst-Block. Der Hoster wird daher ausschliesslich an der URL erkannt.
# Es gibt keine Eigenaufloesung mehr, jede Domain laeuft ueber ResolveURL
# (dahinter stehen Streamix, FileLions, VOE, Byse und KinoGer — welche Subdomain
# welchem Hoster gehoert, entscheidet ResolveURL an der Adresse).
# Ohne passendes Plugin faellt die Domain ueber isBlockedHoster raus.

# kinoger.be ist domain-locked: ohne passenden Referer liefert der Embed nur
# "Video embed restricted for this domain", der Resolver findet dann keine Quelle.
# kinoger.re (Byse) ist ebenso an die Einbettseite gebunden: ohne sie antwortet die
# Byse-API mit 403 "embedding from kinoger.re is not allowed for this video" (gemessen
# 19.10.2026, mit einer fremden Einbettseite ebenso).
# ResolveURL nimmt den Referer ueber die $$-Konvention entgegen (wie in filmpalast.py),
# der FileLions-Resolver wertet sie als Referer aus, der Byse-Resolver als Einbettseite
# (X-Embed-Origin/-Referer). Akzeptiert wird jede kinoger-Hauptdomain
# (.to und .com live geprueft), deshalb URL_MAIN statt fester Adresse — so folgt der
# Referer automatisch der Domain-Einstellung des Plugins.
HOST_REFERER_REQUIRED = ('kinoger.be', 'kinoger.re')


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

    Jeder Klick ist ein eigener Aufruf des Addons, und die Freigabe des WAF haengt
    am UA — sie darf nicht davon abhaengen, welchen UA der requestHandler beim
    naechsten Aufruf liefert. Deshalb liegt der einmal gewaehlte UA als
    Window-Property vor (wie lastSearchText). Nach einem Kodi-Neustart oder dem
    Leeren des Caches wird neu gewaehlt; passt die alte Freigabe dann nicht mehr,
    kommt die Pruefseite und wird neu geloest.
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

    Entstanden am 19.09.2026, als der requestHandler je Domain EINEN Opener
    wiederverwendete und dessen Cookie-Speicher der des ERSTEN Abrufs blieb:
    das hash-Cookie der Einreichung kam beim Folgeabruf nie an, die Pruefseite
    kam wieder. Seit dem 02.11.2026 legt der requestHandler die Cookies jeder
    Antwort selbst in die Dose der Domain und speichert sie (_cookieJar) — der
    Weg hier ist damit doppelt, aber unschaedlich (dieselben Cookies, dieselbe
    Dose); er bleibt, bis die WAF-Freigabe ohne ihn live belegt ist (am
    02.11.2026 noch nicht). Das Parsen macht die Standardbibliothek (Max-Age, Domain, Secure).
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


def _requestGated(oRequest):
    """request() mit WAF-Behandlung. EIN Anlauf je Aufruf, keine Schleife.

    Ablauf bei einer Pruefseite: Cache-Eintrag verwerfen (sie kommt mit Status
    200 und wurde wie Inhalt gecacht), loesen, einreichen, EINMAL neu holen —
    drei Netzabrufe, mehr nicht: die Gegenseite kippt unter Last in
    Zeitueberschreitungen. Scheitert etwas, kommt '' zurueck und der Aufrufer
    zeigt seine normale Leer-Meldung; der naechste Klick ist der naechste Versuch.
    Eine Inhaltsseite, auf der der WAF nur im Hintergrund mitlaeuft
    (is_hostadmin_background), ist keine Pruefseite und gilt als Inhalt.
    """
    oRequest.addHeaderEntry('User-Agent', _sessionUA())
    sHtmlContent = oRequest.request()
    if not sHtmlContent or sHtmlContent in REQUEST_ERRORS or not is_hostadmin_gate(sHtmlContent):
        if is_hostadmin_background(sHtmlContent):
            # Inhalt mit Hintergrund-Pruefung: die frischt im Browser nur die
            # Freigabe auf, der Inhalt gilt. Geloest wird erst an der Pruefseite.
            logger.info('%s: WAF prueft nur im Hintergrund, Inhalt uebernommen' % SITE_NAME)
        return sHtmlContent
    oRequest.dropCacheEntry()
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


def _searchRequest(sSearchText, iPage=1, bIgnoreErrors=False):
    """Abruf einer Suchseite. Die Suche ist ein Formular (do=search, als Rumpf
    geschickt), die Folgeseiten blaettern ueber `search_start` und `result_from`
    — genau das setzt das list_submit-JS der Seite (Mitschnitt 21.10.2026:
    `frm.result_from.value=(prm-1) * 12 + 1; frm.search_start.value=prm;
    frm.submit()`).

    Der Weiter-Eintrag traegt nur Begriff und Seitenzahl, der Abruf entsteht
    hier aus dem rohen Begriff (Regel: roh im Parameter,
    kodiert nur am Abruf; bis zum 02.11.2026 loeste der Parameterweg eine fertige
    Adresse ohnehin wieder auf, unquote_plus).
    """
    oRequest = cRequestHandler(URL_SEARCH, ignoreErrors=bIgnoreErrors)
    oRequest.addParameters('do', 'search')
    oRequest.addParameters('subaction', 'search')
    oRequest.addParameters('story', sSearchText)
    oRequest.addParameters('titleonly', '3')
    oRequest.addParameters('submit', 'submit')
    if iPage > 1:
        oRequest.addParameters('search_start', str(iPage))
        oRequest.addParameters('result_from', str((iPage - 1) * 12 + 1))
    return oRequest


def _searchPages(sHtmlContent, iPage):
    """Seitenlage der Suche aus der Blaetterleiste: (hat Folgeseite, letzte Seite).

    Die Suchseite blaettert nicht ueber Links, sondern ueber `list_submit(N)` im
    onclick — die Leiste fuehrt jede andere Seite so, die aktive als <span>, und
    auf der letzten Seite steht keine hoehere Zahl mehr. Die hoechste Zahl ist
    die letzte Seite (die Leiste zeigt sie auch hinter der Auslassung: "love"
    2..10 und 16), eine hoehere Zahl als die aktive belegt die Folgeseite. Ohne
    Leiste gibt es nur diese eine Seite (gemessen 21.10.2026 ueber 11 Begriffe).
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
    bNext, iLast = False, 1
    if sSearchText:
        iPage = int(params.getValue('page') or 1)
        entryUrl = URL_SEARCH   # die Serienerkennung unten prueft die Adresse auf /serie/
    elif not entryUrl:
        entryUrl = params.getValue('sUrl')
    pattern = 'class="title".*?href="([^"]+)">([^<]+).*?src="([^"]+)(.*?)</a> </span>'
    while True:
        if sSearchText:
            # Eine Folgeseite der Suche meldet Fehler nicht als Fenster: dort gilt wie
            # beim Blaettern „Kein Eintrag gefunden" (Seite 1 meldet wie bisher).
            oRequest = _searchRequest(sSearchText, iPage, sGui is not False or iPage > 1)
        else:
            oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
        sHtmlContent = _requestGated(oRequest)
        isMatch, aResult = cParser.parse(sHtmlContent, pattern)
        if not sSearchText or not isMatch:
            break
        # Titelfilter wie an allen Filterstellen (cParser.searchTitle, normalisiert)
        aResult = [row for row in aResult if cParser.searchTitle(sSearchText, row[1])]
        bNext, iLast = _searchPages(sHtmlContent, iPage)
        if aResult or sGui or not bNext:
            break
        # Seite nach dem Titelfilter leer, aber die Leiste fuehrt eine Folgeseite:
        # gleich weiterblaettern statt dem Nutzer leere Seiten zu zeigen (gefunden
        # 21.10.2026 an hdfilme „der pate"). Nur in der Einzelsuche — die globale
        # Suche bleibt bei Seite 1.
        iPage += 1
    if not isMatch:
        if not sGui:
            oGui.showInfo()
        return

    total = len(aResult)
    iShown = 0
    isTvshow = False
    for sUrl, sName, sThumbnail, sDummy in aResult:
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
    if sGui:
        return
    if sSearchText:
        # Suche: eine Seite je Aufruf, die Folgeseite ueber den Weiter-Eintrag mit
        # Begriff und Seitenzahl (Bauform wie bei den anderen Seiten). Leere Seiten
        # wurden oben uebersprungen; ohne Treffer und ohne Folgeseite kommt die
        # Meldung „Kein Eintrag gefunden" (belegt mit "koenig", 01.09.2026).
        if not iShown:
            oGui.showInfo()
        if bNext:
            nextParams = ParameterHandler()
            nextParams.setParam('sSearchText', sSearchText)
            nextParams.setParam('page', iPage + 1)
            oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', nextParams, cGui.pageInfo(iPage, iLast))
    else:
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
        # Eine Form auf allen Sites ("S01E05", cParser.episodeLabel) — ohne Seriennamen, der steht als TVShowTitle am Eintrag
        sTitle = cParser.episodeLabel(sStaffel, iEpisode)
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
    was nicht abspielt. Die Subdomains der Seite und die externen Hoster (Firestream,
    VOE, Veev, DSVPlay) sind damit abgedeckt, ohne sie hier einzeln zu pflegen.
    Eine Ausnahme betrifft kinoger.be und kinoger.re: der Referer (HOST_REFERER_REQUIRED),
    oben begruendet.

    WICHTIG: fuer den Blocked-Check den VOLLEN Hostnamen nehmen, nicht wie sonst
    ueblich nur den ersten Namensteil. kinoger versteckt seine Hoster hinter
    eigenen Subdomains — mit 'Kinoger' als Suchbegriff wuerden die alle faelschlich
    auf den KinoGer-Resolver passen und als spielbar gelistet, obwohl sie es nicht
    sind.
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
    # Das Verzeichnis schliesst showEntries selbst ab — so wie bei jeder
    # Weiter-Seite der Suche, die Kodi direkt dort aufruft.
    _search(False, sSearchText)


def _search(oGui, sSearchText):
    showEntries(False, oGui, sSearchText)
