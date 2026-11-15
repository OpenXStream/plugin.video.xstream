# -*- coding: utf-8 -*-
# Python 3

# Always pay attention to the translations in the menu!
# Keine Sprachlogik (seit 2026.09.10): die Seite ist deutsch, englische Fassungen
# fuehrt sie als Genre „Englisch" — das steht in unserer dynamischen Genre-Liste
# (Filme > Genre) und traegt die (EN)-Kennung ueber die Adresse.

import re
import time
import concurrent.futures
import xbmcgui
from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler, REQUEST_ERRORS
from resources.lib.logger import logger
from resources.lib.tools import cParser
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui


SITE_IDENTIFIER = 'filmpalast'
SITE_NAME = 'FilmPalast'
SITE_ICON = 'filmpalast.png'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'filmpalast.to')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)

URL_MAIN = 'https://' + DOMAIN
URL_MOVIES = URL_MAIN + '/movies/%s'
URL_SEARCH = URL_MAIN + '/search/title/%s'
URL_SERIES = URL_MAIN + '/serien/view'


def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.filmpalast.lastSearchText')
    params = ParameterHandler()
    params.setParam('sUrl', URL_MAIN)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30500), SITE_IDENTIFIER, 'showEntries'), params)  # Neu
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30502), SITE_IDENTIFIER, 'showMoviesMenu'))   # Filme (Submenü)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30511), SITE_IDENTIFIER, 'showSeriesMenu'))   # Serien (Submenü)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'), params)   # Search
    cGui().setEndOfDirectory()


def showMoviesMenu(): # Submenü Filme: Alle / Blockbuster / IMDB / Genre / A-Z
    params = ParameterHandler()
    params.setParam('sUrl', URL_MOVIES % 'new')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30542), SITE_IDENTIFIER, 'showEntries'), params)    # All Movies / Alle Filme
    params.setParam('sUrl', URL_MOVIES % 'top')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30509), SITE_IDENTIFIER, 'showEntries'), params)    # Top movies
    params.setParam('sUrl', URL_MOVIES % 'imdb')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30510), SITE_IDENTIFIER, 'showEntries'), params)    # IMDB rating
    params.setParam('sUrl', URL_MOVIES % 'new')
    params.setParam('value', 'genre')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30506), SITE_IDENTIFIER, 'showValue'), params)      # Genre
    params.setParam('value', 'movietitle')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30814), SITE_IDENTIFIER, 'showValue'), params)      # A-Z
    cGui().setEndOfDirectory()


def showSeriesMenu(): # Submenü Serien: Alle / A-Z
    params = ParameterHandler()
    params.setParam('sUrl', URL_SERIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30518), SITE_IDENTIFIER, 'showEntries'), params)    # All Series
    params.setParam('value', 'movietitle')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30814), SITE_IDENTIFIER, 'showValue'), params)      # A-Z
    cGui().setEndOfDirectory()


def _requestUrl(sUrl):
    # Kodiert unmittelbar vor dem Abruf (movie2k-Muster). Die Seite schreibt
    # Genre-Links roh mit Umlaut ins Markup ('/search/genre/Komödie') und auch
    # die Folgeseiten der Suche tragen den Suchbegriff roh — ohne Kodierung
    # bricht urllib mit UnicodeEncodeError ab. Kodiert wird NIE im Parameter
    # (der Parameterweg dekodiert per unquote_plus wieder), sondern nur hier.
    # '%' bleibt in der safe-Liste, damit bereits kodierte Adressen nicht ein
    # zweites Mal kodiert werden; Leerzeichen werden zu %20.
    return cParser.urlEncode(sUrl, safe=':/?&=%#+')


def showValue():
    params = ParameterHandler()
    value = params.getValue("value")
    oRequest = cRequestHandler(_requestUrl(params.getValue('sUrl')))
    sHtmlContent = oRequest.request()
    pattern = '<section[^>]id="%s">(.*?)</section>' % value
    isMatch, sContainer = cParser.parseSingleResult(sHtmlContent, pattern)
    if isMatch:
        isMatch, aResult = cParser.parse(sContainer, 'href="([^"]+)">([^<]+)')
        aResult = sorted(aResult, key=lambda x: x[1].lower())
        for sUrl, sName in aResult:
            params.setParam('sUrl', sUrl)
            cGui().addFolder(cGuiElement(sName, SITE_IDENTIFIER, 'showEntries'), params)
    if not isMatch:
        cGui().showInfo()
        return
    cGui().setEndOfDirectory()


