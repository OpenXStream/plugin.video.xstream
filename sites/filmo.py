# -*- coding: utf-8 -*-
# Python 3
# ------------------------------------------------------------------------------
# filmo.to — reine Filmseite, Laravel-App mit serverseitig gerendertem Katalog.
#
# BESONDERHEIT: der Hosterlink steht NICHT im HTML. Auf der Detailseite liegt je
# Sprache eine provider-row mit Chips, die einen laravel-verschluesselten Payload
# im Attribut data-p tragen. Der echte Link entsteht erst in drei Schritten:
#
#   1. Detailseite laden  -> CSRF-Token (<meta name="csrf-token">) + Session-Cookie
#   2. POST /n mit p=<data-p>, Header X-CSRF-TOKEN + X-Requested-With
#                         -> {"x": "<Einmal-Token>"}
#   3. GET /n/<Token>     -> Redirect auf voe.sx/e/<id>?default_audio_language=xx
#
# Schritt 2 und 3 laufen erst beim Abspielen (getHosterUrl), nicht beim Auflisten —
# sonst wuerde jede Hosterliste ein Dutzend Requests ausloesen.
#
# SPRACHE: die Zuordnung laeuft ueber die FLAGGENKLASSE (fi fi-de), NICHT ueber das
# Textlabel. Bei selteneren Sprachen faellt die Seite auf einen Dreibuchstaben-Code
# zurueck — Japanisch zeigt "JPN" statt "Japanisch". Die Flagge bleibt stabil.
# ------------------------------------------------------------------------------

import json
import re
from urllib.parse import quote_plus

from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger
from resources.lib.tools import cParser, cUtil

import xbmcgui

SITE_IDENTIFIER = 'filmo'
SITE_NAME = 'Filmo'
SITE_ICON = 'filmo.png'

# Label des Hero-Sliders auf der Startseite. Der Slider selbst traegt im HTML keinen
# Namen; seine Karten fuehren die Marker "NEU DIESE WOCHE" und "JETZT TRENDING"
# (gemessen 2026-09-24: je 3 Karten, 5 ohne Marker) — kein Kartenlabel passt fuer
# die ganze Reihe, das Label fasst die beiden zusammen (Jacks Wahl 24.09.2026).
HERO_TITLE = 'Neu & Trending'

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'filmo.to')
URL_MAIN = 'https://' + DOMAIN
URL_MOVIES = URL_MAIN + '/movies'
URL_POPULAR = URL_MAIN + '/popular'
URL_GENRES = URL_MAIN + '/genres'
URL_COLLECTIONS = URL_MAIN + '/collections'
URL_LETTERS = URL_MAIN + '/letters'
URL_SEARCH = URL_MAIN + '/search?q=%s'
URL_MINT = URL_MAIN + '/n'      # Aufloesungs-Endpunkt, siehe Kopf

# Flaggenklasse -> (Anzeigelabel, prefLanguage-Wert). Nur was wir wirklich
# zuordnen koennen; alles andere erscheint mit dem Klartext der Seite und
# ausschliesslich unter der Einstellung "Alle".
LANG_FLAGS = {
    'de': ('(DE)', '1'),
    'gb': ('(EN)', '2'),
    'us': ('(EN)', '2'),
    'jp': ('(JPN)', '3'),
}

