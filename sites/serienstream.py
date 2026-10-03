# -*- coding: utf-8 -*-
# Python 3

# Always pay attention to the translations in the menu!
# Language selection for hosters included.
# 2022-12-06 Heptamer - Search function reworked
# 2026-12-29 viewIT   - Hotfix for V2 of SerienStream
# 2026-02-02 SatBandit - Hotfix for V2 of SerienStream

import ast
import xbmcgui
import string
import re

from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger
from resources.lib.tools import cParser, cUtil
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui
from urllib.parse import quote_plus, urljoin
from html import unescape

SITE_IDENTIFIER = 'serienstream'
SITE_NAME = 'SerienStream'
SITE_ICON = 'serienstream.png'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'serienstream.to')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)

URL_MAIN = 'https://' + DOMAIN

# Beschriftung der Sprachen. Schluessel sind die data-language-label der Seite; alles
# andere wird unveraendert in Klammern angezeigt, damit auch eine kuenftige Sprache
# lesbar in der Liste steht statt als Zahl.
LANG_LABELS = {'Deutsch': '(DE)', 'Englisch': '(EN)', 'Ger-Sub': '(Ger-Sub)'}
REFERER = 'https://' + DOMAIN
URL_SERIES = URL_MAIN + '/serien'
URL_NEW_SERIES = URL_MAIN + '/neu'
URL_NEW_EPISODES = URL_MAIN + '/neue-episoden'
URL_POPULAR = URL_MAIN + '/beliebte-serien'
URL_COLLECTIONS = URL_MAIN + '/sammlungen'
URL_LOGIN = URL_MAIN + '/login'
URL_SEARCH = URL_MAIN + '/suche?term='

PAGE_SIZE = 20  # Ab wie vielen Seiten der Sprung-Eintrag erscheint. Hier ist die letzte
# Seitenzahl exakt bekannt, deshalb kommt er auf JEDER Liste mit mehr als einer
# Seite (Jack 04.09.2026: "selbst wenn es nur drei sind, wenn es geht kommt es
# rein"). Bei den DLE-Sites steht die Zahl erst ab der "…"-Auslassung der
# Blaetterleiste zur Verfuegung — dort bleibt es technisch bedingt bei rund 11.


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _abs_url(url):
    """Macht aus einer relativen URL eine absolute."""
    if not url:
        return ''
    if url.startswith('http://') or url.startswith('https://'):
        return url
    return URL_MAIN + url if url.startswith('/') else URL_MAIN + '/' + url


def extractPoster(sHtml):
    """Extrahiert das Serien-Poster aus der Detailseite.
    Bevorzugt Desktop-Container (col-lg-2), Fallback: show-cover-mobile."""
    sThumbnail = ''
    match = re.search(r'class="[^"]*col-lg-2[^"]*">.*?<img[^>]+data-src="([^"]+)"', sHtml, re.DOTALL)
    if not match:
        match = re.search(r'class="[^"]*show-cover-mobile[^"]*">.*?<img[^>]+data-src="([^"]+)"', sHtml, re.DOTALL)
    if match:
        sThumbnail = match.group(1).strip()
        if sThumbnail.startswith('/'):
            sThumbnail = URL_MAIN + sThumbnail
        sThumbnail = sThumbnail.replace('format=webp', 'format=jpg').replace('format=avif', 'format=jpg')
    return sThumbnail


def _requestUrl(sUrl):
    # Kodiert unmittelbar vor dem Abruf (movie2k-Muster). Die Seite verlinkt
    # einzelne Serien mit kodierten Zeichen im Pfad ('/serie/25%20Years%20of%20You',
    # belegt am Neu-Slider) — der Parameterweg dekodiert das zu Leerzeichen und
    # der Request bricht ab. Kodiert wird NIE im Parameter, sondern nur hier;
    # '%' bleibt in der safe-Liste, damit bereits kodierte Adressen nicht ein
    # zweites Mal kodiert werden.
    return cParser.urlEncode(sUrl, safe=':/?&=%#+')


def _fetchPosterFallback(sUrl):
    """Holt Poster per Detail-Request — nur als Fallback wenn kein Bild im HTML."""
    try:
        oReq = cRequestHandler(_requestUrl(sUrl), caching=True)
        sHtml = oReq.request()
        if sHtml:
            return extractPoster(sHtml)
    except Exception:
        pass
    return ''


def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.serienstream.lastSearchText')
    xbmcgui.Window(10000).clearProperty('xstream.serienstream.lastYear')
    params = ParameterHandler()
    # Login ist optional — Settings 'serienstream.user' / 'serienstream.pass'
    # bleiben in settings.xml verfuegbar, werden aber nicht erzwungen.
    # (URL_LOGIN ist im Code deklariert aber nirgends genutzt — Plugin
    # funktioniert ohne Login.)

    # Neues (Submenü)
    params = ParameterHandler()
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30554), SITE_IDENTIFIER, 'showNeues'), params)
    # Trends (Submenü)
    params = ParameterHandler()
    params.setParam('sUrl', URL_MAIN)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30555), SITE_IDENTIFIER, 'showTrends'), params)
    # Genre
    params = ParameterHandler()
    params.setParam('sUrl', URL_SERIES + "?by=genre")
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30506), SITE_IDENTIFIER, 'showGenericMenu'), params)
    # Jahr (User gibt Jahr ein, /jahr/YYYY) — gleiche Bedienung wie bei AniWorld
    params = ParameterHandler()
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30564), SITE_IDENTIFIER, 'showYearSearch'), params)
    # Kollektionen (Submenü; die Seite nennt sie Sammlungen — String 30543 wie bei
    # filmo, megakino, moflix, einschalten, damit der Block auf allen Seiten gleich heisst)
    params = ParameterHandler()
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30543), SITE_IDENTIFIER, 'showCollectionsMenu'), params)
    # A-Z
    params = ParameterHandler()
    params.setParam('sUrl', URL_SERIES + "?by=alpha")
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30814), SITE_IDENTIFIER, 'showGenericMenu'), params)
    # Suche
    params = ParameterHandler()
    params.setParam('sUrl', URL_SEARCH)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'), params)
    cGui().setEndOfDirectory()

import xbmc


def showYearSearch():
    """Jahr-Suche — User gibt ein Jahr ein, die Seite listet unter /jahr/YYYY.

    Die Seite fuehrt selbst keine Uebersicht aller Jahre (kein /jahr, /jahre),
    das Jahr steht dort nur als Link auf den Serien-Detailseiten. Deshalb die
    Eingabe wie bei AniWorld. Die Ausgabe uebernimmt showCatalog: die Jahresseite
    benutzt denselben Aufbau wie der Katalog (Container row g-3, rel=next fuer
    die Folgeseiten), ein eigener Parser waere doppelter Code.
    """
    win = xbmcgui.Window(10000)
    sYear = win.getProperty('xstream.serienstream.lastYear')
    if not sYear:
        # Zahlenfeld statt Freitext, und eine verworfene Eingabe wird gemeldet
        # statt stumm abzubrechen (gleiche Aenderung wie bei aniworld, 01.09.2026).
        sYear = str(cGui().showNumpad(numPadTitle=cConfig().getLocalizedString(30563)) or '').strip()
        if not sYear:
            return
        # Validierung: nur vierstellige Jahre. Untergrenze 1900, weil die Seite
        # tatsaechlich bis in die 1930er zurueckreicht (1930 liefert Treffer).
        if not sYear.isdigit() or len(sYear) != 4 or int(sYear) < 1900:
            cGui().showInfo('xStream', cConfig().getLocalizedString(30563))
            return
        win.setProperty('xstream.serienstream.lastYear', sYear)
    # Direkt uebergeben: showCatalog liest seinen ParameterHandler aus der
    # plugin-URL: ein hier gesetzter Wert kaeme dort nicht an.
    showCatalog(URL_MAIN + '/jahr/' + sYear)


def _catalogPageInfo(sHtmlContent):
    """Seitenlage fuer Katalog (A-Z) und Jahr-Suche. Die Seite traegt ZWEI
    Blaetterleisten im selben Markup: die mobile nennt nur die Nachbarseiten
    ("... 2 [3] 4 ..."), die Desktop-Leiste (class d-none ... d-sm-flex) fuehrt
    die hoechste Seite als Link. Aktuelle Seite = aktiver Eintrag dieser Leiste.
    Gemessen 06.09.2026: Katalog D 43, A 23, 0-9 4, Jahr 2020 32; Listen mit
    einer Seite (X, 1965) haben keine Leiste und keinen Weiter-Eintrag."""
    match_bar = re.search(r'class="d-none[^"]*d-sm-flex[^"]*"([\s\S]*?)</ul>', sHtmlContent)
    if not match_bar: return ''
    aPages = re.findall(r'[?&]page=(\d+)', match_bar.group(1))
    if not aPages: return ''
    match_active = re.search(r'page-item active[^>]*>\s*<span class="page-link">(\d+)</span>', match_bar.group(1))
    iCurrent = int(match_active.group(1)) if match_active else 1
    return cGui.pageInfo(iCurrent, max(int(p) for p in aPages))


