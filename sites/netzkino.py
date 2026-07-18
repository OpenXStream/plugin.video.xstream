# -*- coding: utf-8 -*-
# Python 3
# Always pay attention to the translations in the menu!
# HTML LangzeitCache hinzugefügt
# showEntries:      6 Stunden
# showEntriesUnJson:6 Stunden


import json

from resources.lib.handler.ParameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.tools import cParser
from resources.lib.logger import logger
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui

SITE_IDENTIFIER = 'netzkino'
SITE_NAME = 'NetzKino'
SITE_ICON = 'netzkino.png'

# Global search function is thus deactivated!
if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

# Domain Abfrage
DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'www.netzkino.de') # Domain Auswahl über die xStream Einstellungen möglich
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status') # Status Code Abfrage der Domain
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER) # Ob Plugin aktiviert ist oder nicht

URL_MAIN = 'https://api.netzkino.de.simplecache.net/capi-2.0a/categories/%s.json?d=www&l=de-DE'
URL_SEARCH = 'https://api.netzkino.de.simplecache.net/capi-2.0a/search?q=%s&d=www&l=de-DE'
URL_START = 'https://' + DOMAIN + '/category/%s'
URL_INDEX = 'https://api.netzkino.de.simplecache.net/capi-2.0a/index.json?d=www'
#

def load(): # Menu structure of the site plugin
    logger.info('Load %s' % SITE_NAME)
    oGui = cGui()
    params = ParameterHandler()
    oGui.addFolder(cGuiElement('Startseite', SITE_IDENTIFIER, 'showStart'), params)  # Startseite
    oGui.addFolder(cGuiElement('Genres', SITE_IDENTIFIER, 'showGenreMenu'))
    oGui.addFolder(cGuiElement('Suche', SITE_IDENTIFIER, 'showSearch'), params)
    oGui.setEndOfDirectory()


def showStart():
    params = ParameterHandler()
    oRequest = cRequestHandler(URL_INDEX)
    jSearch = json.loads(oRequest.request())
    if not jSearch: return
    total = len(jSearch['homepage_categories'])
    for item in jSearch['homepage_categories']:
        params.setParam('sUrl', URL_MAIN % item['slug'])
        cGui().addFolder(cGuiElement( item['title'], SITE_IDENTIFIER, 'showEntries'), params)
    cGui().setEndOfDirectory()
    

def showGenreMenu():
    oGui = cGui()
    params = ParameterHandler()
    oRequest = cRequestHandler(URL_INDEX)
    jSearch = json.loads(oRequest.request())
    if not jSearch: return
    total = len(jSearch['categories'])
    for item in jSearch['categories']:
        params.setParam('sUrl', URL_MAIN % item['slug'])
        oGui.addFolder(cGuiElement(item['title'], SITE_IDENTIFIER, 'showEntries'), params)    
    oGui.setEndOfDirectory()


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl: entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=sGui is not False)
    if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'true':
        oRequest.cacheTime = 60 * 60 * 6  # 6 Stunden
    jSearch = json.loads(oRequest.request())  # Lade JSON aus dem Request der URL
    if not jSearch: return  # # Wenn Suche erfolglos - Abbruch

    if 'posts' not in jSearch or len(jSearch['posts']) == 0:
        if not sGui: oGui.showInfo()
        return

    total = len(jSearch['posts'])
    for item in jSearch['posts']:
        try:
            if sSearchText and not cParser.search(sSearchText, item['title']):
                continue
            oGuiElement = cGuiElement(str(item['title']), SITE_IDENTIFIER, 'showHosters')
            oGuiElement.setThumbnail(str(item['thumbnail']))
            oGuiElement.setDescription(str(item['content']))
            oGuiElement.setFanart(str(item['custom_fields']['featured_img_all'][0]))
            oGuiElement.setYear(str(item['custom_fields']['Jahr'][0]))
            oGuiElement.setQuality(str(item['custom_fields']['Adaptives_Streaming'][0]))
            oGuiElement.setMediaType('movie')
            if 'Duration' in item['custom_fields'] and item['custom_fields']['Duration'][0]:
                oGuiElement.addItemValue('duration', item['custom_fields']['Duration'][0])
            urls = ''
            if 'Streaming' in item['custom_fields'] and item['custom_fields']['Streaming'][0]:                                  
                urls += 'https://pmd.netzkino-seite.netzkino.de/%s.mp4' % item['custom_fields']['Streaming'][0]
            if 'Youtube_Delivery_Id' in item['custom_fields'] and item['custom_fields']['Youtube_Delivery_Id'][0]:
                urls += '#' + 'plugin://plugin.video.youtube/play/?video_id=%s' % item['custom_fields']['Youtube_Delivery_Id'][0]
            params.setParam('entryUrl', urls)
            oGui.addFolder(oGuiElement, params, False, total)
        except:
            continue

    if not sGui:
        oGui.setView('movies')
        oGui.setEndOfDirectory()