_RE_MOVIE = re.compile(r'<a[^>]+href="https://%s/movies/([a-z0-9\-]+)"' % re.escape(DOMAIN))
# Die Seite nutzt DREI verschiedene Kartenlayouts, je nach Bereich:
#   Listen (/movies, /genres, /letters) -> Titel im alt-Attribut des Posters
#   /popular                            -> Titel in popular-spotlight-card__title
#   /search                             -> Titel in movie-poster-grid-card__title
# Statt drei Gesamtmuster wird deshalb je Karte gesucht: erst am Link auftrennen,
# dann im Kartenstueck der Reihe nach die drei Titelquellen probieren. Das ist
# robuster als ein Muster, das alle Layouts gleichzeitig treffen muss — und es
# verschluckt keine Treffer, wenn auf einer Seite mehrere Layouts vorkommen.
_RE_CARD_SPLIT = re.compile(r'<a[^>]+href="https://%s/movies/([a-z0-9\-]+)"' % re.escape(DOMAIN))
_RE_TITLE_SOURCES = (
    re.compile(r'spotlight-card__title[^>]*>\s*([^<]+?)\s*<'),
    re.compile(r'grid-card__title[^>]*>\s*([^<]+?)\s*<'),
    re.compile(r'<img[^>]+alt="([^"]+)"'),
)
# BEWUSST KEIN Freitext-Fallback: die Karten des Hero-Sliders ueberlappen sich im
# Markup — jeder Film kommt zweimal vor (Bild- und Button-Link), und der zweite
# Block enthaelt bereits den Titel des NAECHSTEN Films. Ein Textknoten-Fallback
# haengte damit falsche Titel an Filme ("Hoppers" bekam "Jetzt geniessen"), was
# schlimmer ist als ein fehlender Eintrag, weil es niemandem auffaellt. Karten
# ohne erkennbaren Titel bekommen stattdessen den Slug — immer der richtige Film.
_RE_THUMB = re.compile(r'<img[^>]+src="([^"]+)"')
# Poster auf der Detailseite. Der Hero-Slider der Startseite liefert naemlich
# Breitbilder (/img/hero/, /img/backdrop/), transparente Logos (/img/logo/) oder
# gar nichts — als Cover in einer Liste sieht das kaputt aus. Nur fuer diese
# Faelle wird die Detailseite nachgeladen; die normalen Listen bringen ihr
# Poster (/img/poster/) selbst mit und bleiben unangetastet.
_RE_DETAIL_POSTER = re.compile(r'(https://%s/img/poster/[a-z0-9\-]+/[^"\s?]+)' % re.escape(DOMAIN))
_POSTER_OK = '/img/poster/'
# Der Sammlungsname steht in einer eigenen Klasse und liegt gut 2000 Zeichen
# hinter dem Link — dazwischen stehen die Poster-Vorschauen der Sammlung.
_RE_COLLECTION_TITLE = re.compile(r'collection-index-card__title[^>]*>\s*([^<]+?)\s*<')
# Reihenkopf der Start- und Beliebt-Seite: der Titel steht im h3, direkt gefolgt
# vom "Mehr anzeigen"-Link auf die zugehoerige Collection bzw. das Genre.
_RE_ROW_HEAD = re.compile(
    r'<h3[^>]*>\s*([^<]{2,60}?)\s*<a[^>]+href="https://%s/((?:collections|genres)/[a-z0-9\-]+)"' % re.escape(DOMAIN))
# Reihen ohne "Mehr anzeigen" (Highlights, Spotlight, Blockbuster & Kinostarts …)
# haben keine eigene Zielseite. Getrennt wird deshalb NICHT am Container — den
# gibt es in mehreren Varianten (video-row, popular-featured-row,
# popular-backdrop-grid-section …) — sondern an der Ueberschrift selbst. Alles
# bis zur naechsten Ueberschrift gehoert zur Reihe.
# NUR die Reihenkoepfe: die tragen class="mb-0" (teils zusaetzlich eine id),
# waehrend die Ueberschriften INNERHALB der Kacheln headline__marker heissen.
# Ohne diese Einschraenkung wuerde an jeder Kachel getrennt und die Bloecke
# waeren zu klein, um Filme zu enthalten.
_RE_ROW_SPLIT = re.compile(r'<h3[^>]*class="mb-0"[^>]*>\s*([^<]{2,60}?)\s*<')
# Genre-Links der Seite: der Name steht in einem <span> IM Link (Navigation:
# navbar-truncate-text, Uebersicht: typography-root), der Slug im href. Bis
# 2026.09.10 griff das Muster den Text direkt hinter dem Link ab, fand nichts
# und fiel auf den englischen Slug zurueck („War“, „Romance“ statt Kriegsfilm,
# Liebesfilm). Die Uebersicht traegt alle 19 Genres, die Navigation nur 16.
_RE_GENRE = re.compile(r'<a[^>]+href="https://%s/genres/([a-z0-9\-]+)"[^>]*>\s*<span[^>]*>\s*([^<]{2,40}?)\s*</span>' % re.escape(DOMAIN))
# Nur die Karten der Uebersicht, nicht die Reihen-Links aus Kopf- und Fussbereich —
# sonst wandern "Mehr anzeigen"-Ziele als Doubletten in die Liste.
_RE_COLLECTION_SPLIT = re.compile(
    r'<a[^>]+class="collection-index-card[^"]*"[^>]+href="https://%s/collections/([a-z0-9\-]+)"' % re.escape(DOMAIN))