def _parsePage(sHtmlContent):
    """Parst eine einzelne Seite und gibt (isMatch, aResult) zurück."""
    pattern = r'<article[^>]*>\s*<a href="([^"]+)" title="([^"]+)">\s*<img src=["\']([^"\']+)["\'][^>]*>(.*?)</article>'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        pattern = r'<a[^>]*href="([^"]*)"[^>]*title="([^"]*)"[^>]*>[^<]*<img[^>]*src=["\']([^"\']*)["\'][^>]*>\s*</a>(\s*)</article>'
        isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    return isMatch, aResult if isMatch else []


def _getNextPageUrl(sHtmlContent):
    """Extrahiert die nächste Seiten-URL oder gibt False zurück.

    Das Muster haengt am VORWAERTS-Link selbst: zwischen `>` und dem `+` darf kein
    weiteres Tag stehen. Vorher konnte die Suche stattdessen den Link auf Seite 1
    erwischen, weil auf der letzten Trefferseite ein Leerzeichen vor dem `>` steht
    (`href='…/1' >1</a>`) — daraus wurde eine kaputte Adresse mit Anfuehrungszeichen
    und Leerzeichen, die die Seite mit 404 beantwortet hat.
    """
    pattern = r'<a class="pageing[^"]*"\s*href=[\'"]?([^\'">]+)[\'"]?\s*>[^<]*\+\s*</a>'
    isMatch, sNextUrl = cParser.parseSingleResult(sHtmlContent, pattern)
    if isMatch:
        sNextUrl = sNextUrl.replace("'", "").replace('"', '').strip()
        if sNextUrl.startswith('/'):
            sNextUrl = URL_MAIN + sNextUrl
        return sNextUrl
    return False


# Pause vor jedem Nachholversuch: gibt einem Rate-Limit Luft. Laenger kostet
# nur im Fehlerfall — im Normalfall laeuft keine einzige Pause.
RETRY_PAUSE = 0.6


def _fetchSearchPage(sUrl, bFrisch=False):
    """Eine Trefferseite holen. Liefert (Treffer, hat-Vorwaerts-Link, erreicht).

    Das zweite Feld ist der Abbruch und NICHT verzichtbar: jenseits der letzten
    Seite liefert filmpalast keine leere Liste, sondern WIEDERHOLT den Inhalt.
    Wer nur auf „leer" prueft, laeuft bis zum Sicherheitslimit weiter und sammelt
    die Wiederholungen ein — gemessen 211 statt 109 Treffern bei „könig". Der
    Vorwaerts-Link fehlt dagegen auf der letzten Seite, genau daran hat sich
    schon die frueher sequenzielle Schleife orientiert.

    Fehler werden hier nicht gemeldet, aber seit 31.08. UNTERSCHEIDBAR
    zurueckgegeben (drittes Feld): die Funktion holt ausschliesslich
    Folgeseiten, und ein 404 am Listenende ist dort der Normalfall — der
    Sammler entscheidet per Nachfassversuch, ob ein Fehlschlag ein Aussetzer
    oder das Ende ist (Begruendung in _fetchAllSearchPages).
    """
    # bFrisch=True zwingt am HTML-Cache vorbei: Nachhol- und Bestaetigungs-
    # abrufe muessen den SERVER fragen — der Cache liefert sonst exakt die
    # Antwort zurueck, die gerade geheilt oder bestaetigt werden soll
    # (Drosselseiten mit Status 200 werden wie normale Antworten gecacht).
    oRequest = cRequestHandler(_requestUrl(sUrl), ignoreErrors=True, caching=not bFrisch)
    sHtmlContent = oRequest.request()
    if not sHtmlContent or sHtmlContent in REQUEST_ERRORS:
        return [], False, False
    isMatch, aResult = _parsePage(sHtmlContent)
    if not isMatch:
        return [], False, True
    return aResult, bool(_getNextPageUrl(sHtmlContent)), True


