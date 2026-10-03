# -*- coding: utf-8 -*-
# Python 3
# ------------------------------------------------------------------------------
# kellerkino.com — reine Filmseite (WordPress, alles serverseitig gerendert).
#
# Die Hosterlinks stehen fertig im HTML der Detailseite: je Player-Reiter ein
# Panel (data-nfo-player-panel / data-nfo-player-label) mit einem <template>,
# das den <iframe src="…"> traegt. Kein Token, kein JS-Nachladen, keine Cookies.
#
# Listen (Archiv, IMDb, Kategorien, A-Z, Suche) teilen sich ein Karten-Markup
# (<article class="movie-card">) und eine WordPress-Blaetterleiste
# (class="pagination"): die letzte Seite steht als Link, die aktive als
# <span class="page-numbers current">, der Weiter-Link als class="next".
#
# Startseite: die Reihen kommen aus dem Markup — Kino-Buehne, Neuerscheinungen,
# "Zuletzt hinzugefuegt", die Themen-Reiter (Stand 07.09.2026 acht, je 5 Filme,
# alle Panels stehen im HTML) und "Empfehlungen" (die Seite wuerfelt sie je
# Abruf neu). Keine Reihe ausser "Zuletzt hinzugefuegt" hat eine eigene
# Listenseite, deshalb liest showEntries den Block der Reihe aus der Startseite.
# ------------------------------------------------------------------------------
import re
from urllib.parse import quote
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger
from resources.lib.tools import cParser, cUtil
import xbmcgui

SITE_IDENTIFIER = 'kellerkino'
SITE_NAME = 'Kellerkino'
SITE_ICON = 'kellerkino.png'
DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'kellerkino.com')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)
URL_MAIN = 'https://' + DOMAIN
URL_ARCHIVE = URL_MAIN + '/archiv/'
URL_IMDB = URL_MAIN + '/imdb-rating/'
URL_CATEGORIES = URL_MAIN + '/kategorien/'
URL_LETTERS = URL_MAIN + '/filme-a-z/'
# Suche ueber den WordPress-Permalink /search/<begriff>/ statt /?s=<begriff>: seit
# 02.10.2026 legt Cloudflare auf ?s= im Root-Pfad eine Managed Challenge (403,
# cf-mitigated: challenge, im Addon nicht loesbar); die Permalink-Route und die
# seiteneigenen Blaetterlinks (/seite/N/?s=...) kommen durch, Treffer und Leiste sind
# gleich. Der Begriff bleibt in _search per urlEncode voll kodiert (%2F, %26, %23).
URL_SEARCH = URL_MAIN + '/search/%s/'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