_RE_PAGE = re.compile(r'[?&]page=(\d+)')

# Nicht jeder Hoster wird per Redirect erreicht: manche (z.B. Byse) liefern
# stattdessen eine Zwischenseite „Du verlaesst Filmo …" mit dem externen Link
# darin. Das Muster greift jeden href, der NICHT auf die eigene Domain zeigt.
_RE_EXTERN = re.compile(r'href="(https?://(?!(?:www\.)?%s)[^"]+)"' % re.escape(DOMAIN))
_RE_CSRF = re.compile(r'<meta name="csrf-token" content="([^"]+)"')
# Eine provider-row je Sprache; der Split traegt die Zeilen auseinander.
_RE_LANGROW_SPLIT = re.compile(r'<div\s+class="provider-row"')
_RE_FLAG = re.compile(r'class="fi fi-(\w+)"')
_RE_LANG = re.compile(r'provider-row__lang"[^>]*>\s*([^<]+?)\s*<')
# Chip = ein Hoster in einer Sprachzeile. Hinter dem Namen stehen ein bis zwei
# Metadaten-Tags mit Quelle und Aufloesung (z.B. WEB und 720p, oder TS) — die
# werden mitgenommen, damit man in der Hosterliste sieht, was einen erwartet.
_RE_CHIP = re.compile(
    r'data-p="([^"]+)"[^>]*>.*?provider-chip__name"[^>]*>\s*([^<]+?)\s*<'
    r'(.*?)(?=data-p="|</div></div>|$)', re.DOTALL)
_RE_CHIP_TAG = re.compile(r'provider-chip__metadata-tag"[^>]*>\s*([^<]{1,12}?)\s*<')
_RE_RES = re.compile(r'^(\d{3,4})p?$', re.I)
_RE_YEAR = re.compile(r'(\d{4})')


def load():
    logger.info('Load %s' % SITE_NAME)
    # Beim Betreten des Hauptmenues den gemerkten Suchbegriff verwerfen, sonst
    # wuerde die Suche beim naechsten Aufruf wortlos das alte Ergebnis zeigen.
    xbmcgui.Window(10000).clearProperty('xstream.%s.lastSearchText' % SITE_IDENTIFIER)
    # WICHTIG: fuer JEDEN Eintrag ein frischer ParameterHandler. Wird einer
    # wiederverwendet, erben die spaeteren Eintraege die zuletzt gesetzte sUrl —
    # der Kollektionen-Eintrag bekam so die Film-URL und lud /movies statt
    # /collections, wo es keine Sammlungskarten gibt: die Liste blieb leer.
    params = ParameterHandler()
    params.setParam('sUrl', URL_MAIN)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30881), SITE_IDENTIFIER, 'showRows'), params)  # Startseite

    params = ParameterHandler()
    params.setParam('sUrl', URL_MOVIES)
    # Die drei oberen Menuepunkte heissen wie die Navigation der Website selbst und
    # stehen in deren Reihenfolge: "Startseite", "Filme", "Beliebt" (im Markup als
    # navbar-truncate-text). Bezeichnungen aus unserem String-Katalog, die dort
    # nirgends stehen, waeren irrefuehrend — der Nutzer soll wiedererkennen, was er
    # im Browser sieht. Die Liste vor der Rangliste ist zugleich das Menue-Muster
    # aller Sites (Filme, dann Beliebt/Top/IMDb).
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30502), SITE_IDENTIFIER, 'showEntries'), params)

    params = ParameterHandler()
    params.setParam('sUrl', URL_POPULAR)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30874), SITE_IDENTIFIER, 'showRows'), params)  # Beliebt

    params = ParameterHandler()
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30506), SITE_IDENTIFIER, 'showGenres'), params)   # Genre
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30543), SITE_IDENTIFIER, 'showCollections'), params)  # Kollektionen
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30814), SITE_IDENTIFIER, 'showLetters'), params)  # A-Z
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'), params)   # Suche
    cGui().setEndOfDirectory()


