# -*- coding: utf-8 -*-
# Python 3
# Always pay attention to the translations in the menu!
# Seite vollständig mit JSON erstellt


import json
import re
import xbmcgui
import time
from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger
from resources.lib.tools import cParser
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui

SITE_IDENTIFIER = 'moflix-stream'
SITE_NAME = 'Moflix-Stream'
SITE_ICON = 'moflix-stream.png'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'moflix-stream.xyz')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)

URL_MAIN = 'https://' + DOMAIN + '/'
# Die Suche laeuft ueber die SUCHSEITE, nicht ueber api/v1/search: seit dem
# 29.09.2026 legt der Betreiber genau die Such-Endpunkte (api/v1/search und die
# Titelliste api/v1/titles) hinter eine Cloudflare Managed Challenge — mit jedem
# Kopfsatz, mit Cookies, mit und ohne Referer (gemessen 01.10.2026); die Listen-
# Endpunkte (channel, titles/<id>, episodes) kommen durch. Die Seite ist eine
# Single-Page-App und rendert ihre Suchtreffer serverseitig als JSON in das
# HTML (`window.bootstrapData`, Loader `searchPage`): dieselbe Suchmaschine wie
# die API (unscharf: „koenig" findet Koenig-Titel, „spider man" Spider-Man),
# derselbe Deckel von 20 Treffern, dieselben Felder.
URL_SEARCH = URL_MAIN + 'search/%s'
_RE_BOOTSTRAP = re.compile(r'bootstrapData\s*=\s*(\{.*?\})\s*;?\s*</script>', re.S)
# paginate=lengthAware statt simple: dann nennt die Antwort `total` (gemessen
# 10.09.2026: movies 9042, now-playing 7057, series 372, Kollektionen ihre
# Groesse), und daraus wird die Seitenlage am Weiter-Eintrag — bei gleicher
# Antwortzeit und gleichem Inhalt. Mit `simple` stand dort `total: null`.
URL_VALUE = URL_MAIN + 'api/v1/channel/%s?channelType=channel&restriction=&paginate=lengthAware'
# Kanaele der Startseite, die das Menue selbst fuehrt (load) — showCollections laesst sie aus
MENU_CHANNELS = ('now-playing', 'movies', 'top-rated-movies', 'top-10-movies-serien', 'trending-tv', 'series')
URL_HOSTER = URL_MAIN + 'api/v1/titles/%s?load=images,genres,productionCountries,keywords,videos,primaryVideo,seasons,compactCredits'


def load():
    logger.info("Load %s" % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.moflix-stream.lastSearchText')
    params = ParameterHandler()
    params.setParam('page', (1))
    params.setParam('sUrl', URL_VALUE % 'now-playing')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30500), SITE_IDENTIFIER, 'showEntries'), params)  # Neues
    # Menue nach filmpalast-Vorbild (Jack 10.09.2026 spaet, „wenn wir schon dabei sind“):
    # Filme und Serien als Untermenues mit je zwei Listen, dazwischen die gemischte
    # Rangliste „Top 10“ (Kanal top-10-movies-serien, 20 Eintraege), Suche zuletzt. Die
    # Untermenues halten Liste, Rangliste und Kollektionen bzw. Liste und Neuzugang
    # zusammen — vorher standen alle acht Eintraege flach.
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30502), SITE_IDENTIFIER, 'showMoviesMenu'))  # Filme (Untermenue)
    params.setParam('sUrl', URL_VALUE % 'top-10-movies-serien')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30883), SITE_IDENTIFIER, 'showEntries'), params)  # Top 10
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30511), SITE_IDENTIFIER, 'showSeriesMenu'))  # Serien (Untermenue)
    # Die Suche erbt die sUrl des letzten Eintrags mit Parametern (gemeinsamer
    # ParameterHandler, Referer haengt daran) — die Top-10-Adresse; sie liegt auf der
    # eigenen Domain, mehr braucht die API nicht. Kollektionen sind Filmreihen und
    # stehen im Filme-Untermenue (Jack 10.09.2026: „gehoert eigentlich zu Filmen“).
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'), params)  # Search
    cGui().setEndOfDirectory()


