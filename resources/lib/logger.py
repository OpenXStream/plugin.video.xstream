# -*- coding: utf-8 -*-
# Python 3
# xStream interner Log
import re
import sys
import xbmc
import xbmcaddon
from urllib.parse import parse_qsl, urlsplit

# API-Schluessel in Adressen kommen nie ins Log (Hilfe-Logs landen oft in fremden Haenden): TMDB
# traegt ihn als api_key in der Adresse, und der requestHandler schreibt jede Adresse mit — ein selbst
# eingetragener TMDB-Schluessel stand so bis zum 31.10.2026 im Klartext im Log; YouTube traegt ihn als
# key, und trailer.py schreibt die Adresse bei einem Fehler gekuerzt mit.
_SECRET_PARAM = re.compile(r'([?&](?:api_key|key)=)[^&\s]+', re.IGNORECASE)


class logger:
    ADDON_NAME = xbmcaddon.Addon().getAddonInfo('name')

    @staticmethod
    def info(sInfo):
        logger.__writeLog(sInfo, cLogLevel=xbmc.LOGINFO)

    @staticmethod
    def debug(sInfo):
        logger.__writeLog(sInfo, cLogLevel=xbmc.LOGDEBUG)

    @staticmethod
    def warning(sInfo):
        logger.__writeLog(sInfo, cLogLevel=xbmc.LOGWARNING)

    @staticmethod
    def error(sInfo):
        logger.__writeLog(sInfo, cLogLevel=xbmc.LOGERROR)

    @staticmethod
    def __writeLog(sLog, cLogLevel=xbmc.LOGDEBUG):
        try:
            params = dict()
            if len(sys.argv) >= 3 and len(sys.argv[2]) > 0:
                params = dict(parse_qsl(urlsplit(sys.argv[2]).query))
            if 'site' in params:
                sLog = "[%s] -> [%s]: %s" % (logger.ADDON_NAME, params['site'], sLog)
            else:
                sLog = "[%s] %s" % (logger.ADDON_NAME, sLog)
            xbmc.log(_SECRET_PARAM.sub(r'\1***', sLog), cLogLevel)
        except Exception as e:
            xbmc.log('Logging Failure: %s' % e, cLogLevel)