# Filmkarte einer Liste. Das Bild traegt in den versteckten Themen-Panels der
# Startseite data-dmt-theme-src statt src (Lazy-Loading), deshalb beide Formen.
_RE_CARD = re.compile(r'<article class="movie-card[^"]*">(.*?)</article>', re.S)
_RE_CARD_LINK = re.compile(r'<h2><a href="([^"]+)">(.*?)</a></h2>', re.S)
_RE_CARD_IMG = re.compile(r'<img[^>]+(?:src|data-dmt-theme-src)="([^"]+)"')
_RE_CARD_YEAR = re.compile(r'<span>\s*(\d{4})\s*</span>')
_RE_CARD_DURATION = re.compile(r'<span>\s*(\d+)\s*Min\s*</span>')
_RE_CARD_RATING = re.compile(r'<span>\s*IMDb\s*(\d+(?:\.\d+)?)\s*</span>')
# Blaetterleiste (Archiv, Kategorien, IMDb, Suche, A-Z — ueberall dieselbe Form)
_RE_PAGINATION = re.compile(r'class="pagination[^"]*"[^>]*>(.*?)</(?:div|nav)>', re.S)
_RE_PAGE_CURRENT = re.compile(r'class="page-numbers current">\s*(\d+)\s*<')
_RE_PAGE_NUMBER = re.compile(r'class="page-numbers"[^>]*>\s*(\d+)\s*<')
_RE_PAGE_NEXT = re.compile(r'class="next page-numbers"\s+href="([^"]+)"')
# Startseite
_RE_HOME_TOPCOVER = re.compile(r'<a class="top-cover" href="([^"]+)"[^>]*>\s*<img src="([^"]+)"[^>]*>\s*<span>([^<]*)</span>', re.S)
_RE_HOME_CINEMA_LABEL = re.compile(r'class="dmt-home-cinema-title-default">\s*([^<]+?)\s*<')
_RE_HOME_CINEMA_CARD = re.compile(r'<a class="dmt-home-cinema-(?:focus|secondary)" href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_RE_HOME_NEW_LABEL = re.compile(r'<div class="dmt-home-cinema-more-head">\s*<h2>\s*([^<]+?)\s*</h2>', re.S)
_RE_HOME_NEW_CARD = re.compile(r'<a class="dmt-home-cinema-more-card" href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_RE_HOME_SECTION_LABEL = re.compile(r'<h2>\s*([^<]+?)\s*</h2>')
_RE_HOME_THEME_TAB = re.compile(r'<button[^>]*data-dmt-home-theme-tab="([^"]+)"[^>]*data-dmt-home-theme-label="([^"]+)"', re.S)
_RE_HOME_THEME_PANEL = re.compile(r'id="dmt-home-theme-panel-([^"]+)"')
# Kategorien-Uebersicht und A-Z-Leiste
_RE_CATEGORY_CARD = re.compile(r'<div class="category-card">(.*?)<span class="category-card-count">', re.S)
_RE_CATEGORY_LINK = re.compile(r'<a class="category-card-name" href="([^"]+)"><strong>([^<]+)</strong></a>')
_RE_CATEGORY_IMG = re.compile(r'<img src="([^"]+)"')
_RE_LETTER = re.compile(r'<a class="dmt-az-letter-link[^"]*"\s+href="[^"]*dmt_letter=([^"&]*)"[^>]*>\s*<span class="dmt-az-letter-main">\s*([^<]+?)\s*</span>', re.S)
# Hoster-Panels der Detailseite
_RE_HOSTER_LABEL = re.compile(r'data-nfo-player-label="([^"]*)"')
_RE_HOSTER_IFRAME = re.compile(r'<iframe[^>]+src="(https?://[^"]+)"')


def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.%s.lastSearchText' % SITE_IDENTIFIER)
    # Menuepunkte tragen die Bezeichnungen der Seite: "Alle Filme", "IMDb",
    # "Kategorien" und "A-Z" sind ihre Navigation. Jeder Eintrag bekommt einen
    # frischen ParameterHandler, sonst erben die spaeteren die sUrl des vorigen.
    params = ParameterHandler()
    params.setParam('sUrl', URL_MAIN)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30881), SITE_IDENTIFIER, 'showRows'), params)  # Startseite
    params = ParameterHandler()
    params.setParam('sUrl', URL_ARCHIVE)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30542), SITE_IDENTIFIER, 'showEntries'), params)  # Alle Filme
    params = ParameterHandler()
    params.setParam('sUrl', URL_IMDB)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30510), SITE_IDENTIFIER, 'showEntries'), params)  # IMDB-Bewertung
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30507), SITE_IDENTIFIER, 'showCategories'))  # Kategorien
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30814), SITE_IDENTIFIER, 'showLetters'))  # A-Z
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'))  # Suche
    cGui().setEndOfDirectory()


def _requestUrl(sUrl):
    # Kodiert unmittelbar vor dem Abruf — der Parameterweg macht jede Kodierung
    # rueckgaengig (unquote_plus). Anders als sonst ist '#' hier NICHT sicher:
    # der A-Z-Abschnitt "#" heisst in der Adresse ?dmt_letter=# und muss als
    # %23 raus, sonst streicht urllib alles ab '#' und die Seite liefert
    # Buchstabe A. '+' ebenso nicht, damit ein Suchbegriff mit Pluszeichen
    # nicht zum Leerzeichen wird. '%' bleibt, damit bereits kodierte Adressen
    # nicht doppelt kodiert werden.
    return quote(sUrl, safe=':/?&=%')