def _request(sUrl, ignoreErrors=False):
    """Seite holen. Zeilenumbrueche fliegen raus, damit die Regexes ohne DOTALL
    ueber Tag-Grenzen kommen — Hausstil wie in den uebrigen Site-Files."""
    oRequest = cRequestHandler(sUrl, ignoreErrors=ignoreErrors)
    oRequest.addHeaderEntry('Accept-Language', 'de-DE,de;q=0.9')
    return oRequest.request()


def showRows():
    """Reihen einer Uebersichtsseite als Ordner — Vorbild netzkino.showStart().

    Start- und Beliebt-Seite bestehen aus Reihen ("Kinder- und Familienfilme",
    "Entdecken: Beliebte Filme" …), die jeweils per "Mehr anzeigen" auf eine
    Collection oder ein Genre zeigen. Statt die Filme aller Reihen in einen Topf
    zu werfen, wird hier die Gliederung der Seite uebernommen — sie ist
    dynamisch, es wird nichts fest verdrahtet.
    """
    oGui = cGui()
    params = ParameterHandler()
    entryUrl = params.getValue('sUrl') or URL_MAIN
    sHtmlContent = _request(entryUrl)

    seen = set()
    seenTitles = set()

    # 0) Der Hero-Slider ganz oben. Er hat auf der Website kein eigenes Label, nur
    #    wechselnde Marker an einzelnen Karten — deshalb kommt die Bezeichnung aus
    #    HERO_TITLE (Begruendung dort). Die Filme selbst liegen im Bereich VOR der
    #    ersten Reihenueberschrift.
    mFirstRow = _RE_ROW_SPLIT.search(sHtmlContent)
    if mFirstRow and _RE_CARD_SPLIT.search(sHtmlContent[:mFirstRow.start()]):
        sHero = HERO_TITLE
        seen.add('__hero__')
        seenTitles.add(sHero)
        params = ParameterHandler()
        params.setParam('sUrl', entryUrl)
        params.setParam('sRow', '__hero__')
        params.setParam('bPoster', '1')     # Cover von den Detailseiten holen
        oGui.addFolder(cGuiElement(sHero, SITE_IDENTIFIER, 'showEntries'), params)

    # 1) Reihen MIT Zielseite -> Ordner, der die Zielseite laedt
    for sTitle, sPath in _RE_ROW_HEAD.findall(sHtmlContent):
        if sPath in seen:
            continue
        seen.add(sPath)
        sTitle = cUtil.unescape(sTitle.strip())
        seenTitles.add(sTitle)
        params = ParameterHandler()
        params.setParam('sUrl', '%s/%s' % (URL_MAIN, sPath))
        oGui.addFolder(cGuiElement(sTitle, SITE_IDENTIFIER, 'showEntries'), params)

    # 2) Reihen OHNE Zielseite -> Ordner, der beim Oeffnen dieselbe Seite nochmal
    #    laedt und nur diesen einen Reihenblock ausliest. Ohne das fehlten auf
    #    /popular Highlights, Spotlight und Blockbuster & Kinostarts komplett.
    aParts = _RE_ROW_SPLIT.split(sHtmlContent)
    for i in range(1, len(aParts) - 1, 2):
        sTitle, sBlock = cUtil.unescape(aParts[i].strip()), aParts[i + 1]
        if sTitle in seenTitles or not _RE_CARD_SPLIT.search(sBlock):
            continue
        seenTitles.add(sTitle)
        seen.add(sTitle)
        params = ParameterHandler()
        params.setParam('sUrl', entryUrl)
        params.setParam('sRow', sTitle)
        oGui.addFolder(cGuiElement(sTitle, SITE_IDENTIFIER, 'showEntries'), params)

    if not seen:
        # Keine Reihen gefunden — dann die Seite als flache Liste zeigen, damit
        # der Eintrag nicht leer bleibt.
        showEntries(entryUrl)
        return
    oGui.setEndOfDirectory()


