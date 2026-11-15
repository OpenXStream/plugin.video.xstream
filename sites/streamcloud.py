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
from resources.lib.wrappers.meinecloud import resolveMeinecloud, resolveMeinecloudSerial, expandHosterList, buildHosterFromUrl, buildMergedHosters, MEINECLOUD_TRIGGER, isPlatformUrl, platformImdbId, platformSnippetId, packSourceUrls, unpackSourceUrls
from resources.lib.tools import cParser, cUtil
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui

SITE_IDENTIFIER = 'streamcloud'
SITE_NAME = 'Streamcloud'
SITE_ICON = 'streamcloud.png'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'streamcloud.date')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)

# Seit dem 03.11.2026 ist die Seite eine Next.js-App: Adressen ohne Schraegstrich am Ende (die alten
# DLE-Pfade wie /filme-stream/ und /serien/ leiten weiter), Karten statt DLE-Kurzmeldungen, der
# Player bettet weiter die Plattform ein (DEVIDEOSRC, Wrapper meinecloud).
URL_MAIN = 'https://' + DOMAIN + '/'
URL_MAINPAGE = URL_MAIN + 'streamcloud'
URL_KINO = URL_MAIN + 'kinofilme'
# Trends: eine Uebersichtsseite wie die Startseite — eine Kartenliste „Trends heute" und die Reihen „Beliebt in
# Deutschland" und „Trends der Woche" (03.11.2026: 11, 16 und 12 Titel, Filme und zum Teil Serien, laut Seite
# mehrmals taeglich neu); in der Navigation der Seite heisst der Punkt „Trending"
URL_TRENDS = URL_MAIN + 'trends'
# Die Gesamtlisten kommen ueber /discover: dieselben Titel in derselben Reihenfolge wie /filme bzw.
# /serien (03.11.2026: die ersten 48 gleich, 34.202 Filme und 1.426 Serien auf beiden Wegen), aber
# mit „Seite x von y" — /filme und /serien nennen ihr Ende nicht.
URL_MOVIES = URL_MAIN + 'discover?t=movie&sort=neu'
URL_SERIES = URL_MAIN + 'discover?t=tv&sort=neu'
URL_DISCOVER = URL_MAIN + 'discover'
URL_GENRE = URL_MAIN + 'discover?g=%s&sort=neu'
# Suche zuerst ueber den Textfilter von /discover: er sucht die Wortfolge am Stueck im Titel und im
# Originaltitel und blaettert (03.11.2026: „star wars" 23 samt „Krieg der Sterne", „walking dead" 9,
# „könig" 227 auf 4 Seiten) — deshalb dort kein Titelfilter im Addon, er wuerfe die Originaltitel-Treffer
# weg. Die Wortfolge muss aber zeichengleich stehen: „spider man" 0 (die Seite schreibt „Spider-Man", 13),
# „Der Herr der Ringe: Die Rückkehr des Königs" 0 (die Seite schreibt „ - " statt „: "). Findet /discover
# nichts, fragt die Suche einmal /suche: ODER ueber die Woerter, nach Relevanz, hoechstens 60 Titel ohne
# Folgeseite („spider man" 60, davon 13 mit allen Woertern im Titel) — dort filtert das Addon mit
# cParser.searchTitle und bietet kein Weiter an.
URL_SEARCH = URL_MAIN + 'discover?q=%s'
URL_SEARCH_ANY = URL_MAIN + 'suche?q=%s'
# Jahr: /jahr/<JJJJ> listet die Filme und Serien eines Jahres wie die Listen mit „Seite x von y" (03.11.2026: 2025
# 954 Titel auf 16 Seiten, 1950 41 Titel). Eine Uebersicht aller Jahre gibt es nicht (/jahr antwortet 404), deshalb
# die Eingabe wie bei AniWorld und SerienStream.
URL_YEAR = URL_MAIN + 'jahr/%s'


