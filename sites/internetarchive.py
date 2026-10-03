# -*- coding: utf-8 -*-
# Python 3
# Always pay attention to the translations in the menu!


import json
import re
from urllib.parse import urlencode

import xbmcgui
from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger
from resources.lib.tools import cParser, cUtil
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui

SITE_IDENTIFIER = 'internetarchive'
SITE_NAME = 'Internet Archive'
SITE_ICON = 'internetarchive.png'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'archive.org')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)

URL_MAIN = 'https://' + DOMAIN
URL_MOVIE = URL_MAIN + '/details/'
URL_SEARCH_API = URL_MAIN + '/advancedsearch.php'

# Eintraege je Seite. Hier stand frueher 80000 — der Scraper holte damit bei
# JEDEM Aufruf zehntausende Eintraege und warf nach dem Filtern die meisten
# wieder weg (gemessen: 7 s fuer 28.000 Zeilen gegenueber 0,2 s fuer 50).
ITEMS_PER_PAGE = 50
# Die API gibt hoechstens 10.000 Treffer heraus (danach leeres Ergebnisfeld),
# gemessen 04.09.2026: ab Seite 201 kommt nur noch die Meldung. Die Seitenlage am
# Weiter-Eintrag nennt deshalb hoechstens 200 als letzte Seite, und der
# Weiter-Eintrag selbst endet dort (_hasNextPage) — vorher stand auf Seite 200
# noch ein Weiter, das in die leere Seite 201 fuehrte (Audit 07.09.2026).
MAX_PAGES = 200

# Sammlungen, die nicht ins Menue sollen. Geprueft wird gegen Kennung UND
# Titel, weil die Seite beides frei vergibt und mal das eine, mal das andere
# eindeutig ist.
BLOCKED_WORDS = ('hentai', 'adult', 'erotic', 'porn', 'xxx', 'nsfw', 'nude',
                 'playboy', 'fetish', 'bdsm')

# Sprachkennungen je xStream-Einstellung (1 Deutsch, 2 Englisch, 3 Japanisch).
# Die Seite laesst das Sprachfeld frei beschriften, deshalb stehen je Sprache
# die ISO-Kurzformen (zwei- und dreistellig), der englische Name und bei
# Deutsch die Eigenbezeichnung drin — gemessen ueber alle deutschsprachigen
# Filme der Seite: 'ger' 55.000, 'German' 28.000, 'de' 500, 'Deutsch' 150,
# 'deu' 80. Bei Japanisch ist 'jpn' mit 96 Prozent die Hauptform. Die Suche
# der Seite vergleicht wortweise und ohne Gross-/Kleinschreibung, 'german'
# trifft also auch 'German' und 'GERMAN'. Aus derselben Tabelle entsteht die
# Abfrage UND die Nachpruefung in _langOk, damit beide nie auseinanderlaufen.
LANG_TOKENS = {'1': ('ger', 'german', 'deu', 'de', 'deutsch'),
               '2': ('eng', 'english', 'en'),
               '3': ('jpn', 'japanese', 'jap', 'ja', 'jp')}
LANG_FILTER = {k: '(' + ' OR '.join(v) + ')' for k, v in LANG_TOKENS.items()}

# Woerter, die eine Untertitel- oder Textspur ankuendigen. Steht die gesuchte
# Sprache im selben Teilsatz wie eines davon, ist sie nur Untertitel.
_RE_SUB_WORD = re.compile(r'^(?:sub.*|cc|untertitel|text|titles)$')
# Trenner zwischen den Teilsaetzen eines Sprachfelds: Komma, Semikolon,
# Schraegstrich, Plus, Und-Zeichen, das Wort „with" und die Seitenmarke ':::'
_RE_LANG_CLAUSE = re.compile(r'[,;/|+&]|\bwith\b|\bw/|:::')
_RE_LANG_PAREN = re.compile(r'\([^)]*\)')
_RE_LANG_WORD = re.compile(r'[^\W\d_]+')

# Playlist des Seiten-Players: die Embed-Seite traegt sie als JSON-Array im
# playlist-Attribut des play-av-Elements — je Video Titel, Datei(en) und
# Vorschaubild. Einzige Stelle, an der die Seite ihre Videoliste fertig
# kuratiert liefert; die Suchergebnisse verraten die Videozahl nicht.
_RE_PLAYLIST = re.compile(r"playlist='(\[.*?\])'", re.DOTALL)

