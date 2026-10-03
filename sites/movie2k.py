# -*- coding: utf-8 -*-
# Python 3

# Always pay attention to the translations in the menu!
# HTML LangzeitCache hinzugefügt
# showGenres:     24 Stunden
# showEntries:     6 Stunden
# showUpdates:     1 Stunde
# showTiles:       6 Stunden
# showSeasons:     6 Stunden
# showEpisodes:    4 Stunden

import re

import xbmcgui
from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger
from resources.lib.tools import cParser, cUtil
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui


SITE_IDENTIFIER = 'movie2k'
SITE_NAME = 'Movie2k'
SITE_ICON = 'movie2k.png'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'movie2k.cx')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)

URL_MAIN = 'https://' + DOMAIN
URL_MOVIES = URL_MAIN + '/movies'
URL_MOVIE_GENRES = URL_MAIN + '/genres'
URL_TV = URL_MAIN + '/tv'
URL_TV_ALL = URL_MAIN + '/tv/all'
URL_TV_GENRES = URL_MAIN + '/tv/genres'
URL_SEARCH = URL_MAIN + '/search?q=%s'

# Ein Listeneintrag: Cover, Link, Titel, Rest der Überschrift (S..E.. und Flagge),
# danach der Beschreibungsblock mit Genre, Bewertung, Jahr und Laufzeit.
# Der Kommentar vor dem <a> steht nur in den Suchergebnissen, deshalb optional.
_RE_ENTRY = (r'<td width="115" valign="top">\s*<img src="([^"]+)"[^>]*>\s*</td>\s*'
             r'<td valign="top">\s*<h2[^>]*>\s*(?:<!--[^>]*-->\s*)?'
             r'<a href="([^"]+)"[^>]*>(.*?)</a>(.*?)</h2>\s*'
             r'<div class="beschreibung"[^>]*>(.*?)</span>')
# Genre-Kachel auf den beiden Genre-Übersichten
_RE_GENRE = (r'<a href="([^"]+)" class="genre-item">\s*<div class="genre-name">([^<]+)</div>')
# Staffel- und Episodenauswahl der Detailseite
_RE_SEASON_BOX = r'<select id="season-select".*?</select>'
_RE_EPISODE_BOX = r'<select id="episode-select".*?</select>'
_RE_SEASON_OPT = r'<option[^>]*>\s*S(\d+)\s*</option>'
_RE_EPISODE_OPT = r'<option value="([^"]+)"[^>]*data-name="([^"]*)"[^>]*data-overview="([^"]*)"[^>]*>\s*E(\d+)'
# Hoster: bei Filmen aus der Hosterauswahl, bei Episoden aus dem Block der Folge
_RE_MOVIE_HOSTER = r'<option value="(http[^"]+)"[^>]*data-quality="([^"]*)"'
_RE_EPISODE_BLOCK = r'data-episode-id="%s"(.*?)</table>'
_RE_EPISODE_HOSTER = r'''loadMirror\('(http[^']+)'\)"\s*data-host="[^"]+"\s*data-mirror="true"'''
# Kennzeichen einer Serie im Listeneintrag
_RE_SERIES_MARK = r'type=(?:tv|series)'
# Startseite und /tv liefern ihre drei Tabs (Updates/Kino/Beliebt bzw.
# Episoden/Beliebt/Trending) in EINEM Markup, umgeschaltet wird nur per
# Javascript — eigene Adressen je Tab gibt es nicht. Die Tab-Listen schneiden
# deshalb zuerst den Container ihres Tabs aus (_paneContent), sonst greifen die
# Muster auch im Nachbar-Tab und im Desktop-Block und mischen die Inhalte.
_PANE_UPDATES = 'tab-updates'  # Startseite: Updates · /tv: Episoden
_PANE_CINEMA = 'tab-cinema'    # Startseite: Kino · /tv: Beliebt
_PANE_POPULAR = 'tab-popular'  # Startseite: Beliebt · /tv: Trending
# Eintrag der Updates-/Episodenliste: Titelzeile mit Link, bei Folgen dahinter
# die S..E..-Angabe in einem zweiten font. Die "watch on"-Zeilen darunter
# stehen in einer eigenen Zelle (td height="20px") und matchen hier bewusst
# nicht — sie zeigen nur je Hoster denselben Titel noch einmal.
_RE_UPDATE = (r'<td valign="top" height="100%">\s*<a href="([^"]+)">\s*'
              r'<font[^>]*>\s*<strong>(.*?)</strong>\s*</font>\s*'
              r'(?:<font[^>]*>[^<]+</font>\s*)?</a>')