def showGenres():
    oGui = cGui()
    params = ParameterHandler()
    sHtmlContent = _request(URL_GENRES)
    seen = set()
    for sSlug, sName in _RE_GENRE.findall(sHtmlContent):
        if sSlug in seen:
            continue
        seen.add(sSlug)
        oGuiElement = cGuiElement(sName.strip() or sSlug.replace('-', ' ').title(), SITE_IDENTIFIER, 'showEntries')
        params.setParam('sUrl', '%s/%s' % (URL_GENRES, sSlug))
        oGui.addFolder(oGuiElement, params)
    if not seen:
        oGui.showInfo()
    oGui.setEndOfDirectory()


def showCollections():
    """Sammlungs-Uebersicht. Paginiert wie die Filmlisten — es sind ueber 190
    Sammlungen auf mehreren Seiten (02.09.2026: fuenf), nicht die 48 der ersten Seite."""
    oGui = cGui()
    params = ParameterHandler()
    entryUrl = params.getValue('sUrl') or ''
    if '/collections' not in entryUrl:
        entryUrl = URL_COLLECTIONS   # gegen versehentlich geerbte Parameter
    sHtmlContent = _request(entryUrl)
    seen = set()
    # Der Name steht NICHT am Link, sondern als Textknoten in der Karte —
    # deshalb wie bei den Filmen am Link auftrennen und im Stueck suchen.
    aParts = _RE_COLLECTION_SPLIT.split(sHtmlContent)
    for i in range(1, len(aParts) - 1, 2):
        sSlug, sChunk = aParts[i], aParts[i + 1]
        if sSlug in seen:
            continue
        seen.add(sSlug)
        mName = _RE_COLLECTION_TITLE.search(sChunk)
        sName = cUtil.unescape(mName.group(1).strip()) if mName else ''
        oGuiElement = cGuiElement(sName or sSlug.replace('-', ' ').title(),
                                  SITE_IDENTIFIER, 'showEntries')
        params.setParam('sUrl', '%s/%s' % (URL_COLLECTIONS, sSlug))
        oGui.addFolder(oGuiElement, params)
    if not seen:
        oGui.showInfo()
    _addNextPage(oGui, params, entryUrl, sHtmlContent, 'showCollections')
    oGui.setEndOfDirectory()


