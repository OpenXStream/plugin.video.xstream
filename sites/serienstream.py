# -*- coding: utf-8 -*-
# Python 3

# Always pay attention to the translations in the menu!
# Language selection for hosters included.
# Ajax search function included.
# HTML long-term cache added
# showValue:     24 hours
# showAllSeries: 24 hours
# showEpisodes:   4 hours
# SSsearch:      24 hours
    
# 2022-12-06 Heptamer - Search function reworked
# 2026-12-29 viewIT   - Hotfix for V2 of SerienStream
# 2026-02-02 SatBandit - Hotfix for V2 of SerienStream
import ast
import xbmcgui
import string  # MERGED: Required for A-Z loop
import re

from resources.lib.handler.ParameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger
from resources.lib.tools import cParser, cUtil
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui
from urllib.parse import quote_plus
from html import unescape

SITE_IDENTIFIER = 'serienstream'
SITE_NAME = 'SerienStream'
SITE_ICON = 'serienstream.png'

# Global search function is thus deactivated!
if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

# Domain query
DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain') # Domain selection via addon settings
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status') # Domain status code query
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER) # Whether plugin is active or not

# URL_MAIN = 'https://s.to/'
if DOMAIN == '186.2.175.5': # For proxy change, update IP here and in settings
    URL_MAIN = 'http://' + DOMAIN
    REFERER = 'http://' + DOMAIN
    proxy = 'true'
else:
    URL_MAIN = 'https://' + DOMAIN
    REFERER = 'https://' + DOMAIN
    proxy = 'false'
URL_SERIES = URL_MAIN + '/serien'
URL_NEW_SERIES = URL_MAIN + '/neu'
URL_NEW_EPISODES = URL_MAIN + '/neue-episoden'
URL_POPULAR = URL_MAIN + '/beliebte-serien'
URL_COLLECTIONS = URL_MAIN + '/sammlungen'
URL_LOGIN = URL_MAIN + '/login'
URL_SEARCH = URL_MAIN + '/suche?term='

PAGE_SIZE = 20  # Serien pro Seite bei Pagination


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


def _fetchPosterFallback(sUrl):
    """Holt Poster per Detail-Request — nur als Fallback wenn kein Bild im HTML."""
    try:
        oReq = cRequestHandler(sUrl, caching=True)
        sHtml = oReq.request()
        if sHtml:
            return extractPoster(sHtml)
    except Exception:
        pass
    return ''


def load(): # Menu structure of the site plugin
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.serienstream.lastSearchText')
    params = ParameterHandler()
    username = cConfig().getSetting('serienstream.user')# Username
    password = cConfig().getSetting('serienstream.pass')# Password
    if username == '' or password == '':                # If no username and password were set, close the plugin!
        xbmcgui.Dialog().ok(cConfig().getLocalizedString(30241), cConfig().getLocalizedString(30264))   # Info Dialog!
    else:
        # Neues (Submenü)
        params = ParameterHandler()
        cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30554), SITE_IDENTIFIER, 'showNeues'), params)
        # Trends (Submenü)
        params = ParameterHandler()
        params.setParam('sUrl', URL_MAIN)
        cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30555), SITE_IDENTIFIER, 'showTrends'), params)
        # Sammlungen (Submenü)
        params = ParameterHandler()
        cGui().addFolder(cGuiElement('Sammlungen', SITE_IDENTIFIER, 'showCollectionsMenu'), params)
        # Genre
        params = ParameterHandler()
        params.setParam('sUrl', URL_SERIES + "?by=genre")
        cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30506), SITE_IDENTIFIER, 'showGenericMenu'), params)
        # A-Z
        params = ParameterHandler()
        params.setParam('sUrl', URL_SERIES + "?by=alpha")
        cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30814), SITE_IDENTIFIER, 'showGenericMenu'), params)
        # Suche
        params = ParameterHandler()
        params.setParam('sUrl', URL_SEARCH)
        cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'), params)
        cGui().setEndOfDirectory()

import xbmc # Required for logging