# Kachel der Beliebt-/Trending-Liste: Poster, danach der Titel-Link in der h2.
# Der Link am Poster selbst ist bei fehlendem Bild nur '#', deshalb zählt
# ausschließlich der Link aus der h2.
_RE_TILE = (r'<img src="([^"]+)"[^>]*>\s*</a>\s*</div>\s*<div[^>]*>\s*'
            r'<h2[^>]*>\s*<a href="([^"]+)">\s*'
            r'<font[^>]*>\s*<strong>(.*?)</strong>\s*</font>\s*'
            r'(?:<font[^>]*>[^<]+</font>\s*)?</a>')
# Poster der Detailseite: das og:image-Meta trägt dasselbe TMDB-Cover wie die
# Listen-Kacheln und existiert genau einmal je Detailseite — Übersichtsseiten
# haben es nicht. Dient als Cover-Quelle für Einstiege ohne Listen-Poster.
_RE_OG_IMAGE = r'<meta property="og:image" content="([^"]+)"'

# Qualitätsangabe der Seite auf eine Höhenangabe abbilden. Die Seite kennt nur
# diese vier Stufen; 'dvd' und 'cam' bekommen bewusst keine Auflösung, weil eine
# erfundene Zahl in der Hosterliste mehr verspricht als die Quelle hergibt.
QUALITY_MAP = {'hd': '720', 'sd': '480', 'dvd': '', 'cam': ''}




def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.movie2k.lastSearchText')

    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30500), SITE_IDENTIFIER, 'showNewMenu'))  # Neu auf der Seite
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30502), SITE_IDENTIFIER, 'showMoviesMenu'))  # Filme
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30511), SITE_IDENTIFIER, 'showSeriesMenu'))  # Serien

    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'))  # Search
    cGui().setEndOfDirectory()


def showNewMenu():  # Submenü Neu auf der Seite: Filme / Serien
    params = ParameterHandler()
    params.setParam('sUrl', URL_MAIN)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30502), SITE_IDENTIFIER, 'showUpdates'), params)  # Filme
    params = ParameterHandler()
    params.setParam('sUrl', URL_TV)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30511), SITE_IDENTIFIER, 'showUpdates'), params)  # Serien
    cGui().setEndOfDirectory()


def showMoviesMenu():  # Submenü Filme: Alle Filme / Kinofilme / Beliebt / Genre
    params = ParameterHandler()
    params.setParam('sUrl', URL_MOVIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30542), SITE_IDENTIFIER, 'showEntries'), params)  # Alle Filme
    params = ParameterHandler()
    params.setParam('sUrl', URL_MAIN)
    params.setParam('sPane', _PANE_CINEMA)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30530), SITE_IDENTIFIER, 'showEntries'), params)  # Kinofilme
    params = ParameterHandler()
    params.setParam('sUrl', URL_MAIN)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30874), SITE_IDENTIFIER, 'showTiles'), params)  # Beliebt
    params = ParameterHandler()
    params.setParam('sUrl', URL_MOVIE_GENRES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30506), SITE_IDENTIFIER, 'showGenres'), params)  # Genre
    cGui().setEndOfDirectory()