def _fetchAllSearchPages(startUrl, sGui=False):
    """Holt ALLE Seiten einer Suche und gibt kombinierte Ergebnisse zurück.

    Die Folgeseiten werden in Gruppen PARALLEL geholt. Nacheinander summierte
    sich die Ladezeit der Seite auf: gemessen 11,8 s fuer „walking dead" (sechs
    Seiten), also ueber der Grenze, ab der sich eine Liste haengend anfuehlt.
    Dasselbe Muster wie das Meta-Nachladen in xstream.py.

    Warum in Gruppen und nicht alles auf einmal: wie viele Seiten es gibt,
    verraet die Seite NICHT — Seite 1 fuehrt nur einen Vorwaerts-Link, keine
    Gesamtzahl. Wer spekulativ alle Seiten bis zum Sicherheitslimit holt,
    feuert bei den meisten Suchbegriffen (eine bis zwei Seiten) fast alle
    Abrufe ins Leere. Die Gruppe begrenzt das auf hoechstens drei.

    Fehlertoleranz seit 31.08. (Anlass: unter Parallellast fielen bei den
    Schwester-Sites zufaellig ganze Seiten still aus): je Seite hoechstens
    zwei Versuche — ein Fehlschlag wird einmal mit Pause nachgefasst, eine
    erreichte leere Seite einmal bestaetigt. Bleibt eine Seite danach tot
    oder leer, gilt das wie bisher als Listenende; Luecken mitten in der
    Liste kann es so nicht geben.
    """
    allResults = []
    maxPages = 5 if sGui else 10  # Sicherheitslimit
    iBatch = 4      # Folgeseiten je Gruppe

    # Seite 1 einzeln: nur hier ist ein Fehler eine echte Nachricht. Ab der
    # ZWEITEN Seite werden Fehler geschluckt, weil die Blaetter-Leiste der Seite
    # bei manchen Suchbegriffen mehr Seiten verspricht als es gibt („walking
    # dead": sechs Seiten mit Inhalt, die Leiste bietet trotzdem eine siebte an),
    # und die antwortet mit 404. Weil die Seite hinter Cloudflare liegt, steht in
    # JEDER Antwort `server: cloudflare` — frueher hielt der requestHandler den
    # 404 deshalb fuer eine Sperre und warf die Warnung 30829, obwohl die Suche
    # laengst alle Treffer hatte.
    oRequest = cRequestHandler(_requestUrl(startUrl), ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()
    if not sHtmlContent:
        return allResults
    isMatch, aResult = _parsePage(sHtmlContent)
    if not isMatch:
        return allResults
    allResults.extend(aResult)

    nextUrl = _getNextPageUrl(sHtmlContent)
    if not nextUrl:
        return allResults

    # Das Adressmuster kommt aus dem Vorwaerts-Link der SEITE, nicht aus dem
    # Code: er endet auf der Nummer der naechsten Seite. Ersetzt wird nur die
    # Zahl, alles davor bleibt so, wie die Seite es liefert. Passt die Form
    # nicht, bleibt es bei Seite 1 statt eine Adresse zu raten.
    oMatch = re.search(r'^(.*/)(\d+)$', nextUrl)
    if not oMatch:
        return allResults
    sBase, iPage = oMatch.group(1), int(oMatch.group(2))

    while iPage <= maxPages:
        aUrls = [sBase + str(p) for p in range(iPage, min(iPage + iBatch, maxPages + 1))]
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(aUrls)) as oPool:
            aPages = list(oPool.map(_fetchSearchPage, aUrls))
        bEnde = False
        for sUrl, (aSeite, bHasNext, bErreicht) in zip(aUrls, aPages):
            # Reihenfolge zaehlt: ab dem ersten bestaetigten Ende wird alles
            # Nachfolgende verworfen. Sonst landen entweder Luecken oder die
            # Wiederholungen jenseits des Endes in der Liste.
            if not bErreicht:
                # Gescheitert: einmal mit Pause nachfassen. Ein Aussetzer auf
                # der Leitung heilt so; der 404 hinter der Blaetter-Leiste (die
                # Seite verspricht manchmal eine Seite mehr als existiert)
                # bleibt tot und ist dann wie vor dem Umbau das Listenende.
                time.sleep(RETRY_PAUSE)
                aSeite, bHasNext, bErreicht = _fetchSearchPage(sUrl, bFrisch=True)
                if not bErreicht:
                    bEnde = True
                    break
                if aSeite:
                    logger.info('searchRetry %s: Seite %s nachgeholt, %d Treffer' % (SITE_NAME, sUrl.rsplit('/', 1)[-1], len(aSeite)))
            if not aSeite:
                # Erreicht, aber leer: einmal bestaetigen — ein 200er-Hickser
                # saehe sonst exakt wie das Ende aus und schnitte den Rest ab.
                time.sleep(RETRY_PAUSE)
                aSeite2, bHasNext2, bErreicht2 = _fetchSearchPage(sUrl, bFrisch=True)
                if not bErreicht2 or not aSeite2:
                    bEnde = True
                    break
                logger.info('searchRetry %s: Seite %s nachgeholt, %d Treffer' % (SITE_NAME, sUrl.rsplit('/', 1)[-1], len(aSeite2)))
                aSeite, bHasNext = aSeite2, bHasNext2
            allResults.extend(aSeite)
            if not bHasNext:
                bEnde = True
                break
        if bEnde:
            break
        iPage += iBatch

    return allResults


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl: entryUrl = params.getValue('sUrl')
    isTvshow = False

    # Bei Suche: ALLE Seiten auf einmal holen
    if sSearchText:
        aResult = _fetchAllSearchPages(entryUrl, sGui)
        isMatch = len(aResult) > 0
        sHtmlContent = None  # Nicht mehr nötig für Pagination
    else:
        oRequest = cRequestHandler(_requestUrl(entryUrl), ignoreErrors=(sGui is not False))
        sHtmlContent = oRequest.request()
        isMatch, aResult = _parsePage(sHtmlContent)

    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    total = len(aResult)
    iShown = 0
    seen_tv_shows = set()
    
    # Alphabetisch nur bei der Suche: dort liegen alle Ergebnisseiten zusammen vor, A-Z macht
    # die Liste findbar. Kategorien kommen seitenweise und behalten die Reihenfolge der Seite
    # (neueste zuerst) - je Seite zu sortieren wuerde nur diese Information zerstoeren.
    if sSearchText:
        aResult = sorted(aResult, key=lambda x: x[1].lower())
    
    for sUrl, sName, sThumbnail, sDummy in aResult:
        isTvshow, _ = cParser.parse(sName, r'S\d\dE\d\d')
        
        # Lockerer Suchfilter (ignoriert Sonderzeichen/Case)
        if sSearchText:
            search_clean = re.sub(r'\W+', '', sSearchText).lower()
            name_clean = re.sub(r'\W+', '', sName).lower()
            if search_clean not in name_clean:
                continue

        # Dedupe fuer Serien: je Serie nur der erste Folgen-Eintrag
        if isTvshow:
            cleanNameMatch = re.search(r'(.*?)\s*S\d+E\d+', sName, re.IGNORECASE)
            if cleanNameMatch:
                cleanName = cleanNameMatch.group(1).strip()
                if cleanName in seen_tv_shows:
                    continue
                seen_tv_shows.add(cleanName)
                sName = cleanName

        if sThumbnail.startswith('/'):
            sThumbnail = URL_MAIN + sThumbnail

        isYear, sYear = cParser.parseSingleResult(sDummy, r'Jahr:[^>]([\d]+)')
        isDuration, sDuration = cParser.parseSingleResult(sDummy, r'(?:Laufzeit|Spielzeit):[^>]([\d]+)')
        isRating, sRating = cParser.parseSingleResult(sDummy, 'Imdb:[^>]([^/]+)')

        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons' if isTvshow else 'showHosters')
        oGuiElement.setMediaType('tvshow' if isTvshow else 'movie')
        oGuiElement.setThumbnail(sThumbnail)
        if isYear: oGuiElement.setYear(sYear)
        if isDuration: oGuiElement.addItemValue('duration', sDuration)
        if isRating: oGuiElement.addItemValue('rating', sRating.replace(',', '.'))

        if sUrl.startswith('//'):
            params.setParam('entryUrl', 'https:' + sUrl)
        else:
            params.setParam('entryUrl', sUrl)
        
        params.setParam('sName', sName)
        params.setParam('sThumbnail', sThumbnail)
        if isYear: params.setParam('sYear', sYear)  # Aki: Year an showSeasons weitergeben
        oGui.addFolder(oGuiElement, params, isTvshow, total)
        iShown += 1

    # Kamen Treffer an, wurden aber ALLE vom Titelfilter verworfen, stand hier
    # ein leeres Verzeichnis ohne Hinweis (belegt mit "koenig", Audit 01.09.2026).
    # BEWUSST VOR dem Pagination-Block: dessen Bedingung schliesst die Suche aus,
    # die Meldung wuerde dort nie erreicht. Gleiches Muster wie in hdfilme.
    if not sGui and not iShown:
        oGui.showInfo()

    # --- PAGINATION nur für Kategorien (nicht für Suche, da schon alle Seiten geholt) ---
    if not sGui and not sSearchText and sHtmlContent:
        nextUrl = _getNextPageUrl(sHtmlContent)
        if nextUrl:
            # FRISCHER ParameterHandler: der oben in der Schleife benutzte traegt noch
            # entryUrl, sName und sThumbnail des LETZTEN Listeneintrags mit sich. Die
            # Folgeseite braucht davon nichts, und geerbte Werte sind eine Falle, sobald
            # showEntries irgendwann mehr als sUrl liest.
            nextParams = ParameterHandler()
            nextParams.setParam('sUrl', nextUrl)
            oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', nextParams)
    if not sGui:
        oGui.setView('tvshows' if isTvshow else 'movies')
        if not sSearchText:
            oGui.setEndOfDirectory()