def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.streamcloud.lastSearchText')
    xbmcgui.Window(10000).clearProperty('xstream.streamcloud.lastYear')
    params = ParameterHandler()
    params.setParam('sUrl', URL_MAINPAGE)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30881), SITE_IDENTIFIER, 'showRows'), params)  # Startseite
    params = ParameterHandler()
    params.setParam('sUrl', URL_KINO)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30501), SITE_IDENTIFIER, 'showEntries'), params)  # Latest Releases
    params = ParameterHandler()
    params.setParam('sUrl', URL_MOVIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30502), SITE_IDENTIFIER, 'showEntries'), params)  # Movies
    params = ParameterHandler()
    params.setParam('sUrl', URL_TRENDS)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30555), SITE_IDENTIFIER, 'showRows'), params)  # Trends
    params = ParameterHandler()
    params.setParam('sUrl', URL_SERIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30511), SITE_IDENTIFIER, 'showEntries'), params)  # Series
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30506), SITE_IDENTIFIER, 'showGenre'))  # Categories
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30564), SITE_IDENTIFIER, 'showYearSearch'))  # Year
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'))  # Search
    cGui().setEndOfDirectory()


# Karte (Listen, Reihen der Startseite, Entdecken; Markup 03.11.2026):
# <a class="cv" href="/filme/<id>-<slug>" title="Name" …><div class="cv-art"><img src="…">…</div>
# <div class="cv-t">Name</div><div class="cv-m">2026 · ★ 6,8</div></a>
# Film oder Serie steht in der Adresse (/filme/ bzw. /serie/) — kein Abruf der Detailseite mehr.
_RE_CARD = re.compile(r'<a class="cv" href="([^"]+)" title="([^"]*)"[^>]*>(.*?)</a>', re.S)
_RE_CARD_TYPE = re.compile(r'^(?:https?://[^/]+)?/(filme|serie)/')
_RE_CARD_IMG = re.compile(r'<img[^>]+src="([^"]+)"')
_RE_CARD_META = re.compile(r'class="cv-m">(.*?)</div>', re.S)
# Uebersichtsseiten (Startseite, Trends): jede Reihe eine <section class="rail"> mit <h2 class="rail-title">Name</h2>
# — ueber die Section begrenzt, damit die letzte Reihe nicht bis zum Dokumentende laeuft; dazu eine Kartenliste
# <div class="grid"> unter der Seitenueberschrift <h1 class="sec-t">Name</h1> (Trends: „Trends heute" vor den
# Reihen; die Liste endet an der ersten Reihe bzw. am Ende von <main>, die Karten tragen eigene </div>)
_RE_RAIL = re.compile(r'<section class="rail">(.*?)</section>', re.S)
_RE_RAIL_HEAD = re.compile(r'<h2 class="rail-title">(.*?)</h2>', re.S)
_RE_GRID = re.compile(r'<div class="grid">(.*?)(?=<section\b|</main>)', re.S)
_RE_GRID_HEAD = re.compile(r'<h1 class="sec-t">(.*?)</h1>', re.S)
# Seitenlage und Vorwaerts-Link der Listen: <p class="conta">… · Seite 1 von 594</p> und
# <div class="carica">…<a href="/discover?…&amp;page=2">weitere Titel</a></div> — auf der letzten
# Seite fehlt der Link (03.11.2026 an /serien Seite 30 und /discover?t=tv Seite 24 gemessen)
_RE_CONTA = re.compile(r'<p class="conta">(.*?)</p>', re.S)
_RE_PAGES = re.compile(r'Seite\s*(\d+)\s*von\s*(\d+)')
_RE_MORE = re.compile(r'<div class="carica">(.*?)</div>', re.S)
_RE_HREF = re.compile(r'href="([^"]+)"')
# Genres im Filter der Entdecken-Seite (<select name="g">; Name und Kennung von der Seite)
_RE_GENRE_SELECT = re.compile(r'<select[^>]*name="g"[^>]*>(.*?)</select>', re.S)
_RE_OPTION = re.compile(r'<option[^>]*value="([^"]+)"[^>]*>([^<]+)</option>')
# Plattform-Player der Detailseite (Film: …/movie/<imdb>, Serie: …/custom/serial/<imdb>/1/1), aufs Tag begrenzt
_RE_IFRAME = re.compile(r'<iframe[^>]+src="(https?://[^"]+)"')
# Poster der Detailseite: <img class="sc-poster" src="https://img.streamcloud.date/t/p/w342/…">
_RE_DETAIL_COVER = re.compile(r'<img[^>]+class="sc-poster"[^>]+src="([^"]+)"')