def _request(sUrl, ignoreErrors=False, caching=True):
    oRequest = cRequestHandler(_requestUrl(sUrl), ignoreErrors=ignoreErrors, caching=caching)
    return oRequest.request()


def _cardMeta(sChunk):
    """(year, duration, rating) aus den Meta-Spans einer Karte — jede Angabe
    einzeln, weil nicht jede Kartenform alle drei fuehrt (die Kino-Buehne hat
    keine Laufzeit)."""
    mYear = _RE_CARD_YEAR.search(sChunk)
    mDuration = _RE_CARD_DURATION.search(sChunk)
    mRating = _RE_CARD_RATING.search(sChunk)
    return (mYear.group(1) if mYear else '', mDuration.group(1) if mDuration else '', mRating.group(1) if mRating else '')


def _parseCards(sHtmlContent):
    """Filmkarten einer Liste als (url, name, thumb, year, duration, rating)."""
    aCards = []
    for sCard in _RE_CARD.findall(sHtmlContent):
        m = _RE_CARD_LINK.search(sCard)
        if not m:
            continue
        sName = cUtil.unescape(cUtil.removeHtmlTags(m.group(2))).strip()
        if not sName:
            continue
        mImg = _RE_CARD_IMG.search(sCard)
        aCards.append((m.group(1), sName, mImg.group(1) if mImg else '') + _cardMeta(sCard))
    return aCards


def _homeBlocks(sHtmlContent):
    """Die <section>-Bloecke der Startseite als (class, inhalt), in Seitenreihenfolge."""
    aBlocks = []
    aStarts = [m for m in re.finditer(r'<section\s+class="([^"]*)"[^>]*>', sHtmlContent)]
    for i, m in enumerate(aStarts):
        iEnd = aStarts[i + 1].start() if i + 1 < len(aStarts) else len(sHtmlContent)
        aBlocks.append((m.group(1), sHtmlContent[m.end():iEnd]))
    return aBlocks


def _homeRows(sHtmlContent):
    """Reihen der Startseite als [(key, label, [(url, name, thumb, year, duration, rating), …])].

    Die Kino-Buehne fuehrt Backdrops (1280x720) statt Poster; die Poster der
    Kino- und Neuerscheinungs-Filme stehen in der top-cover-Reihe desselben
    Blocks (dieselben 25 Filme, Mobil-Layout). Adressen kommen deshalb aus der
    Buehne, Poster und Titel per Adresse aus der top-cover-Reihe.
    """
    aRows = []
    for sClass, sBlock in _homeBlocks(sHtmlContent):
        if 'top-strip' in sClass:
            dCover = {}
            for sUrl, sThumb, sName in _RE_HOME_TOPCOVER.findall(sBlock):
                dCover[sUrl] = (cUtil.unescape(sName).strip(), sThumb)
            for sKey, oLabel, oCard in (('cinema', _RE_HOME_CINEMA_LABEL, _RE_HOME_CINEMA_CARD),
                                        ('new', _RE_HOME_NEW_LABEL, _RE_HOME_NEW_CARD)):
                mLabel = oLabel.search(sBlock)
                aEntries = []
                seen = set()
                for sUrl, sInner in oCard.findall(sBlock):
                    if sUrl in seen:
                        continue
                    seen.add(sUrl)
                    sName, sThumb = dCover.get(sUrl, ('', ''))
                    if not sName:
                        mName = re.search(r'<strong>([^<]*)</strong>', sInner)
                        sName = cUtil.unescape(mName.group(1)).strip() if mName else ''
                    if not sThumb:
                        mThumb = re.search(r'srcset="([^"]+)"', sInner)
                        sThumb = mThumb.group(1) if mThumb else ''
                    if sName:
                        aEntries.append((sUrl, sName, sThumb) + _cardMeta(sInner))
                if mLabel and aEntries:
                    aRows.append((sKey, cUtil.unescape(mLabel.group(1)).strip(), aEntries))
        elif 'movie-list-section' in sClass:
            if 'theme' in sClass:
                # Themen-Reiter: Label aus dem Button, Filme aus dem Panel mit demselben Schluessel
                aParts = _RE_HOME_THEME_PANEL.split(sBlock)
                dPanels = dict(zip(aParts[1::2], aParts[2::2]))
                for sKey, sLabel in _RE_HOME_THEME_TAB.findall(sBlock):
                    aEntries = _parseCards(dPanels.get(sKey, ''))
                    if aEntries:
                        aRows.append(('theme-' + sKey, cUtil.unescape(sLabel).strip(), aEntries))
                continue
            mLabel = _RE_HOME_SECTION_LABEL.search(sBlock)
            aEntries = _parseCards(sBlock)
            if mLabel and aEntries:
                # Schluessel ist die unterscheidende Klasse des Blocks (dmt-…-section)
                sKey = 'section-' + sClass.split()[-1]
                aRows.append((sKey, cUtil.unescape(mLabel.group(1)).strip(), aEntries))
    return aRows


