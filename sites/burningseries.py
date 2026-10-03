# -*- coding: utf-8 -*-
# Python 3

# Always pay attention to the translations in the menu!



import ast
import json
import locale
import re
import time

import xbmcgui
from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler, REQUEST_ERRORS
from resources.lib.logger import logger
from resources.lib.tools import cParser, cUtil, infoDialog
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui
from resources.lib.captcha.captcha_helper import captcha_ready, solve_recaptcha, extract_recaptcha_sitekey


SITE_IDENTIFIER = 'burningseries'
SITE_NAME = 'BurningSeries'
SITE_ICON = 'burningseries.png'

if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

if cConfig().getSetting('2captcha.pass') == '':
    cConfig().setSetting('plugin_burningseries', 'false')
    cConfig().setSetting('global_search_burningseries', 'false')
    cConfig().setSetting('plugin_burningseries_checkDomain', 'false')
    logger.info('-> [SitePlugin]: 2Captcha API Key not set')

DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'burningseries.ac')
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)

URL_LOGIN = ''
URL_MAIN = 'https://' + DOMAIN
REFERER = 'https://' + DOMAIN
URL_SERIES = URL_MAIN + '/andere-serien'
URL_NEW_SERIES = URL_MAIN + '/'
URL_NEW_EPISODES = URL_MAIN + '/'
URL_POPULAR = URL_MAIN + '/vorgeschlagene-serien'
URL_ALPHABET = URL_MAIN + '/serie-alphabet'
URL_GENRES = URL_MAIN + '/serie-genre'

# --- Sprachfassungen ------------------------------------------------------
# Die Seite haengt die Fassung als letztes Pfadstueck an: serie/<Name>/<Staffel>/<lang>
# bzw. serie/<Name>/<Staffel>/<Episode>/<lang>. Welche Fassungen es gibt, steht in einem
# <select class="series-language"> auf der Staffel- UND der Episodenseite; die Serienseite
# ist die Ansicht der Standardstaffel und traegt nur deren Auswahl. Die Auswahl ist pro
# Staffel verschieden (Bridgerton hat "des" nur in Staffel 1 — live bestaetigt 02.09.2026).
# Die Beschriftungen der Seite lauten "Deutsch", "Deutsch Sub", "English" und
# "English Sub". Sub heisst dabei Originalton mit Untertiteln — welche Sprache der Ton
# hat, sagt die Seite NICHT. Deshalb behaupten wir es auch nicht: die Sub-Fassungen
# werden keiner Spracheinstellung zugeordnet und erscheinen nur unter "Alle", genauso
# wie Ger-Sub bei serienstream.
LANG_LABELS = {'de': '(DE)', 'des': '(Sub: DE)', 'en': '(EN)', 'jps': '(Sub: EN)'}
# prefLanguage: 0 Alle, 1 Deutsch, 2 Englisch, 3 Japanisch.
# BurningSeries hat keine als japanisch gekennzeichnete Fassung — deshalb liefert 3
# bewusst nichts und der Hinweis kommt ueber den 'if not hosters'-Zweig.
LANG_PREF = {'1': ('de',), '2': ('en',), '3': ()}

def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.burningseries.lastSearchText')
    params = ParameterHandler()
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30554), SITE_IDENTIFIER, 'showNeues'), params)      # Neues (Submenue)
    params.setParam('sUrl', URL_GENRES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30506), SITE_IDENTIFIER, 'showValue'), params)    # Genre
    params.setParam('sUrl', URL_ALPHABET)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30814), SITE_IDENTIFIER, 'showValue'), params)    # A-Z
    params.setParam('sUrl', URL_SERIES)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'), params)   # Search
    cGui().setEndOfDirectory()


def showNeues():
    """Submenue 'Neues' — fasst Neue Serien und Neue Folgen zusammen (wie serienstream).

    Fuer jeden Eintrag ein FRISCHER ParameterHandler, damit sich die sUrl der
    beiden Punkte nicht gegenseitig ueberschreibt.
    """
    oGui = cGui()
    params = ParameterHandler()
    params.setParam('sUrl', URL_NEW_SERIES)
    oGui.addFolder(cGuiElement(cConfig().getLocalizedString(30511), SITE_IDENTIFIER, 'showNewSeries'), params)    # Serien (30511/30557 wie SerienStream und AniWorld)
    params = ParameterHandler()
    params.setParam('sUrl', URL_NEW_EPISODES)
    oGui.addFolder(cGuiElement(cConfig().getLocalizedString(30557), SITE_IDENTIFIER, 'showNewEpisodes'), params)  # Episoden
    oGui.setEndOfDirectory()