def showEntriesUnJson(entryUrl=False, sGui=False, sSearchText=False):
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl: entryUrl = params.getValue('sUrl')
    oRequest = cRequestHandler(entryUrl, ignoreErrors=(sGui is not False))
    if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'true':
        oRequest.cacheTime = 60 * 60 * 6  # 6 Stunden
    sHtmlContent = oRequest.request()
    #Aufbau pattern
    #'item":.*?'  # Container Start
    #'image.*?(https[^"]+).*?'  # Image
    #'name":\s.*?([^"]+).*?'  # Name
    #'url":\s.*?([^"]+).*?'  # URL
    #'(.*?)}'  # Dummy
    pattern = r'item":.*?image.*?(https[^"]+).*?name":\s.*?([^"]+).*?url":\s.*?([^"]+).*?(.*?)}'
    isMatch, aResult = cParser.parse(sHtmlContent, pattern)

    if not isMatch:
        if not sGui: oGui.showInfo()
        return

    total = len(aResult)
    for sThumbnail, sName, sUrl, sDummy in aResult:
        try:
            if sSearchText and not cParser.search(sSearchText, sName):
                continue
            isDuration, sDurationH = cParser.parseSingleResult(sDummy, r'duration":\s"([\d]+).*?')  # Laufzeit Stunden
            isDuration, sDurationM = cParser.parseSingleResult(sDummy, r'H([\d]+).*?')  # Laufzeit Minuten
            oGuiElement = cGuiElement(sName, SITE_IDENTIFIER, 'showHostersUnJson')
            oGuiElement.setThumbnail(sThumbnail)
            if isDuration:
                oGuiElement.addItemValue('duration', int(sDurationH) *60 + int(sDurationM))
            oGuiElement.setMediaType('movie')
            params.setParam('entryUrl', sUrl)
            params.setParam('sName', sName)
            params.setParam('sThumbnail', sThumbnail)
            oGui.addFolder(oGuiElement, params, False, total)
        except:
            continue
    if not sGui:
        oGui.setView('movies')
        oGui.setEndOfDirectory()


def showHosters():
    hosters = []
    URL = ParameterHandler().getValue('entryUrl')
    for sUrl in URL.split('#'):
        hoster = {'link': sUrl, 'name': 'Netzkino' if 'netzkino' in sUrl else 'Youtube', 'resolveable': True}
        hosters.append(hoster)
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def showHostersUnJson():
    hosters = []
    sHtmlContent = cRequestHandler(ParameterHandler().getValue('entryUrl')).request()
    isMatch, aResult = cParser.parse(sHtmlContent, 'pmdUrl":"([^"]+)')
    if isMatch:
        for sUrl in aResult:
            sName = 'Netzkino'
            sUrl = 'https://pmd.netzkino-seite.netzkino.de/' + sUrl
            hoster = {'link': sUrl, 'name': sName, 'resolveable': True}
            hosters.append(hoster)
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def getHosterUrl(sUrl=False):
    return [{'streamUrl': sUrl, 'resolved': True}]


def showSearch():
    sSearchText = cGui().showKeyBoard(sHeading=cConfig().getLocalizedString(30287))
    if not sSearchText: return
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def _search(oGui, sSearchText):
    showEntries(URL_SEARCH % cParser.quotePlus(sSearchText), oGui, sSearchText)