def _absoluteUrl(sUrl):
    if sUrl.startswith('//'):
        return 'https:' + sUrl
    return sUrl if sUrl.startswith('http') else URL_MAIN.rstrip('/') + '/' + sUrl.lstrip('/')


def _requestUrl(sUrl):
    """Adresse unmittelbar vor dem Abruf kodieren (Leerzeichen, Umlaute) — im Parameter steht sie roh,
    schon kodierte Teile bleiben (`%` ist sicher)."""
    return cParser.urlEncode(sUrl, safe="/:?=&%#")


def _cards(sHtmlContent):
    """Karten in Seitenreihenfolge als [(Adresse, Name, Bild, Jahr, Wertung, Serie?)], je Adresse einmal.
    Karten ohne Namen oder mit einer anderen Adresse als /filme/ bzw. /serie/ fallen weg."""
    aCards, aSeen = [], set()
    for sHref, sTitle, sInner in _RE_CARD.findall(sHtmlContent or ''):
        sHref = cUtil.unescape(sHref)
        mType = _RE_CARD_TYPE.match(sHref)
        sName = cUtil.unescape(sTitle).strip()
        if not mType or not sName:
            continue
        sUrl = _absoluteUrl(sHref)
        if sUrl in aSeen:
            continue
        aSeen.add(sUrl)
        mImg = _RE_CARD_IMG.search(sInner)
        sThumb = _absoluteUrl(cUtil.unescape(mImg.group(1))) if mImg else ''
        mMeta = _RE_CARD_META.search(sInner)
        sMeta = cUtil.removeHtmlTags(mMeta.group(1)) if mMeta else ''
        mYear = re.search(r'\b(\d{4})\b', sMeta)
        mRating = re.search(r'★\s*(\d+(?:[.,]\d+)?)', sMeta)
        aCards.append((sUrl, sName, sThumb, mYear.group(1) if mYear else '',
                       mRating.group(1).replace(',', '.') if mRating else '', mType.group(1) == 'serie'))
    return aCards


def _addCards(oGui, params, aCards):
    """Die Karten als Eintraege: Serie → showSeasons (Ordner), Film → showHosters (abspielbar)."""
    total = len(aCards)
    for sUrl, sName, sThumb, sYear, sRating, isTvshow in aCards:
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons' if isTvshow else 'showHosters')
        oGuiElement.setThumbnail(sThumb)
        oGuiElement.setMediaType('tvshow' if isTvshow else 'movie')
        if sYear:
            oGuiElement.setYear(sYear)
        if sRating:
            oGuiElement.addItemValue('rating', sRating)
        params.setParam('entryUrl', sUrl)
        params.setParam('sName', sName)
        params.setParam('sThumbnail', sThumb)
        oGui.addFolder(oGuiElement, params, isTvshow, total)


def _rows(sHtmlContent):
    """Reihen einer Uebersichtsseite in Seitenreihenfolge als [(Name, Karten)]: die Reihen der Seite und die
    Kartenliste unter der Seitenueberschrift, falls es eine gibt. Name und Einteilung kommen aus dem Markup —
    aendert die Seite ihre Reihen, aendert sich das Menue mit. Reihen ohne Namen oder ohne Karten fallen weg
    (kein toter Menuepunkt)."""
    sHtmlContent = sHtmlContent or ''
    aBlocks = []
    mGrid = _RE_GRID.search(sHtmlContent)
    mHead = _RE_GRID_HEAD.search(sHtmlContent)
    if mGrid and mHead and mHead.start() < mGrid.start():
        aBlocks.append((mGrid.start(), mHead.group(1), mGrid.group(1)))
    for mRail in _RE_RAIL.finditer(sHtmlContent):
        mRailHead = _RE_RAIL_HEAD.search(mRail.group(1))
        if mRailHead:
            aBlocks.append((mRail.start(), mRailHead.group(1), mRail.group(1)))
    aRows = []
    for iPos, sHead, sBlock in sorted(aBlocks, key=lambda b: b[0]):
        sLabel = cUtil.unescape(cUtil.removeHtmlTags(sHead)).strip()
        aCards = _cards(sBlock)
        if sLabel and aCards:
            aRows.append((sLabel, aCards))
    return aRows