def showCatalog():
    params = ParameterHandler()
    sUrl = params.getValue('sUrl')
    sTargetGenre = params.getValue('sGenreFilter')
    
    oRequest = cRequestHandler(sUrl)
    sHtmlContent = oRequest.request()
    if not sHtmlContent: return
    oGui = cGui()

    # --- NEU: Globaler Bilder-Index (Dictionary) ---
    # Wir suchen auf der gesamten Seite nach Bild+Name Kombinationen
    dictThumbs = {}
    # s.to Kacheln haben oft: <img src="URL" alt="Serienname">
    # oder data-src. Dieser Regex fischt alle Bilder mit ihren Titeln ab.
    all_images = re.findall(r'(?:data-src|src)="([^"]+)"[^>]*alt="([^"]+)"', sHtmlContent)
    for sThumb, sTitle in all_images:
        name_key = unescape(sTitle).strip()
        if sThumb.startswith('/'): sThumb = URL_MAIN + sThumb
        dictThumbs[name_key] = sThumb

    # 1. Block-Isolierung (Deine funktionierende Logik)
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

        # Erst schauen wir im Dictionary nach (Genre-Modus Vorteil)
        sThumb = dictThumbs.get(sSeriesName, "")

        # Fallback for A-Z mode (window logic for safety)
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

    # 3. Pagination (unchanged)
    if not sTargetGenre:
        match_next = re.search(r'href="([^"]+)"[^>]*rel="next"', sHtmlContent)
        if match_next:
            next_url = match_next.group(1)
            if not next_url.startswith('http'): next_url = URL_MAIN + next_url
            
            p_next = ParameterHandler()
            p_next.setParam('sUrl', next_url)
            p_next.setParam('sName', params.getValue('sName'))
            oGui.addFolder(cGuiElement(cConfig().getLocalizedString(30558), SITE_IDENTIFIER, 'showCatalog'), p_next)

    oGui.setEndOfDirectory()
            
def showGenericMenu():
    params = ParameterHandler()
    sUrl = params.getValue('sUrl')
    sHtmlContent = cRequestHandler(sUrl).request()
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
            # Prefix entfernen, falls vorhanden
            sDisplay = sRawName.replace('filter.genre_', '').replace('-', ' ').replace('_', ' ').title()
            if not sDisplay: continue

            p = ParameterHandler()
            p.setParam('sUrl', sUrl)
            p.setParam('sGenreFilter', sRawName) # Original für HTML-Suche
            oGui.addFolder(cGuiElement(sDisplay, SITE_IDENTIFIER, 'showGenreEntries'), p)
    else:
        # A-Z Logik (bleibt wie gehabt)
        match_bar = re.search(r'class="alphabet-bar[^"]*">([\s\S]*?)</nav>', sHtmlContent)
        if match_bar:
            results = re.findall(r'href="(/katalog/[^"]+)"[^>]*>([^<]+)</a>', match_bar.group(1))
            for sNextUrl, sTitle in results:
                p = ParameterHandler()
                p.setParam('sUrl', _abs_url(sNextUrl))
                p.setParam('sName', sTitle.strip())
                oGui.addFolder(cGuiElement(sTitle.strip(), SITE_IDENTIFIER, 'showCatalog'), p)

    oGui.setEndOfDirectory()


def showGenreEntries():
    """Genre-Einträge mit Pagination und Poster-Fallback."""
    params       = ParameterHandler()
    sUrl         = params.getValue('sUrl')
    sTargetGenre = params.getValue('sGenreFilter')
    iPage        = int(params.getValue('iPage') or 1)
    oGui = cGui()

    sHtmlContent = cRequestHandler(sUrl).request()
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

    # Deduplizieren
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
        oGui.addNextPage(SITE_IDENTIFIER, 'showGenreEntries', p)

    oGui.setView('tvshows')
    oGui.setEndOfDirectory()
                    
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
    iPage = int(params.getValue('iPage') or 1)
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()
    pattern = '<a[^>]*href="(\\/serie\\/[^"]*)"[^>]*>(.*?)</a>'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    # Deduplizieren + optional filtern
    seen  = set()
    clean = []
    for sUrl, sName in aResult:
        if sUrl in seen: continue
        seen.add(sUrl)
        sName = unescape(sName)
        if sSearchText and not cParser.search(sSearchText, sName):
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
        oGui.addNextPage(SITE_IDENTIFIER, 'showAllSeries', p)

    if not sGui:
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()