def showLetters():
    """A-Z-Index. Die Seite fuehrt 0-9, a bis z und 'all' als eigene Pfade."""
    oGui = cGui()
    params = ParameterHandler()
    for sLetter in ['0-9'] + [chr(c) for c in range(ord('a'), ord('z') + 1)]:
        oGuiElement = cGuiElement(sLetter.upper(), SITE_IDENTIFIER, 'showEntries')
        params.setParam('sUrl', '%s/%s' % (URL_LETTERS, sLetter))
        oGui.addFolder(oGuiElement, params)
    oGui.setEndOfDirectory()


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl:
        entryUrl = params.getValue('sUrl')

    sHtmlContent = _request(entryUrl, ignoreErrors=(sGui is not False))
    # Kommt der Aufruf aus einer Reihe ohne eigene Zielseite, wird nur deren
    # Block ausgewertet — siehe showRows().
    bPoster = params.getValue('bPoster') == '1'
    if bPoster:
        params.setParam('bPoster', '')
    sRow = params.getValue('sRow')
    if sRow == '__hero__':
        # Alles vor der ersten Reihenueberschrift ist der Hero-Slider.
        mFirstRow = _RE_ROW_SPLIT.search(sHtmlContent)
        if mFirstRow:
            sHtmlContent = sHtmlContent[:mFirstRow.start()]
        params.setParam('sRow', '')
        sRow = ''
    if sRow:
        aParts = _RE_ROW_SPLIT.split(sHtmlContent)
        for i in range(1, len(aParts) - 1, 2):
            if cUtil.unescape(aParts[i].strip()) == sRow:
                sHtmlContent = aParts[i + 1]
                break
        params.setParam('sRow', '')
    aResult = _parseCards(sHtmlContent)
    if not aResult:
        if not sGui:
            oGui.showInfo()
        return

    total = len(aResult)
    seen = set()
    for sSlug, sThumb, sName in aResult:
        # Entdoppelt wird NUR ueber den Slug. Ein zusaetzlicher Titel-Abgleich
        # klang naheliegend (der Hero-Slider fuehrt jede Karte zweimal), warf in
        # den normalen Listen aber echte Filme mit aehnlichem Titel weg — dort
        # fehlten dann 39 statt 42 Eintraege pro Seite.
        sKey = sSlug.strip('/').lower()
        if sKey in seen:
            continue
        seen.add(sKey)
        sName = cUtil.unescape(sName.strip())
        # BEWUSST KEIN Titelfilter (cParser.searchTitle) bei der Suche: filmo sucht
        # serverseitig ueber Original- und Alternativtitel und findet zu
        # "star wars" auch "Krieg der Sterne". Ein Abgleich mit dem Suchwort
        # wuerde genau diese Treffer wieder wegwerfen — gemessen 6 statt 17.
        # Dieselbe Lehre wie bei animetoast.
        if bPoster and _POSTER_OK not in sThumb:
            sThumb = _fetchPoster(sSlug) or sThumb
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setMediaType('movie')
        oGuiElement.setThumbnail(sThumb)
        oGuiElement.setTitle(sName)
        params.setParam('entryUrl', '%s/%s' % (URL_MOVIES, sSlug))
        params.setParam('sName', sName)
        oGui.addFolder(oGuiElement, params, False, total)

    if not sGui:
        _addNextPage(oGui, params, entryUrl, sHtmlContent)
        oGui.setView('movies')
        oGui.setEndOfDirectory()


def _cleanThumb(sUrl):
    """Query aus der Bild-URL entfernen.

    filmo haengt an jedes Bild ein `?format=webp`. Diese URL wandert als
    Parameter in die plugin://-Adresse — und das Fragezeichen samt & zerreisst
    dort die Parameterliste, sodass Kodi den Rest falsch liest und der Titel
    nicht mehr abspielbar ist. Ohne die Query liefert der Server dasselbe Bild
    in gleicher Groesse, also faellt sie ersatzlos weg.
    """
    return sUrl.split('?')[0] if sUrl else sUrl


def _fetchPoster(sSlug):
    """Poster von der Detailseite. Nur fuer Karten ohne brauchbares Bild."""
    try:
        m = _RE_DETAIL_POSTER.search(_request('%s/%s' % (URL_MOVIES, sSlug), ignoreErrors=True))
        return _cleanThumb(m.group(1)) if m else ''
    except Exception:
        return ''   # ein fehlendes Cover darf die Liste nicht kippen


def _parseCards(sHtmlContent):
    """Filmkarten einer Listenseite als (slug, thumb, name).

    Getrennt wird am Link zur Detailseite; alles bis zum naechsten Link gilt als
    eine Karte. Der Titel kommt aus der ersten Quelle, die etwas liefert.
    """
    aCards = []
    aParts = _RE_CARD_SPLIT.split(sHtmlContent)
    # split() liefert [Vorspann, slug1, Rest1, slug2, Rest2, …]
    for i in range(1, len(aParts) - 1, 2):
        sSlug, sChunk = aParts[i], aParts[i + 1]
        sName = ''
        for oPattern in _RE_TITLE_SOURCES:
            m = oPattern.search(sChunk)
            if m and m.group(1).strip():
                sName = m.group(1).strip()
                break
        if not sName:
            sName = sSlug.replace('-', ' ').title()
        mThumb = _RE_THUMB.search(sChunk)
        aCards.append((sSlug, _cleanThumb(mThumb.group(1)) if mThumb else '', sName))
    return aCards