def showRows():
    """Uebersichtsseite (Startseite, Trends): je Reihe der Seite ein Ordner, so wie die Seite sie im HTML liefert
    (03.11.2026 Startseite: Kinofilme, Neu: Filme, Neu: Serien, Beliebte Filme mit je 20 Titeln — Beliebte Serien
    und die Genre-Reihen laedt die Seite erst im Browser per Skript nach, sie stehen leer im HTML und fallen weg;
    Trends: Trends heute, Beliebt in Deutschland, Trends der Woche)."""
    params = ParameterHandler()
    sUrl = params.getValue('sUrl')
    aRows = _rows(cRequestHandler(_requestUrl(sUrl)).request())
    if not aRows:
        cGui().showInfo()
        return
    for sLabel, aCards in aRows:
        params = ParameterHandler()
        params.setParam('sUrl', sUrl)
        params.setParam('sRow', sLabel)
        oGuiElement = cGuiElement(sLabel, SITE_IDENTIFIER, 'showRowEntries')
        if aCards[0][2]:
            oGuiElement.setThumbnail(aCards[0][2])
        cGui().addFolder(oGuiElement, params)
    cGui().setEndOfDirectory()


def showRowEntries():
    """Die Titel EINER Reihe, so viele wie die Seite zeigt (keine Alle-Links: Filme, Serien und Genre stehen
    ohnehin im Menue). Die Uebersichtsseite kommt aus dem Cache."""
    params = ParameterHandler()
    sUrl = params.getValue('sUrl')
    sRow = params.getValue('sRow')
    aCards = []
    for sLabel, aRowCards in _rows(cRequestHandler(_requestUrl(sUrl)).request()):
        if sLabel == sRow:
            aCards = aRowCards
            break
    if not aCards:
        cGui().showInfo()
        return
    params.setParam('sUrl', '')
    params.setParam('sRow', '')
    _addCards(cGui(), params, aCards)
    cGui().setView('tvshows' if all(c[5] for c in aCards) else 'movies')
    cGui().setEndOfDirectory()


def showGenre():
    """Genres aus dem Filter der Entdecken-Seite (03.11.2026: 26 Genres, „Alle Genres" ohne Kennung faellt weg), je Genre die Liste ueber
    /discover — neueste zuerst wie die Genre-Seiten der Seite, aber mit Seitenlage."""
    sHtmlContent = cRequestHandler(URL_DISCOVER).request()
    mSelect = _RE_GENRE_SELECT.search(sHtmlContent or '')
    aGenres = _RE_OPTION.findall(mSelect.group(1)) if mSelect else []
    if not aGenres:
        cGui().showInfo()
        return
    for sSlug, sName in aGenres:
        params = ParameterHandler()
        params.setParam('sUrl', URL_GENRE % sSlug)
        cGui().addFolder(cGuiElement(cUtil.unescape(sName).strip(), SITE_IDENTIFIER, 'showEntries'), params)
    cGui().setEndOfDirectory()


def showYearSearch():
    """Jahr eingeben wie bei AniWorld und SerienStream: Zahlenfeld, das Jahr bleibt in einer Fenster-Property, damit
    Kodi beim Zurueck aus einem Titel die Liste ohne neues Zahlenfeld aufbaut (load() leert sie). Die Liste baut
    showEntries — Seitenlage und Weiter wie bei Filme und Serien."""
    win = xbmcgui.Window(10000)
    sYear = win.getProperty('xstream.streamcloud.lastYear')
    if not sYear:
        sYear = str(cGui().showNumpad(numPadTitle=cConfig().getLocalizedString(30563)) or '').strip()
        if not sYear:
            return
        # Die Seite fuehrt Jahresseiten von 1900 bis zwei Jahre voraus, davor und danach 404 (03.11.2026: 1899 und
        # 2029); zwei Jahre voraus steht dort noch nichts (2028: 0 Titel, 2027: 1) — erlaubt bis ein Jahr voraus.
        # Eine verworfene Eingabe wird gemeldet statt im Fehlerfenster mit der Adresse zu enden.
        if not sYear.isdigit() or len(sYear) != 4 or not 1900 <= int(sYear) <= time.localtime().tm_year + 1:
            cGui().showInfo('xStream', cConfig().getLocalizedString(30563))
            return
        win.setProperty('xstream.streamcloud.lastYear', sYear)
    showEntries(URL_YEAR % sYear)