def showSeriesMenu():  # Submenü Serien: Alle Serien / Beliebt / Im Trend / Genre
    params = ParameterHandler()
    params.setParam('sUrl', URL_TV_ALL)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30518), SITE_IDENTIFIER, 'showEntries'), params)  # Alle Serien
    params = ParameterHandler()
    params.setParam('sUrl', URL_TV)
    params.setParam('sPane', _PANE_CINEMA)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30874), SITE_IDENTIFIER, 'showEntries'), params)  # Beliebt
    params = ParameterHandler()
    params.setParam('sUrl', URL_TV)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30565), SITE_IDENTIFIER, 'showTiles'), params)  # Im Trend
    params = ParameterHandler()
    params.setParam('sUrl', URL_TV_GENRES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30506), SITE_IDENTIFIER, 'showGenres'), params)  # Genre
    cGui().setEndOfDirectory()


def showGenres():
    # Genres werden aus der Übersicht der Seite gelesen, damit ein neues Genre
    # von selbst im Menü auftaucht.
    params = ParameterHandler()
    oRequest = cRequestHandler(_requestUrl(params.getValue('sUrl')))
    oRequest.cacheTime = 60 * 60 * 24  # 24 Stunden
    sHtmlContent = oRequest.request()
    isMatch, aResult = cParser.parse(sHtmlContent, _RE_GENRE)
    if not isMatch:
        cGui().showInfo()
        return
    total = len(aResult)
    for sUrl, sName in aResult:
        params = ParameterHandler()
        params.setParam('sUrl', _absoluteUrl(sUrl))
        # Ordner, nicht abspielbar: mit bIsFolder=False setzt gui.py MovieTitle und
        # playMode und Kodi versucht den Menüpunkt direkt zu starten.
        cGui().addFolder(cGuiElement(cUtil.unescape(sName).strip(), SITE_IDENTIFIER, 'showEntries'), params, True, total)
    cGui().setEndOfDirectory()


def _absoluteUrl(sUrl):
    # Macht aus einem Seitenlink eine vollständige Adresse. Sonderzeichen im Titel
    # stehen im Markup als HTML-Entität ("Don&#x27;t Say Good Luck") und werden hier
    # aufgelöst, sonst landet die Entität später in der Adresse und die Seite
    # antwortet mit ihrer 'Content Not Found'-Seite.
    # BEWUSST NICHT kodiert: die Adresse wandert als Parameter weiter, und
    # ParameterHandler.getParameterAsUri() jagt jeden Wert durch unquote_plus —
    # eine hier gesetzte Kodierung wäre auf dem Weg wieder aufgelöst. Kodiert wird
    # deshalb erst unmittelbar vor dem Abruf in _requestUrl.
    sUrl = cUtil.unescape(sUrl)
    if sUrl.startswith('//'):
        sUrl = 'https:' + sUrl
    elif sUrl.startswith('/'):
        sUrl = URL_MAIN + sUrl
    return sUrl


def _requestUrl(sUrl):
    # Kodiert unmittelbar vor dem Abruf. Genre- und Titel-Adressen der Seite
    # enthalten Leerzeichen, Umlaute und '&' ('Science Fiction', 'Action &
    # Adventure'); ohne Kodierung bricht der Requesthandler mit
    # "URL can't contain control characters" ab. '%' bleibt unangetastet, damit
    # bereits kodierte Adressen nicht ein zweites Mal kodiert werden.
    # Slash im Titel-Slug: die Seite verlinkt "Victor/Victoria" als
    # /stream/victor/victoria-1982-<id> und beantwortet genau diesen eigenen Link
    # mit 404, weil sie nur ueber die ID am Ende routet (gemessen 03.09.2026:
    # 2 von 891 Titeln, /stream/x-<id> liefert 200). Der Slash wird deshalb hier,
    # an der einzigen Abrufstelle, zum Bindestrich — so heilen auch Favoriten und
    # Cache-Eintraege mit der alten Adresse. Die Query bleibt unangetastet.
    # Dasselbe fuer '#' im Slug ("#9" als /stream/#9-2009-<id>, Audit 07.09.2026):
    # urllib wirft alles ab '#' als Fragment weg und die Seite antwortet mit 404;
    # /stream/-9-2009-<id> liefert 200. Deshalb endet der Slug-Teil erst am '?'.
    sUrl = re.sub(r'(/stream/)([^?]*)', lambda m: m.group(1) + m.group(2).replace('/', '-').replace('#', '-'), sUrl)
    return cParser.urlEncode(sUrl, safe=':/?&=%#+')