# Hilfsfunktion: Extrahiert alle Cards aus einem HTML-Block
def extractCards(sHtml):
    # s.to uses 'data-src' for images (lazy load)
    # Das Pattern sucht den Link, das Bild und den Namen
    pattern = r'href="([^"]+)"[^>]*class="show-card[^"]*".*?data-src="([^"]+)"[^>]*alt="([^"]+)"'
    
    # (?s) allows line breaks within a card
    return re.findall(r'(?s)' + pattern, sHtml)

def showGenericSeriesList(entryUrl=False):
    oGui = cGui()
    params = ParameterHandler()
    
    sUrl = params.getValue('sUrl') or (URL_MAIN + '/beliebte-serien')
    sectionName = params.getValue('sectionName')
    
    oRequest = cRequestHandler(sUrl)
    sHtmlContent = oRequest.request()
    # Clean HTML: collapse all whitespace/newlines to single space
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
    
    # Cards extrahieren
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
    oGui.addFolder(cGuiElement(cConfig().getLocalizedString(30514), SITE_IDENTIFIER, 'showNewSeries'), params)
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
            if sThumb.startswith('/'): sThumb = URL_MAIN + sThumb
            oGuiElement.setThumbnail(sThumb)

            p = ParameterHandler()
            p.setParam('sUrl', URL_MAIN + sSeriesLink)
            p.setParam('sName', sName)
            p.setParam('sThumbnail', sThumb)
            oGui.addFolder(oGuiElement, p)

    oGui.setEndOfDirectory()

def showNeusteEpisoden():
    """Zeigt die neusten Episoden direkt von der Homepage."""
    oGui = cGui()
    sHtmlContent = cRequestHandler(URL_MAIN, caching=True).request()
    if not sHtmlContent:
        oGui.showInfo()
        return

    sHtmlContent = re.sub(r'\s+', ' ', sHtmlContent)

    # Finde die Sektion mit den neuesten Episoden
    pattern = r'data-bs-target="#([^"]+)"[^>]*>([^<]+)</button>'
    sections = re.findall(pattern, sHtmlContent)

    episode_section_id = None
    for sId, sName in sections:
        sName = sName.strip()
        if 'pisod' in sName.lower() or 'folge' in sName.lower():
            episode_section_id = sId
            break

    # Fallback: erste section-0
    if not episode_section_id:
        episode_section_id = 'section-0'

    # Sektion extrahieren
    section_pattern = f'id="{episode_section_id}".*?(?:id="section-|</div> </div> </section>)'
    section_match = re.search(section_pattern, sHtmlContent)

    if section_match:
        fragment = section_match.group(0)
        if 'latest-episode-row' in fragment:
            renderEpisodes(oGui, fragment)
        else:
            renderCards(oGui, fragment)

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
        oGui.addNextPage(SITE_IDENTIFIER, 'showTrendSection', p)

    oGui.setView('tvshows')
    oGui.setEndOfDirectory()


