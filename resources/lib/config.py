# -*- coding: utf-8 -*-
# Python 3

import xbmcaddon
import threading

from urllib.parse import urlparse
from resources.lib.logger import logger

class cConfig:
    _instances = {}  # Cache for addon_id -> cConfig instance
    _addon_cache = {}  # Cache for addon_id -> xbmcaddon.Addon instance
    _settings_lock = threading.Lock()
    _default_id = None  # eigene Addon-ID, einmal pro Interpreter ermittelt

    # singleton implementation
    def __new__(cls, *args, **kwargs):
        # Die eigene Addon-ID wird EINMAL ermittelt und gemerkt. cConfig() laeuft
        # pro Listeneintrag vielfach; ein xbmcaddon.Addon() je Aufruf nur fuer die
        # ID waeren hunderte Kodi-Objekte pro Liste (spuerbar auf schwachen Boxen).
        addon_id = kwargs.get('addon_id') or (args[0] if args else None)
        if not addon_id:
            if cls._default_id is None:
                cls._default_id = xbmcaddon.Addon().getAddonInfo('id')
            addon_id = cls._default_id
        if addon_id not in cls._instances:
            instance = super(cConfig, cls).__new__(cls)
            instance._addon_id = addon_id
            if addon_id not in cls._addon_cache:
                cls._addon_cache[addon_id] = xbmcaddon.Addon(addon_id)
            instance.__addon = cls._addon_cache[addon_id]
            instance.__aLanguage = instance.__addon.getLocalizedString
            cls._instances[addon_id] = instance
        return cls._instances[addon_id]
    
    def showSettingsWindow(self):
        self.__addon.openSettings()

    def getSetting(self, sName, default=''):
        result = self.__addon.getSetting(sName)
        if result:
            return result
        else:
            return default
        
    def getSettingString(self, sName, default=''):
        result = self.__addon.getSetting(sName)
        if result:
            return str(result)
        else:
            return default

    def setSetting(self, id, value):
        # Frueher stand hier `if id and value` — damit liefen alle Versuche ins
        # Leere, einen Wert zu LOESCHEN (Domain zuruecksetzen, Statuscode
        # verwerfen). Ein leerer String ist ein gueltiger Wert und muss
        # gespeichert werden koennen; nur None wird weiterhin verworfen.
        if id and value is not None:
            with cConfig._settings_lock:
                self.__addon.setSetting(id, value)

    def getAddonInfo(self, sName):
        result = self.__addon.getAddonInfo(sName)
        if result:
            return result
        else:
            return ''

    def getLocalizedString(self, sCode):
        return self.__aLanguage(sCode)
        
    def isBlockedHoster(self, domain, checkResolver=True ):
        import html
        domain = urlparse(domain).path if urlparse(domain).hostname == None else urlparse(domain).hostname
        hostblockDict = []  # Filterung erfolgt ueber ResolveURL-Check + User-Setting blockedHoster
        blockedHoster = cConfig().getSetting('blockedHoster').replace(',', ' ').split()  # Komma UND Space als Trenner (frei mischbar)
        for i in blockedHoster: hostblockDict.append(i.strip().lower())
        for i in hostblockDict:
            # Voller Domain-Eintrag (z.B. moflix-stream.click) blockt NUR genau diese Domain.
            # Nackter Name (z.B. doodstream) matcht weiterhin alle TLDs, da Substring von doodstream.xx.
            if i in domain.lower(): return True, domain
        if checkResolver:   # Überprüfung in resolveUrl
            # Lazy Import: der Import von ResolveURL laedt alle Resolver-Plugins
            # (auf schwachen ARM-Boxen spuerbar). Listenansichten ohne Hoster
            # brauchen ihn nicht — deshalb erst hier, wo er wirklich gebraucht wird.
            import resolveurl as resolver
            domain_clean = html.unescape(domain)  # Fix fuer URLs mit &amp; etc. (ResolveURL PR #1115)
            if resolver.relevant_resolvers(domain=domain_clean) == []:
                logger.warning('In resolveUrl no domain for url: %s' % domain)
                return True, domain    # Domain nicht in resolveUrl gefunden
        return False, domain