def _nextPageUrl(sHtmlContent, entryUrl):
    # Die aktuelle Seite steht nur in der aufgerufenen URL. Weitergeblättert wird
    # nur, wenn die Seite den Folgelink auch wirklich anbietet. Die Filmlisten
    # verlinken relativ ('?page=2'), die Serienlisten mit Pfad ('/tv/all?page=2') —
    # beide Formen werden hier abgedeckt.
    isMatch, sPage = cParser.parseSingleResult(entryUrl, r'[?&]page=(\d+)')
    iNext = (int(sPage) if isMatch else 1) + 1
    isMatch, sNextUrl = cParser.parseSingleResult(sHtmlContent, r'href="([^"]*[?&]page=%d)"' % iNext)
    if not isMatch:
        return False
    if sNextUrl.startswith('?'):
        sNextUrl = entryUrl.split('?')[0] + sNextUrl
    return _absoluteUrl(sNextUrl)


def _lastPage(sHtmlContent):
    """Letzte Seitenzahl aus der Blaetterleiste: die Seite verlinkt neben den
    Nachbarseiten auch die letzte (gemessen 04.09.2026: Alle Filme 321, Genre
    Drama 135, Alle Serien 7), die hoechste verlinkte Zahl ist damit das Ende.
    0, wenn die Leiste keine Zahlen fuehrt."""
    aPages = [int(p) for p in re.findall(r'href="[^"]*[?&]page=(\d+)"', sHtmlContent)]
    return max(aPages) if aPages else 0