def _searchUrl(sSearchText, iPage=1):
    """Adresse einer Suchseite, immer aus dem ROHEN Begriff gebaut (Regel: roh im Parameter, kodiert
    am Abruf); die Folgeseiten blaettern ueber `page` wie der Vorwaerts-Link der Seite."""
    sUrl = URL_SEARCH % cParser.quote(sSearchText)
    if iPage > 1:
        sUrl += '&page=%d' % iPage
    return sUrl


def _searchAny(sSearchText, bQuiet):
    """Rueckfall der Suche ueber /suche (ODER, hoechstens 60 Titel, keine Folgeseite): nur Karten, deren
    Titel den Begriff enthaelt (cParser.searchTitle, Interpunktion und Umlaute angeglichen)."""
    sHtmlContent = cRequestHandler(_requestUrl(URL_SEARCH_ANY % cParser.quote(sSearchText)), ignoreErrors=bQuiet).request()
    return [c for c in _cards(sHtmlContent) if cParser.searchTitle(sSearchText, c[1])]


def _pages(sHtmlContent):
    """(aktuelle Seite, letzte Seite) aus „Seite x von y" der Zaehlzeile, sonst (0, 0) — Kinofilme nennt kein Ende."""
    mConta = _RE_CONTA.search(sHtmlContent or '')
    mPages = _RE_PAGES.search(cUtil.removeHtmlTags(mConta.group(1))) if mConta else None
    return (int(mPages.group(1)), int(mPages.group(2))) if mPages else (0, 0)


def _nextUrl(sHtmlContent):
    """Volle Adresse der Folgeseite aus dem Vorwaerts-Link „weitere Titel", sonst ''.

    Die Seite bietet den Link auch auf der letzten Seite an, wenn die Zahl der Titel genau ein Vielfaches von 60
    ist (03.11.2026: Musik 840 Titel, „Seite 14 von 14" mit Link auf eine leere Seite 15) — deshalb gilt der Link
    nur, solange die Zaehlzeile derselben Antwort eine weitere Seite nennt (ohne Zaehlzeile allein der Link)."""
    iPage, iLast = _pages(sHtmlContent)
    if iLast and iPage >= iLast:
        return ''
    mMore = _RE_MORE.search(sHtmlContent or '')
    mHref = _RE_HREF.search(mMore.group(1)) if mMore else None
    return _absoluteUrl(cUtil.unescape(mHref.group(1))) if mHref else ''


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not sSearchText:
        # Weiter-Seite der Suche: Kodi ruft die Funktion neu auf, Begriff und Seitenzahl stehen dann
        # nur noch im Parameter
        sSearchText = params.getValue('sSearchText') or False
    iPage = 1
    if sSearchText:
        iPage = int(params.getValue('page') or 1)
        entryUrl = _searchUrl(sSearchText, iPage)
    elif not entryUrl:
        entryUrl = params.getValue('sUrl')
    # Eine Folgeseite der Suche meldet Fehler nicht als Fenster (wie beim Blaettern „Kein Eintrag
    # gefunden"), die globale Suche bleibt still
    oRequest = cRequestHandler(_requestUrl(entryUrl), ignoreErrors=(sGui is not False or iPage > 1))
    sHtmlContent = oRequest.request()
    aCards = _cards(sHtmlContent)
    bAny = False
    if not aCards and sSearchText and iPage == 1 and sHtmlContent and sHtmlContent not in REQUEST_ERRORS:
        # /discover fand die Wortfolge nicht (andere Schreibweise der Seite): einmal /suche, ohne Weiter
        aCards = _searchAny(sSearchText, sGui is not False)
        bAny = True
    if not aCards:
        if not sGui: oGui.showInfo()
        return
    # Listenadresse und Suchstand gehoeren nicht an die Eintraege (die Folgeseite bekommt sie unten neu)
    params.setParam('sUrl', '')
    params.setParam('sSearchText', '')
    params.setParam('page', '')
    _addCards(oGui, params, aCards)
    if sGui:
        return
    # Weiter nur mit dem Vorwaerts-Link der Seite als Beleg; die Suche traegt Begriff und Seitenzahl
    # (eine Seite je Aufruf, die globale Suche nur Seite 1), die Listen die Adresse der Folgeseite
    sNextUrl = '' if bAny else _nextUrl(sHtmlContent)
    if sNextUrl:
        nextParams = ParameterHandler()
        if sSearchText:
            nextParams.setParam('sSearchText', sSearchText)
            nextParams.setParam('page', iPage + 1)
        else:
            nextParams.setParam('sUrl', sNextUrl)
        oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', nextParams, cGui.pageInfo(*_pages(sHtmlContent)))
    oGui.setView('tvshows' if all(c[5] for c in aCards) else 'movies')
    oGui.setEndOfDirectory()