def showRows():
    params = ParameterHandler()
    sHtmlContent = _request(params.getValue('sUrl') or URL_MAIN)
    aRows = _homeRows(sHtmlContent)
    if not aRows:
        cGui().showInfo()
        return
    for sKey, sLabel, aEntries in aRows:
        params = ParameterHandler()
        params.setParam('sUrl', URL_MAIN)
        params.setParam('sRow', sKey)
        oGuiElement = cGuiElement(sLabel, SITE_IDENTIFIER, 'showEntries')
        oGuiElement.setThumbnail(aEntries[0][2])
        cGui().addFolder(oGuiElement, params)
    cGui().setEndOfDirectory()


def showCategories():
    sHtmlContent = _request(URL_CATEGORIES)
    aCards = _RE_CATEGORY_CARD.findall(sHtmlContent)
    if not aCards:
        cGui().showInfo()
        return
    for sCard in aCards:
        m = _RE_CATEGORY_LINK.search(sCard)
        if not m:
            continue
        mImg = _RE_CATEGORY_IMG.search(sCard)
        params = ParameterHandler()
        params.setParam('sUrl', m.group(1))
        oGuiElement = cGuiElement(cUtil.unescape(m.group(2)).strip(), SITE_IDENTIFIER, 'showEntries')
        if mImg:
            oGuiElement.setThumbnail(mImg.group(1))
        cGui().addFolder(oGuiElement, params)
    cGui().setEndOfDirectory()


def showLetters():
    sHtmlContent = _request(URL_LETTERS)
    aLetters = _RE_LETTER.findall(sHtmlContent)
    if not aLetters:
        cGui().showInfo()
        return
    for sKey, sLabel in aLetters:
        params = ParameterHandler()
        # Der Schluessel wandert roh ('#', '0-9', 'a'); kodiert wird erst im Abruf.
        params.setParam('sUrl', '%s?dmt_letter=%s' % (URL_LETTERS, sKey))
        cGui().addFolder(cGuiElement(cUtil.unescape(sLabel).strip(), SITE_IDENTIFIER, 'showEntries'), params)
    cGui().setEndOfDirectory()


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl:
        entryUrl = params.getValue('sUrl')
    sRow = params.getValue('sRow')
    sHtmlContent = _request(entryUrl, ignoreErrors=(sGui is not False))
    if sRow:
        # Reihe der Startseite: nur der Block dieser Reihe, kein Blaettern.
        params.setParam('sRow', '')
        aResult = []
        for sKey, sLabel, aEntries in _homeRows(sHtmlContent):
            if sKey == sRow:
                aResult = aEntries
                break
    else:
        aResult = _parseCards(sHtmlContent)
    if not aResult:
        if not sGui:
            oGui.showInfo()
        return

    total = len(aResult)
    for sUrl, sName, sThumb, sYear, sDuration, sRating in aResult:
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setMediaType('movie')
        oGuiElement.setThumbnail(sThumb)
        if sYear:
            oGuiElement.setYear(sYear)
        if sDuration:
            oGuiElement.addItemValue('duration', sDuration)
        if sRating:
            oGuiElement.addItemValue('rating', sRating)
        params.setParam('entryUrl', sUrl)
        params.setParam('sName', sName)
        params.setParam('sThumbnail', sThumb)
        oGui.addFolder(oGuiElement, params, False, total)

    if not sGui:
        if not sRow:
            _addNextPage(oGui, sHtmlContent)
        oGui.setView('movies')
        oGui.setEndOfDirectory()