def _paneContent(sHtmlContent, sPaneId):
    # Schneidet den Inhalt eines Tab-Containers aus dem Markup. Gezählt werden
    # öffnende und schließende div, damit verschachtelte Blöcke im Tab den
    # Schnitt nicht verfrühen — ein Muster "bis zum nächsten Tab" wäre von der
    # Reihenfolge der Container abhängig und liefe beim letzten Tab in den
    # Desktop-Block hinein. Kein Treffer ergibt '', der Aufrufer meldet dann
    # wie bei jeder leeren Liste über showInfo.
    oMatch = re.search(r'<div[^>]*id="%s"[^>]*>' % sPaneId, sHtmlContent)
    if not oMatch:
        return ''
    iStart = oMatch.end()
    iDepth = 1
    for oTag in re.finditer(r'<div\b|</div>', sHtmlContent[iStart:]):
        iDepth += 1 if oTag.group(0) == '<div' else -1
        if iDepth == 0:
            return sHtmlContent[iStart:iStart + oTag.start()]
    return sHtmlContent[iStart:]


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl: entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(_requestUrl(entryUrl), ignoreErrors=(sGui is not False))
    oRequest.cacheTime = 60 * 60 * 6  # 6 Stunden
    sHtmlContent = oRequest.request()
    # Kinofilme (Startseite) und Beliebt (/tv) sind Tabs ohne eigene Adresse —
    # hier wird nur ihr Container gelesen, damit die Nachbar-Tabs draußen bleiben.
    sPane = params.getValue('sPane')
    if sPane:
        sHtmlContent = _paneContent(sHtmlContent, sPane)
    isMatch, aResult = cParser.parse(sHtmlContent, _RE_ENTRY)
    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    # Startseite und Serienübersicht liefern jeden Eintrag zweimal, einmal für das
    # Desktop- und einmal für das Mobil-Layout. Ohne diesen Abgleich steht dort
    # alles doppelt in der Liste.
    seen = []
    aEntries = []
    for aEntry in aResult:
        if aEntry[1] in seen: continue
        seen.append(aEntry[1])
        aEntries.append(aEntry)

    total = len(aEntries)
    isTvshow = False
    iShown = 0
    for sThumbnail, sUrl, sTitle, sHeadRest, sDesc in aEntries:
        sName = cUtil.unescape(cUtil.removeHtmlTags(sTitle)).replace('[SERIE]', '').strip()
        if not sName: continue
        # Die Suche wirft Filme und Serien gemeinsam aus, erkennbar am type-Parameter
        # des Links; in den Listen steht er ohnehin nur bei Serien.
        isTvshow = bool(cParser.search(_RE_SERIES_MARK, sUrl))

        # Die Seite sucht im Beschreibungstext mit und liefert dadurch sehr viele
        # Treffer, die den Suchbegriff im Titel gar nicht führen. Verglichen wird
        # normalisiert (cParser.searchTitle): Interpunktion spielt keine Rolle,
        # und der Begriff aus der Tastatur des Nutzers ist kein Regex-Muster mehr.
        if sSearchText and not cParser.searchTitle(sSearchText, sName):
            continue

        isYear, sYear = cParser.parseSingleResult(sDesc, r'\|\s*(\d{4})\s*(?:&nbsp;)?\|')
        isRating, sRating = cParser.parseSingleResult(sDesc, r'Bewertung:\s*([\d.,]+)')
        isDuration, sDuration = cParser.parseSingleResult(sDesc, r'\|\s*(\d+)\s*Min')

        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons' if isTvshow else 'showHosters')
        oGuiElement.setMediaType('tvshow' if isTvshow else 'movie')
        oGuiElement.setThumbnail(sThumbnail)
        if isYear: oGuiElement.setYear(sYear)
        if isRating: oGuiElement.addItemValue('rating', sRating.replace(',', '.'))
        if isDuration: oGuiElement.addItemValue('duration', sDuration)

        params.setParam('entryUrl', _absoluteUrl(sUrl))
        params.setParam('sName', sName)
        params.setParam('sThumbnail', sThumbnail)
        if isYear: params.setParam('sYear', sYear)
        oGui.addFolder(oGuiElement, params, isTvshow, total)
        iShown += 1
    # Kamen Treffer an, wurden aber ALLE vom Titelfilter verworfen, stand
    # hier bisher ein leeres Verzeichnis ohne Hinweis (belegt mit "2019").
    # BEWUSST VOR dem Pagination-Block: dessen Bedingung schliesst die Suche
    # aus, die Meldung wuerde dort nie erreicht.
    if not sGui and not iShown:
        oGui.showInfo()

    if not sGui:
        sNextUrl = _nextPageUrl(sHtmlContent, entryUrl)
        if sNextUrl:
            params.setParam('sUrl', sNextUrl)
            # Seitenlage am Weiter-Eintrag, sofern die Leiste die letzte Seite nennt
            isMatch, sPageActive = cParser.parseSingleResult(entryUrl, r'[?&]page=(\d+)')
            oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', params,
                             cGui.pageInfo(sPageActive if isMatch else 1, _lastPage(sHtmlContent)))
        oGui.setView('tvshows' if isTvshow else 'movies')
        if not sSearchText:
            oGui.setEndOfDirectory()