def _detailCover(sHtmlContent):
    """Volle Adresse des Posters aus dem Detail-HTML, sonst ''. Gebraucht, wenn kein Cover mitkommt
    (Aufruf ohne sThumbnail, z.B. alter Favorit) — die Detailseite ist dann ohnehin geladen."""
    mCover = _RE_DETAIL_COVER.search(sHtmlContent or '')
    return _absoluteUrl(cUtil.unescape(mCover.group(1))) if mCover else ''


def showSeasons():
    """Staffel-Ebene: die Serien kommen allein ueber die Plattform-API (resolveMeinecloudSerial, die
    IMDb-ID liest platformImdbId aus dem Plattform-Player der Detailseite, auch die verlaengerten IDs).
    Bei genau einer Staffel wird die Ordner-Ebene
    uebersprungen (direkt in die Episoden, HTML und Plattform-Folgen werden durchgereicht — kein
    zweiter Abruf)."""
    params = ParameterHandler()
    entryUrl = params.getValue('entryUrl')
    sName = params.getValue('sName') if params.exist('sName') else ''
    sThumbnail = params.getValue('sThumbnail')
    sHtmlContent = cRequestHandler(_requestUrl(entryUrl)).request()
    if not sThumbnail:
        # Kein Cover mitgekommen (z.B. alter Favorit): Poster der Detailseite, und als Parameter weiter,
        # damit auch der Klick auf eine Staffel es hat
        sThumbnail = _detailCover(sHtmlContent)
        if sThumbnail:
            params.setParam('sThumbnail', sThumbnail)
    aMc = []
    sImdbId = platformImdbId(sHtmlContent)
    if sImdbId:
        aMc = resolveMeinecloudSerial(sImdbId, referer=entryUrl, siteHtml=sHtmlContent)
    seasons = sorted(set(ep['season'] for ep in aMc))
    if not seasons:
        cGui().showInfo()
        return

    # Nur eine Staffel: Ordner-Ebene sparen, direkt in die Episoden.
    if len(seasons) == 1:
        showEpisodes(staffel=seasons[0], htmlContent=sHtmlContent, mcEpisodes=aMc)
        return

    for iSeason in seasons:
        oGuiElement = cGuiElement(cConfig().getLocalizedString(30512) + ' %d' % iSeason, SITE_IDENTIFIER, 'showEpisodes')
        oGuiElement.setMediaType('season')
        oGuiElement.setSeason(iSeason)
        if sName: oGuiElement.setTVShowTitle(sName)
        if sThumbnail:
            oGuiElement.setThumbnail(sThumbnail)
        params.setParam('entryUrl', entryUrl)
        params.setParam('staffel', str(iSeason))
        cGui().addFolder(oGuiElement, params, True)
    cGui().setView('seasons')
    cGui().setEndOfDirectory()