# Beim Blaettern ist eine feste Sortierung PFLICHT. Ohne sie liefert die Suche
# nach internem Rang, und der schwankt zwischen Abfragen — dann steht auf
# Seite 3 ein Film, den man auf Seite 1 schon gesehen hat. Das ZWEITE Kriterium
# ist genauso wichtig: bei gleichem Zaehlerstand — und Null Downloads haben
# viele — waere die Reihenfolge sonst wieder offen. Die Kennung ist eindeutig
# und entscheidet die Gleichstaende.
SORT_COLLECTIONS = ('num_favorites desc', 'identifier asc')
SORT_ENTRIES = ('downloads desc', 'identifier asc')


def _apiUrl(sQuery, aFields, iPage=1, aSort=(), iRows=ITEMS_PER_PAGE):
    """Abfrage-URL fuer die Suchschnittstelle der Seite zusammensetzen.

    Der Sprachfilter wandert bewusst IN die Abfrage statt in die Schleife
    danach: vorher wurde die komplette Sammlung geladen und in Python
    aussortiert. Der Server kann das schneller und liefert nur, was gebraucht
    wird — das ist der Unterschied zwischen sieben Sekunden und einer Fuenftel.
    """
    aParams = [('q', sQuery), ('rows', str(iRows)), ('page', str(iPage)),
               ('output', 'json')]
    for sSort in aSort:
        aParams.append(('sort[]', sSort))
    for sField in aFields:
        aParams.append(('fl[]', sField))
    return URL_SEARCH_API + '?' + urlencode(aParams)


def _langQuery():
    """Sprachbedingung fuer die Abfrage, passend zur xStream-Einstellung.

    Bei „alle Sprachen" wird BEWUSST nicht gefiltert. Frueher stand dort eine
    Liste aus Deutsch und Englisch — spanische, tuerkische oder japanische
    Titel fielen damit raus, obwohl der Nutzer alles sehen wollte.
    """
    sLanguage = cConfig().getSetting('prefLanguage')
    sFilter = LANG_FILTER.get(sLanguage)
    return ' AND language:%s' % sFilter if sFilter else ''


def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.internetarchive.lastSearchText')
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30543), SITE_IDENTIFIER, 'menuCollections'))  # Kollektionen
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'))   # Search
    cGui().setEndOfDirectory()


def _hasNextPage(iPage, iTotal):
    """Gibt es hinter iPage noch eine Seite? Die Gesamtzahl der API zaehlt, aber
    nur bis zum Deckel MAX_PAGES — dieselbe Grenze wie in _pageInfo."""
    return iPage < MAX_PAGES and iPage * ITEMS_PER_PAGE < int(iTotal)