def showUpdates():
    # Die Updates- bzw. Episodenliste der Seite: eine schlichte Textliste ohne
    # Cover und Beschreibung — mehr gibt die Quelle hier nicht her, gui.py legt
    # ersatzweise das Site-Logo auf die Einträge. Folgen verlinken mit
    # type=tv&season=N auf die Serienseite, der Eintrag führt deshalb in die
    # Staffelauswahl. Die S..E..-Angabe der Zeile wird bewusst NICHT angezeigt
    # (einsprachige Seite, der Klick zeigt ohnehin alle Staffeln — wie bei
    # filmpalast); sie steckt im Markup in einem eigenen font und bleibt damit
    # automatisch draußen, am Titel wird nichts geschnitten.
    params = ParameterHandler()
    oRequest = cRequestHandler(_requestUrl(params.getValue('sUrl')))
    oRequest.cacheTime = 60 * 60  # 1 Stunde — die Liste wächst laufend
    sHtmlContent = _paneContent(oRequest.request(), _PANE_UPDATES)
    isMatch, aResult = cParser.parse(sHtmlContent, _RE_UPDATE)
    if not isMatch:
        cGui().showInfo()
        return
    # Abgeglichen wird der Pfad ohne Staffel-Parameter: derselbe Titel steht je
    # Folgen-Update einmal drin, und dieselbe Serie kann mit MEHREREN Staffeln
    # im Feed stehen — ohne die Episodenangabe wären das ununterscheidbare
    # Doppelzeilen mit identischem Klickziel. Es bleibt der oberste, also der
    # neueste Eintrag.
    seen = []
    aEntries = []
    for aEntry in aResult:
        sKey = aEntry[0].split('?')[0]
        if sKey in seen: continue
        seen.append(sKey)
        aEntries.append(aEntry)
    total = len(aEntries)
    isTvshow = False
    for sUrl, sTitle in aEntries:
        sName = cUtil.unescape(cUtil.removeHtmlTags(sTitle)).strip()
        if not sName: continue
        isTvshow = bool(cParser.search(_RE_SERIES_MARK, sUrl))
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons' if isTvshow else 'showHosters')
        oGuiElement.setMediaType('tvshow' if isTvshow else 'movie')
        params.setParam('entryUrl', _absoluteUrl(sUrl))
        params.setParam('sName', sName)
        cGui().addFolder(oGuiElement, params, isTvshow, total)
    cGui().setView('tvshows' if isTvshow else 'movies')
    cGui().setEndOfDirectory()


def showTiles():
    # Beliebt (Startseite) und Trending (/tv) teilen sich denselben Container-
    # Slot und dasselbe Kachel-Markup; welche Liste kommt, entscheidet allein
    # die übergebene Adresse.
    params = ParameterHandler()
    oRequest = cRequestHandler(_requestUrl(params.getValue('sUrl')))
    oRequest.cacheTime = 60 * 60 * 6  # 6 Stunden
    sHtmlContent = _paneContent(oRequest.request(), _PANE_POPULAR)
    isMatch, aResult = cParser.parse(sHtmlContent, _RE_TILE)
    if not isMatch:
        cGui().showInfo()
        return
    # Abgleich wie in showUpdates über den Pfad ohne Staffel-Parameter —
    # auch Trending kann dieselbe Serie mit mehreren Staffeln führen.
    seen = []
    aEntries = []
    for aEntry in aResult:
        sKey = aEntry[1].split('?')[0]
        if sKey in seen: continue
        seen.append(sKey)
        aEntries.append(aEntry)
    total = len(aEntries)
    isTvshow = False
    for sThumbnail, sUrl, sTitle in aEntries:
        sName = cUtil.unescape(cUtil.removeHtmlTags(sTitle)).strip()
        if not sName: continue
        isTvshow = bool(cParser.search(_RE_SERIES_MARK, sUrl))
        # Ohne Poster liefert die Seite eine "No Poster"-Grafik vom
        # Platzhalterdienst — die bleibt draußen, gui.py legt dann wie bei den
        # Updates das Site-Logo auf den Eintrag.
        if 'placehold' in sThumbnail:
            sThumbnail = ''
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons' if isTvshow else 'showHosters')
        oGuiElement.setMediaType('tvshow' if isTvshow else 'movie')
        if sThumbnail:
            oGuiElement.setThumbnail(sThumbnail)
        # Bedingungslos setzen, sonst erbt eine Kachel ohne Poster über den
        # geteilten ParameterHandler das Bild der vorherigen.
        params.setParam('sThumbnail', sThumbnail)
        params.setParam('entryUrl', _absoluteUrl(sUrl))
        params.setParam('sName', sName)
        cGui().addFolder(oGuiElement, params, isTvshow, total)
    cGui().setView('tvshows' if isTvshow else 'movies')
    cGui().setEndOfDirectory()