def showEpisodes(staffel=None, htmlContent=None, mcEpisodes=None):
    params = ParameterHandler()
    entryUrl = params.getValue('entryUrl')
    sTVShowTitle = params.getValue('sName') if params.exist('sName') else ''
    sThumbnail = params.getValue('sThumbnail')
    # staffel/htmlContent/mcEpisodes reicht showSeasons durch (eine Staffel), sonst kommt die Staffel
    # aus dem Parameter (Klick auf einen Staffel-Ordner = eigener Aufruf, die Plattform wird neu gefragt)
    if staffel is None and params.exist('staffel'):
        staffel = params.getValue('staffel')
    sStaffel = str(staffel) if staffel is not None else None
    sHtmlContent = htmlContent if htmlContent is not None else cRequestHandler(_requestUrl(entryUrl)).request()
    if mcEpisodes is not None:
        aEpisodes = list(mcEpisodes)
    else:
        sImdbId = platformImdbId(sHtmlContent)
        aEpisodes = resolveMeinecloudSerial(sImdbId, referer=entryUrl, siteHtml=sHtmlContent) if sImdbId else []
    if sStaffel is not None:
        aEpisodes = [ep for ep in aEpisodes if str(ep['season']) == sStaffel]
    if not aEpisodes:
        cGui().showInfo()
        return

    # Falls kein Parent-Thumbnail uebergeben (z.B. alter Favorit): Poster der Detailseite
    if not sThumbnail:
        sThumbnail = _detailCover(sHtmlContent)

    total = len(aEpisodes)
    for ep in aEpisodes:
        # Eine Form auf allen Sites ("S01E11 - Titel", cParser.episodeLabel) mit dem Folgentitel der Plattform
        oGuiElement = cGuiElement(cParser.episodeLabel(ep['season'], ep['episode'], ep['title']), SITE_IDENTIFIER, 'showHosters')
        if sThumbnail:
            oGuiElement.setThumbnail(sThumbnail)
        oGuiElement.setMediaType('episode')
        if sTVShowTitle: oGuiElement.setTVShowTitle(sTVShowTitle)
        oGuiElement.setSeason(ep['season'])
        oGuiElement.setEpisode(ep['episode'])
        params.setParam('entryUrl', entryUrl)
        # alle Quellen der Folge mitgeben (ein Parameter, packSourceUrls), damit showHosters() ohne
        # weiteren Abruf aufloest
        params.setParam('meinecloud_url', packSourceUrls(ep['urls']))
        cGui().addFolder(oGuiElement, params, False, total)
    cGui().setView('episodes')
    cGui().setEndOfDirectory()


def showHosters():
    # Endet ohne Hoster OHNE eigene Meldung: hoster.py meldet die leere Liste selbst mit „Stream //
    # Hoster nicht verfuegbar" (30141), eine eigene Meldung waere die zweite fuer denselben Klick.
    hosters = []
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    sMeinecloudUrl = params.getValue('meinecloud_url') if params.exist('meinecloud_url') else ''

    # Folge: die Adressen kommen direkt aus showEpisodes (alle Quellen der Folge in einem Parameter,
    # unpackSourceUrls), kein Abruf der Seite noetig
    if sMeinecloudUrl:
        for sMcUrl in unpackSourceUrls(sMeinecloudUrl):
            _fixedUrl = ('https:' + sMcUrl) if sMcUrl.startswith('//') else sMcUrl
            sName = cParser.urlparse(_fixedUrl).split('.')[0].strip()
            if not cConfig().isBlockedHoster(sName)[0]:
                hosters.append({'link': _fixedUrl, 'name': sName, 'displayedName': sName})
        if hosters:
            hosters.append('getHosterUrl')
        return hosters

    # Film: das Plattform-iframe der Detailseite; Laden und Aufloesen macht resolveMeinecloud() zentral
    # (Token-Seite plus JSON-API der Plattform, ohne Cache)
    sHtmlContent = cRequestHandler(_requestUrl(sUrl), caching=False).request()
    aPlatform = [s for s in _RE_IFRAME.findall(sHtmlContent or '') if isPlatformUrl(s)]
    if aPlatform:
        for sHosterUrl in expandHosterList(aPlatform[:1], referer=URL_MAIN):
            hoster = buildHosterFromUrl(sHosterUrl, sQuality='720', includeQualitySuffix=True)
            if hoster:
                hosters.append(hoster)
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def getHosterUrl(sUrl=False):
    return [{'streamUrl': sUrl, 'resolved': False}]


def showSearch():
    win = xbmcgui.Window(10000)
    sSearchText = win.getProperty('xstream.streamcloud.lastSearchText')
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30281))
        if not sSearchText: return
        win.setProperty('xstream.streamcloud.lastSearchText', sSearchText)
    # Das Verzeichnis schliesst showEntries selbst ab — so wie bei jeder Weiter-Seite der Suche, die
    # Kodi direkt dort aufruft.
    _search(False, sSearchText)


def _search(oGui, sSearchText):
    showEntries(_searchUrl(sSearchText), oGui, sSearchText)