def showSeasons():
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    sThumbnail = params.getValue("sThumbnail")
    sName = params.getValue('sName')
    sTmdbID = params.getValue('tmdbID') or ''
    sYear = params.getValue('sYear') or ''  # Aki: Year aus Listen-Ebene uebernehmen
    oRequest = cRequestHandler(_requestUrl(sUrl))
    sHtmlContent = oRequest.request()
    pattern = r'<a[^>]*class="staffTab"[^>]*data-sid="(\d+)"[^>]*>'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        cGui().showInfo()
        return
    isDesc, sDesc = cParser.parseSingleResult(sHtmlContent, '"description">([^<]+)')
    # Die Reiter stehen im Markup NICHT immer in der richtigen Reihenfolge (Breaking Bad
    # liefert 3, 2, 4, 1, 5). Deshalb nach Nummer sortieren und Doppelte entfernen —
    # bei den uebrigen Serien aendert das nichts, dort steht die Liste schon aufsteigend.
    aResult = sorted({str(int(s)) for s in aResult if str(s).isdigit()}, key=int) or aResult
    total = len(aResult)
    for sSeason in aResult:
        oGuiElement = cGuiElement(cConfig().getLocalizedString(30512) + ' ' + str(sSeason), SITE_IDENTIFIER, 'showEpisodes')
        oGuiElement.setTVShowTitle(sName)
        oGuiElement.setSeason(sSeason)
        oGuiElement.setMediaType('season')
        if sTmdbID:
            oGuiElement.addItemValue('tmdb_id', sTmdbID)
        if sYear:
            oGuiElement.addItemValue('year', sYear)  # Aki: Year auf Staffel setzen
        oGuiElement.setThumbnail(sThumbnail)
        if isDesc:
            oGuiElement.setDescription(sDesc)
        cGui().addFolder(oGuiElement, params, True, total)
    cGui().setView('seasons')
    cGui().setEndOfDirectory()