def showCatalog(entryUrl=False):
    params = ParameterHandler()
    sUrl = entryUrl if entryUrl else params.getValue('sUrl')
    sTargetGenre = params.getValue('sGenreFilter')
    
    oRequest = cRequestHandler(_requestUrl(sUrl))
    sHtmlContent = oRequest.request()
    if not sHtmlContent: return
    oGui = cGui()

    # Bilder-Index ueber die ganze Seite: Serienname -> Bild
    dictThumbs = {}
    # s.to Kacheln haben oft: <img src="URL" alt="Serienname">
    # oder data-src. Dieser Regex fischt alle Bilder mit ihren Titeln ab.
    all_images = re.findall(r'(?:data-src|src)="([^"]+)"[^>]*alt="([^"]+)"', sHtmlContent)
    for sThumb, sTitle in all_images:
        name_key = unescape(sTitle).strip()
        if sThumb.startswith('/'): sThumb = URL_MAIN + sThumb
        dictThumbs[name_key] = sThumb

    # 1. Block-Isolierung
    if sTargetGenre:
        safe_genre = re.escape(sTargetGenre)
        pattern = r'<h3[^>]*>\s*' + safe_genre + r'\s*</h3>([\s\S]*?)(?=<div[^>]*class="[^"]*mt-4[^"]*"|<h3|$)'
        match = re.search(pattern, sHtmlContent)
        sContent = match.group(1) if match else sHtmlContent
        pattern_list = r'<li[^>]*>\s*<a href="(/serie/[^"]+)"[^>]*>([^<]+)</a>\s*</li>'
    else:
        match_container = re.search(r'class="row g-3">([\s\S]*?)<nav', sHtmlContent)
        sContent = match_container.group(1) if match_container else sHtmlContent
        pattern_list = r'<h6[^>]*>\s*<a href="(/serie/[^"]+)"[^>]*>([^<]+)</a>\s*</h6>'

    results = re.findall(pattern_list, sContent)

    # 2. Schleife mit Bild-Zuweisung
    for sLink, sSeriesName in results:
        sSeriesName = unescape(sSeriesName).strip()
        oGuiElement = cGuiElement(sSeriesName, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')   # wie die uebrigen Serienlisten: ohne Medientyp fehlten Trailer, TMDB-Info und Weitere Quellen im Kontextmenue (Nachpruefung 29.09.2026: A-Z und Jahr, 736 Eintraege)

        sThumb = dictThumbs.get(sSeriesName, "")

        # Fallback im A-Z-Modus: Bild in der Umgebung des Links suchen
        if not sThumb and not sTargetGenre:
            thumb_match = re.search(r'href="' + re.escape(sLink) + r'"[\s\S]*?(?:data-src|src)="([^"]+)"', sContent)
            if thumb_match:
                sThumb = thumb_match.group(1)
                if sThumb.startswith('/'): sThumb = URL_MAIN + sThumb
        
        if sThumb:
            oGuiElement.setThumbnail(sThumb)
        
        p = ParameterHandler()
        p.setParam('sUrl', URL_MAIN + sLink if not sLink.startswith('http') else sLink)
        p.setParam('sName', sSeriesName)
        oGui.addFolder(oGuiElement, p)

    # 3. Pagination
    if not sTargetGenre:
        match_next = re.search(r'href="([^"]+)"[^>]*rel="next"', sHtmlContent)
        if match_next:
            next_url = match_next.group(1)
            if not next_url.startswith('http'): next_url = URL_MAIN + next_url
            
            p_next = ParameterHandler()
            p_next.setParam('sUrl', next_url)
            p_next.setParam('sName', params.getValue('sName'))
            # Gleicher Weiter-Eintrag wie ueberall (30279 mit Seitenlage) statt des
            # frueheren eigenen Textes '>>> Naechste Seite' ohne Angabe — die Seite
            # nennt ihr Ende (Desktop-Leiste, siehe _catalogPageInfo).
            oGui.addNextPage(SITE_IDENTIFIER, 'showCatalog', p_next, _catalogPageInfo(sHtmlContent))

    # Ohne Eintraege bleibt sonst ein leeres Verzeichnis ohne Hinweis stehen. Erreichbar
    # ist das ueber die Jahr-Suche: Jahrgaenge vor etwa 1955 liefern nichts, und die
    # Eingabe laesst bewusst alles ab 1900 zu. aniworld meldet am selben Weg bereits.
    if not results:
        oGui.showInfo()

    oGui.setEndOfDirectory()

def showGenericMenu():
    params = ParameterHandler()
    sUrl = params.getValue('sUrl')
    sHtmlContent = cRequestHandler(_requestUrl(sUrl)).request()
    if not sHtmlContent: return
    oGui = cGui()

    if 'by=genre' in sUrl:
        # Neues HTML-Pattern 2026: <div class="background-1 ..."><h3 class="h5 ...">Abenteuer</h3></div>
        pattern = r'<div[^>]*class="[^"]*background-1[^"]*"[^>]*>\s*<h3[^>]*>([^<]+)</h3>'
        results = re.findall(pattern, sHtmlContent)
        # Fallback: altes Pattern
        if not results:
            pattern = r'<h3[^>]*class="[^"]*h5[^"]*"[^>]*>([^<]+)</h3>'
            results = re.findall(pattern, sHtmlContent)

        for sGenreName in results:
            sRawName = unescape(sGenreName).strip()
            sDisplay = sRawName.replace('filter.genre_', '').replace('-', ' ').replace('_', ' ').title()
            if not sDisplay: continue

            p = ParameterHandler()
            p.setParam('sUrl', sUrl)
            p.setParam('sGenreFilter', sRawName) # Original für HTML-Suche
            oGui.addFolder(cGuiElement(sDisplay, SITE_IDENTIFIER, 'showGenreEntries'), p)
    else:
        # A-Z Logik
        match_bar = re.search(r'class="alphabet-bar[^"]*">([\s\S]*?)</nav>', sHtmlContent)
        if match_bar:
            results = re.findall(r'href="(/katalog/[^"]+)"[^>]*>([^<]+)</a>', match_bar.group(1))
            for sNextUrl, sTitle in results:
                p = ParameterHandler()
                p.setParam('sUrl', _abs_url(sNextUrl))
                p.setParam('sName', sTitle.strip())
                oGui.addFolder(cGuiElement(sTitle.strip(), SITE_IDENTIFIER, 'showCatalog'), p)

    oGui.setEndOfDirectory()


def _pageInfo(iPage, iTotalItems):
    """Seitenlage fuer den Weiter-Eintrag der selbst geschnittenen Listen: die
    vollstaendige Liste liegt vor, die Seitenzahl ist damit bekannt."""
    return cGui.pageInfo(iPage, -(-int(iTotalItems) // PAGE_SIZE))


def showGenreEntries():
    """Genre-Einträge mit Pagination und Poster-Fallback."""
    params       = ParameterHandler()
    sUrl         = params.getValue('sUrl')
    sTargetGenre = params.getValue('sGenreFilter')
    iPage        = int(params.getValue('iPage') or 1)
    oGui = cGui()

    sHtmlContent = cRequestHandler(_requestUrl(sUrl)).request()
    if not sHtmlContent:
        oGui.showInfo()
        return

    # Genre-Block isolieren (neues Pattern: series-list)
    escaped = re.escape(sTargetGenre)
    pattern = r'<h3[^>]*>\s*' + escaped + r'\s*</h3>\s*</div>\s*<ul[^>]*class="[^"]*series-list[^"]*"[^>]*>([\s\S]*?)</ul>'
    match   = re.search(pattern, sHtmlContent)

    # Fallback: altes Pattern
    if not match:
        pattern = r'<h3[^>]*>\s*' + escaped + r'\s*</h3>([\s\S]*?)(?=<div[^>]*class="[^"]*mt-4[^"]*"|<h3|$)'
        match = re.search(pattern, sHtmlContent)

    if not match:
        oGui.showInfo()
        return

    sContainer = match.group(1)
    items = re.findall(r'<a[^>]+href="(/serie/[^"]+)"[^>]*>([^<]+)</a>', sContainer)

    seen  = set()
    clean = []
    for sLink, sName in items:
        if sLink in seen:
            continue
        seen.add(sLink)
        clean.append((_abs_url(sLink), unescape(sName).strip()))

    if not clean:
        oGui.showInfo()
        return

    # Pagination
    iStart = (iPage - 1) * PAGE_SIZE
    iEnd   = iStart + PAGE_SIZE
    page_items = clean[iStart:iEnd]
    total      = len(page_items)

    for sFullUrl, sName in page_items:
        # Erst aus dem Seiten-HTML Bild suchen, dann Fallback
        sThumb = ''
        thumb_match = re.search(r'href="' + re.escape(sFullUrl.replace(URL_MAIN, '')) + r'"[\s\S]*?(?:data-src|src)="([^"]+)"', sContainer)
        if thumb_match:
            sThumb = _abs_url(thumb_match.group(1))
        if not sThumb or 'data:image' in sThumb:
            sThumb = _fetchPosterFallback(sFullUrl)

        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        if sThumb:
            oGuiElement.setThumbnail(sThumb)
        p = ParameterHandler()
        p.setParam('sUrl',       sFullUrl)
        p.setParam('sName',      sName)
        p.setParam('sThumbnail', sThumb)
        oGui.addFolder(oGuiElement, p, True, total)

    # Nächste Seite
    if iEnd < len(clean):
        p = ParameterHandler()
        p.setParam('sUrl',         sUrl)
        p.setParam('sGenreFilter', sTargetGenre)
        p.setParam('iPage',        str(iPage + 1))
        oGui.addNextPage(SITE_IDENTIFIER, 'showGenreEntries', p, _pageInfo(iPage, len(clean)))

    oGui.setView('tvshows')
    oGui.setEndOfDirectory()
                    

def showAllSeries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl: entryUrl = params.getValue('sUrl')
    iPage = int(params.getValue('iPage') or 1)
    oRequest = cRequestHandler(_requestUrl(entryUrl), ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()
    pattern = '<a[^>]*href="(\\/serie\\/[^"]*)"[^>]*>(.*?)</a>'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    seen  = set()
    clean = []
    for sUrl, sName in aResult:
        if sUrl in seen: continue
        seen.add(sUrl)
        sName = unescape(sName)
        if sSearchText and not cParser.searchTitle(sSearchText, sName):
            continue
        clean.append((_abs_url(sUrl), sName))

    # Pagination nur im normalen Modus (nicht bei globaler Suche)
    if sGui or sSearchText:
        page_items = clean
    else:
        iStart = (iPage - 1) * PAGE_SIZE
        iEnd   = iStart + PAGE_SIZE
        page_items = clean[iStart:iEnd]

    total = len(page_items)
    for sFullUrl, sName in page_items:
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        p = ParameterHandler()
        p.setParam('sUrl', sFullUrl)
        p.setParam('TVShowTitle', sName)
        oGui.addFolder(oGuiElement, p, True, total)

    # Nächste Seite (nur im normalen Modus)
    if not sGui and not sSearchText and iEnd < len(clean):
        p = ParameterHandler()
        p.setParam('sUrl',  entryUrl)
        p.setParam('iPage', str(iPage + 1))
        oGui.addNextPage(SITE_IDENTIFIER, 'showAllSeries', p, _pageInfo(iPage, len(clean)))

    if not sGui:
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()


# Hilfsfunktion: Extrahiert alle Cards aus einem HTML-Block
def extractCards(sHtml):
    # s.to uses 'data-src' for images (lazy load)
    pattern = r'href="([^"]+)"[^>]*class="show-card[^"]*".*?data-src="([^"]+)"[^>]*alt="([^"]+)"'
    
    # (?s) allows line breaks within a card
    return re.findall(r'(?s)' + pattern, sHtml)

def showGenericSeriesList(entryUrl=False):
    oGui = cGui()
    params = ParameterHandler()
    
    sUrl = params.getValue('sUrl') or (URL_MAIN + '/beliebte-serien')
    sectionName = params.getValue('sectionName')
    
    oRequest = cRequestHandler(_requestUrl(sUrl))
    sHtmlContent = oRequest.request()
    sHtmlContent = re.sub(r'\s+', ' ', sHtmlContent)

    if sectionName and sectionName in sHtmlContent:
        # Start: Direkt nach dem Sektionsnamen
        sHtmlContent = sHtmlContent.split(sectionName, 1)[1]
        
        # Ende: Wir suchen das Ende der Liste. 
        # S.to often closes grids with </ul> or </section>
        # A safe anchor is the next <h2 (next section heading)
        if '<h2' in sHtmlContent:
            sHtmlContent = sHtmlContent.split('<h2', 1)[0]
        elif '</section>' in sHtmlContent:
            sHtmlContent = sHtmlContent.split('</section>', 1)[0]
    
    aResult = extractCards(sHtmlContent)

    if not aResult:
        # Fallback-Suche, falls das erste Pattern zu streng war
        pattern_fallback = r'href="([^"]+)"[^>]*>.*?data-src="([^"]+)"[^>]*alt="([^"]+)"'
        aResult = re.findall(r'(?s)' + pattern_fallback, sHtmlContent)

    seen = set()
    for sUrl, sThumbnail, sName in aResult:
        if sUrl in seen: continue
        seen.add(sUrl)
        
        if sUrl.startswith('/'): sUrl = URL_MAIN + sUrl
        if sThumbnail.startswith('/'): sThumbnail = URL_MAIN + sThumbnail
            
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setThumbnail(sThumbnail)
        oGuiElement.setMediaType('tvshow')
        
        # Important: New parameter instance for each folder!
        p = ParameterHandler()
        p.setParam('sUrl', sUrl)
        p.setParam('sName', sName)
        p.setParam('sThumbnail', sThumbnail)
        oGui.addFolder(oGuiElement, p, True, len(aResult))

    oGui.setView('tvshows')
    oGui.setEndOfDirectory() 

def showNeues():
    """Submenü 'Neues' mit Neue Serien und Neuste Episoden."""
    oGui = cGui()
    # Neue Serien
    params = ParameterHandler()
    params.setParam('sUrl', URL_NEW_SERIES)
    oGui.addFolder(cGuiElement(cConfig().getLocalizedString(30511), SITE_IDENTIFIER, 'showNewSeries'), params)
    # Neuste Staffel diese Woche (aus Beliebte Serien Seite)
    params = ParameterHandler()
    oGui.addFolder(cGuiElement(cConfig().getLocalizedString(30556), SITE_IDENTIFIER, 'showNeusteStaffel'), params)
    # Neuste Episoden
    params = ParameterHandler()
    oGui.addFolder(cGuiElement(cConfig().getLocalizedString(30557), SITE_IDENTIFIER, 'showNeusteEpisoden'), params)
    oGui.setEndOfDirectory()

def showNeusteStaffel():
    """Zeigt 'Neuste Staffel diese Woche' von der Beliebte-Serien-Seite."""
    oGui = cGui()
    sHtmlContent = cRequestHandler(URL_POPULAR, caching=True).request()
    if not sHtmlContent: return
    sHtmlContent = re.sub(r'\s+', ' ', sHtmlContent)

    # Alle H2/H3-Überschriften durchsuchen - flexibel nach "Staffel" + "Woche" matchen
    titles = re.findall(r'<(?:h2|h3)[^>]*>(.*?)</(?:h2|h3)>', sHtmlContent)
    sTargetTitle = None
    for sTitle in titles:
        sClean = re.sub(r'<[^>]*>', '', sTitle).strip()
        sClean = ''.join(c for c in sClean if ord(c) < 128).strip()
        if 'staffel' in sClean.lower() and 'woche' in sClean.lower():
            sTargetTitle = sClean
            break

    if not sTargetTitle:
        oGui.showInfo()
        return

    # Sektion extrahieren (gleiche Logik wie showSectionContent)
    find_section = r'<(?:h2|h3)[^>]*>[^<]*' + re.escape(sTargetTitle) + r'.*?</(?:h2|h3)>(.*?)(?=<h2|<h3|$)'
    match = re.search(find_section, sHtmlContent)

    if match:
        sFragment = match.group(1)
        pattern = r'href="(/serie/[^"]+)".*?<img.*?(?:data-src|src)="([^"]+)".*?alt="([^"]+)"'
        items = re.findall(pattern, sFragment)

        seen_links = set()
        for sLink, sThumb, sName in items:
            sName = unescape(sName).strip()
            sSeriesLink = sLink.split('/staffel-')[0]
            if sSeriesLink in seen_links: continue
            seen_links.add(sSeriesLink)
            if 'data:image/gif' in sThumb: continue

            oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
            oGuiElement.setMediaType('tvshow')   # wie die uebrigen Serienlisten (Nachpruefung 29.09.2026)
            if sThumb.startswith('/'): sThumb = URL_MAIN + sThumb
            oGuiElement.setThumbnail(sThumb)

            p = ParameterHandler()
            p.setParam('sUrl', URL_MAIN + sSeriesLink)
            p.setParam('sName', sName)
            p.setParam('sThumbnail', sThumb)
            oGui.addFolder(oGuiElement, p)

    oGui.setEndOfDirectory()

def showMeistgesehen():
    """Zeigt 'Meistgesehen gerade' von der Beliebte-Serien-Seite."""
    oGui = cGui()
    sHtmlContent = cRequestHandler(URL_POPULAR, caching=True).request()
    if not sHtmlContent: return
    sHtmlContent = re.sub(r'\s+', ' ', sHtmlContent)

    # Alle H2/H3-Überschriften durchsuchen - flexibel nach "meistgesehen" matchen
    titles = re.findall(r'<(?:h2|h3)[^>]*>(.*?)</(?:h2|h3)>', sHtmlContent)
    sTargetTitle = None
    for sTitle in titles:
        sClean = re.sub(r'<[^>]*>', '', sTitle).strip()
        sClean = ''.join(c for c in sClean if ord(c) < 128).strip()
        if 'meistgesehen' in sClean.lower():
            sTargetTitle = sClean
            break

    if not sTargetTitle:
        oGui.showInfo()
        return

    # Sektion extrahieren (gleiche Logik wie showSectionContent)
    find_section = r'<(?:h2|h3)[^>]*>[^<]*' + re.escape(sTargetTitle) + r'.*?</(?:h2|h3)>(.*?)(?=<h2|<h3|$)'
    match = re.search(find_section, sHtmlContent)

    if match:
        sFragment = match.group(1)
        pattern = r'href="(/serie/[^"]+)".*?<img.*?(?:data-src|src)="([^"]+)".*?alt="([^"]+)"'
        items = re.findall(pattern, sFragment)

        seen_links = set()
        for sLink, sThumb, sName in items:
            sName = unescape(sName).strip()
            sSeriesLink = sLink.split('/staffel-')[0]
            if sSeriesLink in seen_links: continue
            seen_links.add(sSeriesLink)
            if 'data:image/gif' in sThumb: continue

            oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
            oGuiElement.setMediaType('tvshow')   # wie die uebrigen Serienlisten (Nachpruefung 29.09.2026)
            if sThumb.startswith('/'): sThumb = URL_MAIN + sThumb
            oGuiElement.setThumbnail(sThumb)

            p = ParameterHandler()
            p.setParam('sUrl', URL_MAIN + sSeriesLink)
            p.setParam('sName', sName)
            p.setParam('sThumbnail', sThumb)
            oGui.addFolder(oGuiElement, p)

    oGui.setEndOfDirectory()

def showNeusteEpisoden():
    """Neuste Episoden von der dedizierten /neue-episoden Seite (Tabelle, ~170 Einträge statt ~40 auf der Homepage)."""
    oGui = cGui()
    sHtmlContent = cRequestHandler(URL_NEW_EPISODES, caching=True).request()
    if not sHtmlContent:
        oGui.showInfo()
        return

    sHtmlContent = re.sub(r'\s+', ' ', sHtmlContent)

    # Eine Tabellenzeile pro Episode; (?!</tr>)-Tempered-Gap hält jede Zeile für sich (kein Überlauf).
    # Badges/Flag werden PRO Zeile einzeln gesucht: ganz frische Uploads haben Staffel/Folge/Sprache
    # teils noch nicht gesetzt — solche Zeilen erscheinen ohne die fehlenden Teile statt zu verschwinden
    pattern = r'<tr[^>]*>(?:(?!</tr>).)*?href="([^"]+)"[^>]*>([^<]+)</a>((?:(?!</tr>).)*?)</tr>'
    results = re.findall(pattern, sHtmlContent)
    if not results:
        oGui.showInfo()
        return

    for sLink, sTitle, sRest in results:
        sTitle = unescape(sTitle).strip()
        aBadges = [b.strip() for b in re.findall(r'bg-secondary">([^<]+)</span>', sRest)]
        sSE = ''.join(aBadges[:2])
        mLang = re.search(r'icon-flag-([\w-]+)', sRest)
        # exaktes Mapping, kein Substring-Check ('german' steckt auch in 'english-german' = Ger-Sub)
        sLangLabel = {'german': 'DE', 'english': 'EN', 'english-german': 'EN-DE'}.get(mLang.group(1), mLang.group(1).upper()) if mLang else ''
        sDisplay = sTitle + (' (%s)' % sSE if sSE else '') + (' [%s]' % sLangLabel if sLangLabel else '')

        # Auf Serien-Ebene kürzen → Klick führt wie bei AniWorld zur Staffel-Auswahl
        sCleanUrl = re.sub(r'/(?:staffel-\d+/episode|filme/film)-\d+$', '', sLink)
        sFullUrl = URL_MAIN + sCleanUrl if sCleanUrl.startswith('/') else sCleanUrl

        oGuiElement = cGuiElement(sDisplay, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')   # Serieneintrag mit Folgenkennung; wie die uebrigen Serienlisten (Nachpruefung 29.09.2026)
        oGuiElement.setThumbnail("DefaultVideo.png")

        p = ParameterHandler()
        p.setParam('sUrl', sFullUrl)
        p.setParam('sName', sTitle)
        oGui.addFolder(oGuiElement, p)

    oGui.setView('tvshows')
    oGui.setEndOfDirectory()

def showTrends():
    """Submenü 'Trends' - Tab-Sektionen, Discover-Blöcke + Beliebte Serien."""
    oGui = cGui()

    # Tab-Sektionen (section-1 bis section-3) auf der Startseite
    for sLabel, sSection in [
        ('Gerade im Trend',        'tab:section-1'),
        ('W\u00f6chentliche Favoriten', 'tab:section-2'),
        ('Meistbewertete Serien',  'tab:section-3'),
    ]:
        params = ParameterHandler()
        params.setParam('sSection', sSection)
        oGui.addFolder(cGuiElement(sLabel, SITE_IDENTIFIER, 'showTrendSection'), params)

    # Discover-Blöcke (h4-Überschriften in #discover-blocks)
    for sLabel, sSection in [
        ('Geheimtipps',       'discover:Geheimtipps'),
        ('Suchtgefahr',       'discover:Suchtgefahr'),
        ('Die Beliebtesten',  'discover:Die Beliebtesten'),
        ('Aktuell beliebt',   'discover:Aktuell beliebt'),
    ]:
        params = ParameterHandler()
        params.setParam('sSection', sSection)
        oGui.addFolder(cGuiElement(sLabel, SITE_IDENTIFIER, 'showTrendSection'), params)

    # Meistgesehen gerade (von der Beliebte-Serien-Seite)
    params = ParameterHandler()
    oGui.addFolder(cGuiElement(cConfig().getLocalizedString(30560), SITE_IDENTIFIER, 'showMeistgesehen'), params)

    # Beliebte Genres als Eintrag im Trends-Menü
    params = ParameterHandler()
    params.setParam('sUrl', URL_POPULAR)
    oGui.addFolder(cGuiElement(cConfig().getLocalizedString(30817), SITE_IDENTIFIER, 'showBeliebte'), params)

    oGui.setEndOfDirectory()


def showTrendSection():
    """Zeigt eine Trend-Sektion von der Startseite.
    sSection Format:
      'tab:section-1'        -> Tab-Pane mit id="section-1" (Gerade im Trend etc.)
      'discover:Suchtgefahr' -> Discover-Block mit h4 Überschrift
    """
    params   = ParameterHandler()
    sSection = params.getValue('sSection')
    iPage    = int(params.getValue('iPage') or 1)
    oGui     = cGui()

    sHtmlContent = cRequestHandler(URL_MAIN, caching=True).request()
    if not sHtmlContent:
        oGui.showInfo()
        return

    sHtml = re.sub(r'\s+', ' ', sHtmlContent)
    clean = []
    seen  = set()

    if sSection.startswith('tab:'):
        sId = sSection[4:]
        match = re.search(r'id="' + re.escape(sId) + r'"[^>]*>(.*?)(?=id="section-\d+"|</div> </div> </section>|$)', sHtml, re.DOTALL)
        if match:
            fragment = match.group(1)
            items = re.findall(
                r'href="(/serie/[^"]+)"[^>]*>.*?<h3[^>]*title="([^"]+)"',
                fragment, re.DOTALL
            )
            for sLink, sTitle in items:
                sLink = re.sub(r'/staffel-\d+.*$', '', sLink)
                if sLink in seen: continue
                seen.add(sLink)
                clean.append((_abs_url(sLink), unescape(sTitle).strip(), ''))

    elif sSection.startswith('discover:'):
        sHeading = sSection[9:]
        escaped  = re.escape(sHeading)
        match = re.search(
            r'<h4[^>]*>\s*' + escaped + r'\s*</h4>.*?<ul[^>]*class="[^"]*discover-list[^"]*"[^>]*>(.*?)</ul>',
            sHtml, re.DOTALL
        )
        if match:
            fragment = match.group(1)
            items = re.findall(
                r'href="(/serie/[^"]+)"[^>]*>.*?<span[^>]*>([^<]+)</span>',
                fragment, re.DOTALL
            )
            for sLink, sTitle in items:
                if sLink in seen: continue
                seen.add(sLink)
                clean.append((_abs_url(sLink), unescape(sTitle).strip(), ''))

    if not clean:
        oGui.showInfo()
        return

    # Pagination
    iStart     = (iPage - 1) * PAGE_SIZE
    iEnd       = iStart + PAGE_SIZE
    page_items = clean[iStart:iEnd]
    total      = len(page_items)

    for sFullUrl, sTitle, sThumb in page_items:
        # Poster aus HTML nicht verfügbar — Fallback per Detail-Request
        if not sThumb or 'data:image' in sThumb:
            sThumb = _fetchPosterFallback(sFullUrl)

        oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        if sThumb:
            oGuiElement.setThumbnail(sThumb)
        p = ParameterHandler()
        p.setParam('sUrl',       sFullUrl)
        p.setParam('sName',      sTitle)
        p.setParam('sThumbnail', sThumb)
        oGui.addFolder(oGuiElement, p, True, total)

    if iEnd < len(clean):
        p = ParameterHandler()
        p.setParam('sSection', sSection)
        p.setParam('iPage',    str(iPage + 1))
        oGui.addNextPage(SITE_IDENTIFIER, 'showTrendSection', p, _pageInfo(iPage, len(clean)))

    oGui.setView('tvshows')
    oGui.setEndOfDirectory()


def showCollectionsMenu():
    """Submen\u00fc Sammlungen — sortiert nach verschiedenen Kriterien."""
    oGui = cGui()

    for sLabel, sSort in [
        (cConfig().getLocalizedString(30562), 'content_updated_at'),
        ('Meiste Eintr\u00e4ge',           'items'),
        ('Meiste Follower',                'followers'),
        ('A-Z',                            'name'),
    ]:
        params = ParameterHandler()
        params.setParam('sUrl', URL_COLLECTIONS + '?sort=' + sSort)
        oGui.addFolder(cGuiElement(sLabel, SITE_IDENTIFIER, 'showCollections'), params)
    oGui.setEndOfDirectory()


def showCollections():
    """Zeigt alle Sammlungen von /sammlungen mit Cover, Titel und Info."""
    params = ParameterHandler()
    sUrl   = params.getValue('sUrl') or URL_COLLECTIONS
    oGui   = cGui()

    sHtmlContent = cRequestHandler(_requestUrl(sUrl), caching=True).request()
    if not sHtmlContent:
        oGui.showInfo()
        return

    # Jede Sammlung: <a href="/sammlung/xxx" ... title="Titel"> + Cover + Info
    pattern = (
        r'<div[^>]*class="card-body[^"]*"[^>]*>.*?'
        r'<a[^>]+href="(/sammlung/[^"]+)"[^>]*title="([^"]+)".*?'
        r'<div[^>]*class="small"[^>]*>([^<]+)</div>'
    )
    aResult = re.findall(pattern, sHtmlContent, re.DOTALL)

    # Cover separat: data-src aus collection-item-cover
    covers = re.findall(
        r'collection-item-cover.*?data-src="([^"]*channel/desktop[^"]*format=jpg[^"]*)"',
        sHtmlContent, re.DOTALL
    )

    seen  = set()
    total = len(aResult)
    for idx, (sLink, sTitle, sInfo) in enumerate(aResult):
        if sLink in seen: continue
        seen.add(sLink)

        sTitle = unescape(sTitle).strip()
        sInfo  = unescape(sInfo).split('\u00b7')[0].strip()  # "102 Einträge · vor 8 Min" → "102 Einträge"
        sThumb = _abs_url(covers[idx]) if idx < len(covers) else ''

        oGuiElement = cGuiElement('%s (%s)' % (sTitle, sInfo), SITE_IDENTIFIER, 'showCollectionEntries')
        if sThumb:
            oGuiElement.setThumbnail(sThumb)

        p = ParameterHandler()
        p.setParam('sUrl',  _abs_url(sLink))
        p.setParam('sName', sTitle)
        oGui.addFolder(oGuiElement, p, True, total)

    # Serverseitige Pagination — folge rel="next"
    next_match = re.search(r'href="([^"]+)"[^>]*rel="next"', sHtmlContent)
    if next_match:
        # Aki: HTML-Entities decoden — Server schickt &amp; in URLs, sonst wuerde
        # die naechste Seite mit literalem '&amp;page=2' angefragt und Page 1 zurueckkommen
        next_url = unescape(next_match.group(1))
        p = ParameterHandler()
        p.setParam('sUrl', _abs_url(next_url))
        # Seitenlage: die Uebersicht nennt ihre Gesamtzahl ("756 Sammlungen"), und
        # solange es eine Folgeseite gibt, ist die aktuelle Seite voll — daraus die
        # Seitengroesse. Gemessen 04.09.2026: ceil(756/24) = 32 = das gemessene Ende,
        # die Zahl steht auf jeder Seite (auch auf Seite 20).
        oTotal = re.search(r'(\d{1,5})\s*Sammlungen', sHtmlContent)
        isMatch, sPage = cParser.parseSingleResult(sUrl, r'[?&]page=(\d+)')
        oGui.addNextPage(SITE_IDENTIFIER, 'showCollections', p,
                         cGui.pageInfo(sPage if isMatch else 1,
                                       -(-int(oTotal.group(1)) // len(seen)) if (oTotal and seen) else 0))

    oGui.setEndOfDirectory()


def showCollectionEntries():
    """Zeigt die Serien einer einzelnen Sammlung."""
    params = ParameterHandler()
    sUrl   = params.getValue('sUrl')
    sName  = params.getValue('sName') or ''
    oGui   = cGui()

    sHtmlContent = cRequestHandler(_requestUrl(sUrl), caching=True).request()
    if not sHtmlContent:
        oGui.showInfo()
        return

    # Titel + Links aus h6 Tags: <h6 ... title="Titel"><a href="/serie/xxx">
    items = re.findall(
        r'<h6[^>]*title="([^"]+)"[^>]*>\s*<a[^>]+href="(/serie/[^"]+)"',
        sHtmlContent
    )

    # Cover-Index: img src/data-src mit alt-Text als Key
    covers = re.findall(
        r'<img[^>]+(?:src|data-src)="([^"]*channel/desktop[^"]*format=jpg[^"]*)"[^>]*alt="([^"]+)"',
        sHtmlContent
    )
    cover_map = {}
    for sThumb, sAlt in covers:
        cover_map[unescape(sAlt).strip()] = _abs_url(sThumb)

    seen  = set()
    clean = []
    for sTitle, sLink in items:
        if sLink in seen: continue
        seen.add(sLink)
        sTitle = unescape(sTitle).strip()
        sThumb = cover_map.get(sTitle, '')
        clean.append((_abs_url(sLink), sTitle, sThumb))

    if not clean:
        oGui.showInfo()
        return

    total = len(clean)
    for sFullUrl, sTitle, sThumb in clean:
        oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        if sThumb:
            oGuiElement.setThumbnail(sThumb)

        p = ParameterHandler()
        p.setParam('sUrl',       sFullUrl)
        p.setParam('sName',      sTitle)
        p.setParam('sThumbnail', sThumb)
        oGui.addFolder(oGuiElement, p, True, total)

    # Serverseitige Pagination falls vorhanden (große Sammlungen)
    next_match = re.search(r'href="([^"]+)"[^>]*rel="next"', sHtmlContent)

    if next_match:
        next_url = next_match.group(1)
        p = ParameterHandler()
        p.setParam('sUrl',  _abs_url(next_url))
        p.setParam('sName', sName)
        # Seitenlage: die Sammlungsseite nennt ihre Gesamtzahl ("1081 Einträge"),
        # und solange es eine Folgeseite gibt, ist die aktuelle Seite voll — daraus
        # ergibt sich die Seitengroesse ohne feste Zahl im Code (gemessen 04.09.2026
        # an 14 Sammlungen, ceil(Einträge/24) traf jedes gemessene Listenende).
        oTotal = re.search(r'(\d{1,5})\s*Einträge', sHtmlContent)
        isMatch, sPage = cParser.parseSingleResult(sUrl, r'[?&]page=(\d+)')
        oGui.addNextPage(SITE_IDENTIFIER, 'showCollectionEntries', p,
                         cGui.pageInfo(sPage if isMatch else 1,
                                       -(-int(oTotal.group(1)) // len(clean)) if oTotal else 0))

    oGui.setView('tvshows')
    oGui.setEndOfDirectory()


def showAZMenu():
    """Submenü A-Z mit Alle Serien und alphabetischer Sortierung."""
    oGui = cGui()
    # Alle Serien
    params = ParameterHandler()
    params.setParam('sUrl', URL_SERIES)
    oGui.addFolder(cGuiElement(cConfig().getLocalizedString(30518), SITE_IDENTIFIER, 'showAllSeries'), params)
    # A-Z
    params = ParameterHandler()
    params.setParam('sUrl', URL_SERIES + "?by=alpha")
    oGui.addFolder(cGuiElement(cConfig().getLocalizedString(30814), SITE_IDENTIFIER, 'showGenericMenu'), params)
    oGui.setEndOfDirectory()
    
def showNewSeries():
    """
    Zeigt die 'Neu auf S.to' Kacheln von der Homepage.
    Sektion: class="new-shows-slider"
    Bilder nutzen <img src="..."> (kein data-src!)
    """
    oGui = cGui()

    sHtmlContent = cRequestHandler(URL_MAIN, caching=True).request()
    if not sHtmlContent:
        oGui.showInfo()
        return

    sHtml = re.sub(r'\s+', ' ', sHtmlContent)

    # Sektion isolieren
    match_section = re.search(r'class="[^"]*new-shows-slider[^"]*"(.*?)</section>', sHtml, re.DOTALL)
    if not match_section:
        logger.error('[%s] showNewSeries: new-shows-slider nicht gefunden' % SITE_IDENTIFIER)
        oGui.showInfo()
        return

    fragment = match_section.group(1)

    # Jede Karte einzeln parsen - verhindert Offset-Bug durch doppelte hrefs
    cards = re.findall(r'<article[^>]*class="[^"]*continue-card[^"]*"[^>]*>(.*?)</article>', fragment, re.DOTALL)

    seen  = set()
    clean = []
    for card in cards:
        link_match  = re.search(r'href="(/serie/[^"]+)"', card)
        img_match   = re.search(r'<img\s+src="([^"]+)"[^>]*alt="([^"]+)"', card)
        if not link_match or not img_match: continue
        sLink  = link_match.group(1)
        sThumb = img_match.group(1)
        sTitle = img_match.group(2)
        if sLink in seen: continue
        seen.add(sLink)
        if 'data:image' in sThumb: continue
        clean.append((sLink, sThumb, unescape(sTitle).strip()))

    if not clean:
        logger.error('[%s] showNewSeries: Keine Kacheln gefunden' % SITE_IDENTIFIER)
        oGui.showInfo()
        return

    total = len(clean)
    for sLink, sThumb, sTitle in clean:
        sFullUrl   = URL_MAIN + sLink  if sLink.startswith('/') else sLink
        sFullThumb = URL_MAIN + sThumb if sThumb.startswith('/') else sThumb
        sFullThumb = sFullThumb.replace('format=webp', 'format=jpg').replace('format=avif', 'format=jpg')

        oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        oGuiElement.setThumbnail(sFullThumb)

        p = ParameterHandler()
        p.setParam('sUrl',       sFullUrl)
        p.setParam('sName',      sTitle)
        p.setParam('sThumbnail', sFullThumb)
        oGui.addFolder(oGuiElement, p, True, total)

    oGui.setView('tvshows')
    oGui.setEndOfDirectory()


def showHomeSection():
    params = ParameterHandler()
    section_id = params.getValue('section_id')
    oGui = cGui()
    
    sHtmlContent = cRequestHandler(URL_MAIN, caching=True).request()
    if sHtmlContent:
        sHtmlContent = re.sub(r'\s+', ' ', sHtmlContent)
        # Search from ID to next section or end of tab-content
        section_pattern = f'id="{section_id}".*?(?:id="section-|</div> </div> </section>)'
        section_match = re.search(section_pattern, sHtmlContent)
        
        if section_match:
            fragment = section_match.group(0)
            if 'latest-episode-row' in fragment:
                renderEpisodes(oGui, fragment)
            else:
                renderCards(oGui, fragment)

    oGui.setView('tvshows')
    oGui.setEndOfDirectory()

def renderEpisodes(oGui, sHtml):
    # Jede Zeile ist EIN <a class="latest-episode-row">…</a>; (?!</a>)-Tempered-Gap hält die Zeilen getrennt.
    # ep-Felder werden PRO Zeile einzeln gesucht: ganz frische Uploads haben Staffel/Folge/Sprache teils noch
    # nicht gesetzt — das alte ungebremste .*?-Pattern konnte dabei in die Folgezeile überlaufen
    pattern = r'<a[^>]*class="latest-episode-row[^"]*"[^>]*href="([^"]+)"((?:(?!</a>).)*?)</a>'
    
    results = re.findall(pattern, sHtml, re.DOTALL)
    
    for sLink, sRow in results:
        if sLink.startswith('#'): continue
        
        mTitle = re.search(r'class="ep-title" title="([^"]+)"', sRow)
        if not mTitle: continue
        sTitle = unescape(mTitle.group(1)).strip()
        mSeason = re.search(r'class="ep-season">([^<]+)', sRow)
        mEpisode = re.search(r'class="ep-episode">([^<]+)', sRow)
        sSE = (mSeason.group(1).strip() if mSeason else '') + (mEpisode.group(1).strip() if mEpisode else '')
        mLang = re.search(r'icon-flag-([\w-]+)', sRow)
        # Sprach-Label: exaktes Mapping, kein Substring-Check ('german' steckt auch in 'english-german' = Ger-Sub)
        sLangLabel = {'german': 'DE', 'english': 'EN', 'english-german': 'EN-DE'}.get(mLang.group(1), mLang.group(1).upper()) if mLang else ''
        
        # fehlende Teile einfach weglassen statt die Zeile zu verwerfen
        sDisplay = sTitle + (' (%s)' % sSE if sSE else '') + (' [%s]' % sLangLabel if sLangLabel else '')
        
        # Auf Serien-Ebene kürzen (Filme-Pseudostaffel mit abgedeckt) → Klick führt wie bei AniWorld zur Staffel-Auswahl
        sCleanUrl = re.sub(r'/(?:staffel-\d+/episode|filme/film)-\d+$', '', sLink)
        sFullUrl = URL_MAIN + sCleanUrl if sCleanUrl.startswith('/') else sCleanUrl
        
        oGuiElement = cGuiElement(sDisplay, SITE_IDENTIFIER, 'showSeasons')
        # Aus der Episodenzeile wird kein Cover gelesen — Platzhalter
        oGuiElement.setThumbnail("DefaultVideo.png") 
        
        p = ParameterHandler()
        p.setParam('sUrl', sFullUrl)
        p.setParam('sName', sTitle)
        
        oGui.addFolder(oGuiElement, p)

def renderCards(oGui, sHtml):
    # Dieses Regex deckt die Card-Struktur ab:
    # 1. Das Bild (data-src)
    # 2. Den Link zur Serie (href)
    # 3. Den Titel (im h3-Tag oder title-Attribut)
    pattern = r'<img\s+data-src="([^"]+)"[^>]*>.*?<a\s+href="([^"]+)">\s*<h3\s+title="([^"]+)"'
    
    # re.DOTALL needed due to line breaks between image and link
    results = re.findall(pattern, sHtml, re.DOTALL)
    
    for sThumb, sLink, sTitle in results:
        sFullUrl = URL_MAIN + sLink if sLink.startswith('/') else sLink
        sTitle = unescape(sTitle).strip()
        
        oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showSeasons')
        
        oGuiElement.setThumbnail(sThumb)
        
        p = ParameterHandler()
        p.setParam('sUrl', sFullUrl)
        p.setParam('sName', sTitle)
        p.setParam('sThumbnail', sThumb)
        oGui.addFolder(oGuiElement, p)
    
def showBeliebte(sGui=False):
    oGui = sGui if sGui else cGui()
    sHtmlContent = cRequestHandler(URL_POPULAR, caching=True).request()
    
    if not sHtmlContent: return
    sHtmlContent = re.sub(r'\s+', ' ', sHtmlContent)

    # Find all H2 and H3 headings
    # Diese markieren den Start jeder Sektion. Ausgenommen die Ueberschriften
    # der CTA-Banner (popular-cta-*): das sind Hinweiskacheln der Seite ohne
    # Serien dahinter ("Findest du nicht, wonach du suchst?") — als Sektion
    # gelistet ergaeben sie einen leeren Menuepunkt. Gefiltert wird ueber die
    # Klasse statt ueber den Text, damit eine Textaenderung der Seite den
    # Filter nicht aushebelt.
    titles = re.findall(r'<(?:h2|h3)(?![^>]*popular-cta)[^>]*>(.*?)</(?:h2|h3)>', sHtmlContent)

    for sTitle in titles:
        sCleanTitle = re.sub(r'<[^>]*>', '', sTitle).strip()
        # Strip special chars/emojis for submenu matching
        sCleanTitle = ''.join(c for c in sCleanTitle if ord(c) < 128).strip()
        
        if not sCleanTitle or any(x in sCleanTitle for x in ['Kategorien', 'durchsuchen', 'Entdecken']):
            continue
        # "Neuste Staffel diese Woche" ist jetzt unter Neues
        if 'staffel' in sCleanTitle.lower() and 'woche' in sCleanTitle.lower():
            continue
        # "Meistgesehen gerade" ist jetzt unter Trends
        if 'meistgesehen' in sCleanTitle.lower():
            continue

        oGuiElement = cGuiElement(sCleanTitle, SITE_IDENTIFIER, 'showSectionContent')
        p = ParameterHandler()
        p.setParam('sSectionTitle', sCleanTitle)
        oGui.addFolder(oGuiElement, p)

    oGui.setEndOfDirectory()

def showSectionContent():
    params = ParameterHandler()
    sTargetTitle = params.getValue('sSectionTitle')
    oGui = cGui()
    
    sHtmlContent = cRequestHandler(URL_POPULAR, caching=True).request()
    if not sHtmlContent: return
    sHtmlContent = re.sub(r'\s+', ' ', sHtmlContent)

    find_section = r'<(?:h2|h3)[^>]*>[^<]*' + re.escape(sTargetTitle) + r'.*?</(?:h2|h3)>(.*?)(?=<h2|<h3|$)'
    match = re.search(find_section, sHtmlContent)

    if match:
        sFragment = match.group(1)
        pattern = r'href="(/serie/[^"]+)".*?<img.*?(?:data-src|src)="([^"]+)".*?alt="([^"]+)"'
        items = re.findall(pattern, sFragment)

        # Um Dubletten zu vermeiden (wegen <picture> Tags)
        seen_links = set()

        for sLink, sThumb, sName in items:
            sName = unescape(sName).strip()
            
            # 2. Staffel-Zusatz im Link entfernen
            sSeriesLink = sLink.split('/staffel-')[0]
            
            if sSeriesLink in seen_links: continue
            seen_links.add(sSeriesLink)

            # Platzhalter-GIFs ignorieren
            if 'data:image/gif' in sThumb and 'data-src="' in sFragment:
                continue

            oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
            oGuiElement.setMediaType('tvshow')   # wie die uebrigen Serienlisten (Nachpruefung 29.09.2026: Beliebte Genres, 96 Eintraege)
            if sThumb.startswith('/'): sThumb = URL_MAIN + sThumb
            oGuiElement.setThumbnail(sThumb)
            
            p = ParameterHandler()
            p.setParam('sUrl', URL_MAIN + sSeriesLink)
            p.setParam('sName', sName)
            p.setParam('sThumbnail', sThumb)
            oGui.addFolder(oGuiElement, p)

    oGui.setEndOfDirectory()

def showSeasons():
    params = ParameterHandler()
    sUrl = params.getValue('sUrl')
    sName = params.getValue('sName')
    sThumbnail = params.getValue('sThumbnail')
    sTmdbID = params.getValue('tmdbID') or ''
    
    oGui = cGui()
    sHtmlContent = cRequestHandler(_requestUrl(sUrl), caching=True).request()
    if not sHtmlContent: return

    # 1. Serienname fixen (falls von Favoriten/Suche kommend)
    title_match = re.search(r'<title>(.*?)\s+Staffel', sHtmlContent)
    if title_match:
        sName = unescape(title_match.group(1)).strip()   # <title> traegt Entitaeten (&#039;)
    elif not sName or sName == 'False':
        sName = "Serie"

    # 1b. Aki: Year aus Detail-Seite extrahieren (Start-Jahr der Serie)
    sYear = ''
    year_match = re.search(r'href="/jahr/(\d{4})"', sHtmlContent)
    if year_match:
        sYear = year_match.group(1)

    # 2. Description (extract from span "description-text")
    sDesc = ''
    match_span = re.search(r'<span class="description-text">(.*?)</span>', sHtmlContent, re.DOTALL)
    if match_span:
        sDesc = unescape(match_span.group(1)).strip()
        sDesc = re.sub(r'<[^>]*>', '', sDesc)
    
    # Fallback auf Meta-Description, falls der span leer war
    if not sDesc:
        match_desc = re.search(r'name="description"\s+content="([^"]+)"', sHtmlContent)
        if match_desc:
            sDesc = unescape(match_desc.group(1)).strip()

    # 3. Poster extrahieren
    if not sThumbnail: sThumbnail = extractPoster(sHtmlContent)

    # 4. Staffeln finden
    # Sucht nach Links wie /staffel-1, /staffel-2 etc.
    pattern = r'href="([^"]+/staffel-(\d+))"'
    results = re.findall(pattern, sHtmlContent)

    seasons_map = {}
    for sSeasonUrl, sSeasonNum in results:
        if sSeasonNum not in seasons_map:
            seasons_map[sSeasonNum] = sSeasonUrl

    # Sortieren nach Zahl (damit 0 vor 1 kommt, und 10 nach 2)
    sorted_keys = sorted(seasons_map.keys(), key=lambda x: int(x))

    for sSeasonNum in sorted_keys:
        sSeasonUrl = seasons_map[sSeasonNum]
        # Aki: isMovie-Erkennung analog aniworld — Staffel 0 = Filme/Specials
        isMovie = (sSeasonNum == '0')

        # Fix for movies instead of Season 0 (renamed specials)
        if isMovie:
            sDisplay = cConfig().getLocalizedString(30559)
        else:
            sDisplay = "%s %s" % (cConfig().getLocalizedString(30512), sSeasonNum)

        oGuiElement = cGuiElement(sDisplay, SITE_IDENTIFIER, 'showEpisodes')
        oGuiElement.setThumbnail(sThumbnail)
        # Auch der Filme-Ordner ist eine Staffel der Serie (Staffel 0), kein Film: Serienname und
        # Staffelnummer fuer InfoTag, Info-Kontextmenue und Weitere Quellen; tmdb_id nur fuer echte Staffeln
        oGuiElement.setMediaType('season')
        oGuiElement.setTVShowTitle(sName)
        oGuiElement.setSeason(int(sSeasonNum))
        if not isMovie and sTmdbID:
            oGuiElement.addItemValue('tmdb_id', sTmdbID)
        if sYear:
            oGuiElement.addItemValue('year', sYear)
        
        if sDesc:
            oGuiElement.setDescription(sDesc)

        p = ParameterHandler()
        p.setParam('sUrl', URL_MAIN + sSeasonUrl if sSeasonUrl.startswith('/') else sSeasonUrl)
        p.setParam('sName', sName)
        p.setParam('sThumbnail', sThumbnail)
        p.setParam('sDescription', sDesc) 
        # Aki: Year an showEpisodes weitergeben
        if sYear:
            p.setParam('sYear', sYear)
        
        oGui.addFolder(oGuiElement, p)

    oGui.setView('seasons')
    oGui.setEndOfDirectory()
    
def showEpisodes():
    params = ParameterHandler()
    sUrl = params.getValue('sUrl')
    sTVShowTitle = params.getValue('TVShowTitle')
    sThumbnail = params.getValue('sThumbnail')
    sDesc = params.getValue('sDescription')
    # Aki: isMovieList-Erkennung analog aniworld — Listing aus Staffel-0 = Filme
    isMovieList = sUrl.endswith('/staffel-0') or sUrl.endswith('/staffel-0/')

    oRequest = cRequestHandler(_requestUrl(sUrl), caching=False)
    sHtmlContent = oRequest.request()
    if not sHtmlContent: return

    # 1. Serienname & Beschreibung
    if not sTVShowTitle or sTVShowTitle == 'False':
        title_match = re.search(r'<title>(.*?)\s+Staffel', sHtmlContent)
        if title_match: sTVShowTitle = unescape(title_match.group(1)).strip()   # <title> traegt Entitaeten (&#039;)
        
    if not sDesc:
       # 1. Plot/Beschreibung extrahieren
       match_plot = re.search(r'<span class="description-text">(.*?)</span>', sHtmlContent, re.DOTALL)
       if match_plot:
          sDesc = unescape(match_plot.group(1)).strip()

    if not sThumbnail: sThumbnail = extractPoster(sHtmlContent)
		
    # 2. Episoden direkt aus den Tabellenzeilen parsen
    # Jede <tr class="episode-row"> enthält: Nummer, Titel, Link (onclick) und Hoster-Icons
    # NUR Zeilen mit watch-link Icons anzeigen = nur bereits verfügbare Episoden
    sHtmlFlat = re.sub(r'\s+', ' ', sHtmlContent)
    # tr-Tag + Inhalt zusammen erfassen: onclick ist am tr-Tag selbst
    rows = re.findall(r'(<tr[^>]*class="episode-row[^"]*"[^>]*>)(.*?)</tr>', sHtmlFlat, re.DOTALL)

    unique_nav = []
    titles_dict = {}
    for tr_tag, row_content in rows:
        # Nur Episoden mit tatsächlichen Streams anzeigen
        if 'watch-link' not in row_content:
            continue
        nr_match = re.search(r'episode-number-cell">\s*(\d+)\s*<', row_content)
        if not nr_match:
            continue
        ep_nr = nr_match.group(1)
        # Link aus onclick am tr-Tag
        link_match = re.search(r"onclick=\"window\.location='([^']+)'\"", tr_tag)
        if not link_match:
            continue
        ep_url = link_match.group(1)
        # Deutschen Titel bevorzugen, englisch als Fallback
        title_match = re.search(r'episode-title-ger"[^>]*title="([^"]+)"', row_content)
        if not title_match:
            title_match = re.search(r'episode-title-eng"[^>]*title="([^"]+)"', row_content)
        ep_title = unescape(title_match.group(1)).strip() if title_match else ""
        # Aki: [Movie]-Marker von serienstream entfernen (kein Filmtitel-Bestandteil, nur Display-Hint)
        ep_title = re.sub(r'\s*\[Movie\]\s*$', '', ep_title).strip()
        titles_dict[ep_nr] = ep_title
        unique_nav.append((ep_url, ep_nr))

    oGui = cGui()
    total = len(unique_nav)
    if total == 0:
        # Eine Staffelseite kann Zeilen ganz ohne watch-link fuehren (Episode
        # gelistet, aber noch kein Stream — belegt an den Specials von "Die
        # Besucher"). Der Filter oben sortiert die dann komplett aus; ohne
        # Hinweis saehe der Nutzer nur ein leeres Verzeichnis.
        oGui.showInfo()
        return
    
    for sUrl2, sEpNr in unique_nav:
        sEpName = titles_dict.get(sEpNr, "").strip()
        sEpName = unescape(sEpName)
        
        # Formatierung: "1 - Der Tote am See"
        sDisplayTitle = "%s %s" % (cConfig().getLocalizedString(30513), sEpNr)
        if sEpName:
            sDisplayTitle += " - %s" % sEpName
        
        oGuiElement = cGuiElement(sDisplayTitle, SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setMediaType('episode' if not isMovieList else 'movie')
        if isMovieList and sEpName:
            # Filmtitel ohne den "Folge N - "-Vorsatz des Labels (Trailer, TMDB-Info, Weitere Quellen).
            # Gemessen 04.09.2026 ueber 66 Filme aus 9 Serien: die Seite fuehrt konkrete Titel
            # ("Pokémon 1 – Der Film", "El Camino - Ein Breaking Bad Film"), keine generischen.
            oGuiElement.addItemValue('originaltitle', sEpName)
        
        if sThumbnail: oGuiElement.setThumbnail(sThumbnail)
        if sDesc: oGuiElement.setDescription(sDesc)
        
        if not isMovieList:
            # Episoden-Wiring nur fuer echte Episoden
            oGuiElement.setTVShowTitle(sTVShowTitle)
            # Staffel- und Folgennummer als Infolabel mitgeben. Kodi wertet beides
            # fuer Fortsetzen und Bibliothek aus, und externe Werkzeuge finden die
            # Folge nur darueber — die Beschriftung allein reicht ihnen nicht.
            # Die Staffel steckt in der URL des Listings (/staffel-N).
            mSeason = re.search(r'/staffel-(\d+)', sUrl)
            if mSeason:
                oGuiElement.setSeason(mSeason.group(1))
            oGuiElement.setEpisode(sEpNr)
        p = ParameterHandler()
        p.setParam('sUrl', URL_MAIN + sUrl2 if not sUrl2.startswith('http') else sUrl2)
        p.setParam('sThumbnail', sThumbnail)
        p.setParam('sDescription', sDesc)
        
        oGui.addFolder(oGuiElement, p, False, total)
        
    oGui.setView('episodes')
    oGui.setEndOfDirectory()


def showHosters():
    hosters = []
    sUrl = ParameterHandler().getValue('sUrl')
    sHtmlContent = cRequestHandler(_requestUrl(sUrl), caching=False).request()
    
    if not sHtmlContent:
        return []

    button_pattern = r'<button[^>]*class="[^"]*link-box[^"]*"[^>]*>'
    buttons = re.findall(button_pattern, sHtmlContent)

    for sButton in buttons:
        # Individual extraction: HTML order does not matter
        url_match = re.search(r'data-play-url="([^"]+)"', sButton)
        name_match = re.search(r'data-provider-name="([^"]+)"', sButton)
        lang_match = re.search(r'data-language-id="([^"]+)"', sButton)
        # Die Seite liefert die Beschriftung gleich mit — im selben button-Tag steht
        # data-language-label ("Deutsch", "Englisch", "Ger-Sub"). Die auszulesen ist
        # zuverlaessiger, als sie aus der Nummer zu raten: kommt eine neue Sprach-ID
        # dazu, stand hier vorher die nackte Zahl in der Liste.
        label_match = re.search(r'data-language-label="([^"]+)"', sButton)

        if url_match and name_match and lang_match:
            sHUrl = url_match.group(1)
            sName = name_match.group(1)
            sLang = lang_match.group(1)
            sSiteLabel = label_match.group(1).strip() if label_match else ''

            # --- Language filter logic ---
            if cConfig().isBlockedHoster(sName)[0]: continue
            
            sLanguage = cConfig().getSetting('prefLanguage')
            if sLanguage == '1' and sLang != '1': continue
            if sLanguage == '2' and sLang != '2': continue
            # Die Seite kennt genau drei Fassungen: 1 Deutsch, 2 Englisch und 3 Ger-Sub.
            # Ger-Sub heisst Originalton mit deutschen Untertiteln — welche Sprache der
            # Originalton hat, sagt das Label NICHT. Ueber 100 Serien nachgesehen: die
            # Ger-Sub-Fassungen sind ueberwiegend westliche Titel (US-Western, Doku,
            # skandinavisches Drama), ein japanisches Label gibt es auf der Seite gar
            # nicht. Ger-Sub darf deshalb NICHT als japanisch durchgehen.
            # Fuer die Einstellung Japanisch fehlte bisher jede Filterzeile, sie verhielt
            # sich wie "Alle". Richtig ist: es gibt hier nichts Japanisches — der Hinweis
            # kommt unten ueber 'if not hosters', genau wie bei AniWorld fuer Englisch.
            if sLanguage == '3': continue

            sLangLabel = LANG_LABELS.get(sSiteLabel, '(%s)' % sSiteLabel) if sSiteLabel \
                else ('(DE)' if sLang == '1' else '(EN)' if sLang == '2' else sLang)
            sQuality = '720'
            
            hoster = {
                'link': [sHUrl, sName], 
                'name': sName, 
                'displayedName': '%s [I]%s [%sp][/I]' % (sName, sLangLabel, sQuality), 
                'quality': sQuality, 
                'languageCode': sLangLabel
            }
            hosters.append(hoster)

    # Append function name for core callback
    if hosters:
        hosters.append('getHosterUrl')
    if not hosters:
        cGui().showLanguage()
    return hosters

def _isRedirectGate(sUrl):
    # Die Seite schickt sporadisch ein Captcha vor den Player: /r liefert dann KEINE
    # Weiterleitung, sondern eine kurze Seite, die dem Browser per postMessage ein
    # frisches Token schickt ("frameBridge"). Erkennbar daran, dass die Endadresse noch
    # auf der eigenen Domain steht statt beim Hoster.
    return bool(sUrl) and DOMAIN in sUrl


def _passRedirectGate(sPlayPath, sGateHtml=''):
    """
    Loest das Captcha-Gate vor dem Player und liefert die Hoster-Adresse.

    Ablauf wie im Browser: die Gate-Seite haelt ein frisches Token (`t`), die
    Episodenseite den CSRF-Token und den Turnstile-Sitekey. Beides zusammen mit dem
    geloesten Turnstile als POST an /r — die Antwort ist ein 302 auf den Hoster.
    Bei der harten Stufe der Seite (`turnstile_altcha`) kommt als viertes Feld
    die lokal gerechnete Altcha-Antwort dazu.

    Returns:
        str: die Hoster-Adresse oder ''
    """
    from resources.lib.captcha.captcha_helper import captcha_ready, solve_turnstile
    from resources.lib.tools import infoDialog

    # Erst fragen, ob geloest werden darf: ohne Schalter oder Schluessel waeren
    # der Abruf der Gate-Seite, der Abruf der Episodenseite und der Dialog
    # „Captcha wird geloest" umsonst (gleiche Reihenfolge wie im Hoster-Weg).
    if not captcha_ready():
        return ''

    sEntryUrl = ParameterHandler().getValue('entryUrl') or ParameterHandler().getValue('sUrl')
    if not sEntryUrl:
        logger.error('SerienStream: Captcha-Gate ohne Episodenadresse, kein Durchlauf moeglich')
        return ''

    if not sGateHtml:
        Request = cRequestHandler(URL_MAIN + sPlayPath, caching=False)
        Request.addHeaderEntry('Referer', sEntryUrl)
        sGateHtml = Request.request()

    isToken, sToken = cParser.parseSingleResult(sGateHtml, r'var t = "([^"]+)"')
    if not isToken:
        logger.error('SerienStream: Captcha-Gate ohne Token, Seitenaufbau geaendert?')
        return ''

    sPageHtml = cRequestHandler(_requestUrl(sEntryUrl), caching=False).request()
    isCsrf, sCsrf = cParser.parseSingleResult(sPageHtml, r'name="csrf-token" content="([^"]+)"')
    isKey, sSiteKey = cParser.parseSingleResult(sPageHtml, r'data-turnstile-sitekey="([^"]+)"')
    if not (isCsrf and isKey):
        logger.error('SerienStream: Captcha-Gate ohne CSRF-Token oder Sitekey')
        return ''

    # Die Seite stuft ihre Pruefung je Besucher: `turnstile` fuer normale
    # Anschluesse, `turnstile_altcha` fuer auffaellige (Rechenzentrum, VPN —
    # gemessen 10.09.2026: Jacks Anschluss turnstile, die Sandbox
    # turnstile_altcha). Bei der harten Stufe zeigt das Gate-Skript der Seite
    # neben dem Turnstile ein Altcha-Widget und schickt dessen Antwort als
    # viertes Feld `altcha` mit. Altcha ist Proof-of-Work und wird lokal
    # gerechnet, ohne Dienst und ohne Schluessel (resources/lib/captcha/
    # local_solver.py). Die Stufe steht im Log, damit ein Fehlschlag am
    # Geraet der Stufe zuzuordnen ist.
    isTier, sTier = cParser.parseSingleResult(sPageHtml, r'data-redirect-gate-tier="([^"]+)"')
    isAltchaUrl, sAltchaUrl = cParser.parseSingleResult(sPageHtml, r'data-altcha-challenge-url="([^"]+)"')
    sTier = sTier if isTier else 'unbekannt'
    logger.info('SerienStream: Captcha-Gate Stufe %s' % sTier)

    infoDialog(cConfig().getLocalizedString(30825), icon='INFO', time=10000)
    sCaptcha = solve_turnstile(sSiteKey, sEntryUrl)
    if not sCaptcha:
        logger.error('SerienStream: Captcha-Gate nicht geloest')
        infoDialog(cConfig().getLocalizedString(30826), icon='ERROR', time=10000)
        return ''

    aData = {'_token': sCsrf, 't': sToken, 'cf-turnstile-response': sCaptcha}
    if 'altcha' in sTier and isAltchaUrl:
        from resources.lib.captcha.local_solver import solve_altcha
        # Die Seite nennt die Challenge-Adresse absolut (gemessen 20.09.2026). Kaeme
        # sie relativ (/api/...), wuerfe urllib beim Abruf einen ValueError — NACH dem
        # bezahlten Turnstile, als Skriptfehler statt ueber den Weg ohne das Feld.
        # urljoin laesst absolute Adressen unveraendert.
        sAltcha = solve_altcha(urljoin(URL_MAIN + '/', sAltchaUrl), sEntryUrl)
        if sAltcha:
            aData['altcha'] = sAltcha
        else:
            # Ohne das Feld weiter: ob die Seite es verlangt, entscheidet sie
            # am POST — dann kommt unten die gewohnte Meldung, und im Log steht,
            # dass Altcha der Grund war.
            logger.error('SerienStream: Altcha nicht geloest, POST ohne das Feld')

    # Die Antwort auf den POST ist NUR der Location-Header, die Zielseite wird hier
    # bewusst nicht geladen (wie beim DoodStream-Weg) — das macht ResolveURL.
    Request = cRequestHandler(URL_MAIN + '/r', caching=False, method='POST', data=aData)
    Request.addHeaderEntry('Referer', sEntryUrl)
    Request.addHeaderEntry('Origin', URL_MAIN)
    Request.addHeaderEntry('Upgrade-Insecure-Requests', '1')
    sUrl = Request.getRedirectUrl()
    if _isRedirectGate(sUrl):
        logger.error('SerienStream: Captcha-Gate hat das Token nicht angenommen')
        infoDialog(cConfig().getLocalizedString(30826), icon='ERROR', time=10000)
        return ''
    return sUrl


def getHosterUrl(hUrl):
    if type(hUrl) == str: hUrl = ast.literal_eval(hUrl)

    # DoodStream: hengt hinter Cloudflare.
    # Embed-Seite selbst zu laden triggert den CF-Block ("CLOUDFLARE-SCHUTZ AKTIV").
    # Wir reichen daher nur das Redirect-Ziel an ResolveURL weiter (wie einschalten),
    # das die Seite selbst aufloest — byparr wird dafuer nicht mehr benoetigt.
    if 'dood' in hUrl[1].lower():
        Request = cRequestHandler(URL_MAIN + hUrl[0], caching=False)
        Request.addHeaderEntry('Referer', ParameterHandler().getValue('entryUrl'))
        Request.addHeaderEntry('Upgrade-Insecure-Requests', '1')
        sUrl = Request.getRedirectUrl()
        if _isRedirectGate(sUrl):
            sUrl = _passRedirectGate(hUrl[0])
        return [{'streamUrl': sUrl, 'resolved': False}]

    Request = cRequestHandler(URL_MAIN + hUrl[0], caching=False)
    Request.addHeaderEntry('Referer', ParameterHandler().getValue('entryUrl'))
    Request.addHeaderEntry('Upgrade-Insecure-Requests', '1')
    sHtmlContent = Request.request()
    sUrl = Request.getRealUrl()
    if not sUrl:
        # Abruf der Weiterleitung gescheitert (Timeout, Fehler — der requestHandler
        # hat schon gemeldet). Sonst prueft der VOE-Zweig unten eine LEERE Adresse
        # und baut aus ''.replace('', 'voe.sx') die Phantasie-Adresse 'voe.sx'; der
        # Nutzer sah dann noch „Kein unterstuetzter Hoster" obendrauf (Jacks Log
        # 10.09.2026 ueber eine langsame VPN-Route nach Hongkong).
        return [{'streamUrl': '', 'resolved': False}]

    if _isRedirectGate(sUrl):
        # Das Gate steht: die Endadresse ist noch unsere eigene Domain. Ohne den
        # Durchlauf unten hat der VOE-Zweig daraus frueher eine Phantasie-Adresse
        # gebaut (voe.sx/r?t=...), weil er die Domain blind ersetzt hat.
        sUrl = _passRedirectGate(hUrl[0], sHtmlContent)
        return [{'streamUrl': sUrl, 'resolved': False}]

    if 'voe' in hUrl[1].lower():
        isBlocked, sDomain = cConfig().isBlockedHoster(sUrl)
        if isBlocked:  # VOE pseudo domain not known in resolveUrl
            sUrl = sUrl.replace(sDomain, 'voe.sx')
            return [{'streamUrl': sUrl, 'resolved': False}]

    return [{'streamUrl': sUrl, 'resolved': False}]

def showSearch():
    win = xbmcgui.Window(10000)
    sSearchText = win.getProperty('xstream.serienstream.lastSearchText')
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30281))
        if not sSearchText: return
        win.setProperty('xstream.serienstream.lastSearchText', sSearchText)
    _search(False, sSearchText)
    cGui().setEndOfDirectory()

def _search(oGui, sSearchText):
    SSsearch(oGui, sSearchText)

def SSsearch(sGui=False, sSearchText=False, iPage=1):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    
    # Suchtext priorisieren: Erst aus dem Argument, dann aus den Params
    if not sSearchText:
        sSearchText = params.getValue('sSearchText')
    
    # If iPage comes as string from params (when browsing)
    if params.getValue('iPage'):
        iPage = params.getValue('iPage')

    if not sSearchText:
        return

    # Wir bauen die URL jetzt explizit so, wie s.to sie bei direkten Aufrufen erwartet
    # Wichtig: Seite als Zahl mitschicken
    sUrl = f"{URL_MAIN}/suche?term={quote_plus(str(sSearchText))}&tab=shows&page={str(iPage)}"
    
    oRequest = cRequestHandler(_requestUrl(sUrl), caching=True)
    sHtmlContent = oRequest.request()
    
    if not sHtmlContent:
        return

    sHtmlContent = re.sub(r'\s+', ' ', sHtmlContent)
    found_links = set()

    pattern = r'class="card cover-card.*?href="(/serie/[^"]+)".*?(?:data-src|src)="([^"]+)".*?alt="([^"]+)"'
    aResult = re.findall(pattern, sHtmlContent)

    for sLink, sThumbnail, sTitle in aResult:
        if sLink in found_links: continue
        # Platzhalter-Treffer werden uebersprungen, OHNE den Link als gesehen zu
        # merken: jede Serie steht zweimal im Markup, und wuerde die Fundstelle mit
        # dem gif-Platzhalter zuerst kommen, waere die Serie sonst komplett weg —
        # die echte zweite Fundstelle fiele dann als Dublette durch.
        if 'data:image/gif' in sThumbnail: continue
        found_links.add(sLink)

        sTitle = unescape(sTitle)
        sFullUrl = URL_MAIN + sLink if sLink.startswith('/') else sLink
        sFullThumb = URL_MAIN + sThumbnail if sThumbnail.startswith('/') else sThumbnail

        oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        oGuiElement.setThumbnail(sFullThumb)
        
        p = ParameterHandler()
        p.setParam('sUrl', sFullUrl)
        p.setParam('sName', sTitle)
        p.setParam('sThumbnail', sFullThumb)
        
        oGui.addFolder(oGuiElement, p)

    # Weiter-Eintrag nur mit Beleg: die Suchseite fuehrt rel="next" genau dann, wenn es
    # eine Folgeseite gibt (gleiches Muster wie showCatalog und showCollections).
    # Die frueher hier stehende Schwelle auf `total` war eine Heuristik und hat sich
    # verzaehlt: jede Serie steht ZWEIMAL im Markup, `total` ist also die doppelte
    # Trefferzahl. Der Eintrag erschien dadurch schon ab 10 gelisteten Serien und
    # fuehrte bei jeder Suche mit 10-23 Treffern ins Leere.
    # Die Adresse aus dem Link wird bewusst NICHT uebernommen — SSsearch baut sie aus
    # Suchtext und Seitenzahl selbst, der Link dient allein als Nachweis.
    # In der globalen Suche entfaellt der Eintrag: dort blaettert er nur EINE Seite
    # der Sammelliste weiter (Bauform wie in den uebrigen Site-Files).
    if not sGui and re.search(r'href="[^"]+"[^>]*rel="next"', sHtmlContent):
        p = ParameterHandler()
        p.setParam('sSearchText', sSearchText)
        p.setParam('iPage', str(int(iPage) + 1))
        oGui.addNextPage(SITE_IDENTIFIER, 'SSsearch', p)

    if not sGui:
        # Ohne Treffer bekommt der Nutzer sonst ein leeres Verzeichnis ohne jede
        # Erklaerung — serienstream war die einzige Seite im Addon, die hier stumm
        # blieb. Gleiche Bauform wie in showAllSeries. In der globalen Suche
        # unterbleibt der Hinweis, das prueft showInfo anhand des Sammel-Flags selbst.
        if not found_links:
            oGui.showInfo()
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()
                