def showCollectionsMenu():
    """Submen\u00fc Sammlungen — sortiert nach verschiedenen Kriterien."""
    oGui = cGui()
    for sLabel, sSort in [
        ('K\u00fcrzlich hinzugef\u00fcgt', 'content_updated_at'),
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

    sHtmlContent = cRequestHandler(sUrl, caching=True).request()
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
        next_url = next_match.group(1)
        p = ParameterHandler()
        p.setParam('sUrl', _abs_url(next_url))
        oGui.addNextPage(SITE_IDENTIFIER, 'showCollections', p)

    oGui.setEndOfDirectory()


def showCollectionEntries():
    """Zeigt die Serien einer einzelnen Sammlung."""
    params = ParameterHandler()
    sUrl   = params.getValue('sUrl')
    sName  = params.getValue('sName') or ''
    oGui   = cGui()

    sHtmlContent = cRequestHandler(sUrl, caching=True).request()
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
        oGui.addNextPage(SITE_IDENTIFIER, 'showCollectionEntries', p)

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
    # Der Trick: Wir suchen nach 'latest-episode-row' und lassen danach 
    # beliebige Zeichen zu, bis das 'href' kommt.
    pattern = r'class="latest-episode-row[^"]*"\s+href="([^"]+)".*?class="ep-title" title="([^"]+)".*?class="ep-season">([^<]+).*?class="ep-episode">([^<]+).*?use href="#icon-flag-([^"]+)"'
    
    results = re.findall(pattern, sHtml, re.DOTALL)
    
    for sLink, sTitle, sSeason, sEpisode, sLang in results:
        if sLink.startswith('#'): continue
        
        sTitle = unescape(sTitle).strip()
        # Format language labels (german -> DE, english -> EN)
        sLangLabel = 'DE' if 'german' in sLang else 'EN' if 'english' in sLang else sLang.upper()
        
        # Display name including language for overview
        sDisplay = f"{sTitle} ({sSeason.strip()}{sEpisode.strip()}) [{sLangLabel}]"
        
        # Clean URL to season level
        sCleanUrl = re.sub(r'/episode-\d+', '', sLink)
        sFullUrl = URL_MAIN + sCleanUrl if sCleanUrl.startswith('/') else sCleanUrl
        
        # Nur die Zahl aus "E08" -> "8"
        sEpNum = re.sub(r'\D', '', sEpisode)
        
        oGuiElement = cGuiElement(sDisplay, SITE_IDENTIFIER, 'showEpisodes')
        # Falls du das Cover der Serie hast, hier sThumbnail nutzen
        oGuiElement.setThumbnail("DefaultVideo.png") 
        
        p = ParameterHandler()
        p.setParam('sUrl', sFullUrl)
        p.setParam('sName', sTitle)
        p.setParam('sTargetEpisode', sEpNum)
        
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
        # If URL is relative, prepend main URL
        sFullUrl = URL_MAIN + sLink if sLink.startswith('/') else sLink
        sTitle = unescape(sTitle).strip()
        
        oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showSeasons')
        
        # Hier nutzen wir das extrahierte data-src als Thumbnail
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
    # Diese markieren den Start jeder Sektion
    titles = re.findall(r'<(?:h2|h3)[^>]*>(.*?)</(?:h2|h3)>', sHtmlContent)

    for sTitle in titles:
        # Remove HTML tags (e.g. <span> or emojis)
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

    # Find section from our heading to the next one
    find_section = r'<(?:h2|h3)[^>]*>[^<]*' + re.escape(sTargetTitle) + r'.*?</(?:h2|h3)>(.*?)(?=<h2|<h3|$)'
    match = re.search(find_section, sHtmlContent)

    if match:
        sFragment = match.group(1)
        # Regex for link, thumbnail and alt text
        pattern = r'href="(/serie/[^"]+)".*?<img.*?(?:data-src|src)="([^"]+)".*?alt="([^"]+)"'
        items = re.findall(pattern, sFragment)

        # Um Dubletten zu vermeiden (wegen <picture> Tags)
        seen_links = set()

        for sLink, sThumb, sName in items:
            # 1. HTML Entities dekodieren (macht aus &amp; ein &)
            sName = unescape(sName).strip()
            
            # 2. Staffel-Zusatz im Link entfernen
            sSeriesLink = sLink.split('/staffel-')[0]
            
            # Dubletten-Check
            if sSeriesLink in seen_links: continue
            seen_links.add(sSeriesLink)

            # Platzhalter-GIFs ignorieren
            if 'data:image/gif' in sThumb and 'data-src="' in sFragment:
                continue

            oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
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
    
    oGui = cGui()
    sHtmlContent = cRequestHandler(sUrl, caching=True).request()
    if not sHtmlContent: return

    # 1. Serienname fixen (falls von Favoriten/Suche kommend)
    title_match = re.search(r'<title>(.*?)\s+Staffel', sHtmlContent)
    if title_match:
        sName = title_match.group(1).strip()
    elif not sName or sName == 'False':
        sName = "Serie"

    # 2. Description (extract from span "description-text")
    sDesc = ''
    # Suche speziell nach dem span-Inhalt
    match_span = re.search(r'<span class="description-text">(.*?)</span>', sHtmlContent, re.DOTALL)
    if match_span:
        sDesc = unescape(match_span.group(1)).strip()
        # HTML-Reste entfernen (falls vorhanden)
        sDesc = re.sub(r'<[^>]*>', '', sDesc)
    
    # Fallback auf Meta-Description, falls der span leer war
    if not sDesc:
        match_desc = re.search(r'name="description"\s+content="([^"]+)"', sHtmlContent)
        if match_desc:
            sDesc = unescape(match_desc.group(1)).strip()

    # 3. Poster extrahieren
    if not sThumbnail: sThumbnail = extractPoster(sHtmlContent)

    # 4. Staffeln finden (aus deinem Web-Dump)
    # Sucht nach Links wie /staffel-1, /staffel-2 etc.
    pattern = r'href="([^"]+/staffel-(\d+))"'
    results = re.findall(pattern, sHtmlContent)

    # --- FIX START Aki: Sortierung der Staffeln ---
    # Dubletten entfernen und Mapping erstellen
    seasons_map = {}
    for sSeasonUrl, sSeasonNum in results:
        if sSeasonNum not in seasons_map:
            seasons_map[sSeasonNum] = sSeasonUrl

    # Sortieren nach Zahl (damit 0 vor 1 kommt, und 10 nach 2)
    sorted_keys = sorted(seasons_map.keys(), key=lambda x: int(x))

    for sSeasonNum in sorted_keys:
        sSeasonUrl = seasons_map[sSeasonNum]
        
        # Fix for movies instead of Season 0 (renamed specials)
        if sSeasonNum == '0':
            sDisplay = cConfig().getLocalizedString(30559)
        else:
            sDisplay = "%s %s" % (cConfig().getLocalizedString(30512), sSeasonNum)
        
        oGuiElement = cGuiElement(sDisplay, SITE_IDENTIFIER, 'showEpisodes')
        oGuiElement.setThumbnail(sThumbnail)
        oGuiElement.setTVShowTitle(sName)
        
        # Beschreibung hier ebenfalls setzen
        if sDesc:
            oGuiElement.setDescription(sDesc)

        p = ParameterHandler()
        p.setParam('sUrl', URL_MAIN + sSeasonUrl if sSeasonUrl.startswith('/') else sSeasonUrl)
        p.setParam('sName', sName)
        p.setParam('sThumbnail', sThumbnail)
        # Pass description to next level
        p.setParam('sDescription', sDesc) 
        
        oGui.addFolder(oGuiElement, p)
    # --- FIX END ---

    oGui.setView('seasons')
    oGui.setEndOfDirectory()
    
def showEpisodes():
    params = ParameterHandler()
    sUrl = params.getValue('sUrl')
    sTVShowTitle = params.getValue('TVShowTitle')
    sThumbnail = params.getValue('sThumbnail')
    sDesc = params.getValue('sDescription')
    
    oRequest = cRequestHandler(sUrl, caching=False)
    sHtmlContent = oRequest.request()
    if not sHtmlContent: return

    # 1. Serienname & Beschreibung (wie gehabt)
    if not sTVShowTitle or sTVShowTitle == 'False':
        title_match = re.search(r'<title>(.*?)\s+Staffel', sHtmlContent)
        if title_match: sTVShowTitle = title_match.group(1).strip()
        
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
        # Episodennummer
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
        titles_dict[ep_nr] = ep_title
        unique_nav.append((ep_url, ep_nr))

    oGui = cGui()
    total = len(unique_nav)
    
    for sUrl2, sEpNr in unique_nav:
        # Den passenden Titel aus unserem Tabellen-Dict holen
        sEpName = titles_dict.get(sEpNr, "").strip()
        sEpName = unescape(sEpName)
        
        # Formatierung: "1 - Der Tote am See"
        sDisplayTitle = "%s %s" % (cConfig().getLocalizedString(30513), sEpNr)
        if sEpName:
            sDisplayTitle += " - %s" % sEpName
        
        oGuiElement = cGuiElement(sDisplayTitle, SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setMediaType('episode')
        
        if sThumbnail: oGuiElement.setThumbnail(sThumbnail)
        if sDesc: oGuiElement.setDescription(sDesc)
        
        oGuiElement.setTVShowTitle(sTVShowTitle)
        
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
    sHtmlContent = cRequestHandler(sUrl, caching=False).request()
    
    if not sHtmlContent:
        return []

    # Find all buttons (containers)
    button_pattern = r'<button[^>]*class="[^"]*link-box[^"]*"[^>]*>'
    buttons = re.findall(button_pattern, sHtmlContent)

    for sButton in buttons:
        # Individual extraction: HTML order does not matter
        url_match = re.search(r'data-play-url="([^"]+)"', sButton)
        name_match = re.search(r'data-provider-name="([^"]+)"', sButton)
        lang_match = re.search(r'data-language-id="([^"]+)"', sButton)

        if url_match and name_match and lang_match:
            sHUrl = url_match.group(1)
            sName = name_match.group(1)
            sLang = lang_match.group(1)

            # --- Language filter logic ---
            if cConfig().isBlockedHoster(sName)[0]: continue
            
            sLanguage = cConfig().getSetting('prefLanguage')
            if sLanguage == '1' and sLang != '1': continue
            if sLanguage == '2' and sLang != '2': continue
            
            sLangLabel = '(DE)' if sLang == '1' else '(EN)' if sLang == '2' else sLang
            sQuality = '720'
            
            # Structure required by the core for display
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

def getHosterUrl(hUrl):
    if type(hUrl) == str: hUrl = ast.literal_eval(hUrl)
    Request = cRequestHandler(URL_MAIN + hUrl[0], caching=False)
    Request.addHeaderEntry('Referer', ParameterHandler().getValue('entryUrl'))
    Request.addHeaderEntry('Upgrade-Insecure-Requests', '1')
    Request.request()
    sUrl = Request.getRealUrl()

    if 'voe' in hUrl[1].lower():
        isBlocked, sDomain = cConfig().isBlockedHoster(sUrl)  # Function returns 2 values!
        if isBlocked:  # VOE pseudo domain not known in resolveUrl
            sUrl = sUrl.replace(sDomain, 'voe.sx')
            return [{'streamUrl': sUrl, 'resolved': False}]

    return [{'streamUrl': sUrl, 'resolved': False}]

def showSearch():
    # Check if we have a cached search text (e.g. coming back from playback)
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
    
    oRequest = cRequestHandler(sUrl, caching=True)
    sHtmlContent = oRequest.request()
    
    if not sHtmlContent:
        return

    sHtmlContent = re.sub(r'\s+', ' ', sHtmlContent)
    found_links = set()

    # Regex for card structure
    pattern = r'class="card cover-card.*?href="(/serie/[^"]+)".*?(?:data-src|src)="([^"]+)".*?alt="([^"]+)"'
    aResult = re.findall(pattern, sHtmlContent)

    total = len(aResult)
    for sLink, sThumbnail, sTitle in aResult:
        if sLink in found_links: continue
        found_links.add(sLink)
        
        if 'data:image/gif' in sThumbnail: continue

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

    # Next page logic
    if total >= 20:
        p = ParameterHandler()
        p.setParam('sSearchText', sSearchText)
        p.setParam('iPage', str(int(iPage) + 1)) # Explicitly increment page
        oGui.addNextPage(SITE_IDENTIFIER, 'SSsearch', p)

    if not sGui:
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()
                