def showValue():
    params = ParameterHandler()
    sUrl = params.getValue('sUrl')

    oRequest = cRequestHandler(sUrl)
    sHtmlContent = oRequest.request()

    pattern = r'<div class="genre">\s*<span><strong>([^<]+)</strong></span>'
    isMatch, aGenre = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        cGui().showInfo()
        return

    for sName in aGenre:
        params.setParam('sGenre', sName.strip())
        cGui().addFolder(cGuiElement(sName, SITE_IDENTIFIER, 'showEntries'), params)
    cGui().setEndOfDirectory()


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl: entryUrl = params.getValue('sUrl')
    sGenre = params.getValue('sGenre')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()

    genre_div_pattern = rf'<div class="genre">\s*<span><strong>{sGenre}</strong></span>\s*<ul>(.*?)</ul>'
    isMatchGenre, aResultGenre = cParser.parseSingleResult(sHtmlContent, genre_div_pattern)
    if not isMatchGenre:
        if not sGui: oGui.showInfo()
        return

    pattern = r'<a[^>]+href="(serie/[^"]+)"[^>]+title="([^"]+)"'
    isMatch, aResult = cParser.parse(aResultGenre, pattern)
    if not isMatch:
        if not sGui: oGui.showInfo()
        return
    total = len(aResult)
    sst = sSearchText.lower() if sSearchText else ''
    for sUrl, sName in aResult:
        sNameLow = sName.lower()
        if sSearchText and not sst in sNameLow and not cUtil.isSimilarByToken(sst, sNameLow):
            continue
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        params.setParam('sUrl', URL_MAIN + '/' + sUrl)
        params.setParam('TVShowTitle', sName)
        oGui.addFolder(oGuiElement, params, True, total)
    if not sGui:
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()


def showAllSeries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl: entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()


    pattern = r'<a[^>]+href="(serie/[^"]+)"[^>]+title="([^"]+)"'

    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    # Sort entries alphabetically by name (second tuple element)
    # A locale aware sorting is used to get better results for e.g. german umlauts
    locale.setlocale(locale.LC_COLLATE, '')
    aResult = sorted(aResult, key=lambda x: locale.strxfrm(x[1].lower()))

    total = len(aResult)
    sst = sSearchText.lower() if sSearchText else ''
    iShown = 0
    for sUrl, sName in aResult:
        sNameLow = sName.lower()
        if sSearchText and not sst in sNameLow and not cUtil.isSimilarByToken(sst, sNameLow):
            continue
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        params.setParam('sUrl', URL_MAIN + '/' + sUrl)
        params.setParam('TVShowTitle', sName)
        oGui.addFolder(oGuiElement, params, True, total)
        iShown += 1
    if not sGui:
        # Der Titelfilter kann ALLE Eintraege verwerfen: die Seite hat dann geliefert,
        # der isMatch-Zweig oben greift also nicht, und die Liste bleibt trotzdem leer.
        # Ohne diesen Hinweis steht der Nutzer nach einer Suche ohne Treffer vor einem
        # leeren Verzeichnis — burningseries war die letzte Seite im Addon, die schwieg.
        if not iShown:
            oGui.showInfo()
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()