def showMoviesMenu():
    """Untermenue Filme: Alle Filme (Kanal movies), Top Filme (top-rated-movies) und die
    Kollektionen (Filmreihen der Startseite)."""
    params = ParameterHandler()
    params.setParam('page', 1)
    params.setParam('sUrl', URL_VALUE % 'movies')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30542), SITE_IDENTIFIER, 'showEntries'), params)  # Alle Filme
    params.setParam('sUrl', URL_VALUE % 'top-rated-movies')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30509), SITE_IDENTIFIER, 'showEntries'), params)  # Top Filme
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30543), SITE_IDENTIFIER, 'showCollections'), params)  # Kollektionen
    cGui().setEndOfDirectory()


def showSeriesMenu():
    """Untermenue Serien: Neue Serien (trending-tv, „Freshly added series“ der Seite —
    zuletzt eingestellte Serien) und Alle Serien (Kanal series)."""
    params = ParameterHandler()
    params.setParam('page', 1)
    # Neuzugang zuerst, dann die Gesamtliste (Jack 10.09.2026: „bei Serien sollten neue
    # Serien oben sein“ — wie Neu vor Filme im Hauptmenue)
    params.setParam('sUrl', URL_VALUE % 'trending-tv')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30884), SITE_IDENTIFIER, 'showEntries'), params)  # Neue Serien
    params.setParam('sUrl', URL_VALUE % 'series')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30518), SITE_IDENTIFIER, 'showEntries'), params)  # Alle Serien
    cGui().setEndOfDirectory()


def showCollections():
    """Kollektionen der Seite, gelesen aus dem Startseiten-Kanal der API.

    `channel/homepage` liefert alle Kanaele der Startseite (10.09.2026: 36, davon
    30 Kollektionen). Eine Kollektion ist ein Kanal im Grid-Layout, der weder News
    ist noch ueber die Auto-Methoden der Seite laeuft (Top 10 = moflixTop10,
    Releasing soon = upcoming) und nicht schon als eigener Menuepunkt gefuehrt
    wird (MENU_CHANNELS). Mehr laesst die Konfiguration nicht unterscheiden —
    „Herr der Ringe“ traegt exakt dieselben Felder wie „Now playing“. Bis zum
    10.09.2026 stand hier eine feste Liste mit 29 Slugs; die Seite fuehrte da schon
    30 (Final Destination fehlte). Namen sind die der Seite.
    """
    oGui = cGui()
    params = ParameterHandler()
    oRequest = cRequestHandler(URL_VALUE % 'homepage')
    oRequest.addHeaderEntry('Referer', URL_MAIN)
    jHome = oRequest.requestJson()
    aChannels = ((jHome or {}).get('channel') or {}).get('content', {}).get('data') or []
    collections = []
    for jChannel in aChannels:
        jConfig = jChannel.get('config') or {}
        if jConfig.get('layout') != 'grid' or jConfig.get('contentModel') == 'newsArticle':
            continue
        if jConfig.get('autoUpdateMethod') in ('moflixTop10', 'upcoming') or jChannel.get('slug') in MENU_CHANNELS:
            continue
        sName = (jChannel.get('name') or '').strip()
        sSlug = jChannel.get('slug') or ''
        if sName and sSlug:
            collections.append({'name': sName, 'slug': sSlug})
    if not collections:
        oGui.showInfo()
        return
    for coll in sorted(collections, key=lambda x: x['name'].lower()):
        params.setParam('sUrl', URL_VALUE % coll['slug'])
        oGui.addFolder(cGuiElement(coll['name'], SITE_IDENTIFIER, 'showEntries'), params)
    oGui.setEndOfDirectory()


def _handlerWasSilent(oRequest):
    """Hat der requestHandler zu diesem Fehlfall selbst schon etwas gesagt?

    Er meldet von sich aus bei Timeout, Cloudflare/DDoS-Sperre, URL-Fehler und
    bei 4xx/5xx. In all diesen Faellen darf hier KEINE zweite Meldung kommen,
    sonst sieht der Nutzer zwei Hinweise hintereinander.

    Stumm bleibt genau ein Fall: die Antwort war technisch in Ordnung (2xx/3xx),
    enthielt aber kein brauchbares JSON — die API liefert ihre Fehlerseite als
    HTTP 200 mit HTML. Nur dann meldet der Aufrufer selbst.

    Ohne Status (leerer String) lag ein Transportfehler vor, den der Handler
    bereits angezeigt hat.
    """
    try:
        iStatus = int(oRequest.getStatus())
    except (TypeError, ValueError):
        return False
    return 200 <= iStatus < 400