def _addNextPage(oGui, params, entryUrl, sHtmlContent, sFunction='showEntries'):
    """Naechste Seite ueber ?page=N.

    Der Paginator der Seite ist GEKUERZT (1 2 3 ... 159 160) — er listet also
    NICHT alle Seitenzahlen. Der Vergleich mit `max()` traegt trotzdem, weil die
    Seite auf jeder Seite die LETZTE Nummer mitfuehrt; auf der letzten Seite
    selbst faellt sie weg, damit endet der Weiter-Eintrag korrekt. Wer das
    Muster anfasst, darf sich also nicht darauf verlassen, dass alle Zahlen im
    Markup stehen — nur die hoechste muss drin sein."""
    aPages = [int(p) for p in _RE_PAGE.findall(sHtmlContent)]
    if not aPages:
        return
    m = _RE_PAGE.search(entryUrl)
    iCurrent = int(m.group(1)) if m else 1
    if iCurrent >= max(aPages):
        return
    sBase = re.sub(r'[?&]page=\d+', '', entryUrl)
    sSep = '&' if '?' in sBase else '?'
    params.setParam('sUrl', '%s%spage=%d' % (sBase, sSep, iCurrent + 1))
    # Die hoechste Zahl der Leiste ist das Listenende (siehe Docstring) — daraus
    # die Seitenlage fuer den Weiter-Eintrag.
    oGui.addNextPage(SITE_IDENTIFIER, sFunction, params, cGui.pageInfo(iCurrent, max(aPages)))


def showHosters():
    """Sprachzeilen der Detailseite in Hoster-Dicts uebersetzen.

    Aufgeloest wird hier NICHT — der Payload data-p wandert als 'link' mit und
    wird erst in getHosterUrl eingeloest. Sonst kostete jede Hosterliste ein
    Dutzend zusaetzliche Requests, von denen die meisten niemand braucht.
    """
    params = ParameterHandler()
    entryUrl = params.getValue('entryUrl')
    sPrefLang = cConfig().getSetting('prefLanguage', '0')
    sHtmlContent = _request(entryUrl)

    hosters = []
    for sRow in _RE_LANGROW_SPLIT.split(sHtmlContent)[1:]:
        mFlag = _RE_FLAG.search(sRow)
        mLang = _RE_LANG.search(sRow)
        sFlag = mFlag.group(1).lower() if mFlag else ''
        sLabel, sLangPref = LANG_FLAGS.get(sFlag, ('', ''))
        if not sLabel:
            # Unbekannte Sprache: den Klartext der Seite nehmen (JPN, POR, KOR …)
            sLabel = '(%s)' % mLang.group(1).strip() if mLang else ''
        # Filter nach der Spracheinstellung. Was keiner Sprache zugeordnet ist,
        # erscheint ausschliesslich unter "Alle" — gleiche Regel wie bei
        # serienstream und burningseries: das Label der Seite entscheidet.
        if sPrefLang in ('1', '2', '3') and sLangPref != sPrefLang:
            continue
        for sPayload, sHosterName, sRest in _RE_CHIP.findall(sRow):
            sHosterName = sHosterName.strip()
            if cConfig().isBlockedHoster(sHosterName)[0]:
                continue  # Hoster aus settings.xml oder deaktivierten Resolver ausschliessen
            # Tags aufteilen: eine reine Zahl ist die Aufloesung, alles andere
            # (WEB, TS, HDTV …) beschreibt die Quelle.
            aTags = [t.strip() for t in _RE_CHIP_TAG.findall(sRest) if t.strip()]
            sQuality = ''
            aSource = []
            for sTag in aTags:
                mRes = _RE_RES.match(sTag)
                if mRes and not sQuality:
                    sQuality = mRes.group(1)
                else:
                    aSource.append(sTag)
            sInfo = ' '.join(x for x in (sLabel, ' '.join(aSource),
                                         '[%sp]' % sQuality if sQuality else '') if x)
            hosters.append({
                'link': sPayload,
                'name': sHosterName,
                'displayedName': '%s [I]%s[/I]' % (sHosterName, sInfo) if sInfo else sHosterName,
                'quality': sQuality or '720',
                'resolveable': True,
                # languageCode IMMER setzen (notfalls leer): hoster.py sortiert
                # danach und wuerde bei gemischten Typen mit TypeError abbrechen.
                'languageCode': sLabel or '',
            })

    if hosters:
        hosters.append('getHosterUrl')
    else:
        cGui().showLanguage()
    return hosters