def showNewEpisodes(entryUrl=False, sGui=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl:
        entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()
    sectionPattern = r'<section[^>]*id="newest_episodes"[^>]*>.*?<ul[^>]*>(.*?)</ul>.*?</section>'
    isMatch, aResult = cParser.parseSingleResult(sHtmlContent, sectionPattern)

    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    # Das Flaggen-Icon wird komplett mitgenommen: die Klasse traegt den Sprachcode
    # (flag-de, flag-des, flag-en, flag-jps), das title-Attribut den Klartext. Wir nehmen
    # den Code und beschriften ueber dieselbe Tabelle wie die Hosterliste, damit beide
    # nicht auseinanderlaufen; der Klartext bleibt als Rueckfallebene.
    isEpisodesMatch, aEpisodes = cParser.parse(aResult, r'<li[^>]*>\s*<a href="([^"]+)"[^>]*class="title"[^>]*>([^<]+)</a>\s*<div class="info">([^<]+)(<i[^>]*>)</i></div>\s*</li>')

    if not isEpisodesMatch:
        if not sGui: oGui.showInfo()
        return
    total = len(aEpisodes)
    for sUrl, sName, sInfo, sFlag in aEpisodes:
        mCode = re.search(r'flag-([a-z]+)', sFlag)
        sLabel = LANG_LABELS.get(mCode.group(1), '') if mCode else ''
        if not sLabel:  # unbekannter Code -> Klartext der Seite nehmen statt gar nichts
            mTitle = re.search(r'title="([^"]+)"', sFlag)
            sLabel = '(%s)' % mTitle.group(1) if mTitle else ''
        sMovieTitle = ('%s %s %s' % (sName, sInfo, sLabel)).strip()
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        oGuiElement.setTitle(sMovieTitle)
        params.setParam('sUrl', URL_MAIN + '/' + sUrl)
        params.setParam('TVShowTitle', sMovieTitle)

        oGui.addFolder(oGuiElement, params, True, total)
    if not sGui:
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()


def showNewSeries(entryUrl=False, sGui=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl:
        entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    sHtmlContent = oRequest.request()

    pattern = r'<section[^>]*id="newest_series"[^>]*>.*?<ul[^>]*>(.*?)</ul>.*?</section>'
    isMatch, aResult = cParser.parseSingleResult(sHtmlContent, pattern)

    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    series_pattern = r'<li><a href="([^"]+)">([^<]+)</a></li>'
    isSeriesMatch, aSeriesResult = cParser.parse(aResult, series_pattern)

    if not isSeriesMatch:
        if not sGui: oGui.showInfo()
        return

    total = len(aSeriesResult)
    for sUrl, sName in aSeriesResult:
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        params.setParam('sUrl', URL_MAIN + '/' + sUrl)
        params.setParam('TVShowTitle', sName)
        oGui.addFolder(oGuiElement, params, True, total)
    if not sGui:
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()


def showSeasons():
    params = ParameterHandler()
    sUrl = params.getValue('sUrl')
    sTVShowTitle = params.getValue('TVShowTitle')
    sTmdbID = params.getValue('tmdbID') or ''
    oRequest = cRequestHandler(sUrl)
    sHtmlContent = oRequest.request()
    pattern = r'<li class="s(\d+)(?:\s+active)?"><a href="([^"]+)">([^<]+)</a></li>'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)
    if not isMatch:
        cGui().showInfo()
        return

    isDesc, sDesc = cParser.parseSingleResult(sHtmlContent, r'<div id="sp_left">.*?<p>(.*?)</p>')
    isThumbnail, sThumbnail = cParser.parseSingleResult(sHtmlContent, r'<div id="sp_right"[^>]*>.*?<img[^>]*src="([^"]+)"')
    if isThumbnail and sThumbnail.startswith('/'):
        sThumbnail = URL_MAIN + sThumbnail

    # Aki: Year aus Produktionsjahre-Feld der Detail-Seite extrahieren
    sYear = ''
    year_match = re.search(r'<span>Produktionsjahre</span>\s*<p>\s*<em>(\d{4})', sHtmlContent)
    if year_match:
        sYear = year_match.group(1)

    total = len(aResult)
    for sNr, sUrl, sName in aResult:
        isMovie = sNr.startswith('0')
        # Nur echte Staffeln tragen auf der Seite eine Nummer und bekommen das "Staffel"-Praefix.
        # Die Sonderstaffel (s0) beschriftet die Seite selbst ("Specials") — das Label wird
        # unveraendert uebernommen, sonst stuende "Staffel Specials" im Menue.
        sTitle = sName if isMovie else cConfig().getLocalizedString(30512) + ' ' + sName
        oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showEpisodes')
        oGuiElement.setMediaType('season')
        if isThumbnail:
            oGuiElement.setThumbnail(sThumbnail)
        if isDesc:
            oGuiElement.setDescription(sDesc)
        # Auch die Sonderstaffel gehoert zur Serie (Staffel 0): Serienname fuer InfoTag und
        # Weitere Quellen; tmdb_id nur fuer echte Staffeln
        oGuiElement.setTVShowTitle(sTVShowTitle)
        oGuiElement.setSeason(sNr)
        params.setParam('sSeason', sNr)
        if not isMovie:
            if sTmdbID:
                oGuiElement.addItemValue('tmdb_id', sTmdbID)
        if sYear:
            oGuiElement.addItemValue('year', sYear)
            params.setParam('sYear', sYear)
        params.setParam('sThumbnail', sThumbnail)
        params.setParam('sUrl', URL_MAIN + '/' + sUrl)
        cGui().addFolder(oGuiElement, params, True, total)
    cGui().setView('seasons')
    cGui().setEndOfDirectory()


def showEpisodes():
    params = ParameterHandler()
    sUrl = params.getValue('sUrl')
    sTVShowTitle = params.getValue('TVShowTitle')
    sSeason = params.getValue('sSeason')
    sThumbnail = params.getValue('sThumbnail')

    if not sSeason:
        sSeason = '1'
    # Filmliste der Serie (Staffel 0): heute /serie/<name>/0, frueher .../filme
    isMovieList = sUrl.endswith('filme') or sSeason == '0'
    oRequest = cRequestHandler(sUrl)
    sHtmlContent = oRequest.request()
    pattern = r'<tr[^>]*>\s*<td><a href="([^"]+)" title="([^"]+)">(\d+)</a></td>\s*<td>.*?<a href="([^"]+)" title="([^"]+)">.*?</td>\s*<td>(.*?)</td>\s*</tr>'
    isMatch, sEpisodes = cParser.parse(sHtmlContent, pattern)

    if not isMatch:
        logger.error('BurningSeries: showEpisodes: No episodes found for URL: %s' % sUrl)
        cGui().showInfo()
        return

    isDesc, sDesc = cParser.parseSingleResult(sHtmlContent, r'<div id="sp_left">.*?<p>(.*?)</p>')
    total = len(sEpisodes)
    for eLink, eTitle, sNumber, eLink2, eTitle2, eHosterContent in sEpisodes:
        # Die Seite fuehrt manche Titel mit fuehrendem '| ' (leerer deutscher Titel, z.B.
        # '| OVA 01 | Momoiro Genmutan | Pink Phantasm') und mit Leerzeichen am Ende — beides
        # landete bisher im Label und im originaltitle (Trailer, TMDB-Info, Weitere Quellen).
        eTitle = eTitle.strip().lstrip('|').strip()
        sName = sNumber + ' - ' + eTitle
        oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setMediaType('episode' if not isMovieList else 'movie')
        if isMovieList and eTitle:
            # Filmtitel ohne den Nummern-Vorsatz des Labels (Trailer, TMDB-Info, Weitere Quellen)
            oGuiElement.addItemValue('originaltitle', eTitle)
        oGuiElement.setThumbnail(sThumbnail)
        if isDesc:
            oGuiElement.setDescription(sDesc)
        if not isMovieList:
            oGuiElement.setSeason(sSeason)
            oGuiElement.setEpisode(int(sNumber))
            oGuiElement.setTVShowTitle(sTVShowTitle)
        params.setParam('sUrl', URL_MAIN + '/' + eLink2)
        params.setParam('entryUrl', sUrl)
        params.setParam('eHosterContent', eHosterContent)
        cGui().addFolder(oGuiElement, params, False, total)
    cGui().setView('episodes' if not isMovieList else 'movies')
    cGui().setEndOfDirectory()


def _parseLanguages(sHtmlContent):
    """Verfuegbare Fassungen der Seite und die gerade aktive.

    Rueckgabe ([Codes], aktiver Code). Fehlt das Select, ist die Episode einsprachig —
    dann gibt es auf der Seite auch kein Sprachsuffix und (geprueft an 74 Staffeln)
    ohnehin keine Hoster.
    """
    isMatch, sSelect = cParser.parseSingleResult(sHtmlContent, r'<select class="series-language">(.*?)</select>')
    if not isMatch:
        return [], ''
    aOptions = re.findall(r'<option value="([^"]+)"([^>]*)>', sSelect)
    sActive = next((c for c, attr in aOptions if 'selected' in attr), '')
    return [c for c, _ in aOptions], sActive


def _wantedLanguages(aLangs):
    """Welche Fassungen sollen laut Einstellung geholt werden?"""
    sPref = cConfig().getSetting('prefLanguage')
    if sPref in LANG_PREF:
        return [c for c in aLangs if c in LANG_PREF[sPref]]
    return list(aLangs)  # 0 = Alle


def _swapLanguage(sUrl, sActive, sNew):
    """Sprachsuffix der Episoden-URL austauschen.

    Nur das bekannte aktive Kuerzel wird abgeschnitten, damit kein Episodentitel
    zerschnitten wird, der zufaellig wie ein Sprachcode aussieht.
    """
    for sCode in (sActive,) + tuple(LANG_LABELS):
        # Erst das aktive Kuerzel, dann die uebrigen bekannten: faellt die Seite mal auf
        # eine andere Fassung zurueck als die URL nennt, wuerde sonst '.../de/en' gebaut.
        if sCode and sUrl.endswith('/' + sCode):
            return sUrl[:-len(sCode)] + sNew
    return sUrl.rstrip('/') + '/' + sNew


def _buildHosters(sHtmlContent, sLangCode):
    """Hoster-Dicts einer Episodenseite, beschriftet mit der Fassung."""
    hosters = []
    hosterTabspattern = r'<ul class="hoster-tabs[^"]*"[^>]*>(.*?)</ul>'
    hosterPattern = r'<a[^>]*href="([^"]+)"[^>]*>(?:.*?<i[^>]*></i>)?([^<]+)</a>'
    isMatchTabs, rHosterTabs = cParser.parseSingleResult(sHtmlContent, hosterTabspattern)
    if not isMatchTabs:
        return hosters
    isMatch, aResult = cParser.parse(rHosterTabs, hosterPattern)
    if not isMatch:
        return hosters
    sLabel = LANG_LABELS.get(sLangCode, '(%s)' % sLangCode) if sLangCode else ''
    sQuality = '720'
    for sHosterUrl, sName in aResult:
        sName = sName.strip()
        if cConfig().isBlockedHoster(sName)[0]: continue # Hoster aus settings.xml oder deaktivierten Resolver ausschliessen
        sDisplayed = '%s [I]%s [%sp][/I]' % (sName, sLabel, sQuality) if sLabel \
            else '%s [I][%sp][/I]' % (sName, sQuality)
        # languageCode IMMER setzen (notfalls leer): hoster.py sortiert danach und
        # vergleicht die Werte untereinander — ein Mix aus Text und Zahl wuerde krachen.
        hosters.append({'link': [sHosterUrl, sName], 'name': sName, 'displayedName': sDisplayed,
                        'quality': sQuality, 'languageCode': sLabel})
    return hosters


# Pause vor jedem Nachholversuch: gibt einem Rate-Limit Luft. Laenger kostet
# nur im Fehlerfall — im Normalfall laeuft keine einzige Pause.
RETRY_PAUSE = 0.6


def showHosters():
    hosters = []
    sUrl = ParameterHandler().getValue('sUrl')
    sHtmlContent = cRequestHandler(sUrl, caching=False).request()

    aLangs, sActive = _parseLanguages(sHtmlContent)
    if not aLangs:  # einsprachige Episode ohne Auswahl
        hosters = _buildHosters(sHtmlContent, '')
    else:
        for sLang in _wantedLanguages(aLangs):
            if sLang == sActive:
                sPage, sIst = sHtmlContent, sActive
            else:
                sPage = cRequestHandler(_swapLanguage(sUrl, sActive, sLang), caching=False).request()
                if not sPage or sPage in REQUEST_ERRORS:
                    # Eine gescheiterte Sprachseite liess deren Hoster bisher
                    # STILL in der Liste fehlen. Einmal mit Pause nachfassen.
                    time.sleep(RETRY_PAUSE)
                    sPage = cRequestHandler(_swapLanguage(sUrl, sActive, sLang), caching=False).request()
                    if not sPage or sPage in REQUEST_ERRORS:
                        logger.info('fetchRetry %s: Sprachseite %s nicht erreichbar, deren Hoster fehlen' % (SITE_NAME, sLang))
                        continue
                    logger.info('fetchRetry %s: Sprachseite %s nachgeholt' % (SITE_NAME, sLang))
                # Zurueckgelesen statt angenommen: liefert die Seite eine andere Fassung
                # als angefragt (sie faellt bei Unbekanntem selbst zurueck), wird auch die
                # tatsaechliche beschriftet. Doppelte fangen wir uns damit nicht ein, weil
                # der zentrale Dedup ueber Link + Name + Sprache geht.
                _, sIst = _parseLanguages(sPage)
            hosters += _buildHosters(sPage, sIst or sLang)

    if hosters:
        hosters.append('getHosterUrl')
    else:
        cGui().showLanguage()
    return hosters


def getHosterUrl(hUrl):
    if type(hUrl) == str: hUrl = ast.literal_eval(hUrl)

    Request = cRequestHandler(URL_MAIN + '/' + hUrl[0], caching=False)
    Request.addHeaderEntry('Referer', ParameterHandler().getValue('entryUrl'))
    Request.addHeaderEntry('Upgrade-Insecure-Requests', '1')
    htmlContent = Request.request()
    sitekey = extract_recaptcha_sitekey(htmlContent)
    if not sitekey:
        logger.error('BurningSeries: getHosterUrl: No sitekey found in HTML content.')
        return [{'streamUrl': '', 'resolved': False}]

    sUrl = Request.getRealUrl()

    # Ohne Schalter oder Schluessel gar nicht erst den Dialog zeigen
    if not captcha_ready():
        return [{'streamUrl': '', 'resolved': False}]

    infoDialog(cConfig().getLocalizedString(30825), icon='INFO', time=10000)
    google_captcha_token = solve_recaptcha(sitekey, sUrl)
    if not google_captcha_token:
        logger.error('BurningSeries: getHosterUrl: Failed to solve captcha.')
        infoDialog(cConfig().getLocalizedString(30826), icon='ERROR', time=10000)
        return [{'streamUrl': '', 'resolved': False}]

    lIDMatch, lID = cParser.parseSingleResult(htmlContent, r'data-lid="([^"]+)"')
    securityTokenMatch, securityToken = cParser.parseSingleResult(htmlContent, r'security_token" content="([^"]+)"')

    if not lIDMatch:
        logger.error('BurningSeries: getHosterUrl: No lID found in HTML content.')
        return [{'streamUrl': '', 'resolved': False}]

    if not securityTokenMatch:
        logger.error('BurningSeries: getHosterUrl: No securityToken found in HTML content.')
        return [{'streamUrl': '', 'resolved': False}]

    responseHeader = Request.getResponseHeader()
    if hasattr(responseHeader, 'get_all'):
        setCookieHeaders = responseHeader.get_all('Set-Cookie')
    elif hasattr(responseHeader, 'getheaders'):
        setCookieHeaders = responseHeader.getheaders('Set-Cookie')
    else:
        setCookieHeaders = []

    cookie_string_parts = []

    for header in setCookieHeaders:
        name_value = header.split(";", 1)[0].strip()
        if "=" in name_value:
            cookie_string_parts.append(name_value)

    headers = {
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'accept-language': 'de-DE,de;q=0.9',
        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'origin': URL_MAIN,
        'referer': sUrl,
        'user-agent': cRequestHandler.RandomUA(),
        'x-requested-with': 'XMLHttpRequest'
    }

    cookies = {}
    for part in cookie_string_parts:
        if "=" in part:
            name, value = part.split("=", 1)
            cookies[name.strip()] = value.strip()

    data = {
        'token': securityToken,
        'LID': lID,
        'ticket': google_captcha_token
    }

    embedRequest = cRequestHandler(f'{URL_MAIN}/ajax/embed.php', caching=False, method='POST', data=data)
    for k, v in headers.items():
        embedRequest.addHeaderEntry(k, v)
    if cookies:
        cookie_header = '; '.join([f"{k}={v}" for k, v in cookies.items()])
        embedRequest.addHeaderEntry('Cookie', cookie_header)
    # requestJson statt json.loads auf request(): der Handler liefert im
    # Fehlerfall einen Klartext-Sentinel statt zu werfen — json.loads machte
    # daraus einen Kodi-Skriptfehler, bevor der Guard darunter greifen konnte.
    parsedJson = embedRequest.requestJson()
    if not parsedJson or 'link' not in parsedJson:
        logger.error('BurningSeries: getHosterUrl: No result from resolve request.')
        return [{'streamUrl': '', 'resolved': False}]

    return [{'streamUrl': parsedJson['link'], 'resolved': False}]


def showSearch():
    win = xbmcgui.Window(10000)
    sSearchText = win.getProperty('xstream.burningseries.lastSearchText')
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30281))
        if not sSearchText: return
        win.setProperty('xstream.burningseries.lastSearchText', sSearchText)
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def _search(oGui, sSearchText):
    showAllSeries(URL_SERIES, oGui, sSearchText)