def showSeasons():
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    sName = params.getValue('sName')
    sThumbnail = params.getValue('sThumbnail')
    sYear = params.getValue('sYear') or ''
    oRequest = cRequestHandler(_requestUrl(sUrl))
    oRequest.cacheTime = 60 * 60 * 6  # 6 Stunden
    sHtmlContent = oRequest.request()
    # Die Staffelliste kommt aus der Auswahlbox der Seite. Eine Staffelnummer zu
    # raten geht schief: eine zu hohe Nummer liefert kommentarlos wieder Staffel 1.
    isMatch, sContainer = cParser.parseSingleResult(sHtmlContent, _RE_SEASON_BOX)
    if isMatch:
        isMatch, aResult = cParser.parse(sContainer, _RE_SEASON_OPT)
    if not isMatch:
        cGui().showInfo()
        return
    isDesc, sDesc = cParser.parseSingleResult(sHtmlContent, r'<div class="beschreibung"[^>]*>(.*?)</div>')
    # Die Neu-Liste liefert keine Poster mit (reines Text-Markup) — dann kommt
    # das Cover von der ohnehin geladenen Detailseite (og:image). Über den
    # Parameter erben es auch die Episodenlisten. Platzhalter-Grafiken bleiben
    # wie überall draußen, dann greift das Site-Logo.
    if not sThumbnail:
        isPoster, sPoster = cParser.parseSingleResult(sHtmlContent, _RE_OG_IMAGE)
        if isPoster and 'placehold' not in sPoster:
            sThumbnail = sPoster
            params.setParam('sThumbnail', sThumbnail)
    total = len(aResult)
    for sSeason in aResult:
        oGuiElement = cGuiElement(cConfig().getLocalizedString(30512) + ' ' + str(sSeason), SITE_IDENTIFIER, 'showEpisodes')
        oGuiElement.setTVShowTitle(sName)
        oGuiElement.setSeason(sSeason)
        oGuiElement.setMediaType('season')
        oGuiElement.setThumbnail(sThumbnail)
        if sYear: oGuiElement.addItemValue('year', sYear)
        if isDesc: oGuiElement.setDescription(cUtil.unescape(cUtil.removeHtmlTags(sDesc)).strip())
        params.setParam('entryUrl', '%s?season=%s' % (sUrl.split('?')[0], sSeason))
        cGui().addFolder(oGuiElement, params, True, total)
    cGui().setView('seasons')
    cGui().setEndOfDirectory()


def showEpisodes():
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    sName = params.getValue('sName')
    sThumbnail = params.getValue('sThumbnail')
    sSeason = params.getValue('season')
    sShowName = params.getValue('TVShowTitle') or sName
    oRequest = cRequestHandler(_requestUrl(sUrl))
    oRequest.cacheTime = 60 * 60 * 4  # 4 Stunden
    sHtmlContent = oRequest.request()
    # Titel und Beschreibung der Folge liefert die Auswahlbox gleich mit, ein
    # zusätzlicher Abruf je Folge ist dadurch nicht nötig.
    isMatch, sContainer = cParser.parseSingleResult(sHtmlContent, _RE_EPISODE_BOX)
    if isMatch:
        isMatch, aResult = cParser.parse(sContainer, _RE_EPISODE_OPT)
    if not isMatch:
        cGui().showInfo()
        return
    total = len(aResult)
    for sEpisodeId, sEpisodeName, sEpisodeDesc, sEpisode in aResult:
        sTitle = '%s %s' % (cConfig().getLocalizedString(30513), sEpisode)
        if sEpisodeName.strip():
            sTitle = '%s - %s' % (sTitle, cUtil.unescape(cUtil.removeHtmlTags(sEpisodeName)).strip())
        oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setTVShowTitle(sShowName)
        oGuiElement.setSeason(sSeason)
        oGuiElement.setEpisode(sEpisode)
        oGuiElement.setMediaType('episode')
        oGuiElement.setThumbnail(sThumbnail)
        if sEpisodeDesc.strip():
            oGuiElement.setDescription(cUtil.unescape(cUtil.removeHtmlTags(sEpisodeDesc)).strip())
        params.setParam('entryUrl', sUrl)
        params.setParam('episodeId', sEpisodeId)
        cGui().addFolder(oGuiElement, params, False, total)
    cGui().setView('episodes')
    cGui().setEndOfDirectory()