def _pageInfo(iPage, iTotal):
    """Seitenlage fuer den Weiter-Eintrag. Die API nennt die Gesamtzahl
    (numFound), daraus ergibt sich die Seitenzahl; mehr als MAX_PAGES gibt die
    API nicht heraus, deshalb der Deckel."""
    return cGui.pageInfo(iPage, min(-(-int(iTotal) // ITEMS_PER_PAGE), MAX_PAGES))


def menuCollections():
    """Sammlungen der Seite auflisten — dynamisch statt fest eingetragen.

    Hier standen frueher sechs Namen im Code. Die Seite fuehrt aber ueber
    achttausend Filmsammlungen, und die sechs waren nicht einmal die
    groessten — die drei beliebtesten fehlten. Jetzt kommt die Liste von der
    Seite selbst, sortiert nach Beliebtheit, und aendert sich mit ihr.
    """
    oGui = cGui()
    iPage = int(ParameterHandler().getValue('page') or 1)

    sUrl = _apiUrl('mediatype:collection AND collection:movies',
                   ['identifier', 'title', 'num_favorites'],
                   iPage=iPage, aSort=SORT_COLLECTIONS)
    oRequest = cRequestHandler(sUrl)
    jSearch = oRequest.requestJson()
    # Jenseits der letzten Seite antwortet die Seite nur mit einem Fehlerfeld
    # und OHNE Ergebnisblock — ohne diese Pruefung bricht das Addon dort ab.
    if not jSearch or 'response' not in jSearch:
        oGui.showInfo()
        return
    aResults = jSearch['response']['docs']
    iTotal = int(jSearch['response'].get('numFound', 0))

    for i in aResults:
        sId = str(i.get('identifier', ''))
        sName = str(i.get('title', '')) or sId
        if not sId:
            continue
        if _isBlocked(sId, sName):
            continue
        # Jeder Eintrag bekommt einen EIGENEN ParameterHandler — ein
        # gemeinsamer wuerde seine Werte an die folgenden Eintraege vererben.
        params = ParameterHandler()
        params.setParam('sColl', sId)
        params.setParam('page', 1)
        oGui.addFolder(cGuiElement(sName, SITE_IDENTIFIER, 'showCollections'), params)

    # Blaettern, solange die Seite noch mehr fuehrt
    if _hasNextPage(iPage, iTotal):
        params = ParameterHandler()
        params.setParam('page', iPage + 1)
        oGui.addNextPage(SITE_IDENTIFIER, 'menuCollections', params, _pageInfo(iPage, iTotal))
    oGui.setEndOfDirectory()


def _isBlocked(sId, sName):
    """Erwachsenen-Sammlungen aussortieren.

    Die Seite archiviert alles, auch was hier nichts zu suchen hat. Geprueft
    wird gegen Kennung und Titel zusammen — von den 200 groessten Sammlungen
    faellt damit genau eine raus, harmlose werden nicht mitgefangen.
    """
    sTest = ('%s %s' % (sId, sName)).lower()
    return any(w in sTest for w in BLOCKED_WORDS)

def showCollections(entryUrl=False, sGui=False):
    """Filme einer Sammlung auflisten.

    Der Sprachfilter steckt jetzt in der ABFRAGE, nicht mehr in dieser
    Schleife. Vorher wurde die ganze Sammlung geladen — bei „Feature Films"
    sind das ueber 28.000 Eintraege — und anschliessend in Python auf ein paar
    hundert eingedampft. Jetzt liefert die Seite gleich nur das Passende.
    """
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    sColl = params.getValue('sColl')
    iPage = int(params.getValue('page') or 1)
    if not sColl:
        if not sGui:
            oGui.showInfo()
        return

    sQuery = 'collection:"%s" AND mediatype:movies%s' % (sColl, _langQuery())
    sUrl = _apiUrl(sQuery, ['description', 'identifier', 'language', 'title', 'year'],
                   iPage=iPage, aSort=SORT_ENTRIES)
    oRequest = cRequestHandler(sUrl, ignoreErrors=(sGui is not False))
    jSearch = oRequest.requestJson()
    if not jSearch or 'response' not in jSearch:
        if not sGui:
            oGui.showInfo()
        return
    aResults = jSearch['response']['docs']
    iTotal = int(jSearch['response'].get('numFound', 0))
    if not aResults:
        if not sGui:
            oGui.showInfo()
        return

    for i in aResults:
        sId = str(i.get('identifier', ''))
        sName = str(i.get('title', ''))
        if not sId or not sName:
            continue
        if not _langOk(i.get('language')):
            continue
        # Jeder Eintrag ist ein ORDNER auf showParts: ein Eintrag der Seite
        # kann mehrere Filme enthalten, und wie viele es sind, weiss erst
        # dessen Embed-Seite — die Suche liefert dazu nichts Brauchbares
        # (files_count zaehlt auch Vorschaubilder und Metadateien mit).
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showParts')
        # Die Seite liefert die Sprache mal als Text, mal als Liste — beides
        # muss zu einem Wert werden, sonst sortiert hoster.py spaeter falsch.
        oGuiElement.setLanguage(_firstLang(i.get('language')))
        if 'year' in i and len(str(i['year'])) == 4:
            oGuiElement.setYear(i['year'])
        if i.get('description'):
            oGuiElement.setDescription(str(i['description']).replace("'", ""))
        oGuiElement.setMediaType('movie')
        # Eigener ParameterHandler je Eintrag — sonst erben die folgenden
        # Eintraege die Werte des vorherigen.
        oParams = ParameterHandler()
        oParams.setParam('entryUrl', URL_MOVIE + sId)
        oParams.setParam('sName', sName)
        oGui.addFolder(oGuiElement, oParams, True, len(aResults))

    if not sGui:
        if _hasNextPage(iPage, iTotal):
            oParams = ParameterHandler()
            oParams.setParam('sColl', sColl)
            oParams.setParam('page', iPage + 1)
            oGui.addNextPage(SITE_IDENTIFIER, 'showCollections', oParams, _pageInfo(iPage, iTotal))
        oGui.setView('movies')
        oGui.setEndOfDirectory()


def _stripSubParen(oMatch):
    """Klammerzusatz entfernen, wenn er nur die Untertitel beschreibt.

    „ger (English subtitles)" oder „jpn (eng sub)" fuehren die Sprache als
    Ton und nennen in der Klammer die Untertitel — die Klammer fliegt raus,
    damit der Rest als Tonspur zaehlt. Eine Klammer OHNE Sprachangabe wie
    „(subtitles)" oder „(cc)" bleibt stehen: „English (subtitles)" behauptet
    nur englische Untertitel, und das soll der Teilsatz-Check auch sehen.
    """
    aWoerter = _RE_LANG_WORD.findall(oMatch.group(0))
    iSub = sum(1 for w in aWoerter if _RE_SUB_WORD.match(w))
    return ' ' if 0 < iSub < len(aWoerter) else oMatch.group(0)


def _langOk(oLang):
    """Fuehrt der Eintrag die gewaehlte Sprache als TON?

    Die Suche der Seite trifft auch Teiltexte — bei „Deutsch" kommt deshalb
    „English with German subtitles" mit durch. Das behauptet aber nur einen
    Untertitel, keinen deutschen Ton, und faellt hier wieder raus (gleiche
    Regel wie bei Ger-Sub auf den anderen Seiten).

    Geprueft wird WORTWEISE je Teilsatz, nicht der Teilsatz als Ganzes:
    „German and English", „ger (English cc)" oder „German with English
    subtitles" fuehren Deutsch als Ton und bleiben drin. Vorher musste der
    Teil exakt einer Kennung entsprechen, und genau solche Eintraege fielen
    still raus — gemessen je rund 130 bei 84.000 deutschen und 80.000
    japanischen Eintraegen. Ein Teilsatz, in dem ein Untertitel-Wort steht,
    zaehlt nicht als Ton, so faellt „English with German subtitles"
    weiterhin weg.

    Mehrsprachige Titel wie ['German', 'English'] bleiben drin — bei denen
    ist Deutsch tatsaechlich als Tonspur dabei.
    """
    sLanguage = cConfig().getSetting('prefLanguage')
    aErlaubt = LANG_TOKENS.get(sLanguage)
    if not aErlaubt:
        return True

    aWerte = oLang if isinstance(oLang, list) else [oLang]
    for sWert in aWerte:
        sWert = _RE_LANG_PAREN.sub(_stripSubParen, str(sWert or '').lower())
        for sTeil in _RE_LANG_CLAUSE.split(sWert):
            aWoerter = _RE_LANG_WORD.findall(sTeil)
            if any(_RE_SUB_WORD.match(w) for w in aWoerter):
                continue
            if any(w in aErlaubt for w in aWoerter):
                return True
    return False


def _firstLang(oLang):
    """Sprachwert vereinheitlichen.

    Die Seite liefert meist einen Text, bei mehrsprachigen Titeln aber eine
    Liste. Der alte Code verglich die Liste als Ganzes gegen einzelne Werte —
    das schlug immer fehl, mehrsprachige Titel fielen deshalb stillschweigend
    aus der Auswahl.
    """
    if isinstance(oLang, list):
        return str(oLang[0]) if oLang else ''
    return str(oLang or '')


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    """Suchtreffer auflisten.

    Bekommt den SUCHTEXT statt einer fertig zusammengebauten Adresse — die
    Abfrage entsteht an einer Stelle, damit Sprachfilter und Blaettern hier
    genauso greifen wie in den Sammlungen.
    """
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not sSearchText:
        sSearchText = params.getValue('sSearchText')
    iPage = int(params.getValue('page') or 1)
    if not sSearchText:
        if not sGui:
            oGui.showInfo()
        return

    # TITELSUCHE statt Volltext. Die Schnittstelle durchsucht sonst auch
    # Beschreibungen, Kommentare und Rezensionen: „star wars" lieferte 16.431
    # Treffer, ganz oben „Sex Madness (1938)" — der Titel hat mit dem Begriff
    # nichts zu tun, er ist nur der meistgeladene im Treffersatz. Ueber `title:`
    # sind es 5.742, und oben stehen tatsaechlich Star-Wars-Titel.
    #
    # Die ANFUEHRUNGSZEICHEN sind Pflicht, nicht Kosmetik: ohne sie zerreissen
    # Sonderzeichen die Abfrage. `title:(rock & roll)` beantwortet die Seite mit
    # einem Backend-Fehler, `title:("rock & roll")` mit 252 Treffern. Die
    # Phrasenform heilt nebenbei drei Faelle, die vorher schon mit einer
    # Fehlermeldung endeten (Doppelpunkt, Klammer und Anfuehrungszeichen im
    # Suchbegriff, z.B. „C:A:T"). Ein Anfuehrungszeichen IM Begriff wuerde die
    # Phrase vorzeitig schliessen und wird deshalb durch ein Leerzeichen ersetzt.
    sQuery = 'title:("%s") AND mediatype:movies%s' % (sSearchText.replace('"', ' '), _langQuery())
    sUrl = _apiUrl(sQuery, ['description', 'identifier', 'language', 'title', 'year'],
                   iPage=iPage, aSort=SORT_ENTRIES)
    oRequest = cRequestHandler(sUrl, ignoreErrors=(sGui is not False))
    jSearch = oRequest.requestJson()
    if not jSearch or 'response' not in jSearch:
        if not sGui:
            oGui.showInfo()
        return
    aResults = jSearch['response']['docs']
    iTotal = int(jSearch['response'].get('numFound', 0))
    if not aResults:
        if not sGui:
            oGui.showInfo()
        return

    for i in aResults:
        sId = str(i.get('identifier', ''))
        sName = str(i.get('title', ''))
        if not sId or not sName:
            continue
        if not _langOk(i.get('language')):
            continue
        # Ordner auf showParts, gleicher Grund wie in showCollections
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showParts')
        oGuiElement.setLanguage(_firstLang(i.get('language')))
        if 'year' in i and len(str(i['year'])) == 4:
            oGuiElement.setYear(i['year'])
        if i.get('description'):
            oGuiElement.setDescription(str(i['description']).replace("'", ""))
        oGuiElement.setMediaType('movie')
        oParams = ParameterHandler()
        oParams.setParam('entryUrl', URL_MOVIE + sId)
        oParams.setParam('sName', sName)
        oGui.addFolder(oGuiElement, oParams, True, len(aResults))

    if not sGui:
        if _hasNextPage(iPage, iTotal):
            oParams = ParameterHandler()
            oParams.setParam('sSearchText', sSearchText)
            oParams.setParam('page', iPage + 1)
            oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', oParams, _pageInfo(iPage, iTotal))
        oGui.setView('movies')
        oGui.setEndOfDirectory()


def _absolute(sUrl):
    """Adressen der Seite vervollstaendigen.

    Sie liefert drei Formen: vollstaendig, protokoll-relativ (beginnt mit //)
    und domain-relativ (beginnt mit einem /). Ohne die Ergaenzung bekommt Kodi
    eine Adresse ohne Protokoll und kann nichts damit anfangen.
    """
    if sUrl.startswith('//'):
        return 'https:' + sUrl
    if sUrl.startswith('/'):
        return URL_MAIN + sUrl
    return sUrl


def _parsePlaylist(sHtmlContent):
    """Playlist des Seiten-Players lesen: je Video Titel, beste Datei, Bild.

    Bewusst OHNE cParser geschnitten — dessen Sonderzeichen-Ersetzung wuerde
    im rohen JSON herumschreiben. Die Dateiadresse wird DEKODIERT gemerkt und
    erst unmittelbar vor der Wiedergabe wieder kodiert: der Parameterweg jagt
    jeden Wert durch unquote_plus, eine schon kodierte Adresse kaeme dort
    zerlegt an (gleiche Falle wie bei movie2k). Fuehrt ein Video mehrere
    Quellen, sind das Aufloesungsstufen — genommen wird die hoechste.
    """
    aParts = []
    if not sHtmlContent:
        return aParts
    oMatch = _RE_PLAYLIST.search(sHtmlContent)
    if not oMatch:
        return aParts
    try:
        aEntries = json.loads(oMatch.group(1))
    except ValueError:
        return aParts
    for oEntry in aEntries:
        sFile = ''
        iBest = -1
        for oSource in (oEntry.get('sources') or []):
            sCandidate = str(oSource.get('file') or '')
            if not sCandidate:
                continue
            iHeight = cParser.getNumberFromString(str(oSource.get('height') or oSource.get('label') or '0'))
            if not sFile or iHeight > iBest:
                sFile, iBest = sCandidate, iHeight
        if not sFile:
            continue
        sTitle = cUtil.unescape(str(oEntry.get('title') or '')).strip()
        if not sTitle:
            sTitle = cParser.urlDecode(sFile).rsplit('/', 1)[-1]
        # Vorschaubilder ohne etwaige Query-Anhaengsel — ein Fragezeichen im
        # Bildpfad zerreisst spaeter die Parameterliste der plugin-Adresse
        sThumb = _absolute(str(oEntry.get('image') or '')).split('?')[0]
        aParts.append((sTitle, _absolute(cParser.urlDecode(sFile)), sThumb))
    return aParts


def showParts():
    """Videos eines Eintrags als Liste zeigen — wie Folgen in einer Staffel.

    Ein Eintrag der Seite kann mehrere Filme enthalten (Reihen wie die
    Guinea-Pig-Sammlung stecken komplett in einem). Bisher wurde davon still
    genau einer abgespielt, der Rest war unsichtbar. Der Ordner-Schritt gilt
    auch bei nur einem Video: ob es mehrere sind, weiss erst die Embed-Seite.
    """
    oGui = cGui()
    params = ParameterHandler()
    entryUrl = params.getValue('entryUrl')
    sName = params.getValue('sName')
    if not entryUrl:
        oGui.showInfo()
        return
    sHtmlContent = cRequestHandler(entryUrl.replace('/details/', '/embed/'), caching=False).request()
    aParts = _parsePlaylist(sHtmlContent)
    if not aParts:
        # Kein Playlist-Attribut — zum Beispiel wenn der Player des Eintrags
        # eine Anmeldung verlangt. Dann wie frueher: ein Eintrag auf die
        # Detailseite, die ResolveURL selbst aufloest (mit hinterlegten
        # Zugangsdaten kann der sich dort auch anmelden).
        aParts = [(sName or cParser.urlparse(entryUrl), entryUrl, '')]
    iTotal = len(aParts)
    for sTitle, sLink, sThumb in aParts:
        oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setMediaType('movie')
        if sThumb:
            oGuiElement.setThumbnail(sThumb)
        oParams = ParameterHandler()
        oParams.setParam('entryUrl', sLink)
        oParams.setParam('sName', sTitle)
        oGui.addFolder(oGuiElement, oParams, False, iTotal)
    oGui.setView('movies')
    oGui.setEndOfDirectory()


def showHosters():
    # Hier steht schon eine konkrete Videodatei aus showParts — oder beim
    # Fallback ohne Playlist die Detailseite fuer ResolveURL. Beides ist
    # genau EIN Hoster, geladen wird an dieser Stelle nichts mehr.
    hosters = []
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    if sUrl:
        hosters.append({'link': sUrl, 'name': cParser.urlparse(sUrl)})
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def getHosterUrl(sUrl=False):
    if 'youtube' in sUrl:
        import xbmc
        if not xbmc.getCondVisibility('System.HasAddon(%s)' % 'plugin.video.youtube'):
            xbmc.executebuiltin('InstallAddon(%s)' % 'plugin.video.youtube')
    if '/download/' in sUrl:
        # Dateiadresse aus der Playlist: die ist fertig und wird nur noch
        # kodiert (Leerzeichen u.ae. stehen hier roh, siehe _parsePlaylist).
        # NICHT durch ResolveURL schicken — dessen archive-Muster schneidet
        # den Dateinamen an der ersten Schraegstrich-Grenze ab und waehlt
        # aus dem ganzen Eintrag neu, genau der alte Fehler.
        return [{'streamUrl': cParser.urlEncode(sUrl, '/:%&=?'), 'resolved': True}]
    return [{'streamUrl': sUrl, 'resolved': False}]


def showSearch():
    win = xbmcgui.Window(10000)
    sSearchText = win.getProperty('xstream.internetarchive.lastSearchText')
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30287))
        if not sSearchText: return
        win.setProperty('xstream.internetarchive.lastSearchText', sSearchText)
    _search(False, sSearchText)
    cGui().setEndOfDirectory()

def showSearchColl(sName):
    sSearchText = sName
    if not sSearchText: return
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def _search(oGui, sSearchText):
    # Signatur bleibt wie sie ist — die globale Suche ruft genau so auf
    showEntries(False, oGui, sSearchText)