def showEntries(entryUrl=False, sGui=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl:
        entryUrl = params.getValue('sUrl')
    iPage = int(params.getValue('page'))
    oRequest = cRequestHandler(entryUrl + '&page=' + str(iPage) if iPage > 0 else entryUrl, ignoreErrors=(sGui is not False))
    oRequest.addHeaderEntry('Referer', params.getValue('sUrl'))
    jSearch = oRequest.requestJson()
    if not jSearch:
        if not sGui and _handlerWasSilent(oRequest): oGui.showInfo()
        return
    # Die Kanal-API deckelt bei Seite 100: hoehere Seiten liefern Seite 100 erneut, mit
    # next_page 101 — ein endloser Weiter-Eintrag (gemessen 10.09.2026 im Listenende-Test,
    # galt schon mit paginate=simple). Erkennbar nur daran, dass die Antwort eine kleinere
    # Seite nennt als angefragt: dann ist das Ende erreicht, Meldung wie bei jeder Site
    # hinter der letzten Seite.
    jClamp = ((jSearch.get('channel') or {}).get('content') or {}) if isinstance(jSearch, dict) else {}
    if iPage > 0 and jClamp.get('current_page') and int(jClamp['current_page']) < iPage:
        if not sGui:
            oGui.showInfo()
        return
    aResults = jSearch['channel']['content']['data']
    # NICHT sortieren: die Liste kommt seitenweise (50 je Seite), und die Seite liefert
    # ihre eigene Ordnung mit (config.contentOrder, z.B. popularity:desc oder
    # created_at:desc). Alphabetisch je Seite zu sortieren zerstoert diese Ordnung und
    # ist trotzdem nur innerhalb einer Seite alphabetisch. Die Suche sortiert weiterhin
    # (showSearchEntries) - dort liegt die vollstaendige Trefferliste auf einmal vor.
    total = len(aResults)
    if len(aResults) == 0:
        if not sGui: oGui.showInfo()
        return
    for i in aResults:
        sId = str(i['id'])
        sName = str(i['name'])
        if 'is_series' in i: isTvshow = i['is_series']
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons' if isTvshow else 'showHosters')
        if 'release_date' in i and len(str(i['release_date'].split('-')[0].strip())) != '': 
            oGuiElement.setYear(str(i['release_date'].split('-')[0].strip()))
        if 'description' in i and i['description'] != '': 
            oGuiElement.setDescription(str(i['description']))
        if 'poster' in i and i['poster'] != '': 
            oGuiElement.setThumbnail(str(i['poster']))
        if 'backdrop' in i and i['backdrop'] != '': 
            oGuiElement.setFanart(str(i['backdrop']))
        if 'runtime' in i and i['runtime'] != None: 
            oGuiElement.addItemValue('duration', str(i['runtime']))
        if 'rating' in i and i['rating'] != None: 
            oGuiElement.addItemValue('rating', str(i['rating']))
        oGuiElement.setMediaType('tvshow' if isTvshow else 'movie')
        params.setParam('entryUrl', URL_HOSTER % sId)
        params.setParam('sThumbnail', i['poster'])
        params.setParam('sName', sName)
        # Aki: Year an showSeasons weitergeben
        if 'release_date' in i and i['release_date']:
            sYearTmp = str(i['release_date'].split('-')[0].strip())
            if sYearTmp: params.setParam('sYear', sYearTmp)
        oGui.addFolder(oGuiElement, params, isTvshow, total)
    if not sGui:
        # Weiter-Eintrag nur, wenn die Seite tatsaechlich eine Folgeseite meldet.
        # next_page steht in derselben Antwort und kostet keinen Zusatzabruf; ohne die
        # Pruefung landet der Nutzer am Listenende auf "Es wurde kein Eintrag gefunden"
        # (belegt an "Top Filme": 21 Eintraege, next_page null, Seite 2 leer).
        jContent = jSearch['channel']['content']
        if jContent.get('next_page'):
            sPageNr = int(params.getValue('page'))
            if sPageNr == 0:
                sPageNr = 2
            else:
                sPageNr += 1
            params.setParam('page', int(sPageNr))
            # Seitenlage aus derselben Antwort: current_page, per_page und total
            # (Quelle 3 der Seitenlage-Regel, kein Zusatzabruf); fehlt total,
            # bleibt der Eintrag wie immer
            sPageInfo = ''
            try:
                if jContent.get('total') and jContent.get('per_page'):
                    sPageInfo = cGui.pageInfo(jContent.get('current_page'), -(-int(jContent['total']) // int(jContent['per_page'])))
            except (TypeError, ValueError):
                sPageInfo = ''
            oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', params, sPageInfo)
        oGui.setView('tvshows' if isTvshow else 'movies')
        oGui.setEndOfDirectory()


# Pause vor jedem Nachholversuch: gibt einem Rate-Limit Luft. Laenger kostet
# nur im Fehlerfall — im Normalfall laeuft keine einzige Pause.
RETRY_PAUSE = 0.6


def showSeasons(sGui=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    # Form: api/v1/titles/<id>?load=images,genres,productionCountries,keywords,videos,primaryVideo,seasons,compactCredits
    entryUrl = params.getValue('entryUrl')
    sThumbnail = params.getValue('sThumbnail')
    sTmdbID = params.getValue('tmdbID') or ''
    sName = params.getValue('sName') or ''
    sYear = params.getValue('sYear') or ''  # Aki: Year aus Listen-Ebene uebernehmen
    # Immer beim ersten Block anfangen (ohne &page); die Schleife unten holt den Rest.
    oRequest = cRequestHandler(entryUrl)
    oRequest.addHeaderEntry('Referer', entryUrl)
    jSearch = oRequest.requestJson()
    if not jSearch:
        if not sGui and _handlerWasSilent(oRequest): oGui.showInfo()
        return
    sDesc = jSearch['title']['description']
    aResults = jSearch['seasons']['data']
    # Die Seite liefert Staffeln ABSTEIGEND und in 8er-Bloecken. Wer nur den ersten
    # Block nimmt und ihn sortiert, zeigt bei laengeren Serien die spaeten Staffeln
    # zuerst und versteckt Staffel 1 hinter "Naechste Seite" (Stargate: 3-10, dann 1-2).
    # Deshalb hier ALLE Bloecke holen und danach aufsteigend ausgeben — die Staffelebene
    # blaettert nicht mehr. Kostet nur bei Serien mit mehr als 8 Staffeln einen
    # Zusatzabruf (gemessen Supernatural, 15 Staffeln: 0,44 s -> 0,72 s).
    iNext = jSearch['seasons'].get('next_page')
    while iNext:
        oRequestNext = cRequestHandler(entryUrl + '&page=' + str(iNext))
        oRequestNext.addHeaderEntry('Referer', entryUrl)
        jNext = oRequestNext.requestJson()
        if not jNext or not jNext.get('seasons'):
            # Ein gescheiterter Block beendete die Sammlung bisher STILL — bei
            # Serien mit mehr als 8 Staffeln fehlten dann Staffeln ohne jede
            # Meldung. Einmal mit Pause nachfassen (Referer bleibt gesetzt,
            # ohne ihn antwortet die API mit 401); bleibt der Block weg, wird
            # der Abbruch wenigstens geloggt.
            time.sleep(RETRY_PAUSE)
            oRequestNext = cRequestHandler(entryUrl + '&page=' + str(iNext))
            oRequestNext.addHeaderEntry('Referer', entryUrl)
            jNext = oRequestNext.requestJson()
            if not jNext or not jNext.get('seasons'):
                logger.info('fetchRetry %s: Staffel-Block %s weiterhin nicht erreichbar, restliche Staffeln fehlen' % (SITE_NAME, iNext))
                break
            logger.info('fetchRetry %s: Staffel-Block %s nachgeholt' % (SITE_NAME, iNext))
        aResults += jNext['seasons']['data']
        iNext = jNext['seasons'].get('next_page')
    aResults = sorted(aResults, key=lambda k: k['number'])
    total = len(aResults)
    if len(aResults) == 0:
        if not sGui: oGui.showInfo()
        return
    for i in aResults:
        sId = str(i['title_id']) # ID ändert sich !!!
        sSeasonNr = str(i['number'])
        oGuiElement = cGuiElement(cConfig().getLocalizedString(30512) + ' ' + sSeasonNr, SITE_IDENTIFIER, 'showEpisodes')
        oGuiElement.setMediaType('season')
        oGuiElement.setSeason(sSeasonNr)
        if sName:
            oGuiElement.setTVShowTitle(sName)
        if sTmdbID:
            oGuiElement.addItemValue('tmdb_id', sTmdbID)
        if sYear:
            oGuiElement.addItemValue('year', sYear)  # Aki: Year auf Staffel setzen
        oGuiElement.setThumbnail(sThumbnail)
        if sDesc != '': 
            oGuiElement.setDescription(str(sDesc))
        params.setParam('sSeasonNr', sSeasonNr)
        params.setParam('sId', sId)
        cGui().addFolder(oGuiElement, params, True, total)
    cGui().setView('seasons')
    cGui().setEndOfDirectory()


def showEpisodes(sGui=False):
    oGui = cGui()
    params = ParameterHandler()
    sId = params.getValue('sId')
    sSeasonNr = params.getValue('sSeasonNr')
    sTVShowTitle = params.getValue('sName') or ''
    sUrl = URL_MAIN + 'api/v1/titles/%s/seasons/%s/episodes?perPage=100&query=&page=1' % (sId, sSeasonNr) #Hep 02.12.23: Abfrage für einzelne Episoden per query force auf 100 erhöht
    oRequest = cRequestHandler(sUrl)
    oRequest.addHeaderEntry('Referer', sUrl)
    jSearch = oRequest.requestJson()
    if not jSearch:
        if not sGui and _handlerWasSilent(oRequest): oGui.showInfo()
        return
    aResults = jSearch['pagination']['data']
    total = len(aResults)
    if len(aResults) == 0:
        if not sGui: oGui.showInfo()
        return
    iAdded = 0
    for i in aResults:
        if 'primary_video' in i and i['primary_video'] == None: continue # no video available (skip this entry)
        sName = str(i['name'])
        sEpisodeNr = str(i['episode_number'])
        sThumbnail = str(i['poster'])
        oGuiElement = cGuiElement(cConfig().getLocalizedString(30513) + ' ' + sEpisodeNr + ' - ' + sName, SITE_IDENTIFIER, 'showHosters')
        if 'description' in i and i['description'] != '': oGuiElement.setDescription(i['description'])
        oGuiElement.setEpisode(sEpisodeNr)
        oGuiElement.setSeason(sSeasonNr)
        oGuiElement.setMediaType('episode')
        if sTVShowTitle: oGuiElement.setTVShowTitle(sTVShowTitle)
        oGuiElement.setThumbnail(sThumbnail)
        if 'runtime' in i and i['runtime'] != None: 
            oGuiElement.addItemValue('duration', str(i['runtime']))
        if 'rating' in i and i['rating'] != None: 
            oGuiElement.addItemValue('rating', str(i['rating']))
        params.setParam('entryUrl', URL_MAIN + 'api/v1/titles/%s/seasons/%s/episodes/%s?load=videos,compactCredits,primaryVideo' % (sId, sSeasonNr, sEpisodeNr))
        oGui.addFolder(oGuiElement, params, False, total)
        iAdded += 1
    if iAdded == 0:
        # Die API kann eine Staffel liefern, deren Episoden alle noch ohne
        # Video sind (primary_video null) — oben wird dann jeder Eintrag
        # uebersprungen und der Nutzer saehe ein leeres Verzeichnis ohne
        # jeden Hinweis. Belegt an "Alice in Borderland" Staffel 3.
        if not sGui: oGui.showInfo()
        return
    oGui.setView('episodes')
    oGui.setEndOfDirectory()


def _mergeTitleSearch(aResults, sSearchText):
    """Treffer der Kanal-Abfrage ergaenzen.

    Die Suche der Seite deckelt hart bei 20 Treffern und sortiert nach eigener
    Relevanz. Bei Titeln, die mit einem haeufigen Wort beginnen, faellt der
    exakte Treffer dadurch aus der Liste: "Der Kinderfluesterer" und "The Last
    Sunrise" stehen im Katalog, kommen aber unter den 20 nicht vor, waehrend
    "Kinderfluesterer" ohne Artikel sie findet (gemessen 31.08.2026).

    Der Kanal-Endpunkt (unsere Listen-API) beachtet `query=` und sucht enger —
    Teilstring im Titel und Originaltitel, Filme und Serien je ein Aufruf —
    und findet genau diese Faelle, liefert dafuer insgesamt weniger (walking
    dead 6 gegen 14). Deshalb wird ERGAENZT statt getauscht — gemessen bleibt
    die Breite erhalten (01.10.2026: star wars 20 -> 27, der Kinderfluesterer
    +1, alive +3, walking dead und matrix unveraendert). Bis zum 30.09.2026
    kam die Ergaenzung von api/v1/titles?query= — der Endpunkt liegt seitdem
    hinter der Cloudflare-Challenge (siehe URL_SEARCH).

    Kanal-Eintraege tragen dieselben Feldnamen wie die Suchtreffer, die
    Ausgabeschleife braucht also keine Sonderbehandlung. Entdoppelt wird ueber
    die id.
    """
    if not sSearchText:
        return aResults
    aExtra = []
    for sChannel in ('movies', 'series'):
        oRequest = cRequestHandler(URL_VALUE % sChannel + '&query=' + cParser.quotePlus(sSearchText), ignoreErrors=True)
        oRequest.addHeaderEntry('Referer', URL_MAIN)
        jChannel = oRequest.requestJson()
        if not isinstance(jChannel, dict):
            continue
        aData = ((jChannel.get('channel') or {}).get('content') or {}).get('data')
        if isinstance(aData, list):
            aExtra.extend(aData)
    if not aExtra:
        return aResults
    # Die Kanal-Abfrage sucht nur im Titel — inklusive Originaltitel: sie findet
    # „Krieg der Sterne" fuer „star wars". Der Titelfilter der Ausgabeschleife warf
    # genau diesen Treffer wieder weg, auch wenn ihn die Suche der Seite ebenfalls
    # lieferte. Alles, was die Kanal-Abfrage kennt, wird markiert und
    # ueberspringt den Filter (gemessen 02.09.2026 ueber 7 Begriffe: +1, -0).
    aTitleIds = set(str(x.get('id')) for x in aExtra if isinstance(x, dict) and x.get('name'))
    for x in aResults:
        if isinstance(x, dict) and str(x.get('id')) in aTitleIds:
            x['_titleHit'] = True
    aSeen = set(str(x.get('id')) for x in aResults if isinstance(x, dict))
    for x in aExtra:
        if not isinstance(x, dict) or not x.get('name'):
            continue
        if str(x.get('id')) in aSeen:
            continue
        aSeen.add(str(x.get('id')))
        x['_titleHit'] = True
        aResults.append(x)
    return aResults


def _searchPageResults(sHtmlContent):
    """Die Treffer aus dem HTML der Suchseite — None, wenn die Seite keine traegt.

    Die Trefferliste steht als JSON im Inline-Skript `window.bootstrapData`
    unter loaders.searchPage.results (Aufbau in URL_SEARCH). Kein JSON, kein
    Loader oder keine Liste heisst: die Antwort war keine Suchseite — ein
    Fehler-Sentinel des requestHandlers, eine Fehlerseite der Seite oder ein
    Begriff, fuer den die Seite keinen Loader rechnet.
    """
    oMatch = _RE_BOOTSTRAP.search(sHtmlContent or '')
    if not oMatch:
        return None
    try:
        jBoot = json.loads(oMatch.group(1))
    except ValueError:
        return None
    if not isinstance(jBoot, dict):
        return None
    jPage = (jBoot.get('loaders') or {}).get('searchPage')
    aResults = jPage.get('results') if isinstance(jPage, dict) else None
    return aResults if isinstance(aResults, list) else None


def showSearchEntries(entryUrl=False, sGui=False, sSearchText=''):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl: entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    oRequest.addHeaderEntry('Referer', URL_MAIN)
    aResults = _searchPageResults(oRequest.request())
    if aResults is None:
        if not sGui and _handlerWasSilent(oRequest): oGui.showInfo()
        return
    aResults = _mergeTitleSearch(aResults, sSearchText)
    aResults = sorted(aResults, key=lambda x: x['name'].lower())
    total = len(aResults)
    if len(aResults) == 0:
        if not sGui: oGui.showInfo()
        return
    isTvshow = False
    iShown = 0
    for i in aResults:
        if 'person' in i['model_type']: continue # Personen in der Suche ausblenden
        sId = str(i['id'])
        sName = str(i['name'])
        # release_date fehlt bei manchen Eintraegen bzw. kann None sein. Ohne
        # Absicherung wirft der Zugriff und bricht die GANZE Suchliste ab
        # (KeyError/AttributeError, nachgestellt: 0 statt Treffer). Personen
        # fangen wir eine Zeile weiter oben schon ab — der Schutz gilt dem Rest.
        sYear = str((i.get('release_date') or '').split('-')[0].strip())
        if sSearchText.lower() and not i.get('_titleHit') and not cParser.searchTitle(sSearchText, sName.lower()): continue
        if 'is_series' in i: isTvshow = i['is_series']
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons' if isTvshow else 'showHosters')
        if sYear != '': 
            oGuiElement.setYear(sYear)
        if 'description' in i and i['description'] != '': 
            oGuiElement.setDescription(str(i['description']))
        if 'poster' in i and i['poster'] != '': 
            oGuiElement.setThumbnail(str(i['poster']))
        if 'backdrop' in i and i['backdrop'] != '': 
            oGuiElement.setFanart(str(i['backdrop']))
        if 'runtime' in i and i['runtime'] != None: 
            oGuiElement.addItemValue('duration', str(i['runtime']))
        if 'rating' in i and i['rating'] != None: 
            oGuiElement.addItemValue('rating', str(i['rating']))
        oGuiElement.setMediaType('tvshow' if isTvshow else 'movie')
        params.setParam('entryUrl', URL_HOSTER % sId)
        params.setParam('sThumbnail', i['poster'])
        params.setParam('sName', sName)
        oGui.addFolder(oGuiElement, params, isTvshow, total)
        iShown += 1
    if not sGui:
        oGui.setView('tvshows' if isTvshow else 'movies')
        # Kamen Treffer an, wurden aber ALLE vom Titelfilter verworfen,
        # stand hier bisher ein leeres Verzeichnis ohne jeden Hinweis
        # (belegt mit dem Suchbegriff "2019"). Klasse (H): lieber die
        # normale Kein-Inhalt-Meldung als eine stumme leere Liste.
        if not iShown:
            oGui.showInfo()
        oGui.setEndOfDirectory()


def showHosters(sGui=False):
    oGui = sGui if sGui else cGui()
    hosters = []
    sUrl = ParameterHandler().getValue('entryUrl')
    oRequest = cRequestHandler(sUrl, caching=False)
    oRequest.addHeaderEntry('Referer', sUrl)
    jSearch = oRequest.requestJson()
    if not jSearch: return
    if ParameterHandler().getValue('mediaType') == 'movie':
        aResults = jSearch['title']['videos']
    else:
        aResults = jSearch['episode']['videos']
    if len(aResults) == 0:
        if not sGui: oGui.showInfo()
        return
    for i in aResults:
        sQuality = str(i['quality'])
        if 'None' in sQuality: 
            sQuality = '720p'
        sUrl = str(i['src'])
        if 'Mirror' in i['name']: # Wenn Mirror als sName hole realen Name aus der URL
            sName = cParser.urlparse(sUrl)
        else:
            sName = str(i['name'].split('-')[0].strip())
        if cConfig().isBlockedHoster(sUrl)[0]: continue  # Hoster aus settings.xml oder deaktivierten Resolver ausschließen
        if 'youtube' in sUrl: continue # Trailer ausblenden
        hoster = {'link': sUrl, 'name': sName, 'displayedName': '%s [I][%s][/I]' % (sName, sQuality), 'quality': sQuality}
        hosters.append(hoster)
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def getHosterUrl(sUrl=False):
    return [{'streamUrl': sUrl, 'resolved': False}]


def showSearch():
    win = xbmcgui.Window(10000)
    sSearchText = win.getProperty('xstream.moflix-stream.lastSearchText')
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30281))
        if not sSearchText: return
        win.setProperty('xstream.moflix-stream.lastSearchText', sSearchText)
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def _search(oGui, sSearchText):
    # Form: search/Super%20Mario — der Begriff steht im Pfad mit quote
    showSearchEntries(URL_SEARCH % cParser.quote(sSearchText), oGui, sSearchText)