def _addNextPage(oGui, sHtmlContent):
    # Beleg fuer die Folgeseite ist der Weiter-Link der Leiste selbst (auf der
    # letzten Seite fehlt er). Die Seitenlage kommt aus derselben Leiste: die
    # letzte Seite steht dort immer als Link, die aktive als <span>.
    m = _RE_PAGINATION.search(sHtmlContent)
    if not m:
        return
    sNav = m.group(1)
    mNext = _RE_PAGE_NEXT.search(sNav)
    if not mNext:
        return
    mCurrent = _RE_PAGE_CURRENT.search(sNav)
    aNumbers = [int(x) for x in _RE_PAGE_NUMBER.findall(sNav)]
    sPageInfo = ''
    if mCurrent and aNumbers:
        sPageInfo = cGui.pageInfo(int(mCurrent.group(1)), max(aNumbers + [int(mCurrent.group(1))]))
    params = ParameterHandler()
    params.setParam('sUrl', cUtil.unescape(mNext.group(1)))
    oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', params, sPageInfo)


def showSearch():
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
    # quote statt quotePlus: das '+' fuer Leerzeichen wuerde in _requestUrl zu
    # %2B, weil '+' dort bewusst nicht sicher ist — die Seite nimmt %20 genauso
    # wie '+' (Seite 1 bei Zwei-Wort-Begriffen identisch, ihre eigenen
    # Sortier-Links nutzen %20).
    showEntries(URL_SEARCH % cParser.urlEncode(sSearchText), oGui, sSearchText)


def showHosters():
    hosters = []
    params = ParameterHandler()
    sUrl = params.getValue('entryUrl')
    if not sUrl:
        return hosters
    sHtmlContent = _request(sUrl, caching=False)
    # Ein Panel je Player-Reiter; der Link steckt im <template> des Panels.
    aPanels = sHtmlContent.split('data-nfo-player-panel="')[1:]
    for sPanel in aPanels:
        mLabel = _RE_HOSTER_LABEL.search(sPanel)
        mFrame = _RE_HOSTER_IFRAME.search(sPanel)
        if not mFrame:
            continue
        sHosterUrl = mFrame.group(1)
        if 'youtube' in sHosterUrl:
            continue
        # Der Blocked-Check bekommt die volle Adresse: die VOE-Spiegel der Seite
        # heissen z.B. eugenemakedraw.com, nur aus der Adresse findet ResolveURL
        # den Resolver. Angezeigt wird das Label der Seite (VOE, Vidara …).
        isBlocked, sHosterName = cConfig().isBlockedHoster(sHosterUrl)
        if isBlocked:
            continue
        sLabel = cUtil.unescape(mLabel.group(1)).strip() if mLabel else sHosterName
        hosters.append({'link': sHosterUrl, 'name': sHosterName, 'displayedName': sLabel,
                        'languageCode': '', 'quality': '720'})
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def getHosterUrl(sUrl=False):
    return [{'streamUrl': sUrl, 'resolved': False}]