def showHosters():
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    sEpisodeId = params.getValue('episodeId')
    hosters = []
    # getValue liefert bei fehlendem Parameter False, nicht einen leeren String —
    # ohne diese Prüfung landet das False im Requesthandler und der Aufruf bricht
    # mit einem TypeError ab statt still leer zu bleiben.
    if not sUrl:
        return hosters
    sHtmlContent = cRequestHandler(_requestUrl(sUrl), caching=False).request()
    if sEpisodeId:
        # Bei Serien liegen alle Folgen der Staffel samt ihrer Hoster im Markup;
        # es wird nur der Block der gewählten Folge ausgewertet.
        isMatch, sContainer = cParser.parseSingleResult(sHtmlContent, _RE_EPISODE_BLOCK % cParser.escape(sEpisodeId))
        if not isMatch: return hosters
        isMatch, aResult = cParser.parse(sContainer, _RE_EPISODE_HOSTER)
        if not isMatch: return hosters
        for sHosterUrl in aResult:
            hosters = _addHoster(hosters, sHosterUrl, '')
    else:
        isMatch, aResult = cParser.parse(sHtmlContent, _RE_MOVIE_HOSTER)
        if not isMatch: return hosters
        for sHosterUrl, sQuality in aResult:
            hosters = _addHoster(hosters, sHosterUrl, QUALITY_MAP.get(sQuality.lower(), ''))
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def _addHoster(hosters, sHosterUrl, sQuality):
    # Die Seite schreibt vereinzelt Mirror-Adressen mit nur einem Schraegstrich
    # ('https:/doodstream.com/...', belegt an Rick and Morty S1 E1). Ohne
    # Reparatur haelt der Blocked-Check die Adresse fuer einen unbekannten
    # Hoster und die Folge erscheint faelschlich ohne Quelle.
    sHosterUrl = re.sub(r'^(https?:)/+', r'\1//', sHosterUrl)
    # Der Blocked-Check bekommt die volle URL und liefert den Hostnamen zurueck.
    # Das Label der Seite taugt dafuer nicht: bei Filmen steht dort 'Vinovo', bei
    # Folgen 'vinovo.to' — nur die URL ist in beiden Wegen verlaesslich.
    isBlocked, sHosterName = cConfig().isBlockedHoster(sHosterUrl)  # Hoster aus settings.xml oder deaktivierten Resolver ausschließen
    if isBlocked: return hosters
    sDisplayedName = sHosterName
    if sQuality:
        sDisplayedName = '%s [I][%sp][/I]' % (sHosterName, sQuality)
    hosters.append({'link': sHosterUrl, 'name': sHosterName, 'displayedName': sDisplayedName,
                    'languageCode': '', 'quality': sQuality})
    return hosters


def getHosterUrl(sUrl=False):
    return [{'streamUrl': sUrl, 'resolved': False}]


def showSearch():
    win = xbmcgui.Window(10000)
    sSearchText = win.getProperty('xstream.movie2k.lastSearchText')
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30281))
        if not sSearchText: return
        win.setProperty('xstream.movie2k.lastSearchText', sSearchText)
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def _search(oGui, sSearchText):
    # Ohne Suchbegriff liefert die Seite eine beliebige Vorschlagsliste statt
    # eines leeren Ergebnisses, deshalb wird hier abgebrochen.
    if not sSearchText or not sSearchText.strip():
        return
    showEntries(URL_SEARCH % cParser.quote(sSearchText), oGui, sSearchText)