def showEpisodes():
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    sThumbnail = params.getValue("sThumbnail")
    sSeason = params.getValue('season')
    sShowName = params.getValue('TVShowTitle')
    oRequest = cRequestHandler(_requestUrl(sUrl))
    sHtmlContent = oRequest.request()

    # Die Staffelreiter der Seite (data-sid) taugen NICHT als Zuordnung: gemessen an
    # 110 Serien liegen bei zweien mehrere Staffeln in einem Container (Outlander:
    # S1-S3 im Container 3) oder ein Reiter hat gar keinen eigenen (Fear The Walking
    # Dead: Reiter 1 und 2). Beides fuehrte zu leeren oder vermischten Folgenlisten.
    # Verlaesslich ist die Staffelnummer in der Adresse selbst — danach wird gruppiert.
    aResult = _episodeLinks(sHtmlContent, sUrl, sSeason)
    if not aResult:
        # Fallback fuer Serien, deren Folgen nicht dem s01e01-Schema folgen:
        # der alte Weg ueber den Container mit passender data-sid.
        pattern = r'<div[^>]*class="staffelWrapperLoop[^"]*"[^>]*data-sid="%s">(.*?)</ul></div>' % sSeason
        isMatch, sContainer = cParser.parseSingleResult(sHtmlContent, pattern)
        if isMatch:
            isMatch, aLinks = cParser.parse(sContainer, 'href="([^"]+)')
            if isMatch:
                aResult = [(l, cParser.parseSingleResult(l, r'e(\d+)')[1]) for l in aLinks]
    if not aResult:
        cGui().showInfo()
        return

    isDesc, sDesc = cParser.parseSingleResult(sHtmlContent, '"description">([^<]+)')
    total = len(aResult)
    for sUrl, sName in aResult:
        oGuiElement = cGuiElement(cConfig().getLocalizedString(30513) + ' ' + str(sName), SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setThumbnail(sThumbnail)
        oGuiElement.setTVShowTitle(sShowName)
        oGuiElement.setSeason(sSeason)
        oGuiElement.setEpisode(sName)
        oGuiElement.setMediaType('episode')
        if sUrl.startswith('//'):
            params.setParam('entryUrl', 'https:' + sUrl)
        else:
            params.setParam('entryUrl', sUrl)
        if isDesc:
            oGuiElement.setDescription(sDesc)
        cGui().addFolder(oGuiElement, params, False, total)
    cGui().setView('episodes')
    cGui().setEndOfDirectory()


def _episodeLinks(sHtmlContent, sSeriesUrl, sSeason):
    """Folgen-Adressen EINER Staffel, aus der ganzen Detailseite gesammelt.

    Die Seite verlinkt jede Folge als <serien-slug>-sXXeYY. Gesucht wird deshalb
    nach genau diesem Schema mit dem Slug der aufgerufenen Serie — so koennen
    weder Folgen einer fremden Serie noch Folgen einer anderen Staffel hineinlaufen.
    Sortiert wird nach Folgennummer, doppelte Adressen fliegen raus.
    """
    sSlug = re.sub(r'-s\d+e\d+.*$', '', sSeriesUrl.split('/stream/')[-1].split('?')[0])
    if not sSlug:
        return []
    try:
        iSeason = int(sSeason)
    except (TypeError, ValueError):
        return []
    # Der Bindestrich vor der Staffelkennung ist OPTIONAL: dieselbe Serie fuehrt beide
    # Schreibweisen (outlander-s03e10 neben outlanders03e01). Entdeckt wird die Folge
    # ausserdem in mehreren Adressformen (// und https://) — deshalb wird ueber die
    # FOLGENNUMMER entdoppelt, sonst steht die Folge der aufgerufenen Seite zweimal
    # in der Liste.
    pattern = r'href="((?://|https?://)[^"]*?/stream/%s-?s0*%de(\d+))"' % (re.escape(sSlug), iSeason)
    aFound = []
    seen = set()
    for sLink, sEp in re.findall(pattern, sHtmlContent):
        try:
            iEp = int(sEp)
        except ValueError:
            continue
        if iEp in seen:
            continue
        seen.add(iEp)
        aFound.append((sLink, sEp))
    aFound.sort(key=lambda x: int(x[1]))
    return aFound


def showHosters():
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    if '-english' in sUrl: sLang = '(EN)'
    else: sLang = ''
    sHtmlContent = cRequestHandler(_requestUrl(sUrl), caching=False).request()
    pattern = 'hostName">([^<]+).*?(http[^"]+)'
    releaseQuality = r'class="rb">.*?(\d\d\d+)p\.'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    isQuality, sQuality = cParser.parseSingleResult(sHtmlContent, releaseQuality)
    if not isQuality: sQuality = '720'
    hosters = []
    if isMatch:
        for sName, sUrl in aResult:
            sName = sName.split(' HD')[0].strip()
            if 'Filemoon' in sName or 'Swiftload' in sName or 'Vidhide' in sName:
                # Referer = einbettende Hauptdomain, aus URL_MAIN statt hartkodiert:
                # wechselt die Domain, bliebe ein Literal auf der alten stehen.
                sUrl = sUrl + '$$' + URL_MAIN + '/'
                if cConfig().isBlockedHoster(sName)[0]: continue  # Hoster aus settings.xml oder deaktivierten Resolver ausschließen
                hoster = {'link': sUrl, 'name': sName, 'displayedName': '%s [I]%s [%sp][/I]' % (sName, sLang, sQuality), 'languageCode': sLang, 'quality': sQuality}
                hosters.append(hoster)
            else:
                if cConfig().isBlockedHoster(sName)[0]: continue # Hoster aus settings.xml oder deaktivierten Resolver ausschließen
                hoster = {'link': sUrl, 'name': sName, 'displayedName': '%s [I]%s [%sp][/I]' % (sName, sLang, sQuality), 'languageCode': sLang, 'quality': sQuality}
                hosters.append(hoster)
    if hosters:
        hosters.append('getHosterUrl')
    return hosters

def getHosterUrl(sUrl=False):
    return [{'streamUrl': sUrl, 'resolved': False}]


def showSearch():
    win = xbmcgui.Window(10000)
    sSearchText = win.getProperty('xstream.filmpalast.lastSearchText')
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30281))
        if not sSearchText: return
        win.setProperty('xstream.filmpalast.lastSearchText', sSearchText)
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def _search(oGui, sSearchText):
    # Quote nutzen statt quotePlus, damit Leerzeichen als %20 übergeben werden
    showEntries(URL_SEARCH % cParser.quote(sSearchText), oGui, sSearchText)