def getHosterUrl(sUrl=False):
    """Verschluesselten Payload gegen den echten Hosterlink tauschen.

    Der CSRF-Token gilt nur zusammen mit der Session, deshalb wird die
    Detailseite unmittelbar davor nochmal geholt — der requestHandler haelt
    den Cookie-Jar, der Token muss aus derselben Antwort stammen.
    """
    params = ParameterHandler()
    entryUrl = params.getValue('entryUrl')

    sHtmlContent = _request(entryUrl)
    mToken = _RE_CSRF.search(sHtmlContent)
    if not mToken:
        logger.error('%s: kein CSRF-Token auf %s' % (SITE_NAME, entryUrl))
        return [{'streamUrl': '', 'resolved': False}]

    # Der Payload MUSS ueber data= gehen, nicht ueber addParameters: der
    # requestHandler wertet _aParameters ausschliesslich im GET-Zweig aus. Bei
    # method='POST' ohne data bleibt der Body leer, urllib macht daraus ein GET
    # und /n antwortet mit 405 Method Not Allowed.
    oRequest = cRequestHandler(URL_MINT, caching=False, method='POST', data={'p': sUrl})
    oRequest.addHeaderEntry('X-CSRF-TOKEN', mToken.group(1))
    oRequest.addHeaderEntry('X-Requested-With', 'XMLHttpRequest')
    oRequest.addHeaderEntry('Referer', entryUrl)
    oRequest.addHeaderEntry('Accept', 'application/json, text/plain, */*')
    sResponse = oRequest.request()

    try:
        sMintToken = json.loads(sResponse).get('x', '')
    except ValueError:
        logger.error('%s: unerwartete Antwort von %s: %s' % (SITE_NAME, URL_MINT, str(sResponse)[:120]))
        return [{'streamUrl': '', 'resolved': False}]
    if not sMintToken:
        logger.error('%s: kein Token in der Antwort' % SITE_NAME)
        return [{'streamUrl': '', 'resolved': False}]

    # Der Token-Aufruf endet BEI DEN MEISTEN Hostern per Redirect beim Ziel —
    # dann genuegt getRealUrl(). Ausnahme: Hoster wie Byse werden nicht
    # weitergeleitet, sondern ueber eine Zwischenseite verlinkt („Du verlaesst
    # Filmo, um ein Video beim externen Anbieter zu oeffnen"). Dort steht am
    # Ende noch unsere eigene Domain, und der echte Link liegt im HTML.
    # Deshalb wird die Antwort NICHT verworfen, sondern bei Bedarf ausgewertet.
    oFinal = cRequestHandler('%s/%s' % (URL_MINT, sMintToken), caching=False)
    oFinal.addHeaderEntry('Referer', entryUrl)
    sFinalHtml = oFinal.request()
    sStreamUrl = oFinal.getRealUrl()

    if DOMAIN in sStreamUrl:
        mExtern = _RE_EXTERN.search(sFinalHtml or '')
        if not mExtern:
            logger.error('%s: kein externer Link auf der Weiterleitungsseite %s'
                         % (SITE_NAME, sStreamUrl))
            return [{'streamUrl': '', 'resolved': False}]
        sStreamUrl = mExtern.group(1)

    return [{'streamUrl': sStreamUrl, 'resolved': False}]


def showSearch():
    # Der Suchbegriff wird in einer Window-Property gemerkt: kehrt man nach dem
    # Abspielen in die Trefferliste zurueck, wird nicht erneut nach der Eingabe
    # gefragt. Geleert wird sie in load(). Hausstil wie in allen Site-Files.
    win = xbmcgui.Window(10000)
    sKey = 'xstream.%s.lastSearchText' % SITE_IDENTIFIER
    sSearchText = win.getProperty(sKey)
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30281))
        if not sSearchText:
            return
        win.setProperty(sKey, sSearchText)
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def _search(oGui, sSearchText):
    showEntries(URL_SEARCH % quote_plus(sSearchText), oGui, sSearchText)
