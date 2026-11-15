# -*- coding: utf-8 -*-
# Python 3

import sys

from urllib.parse import parse_qsl, urlsplit, urlencode


class ParameterHandler:
    def __init__(self):
        params = dict()
        if len(sys.argv) >= 3 and len(sys.argv[2]) > 0:
            params = dict(parse_qsl(urlsplit(sys.argv[2]).query))
        self.__params = params

    def getAllParameters(self):
        return self.__params

    def getValue(self, paramName):
        # returns value of one parameter as string, if parameter does not exists "False" is returned
        if self.exist(paramName):
            return self.__params[paramName]
        return False

    def exist(self, paramName):
        return paramName in self.__params

    def setParam(self, paramName, paramValue):
        # set the value of the parameter with the name "paramName" to "paramValue"
        # if there is no such parameter, the parameter is created
        paramValue = str(paramValue)
        self.__params.update({paramName: paramValue})

    def to_dict(self):
        """Serialize parameters to a plain dict for caching."""
        return dict(self.__params)

    @classmethod
    def from_dict(cls, data):
        """Reconstruct a ParameterHandler from a cached dict."""
        obj = cls.__new__(cls)
        obj.__params = dict(data) if data else {}
        return obj

    def getParameterAsUri(self):
        # Die Werte gehen unveraendert in die Adresse (urlencode) und kommen beim naechsten Aufruf ueber parse_qsl genauso
        # wieder heraus. Bis zum 02.11.2026 lief jeder Wert vorher durch unquote_plus — '+' wurde Leerzeichen, '%XX' wurde
        # aufgeloest: netzkino verlor die Kodierung seines Stream-Pfads (Leerzeichen in der Adresse), filmo das Plus im Titel
        # „Du+Ich", internetarchive bekam Vorschaubilder mit '/' statt '%2F' (Messung ueber alle 16 Sites, 02.11.2026).
        # Sites, die Adressen erst vor dem Abruf kodieren (movie2k, kellerkino, animetoast), bleiben richtig.
        outParams = dict()
        if 'params' in self.__params:
            del self.__params['params']
        if 'function' in self.__params:
            del self.__params['function']
        if 'title' in self.__params:
            del self.__params['title']
        if 'site' in self.__params:
            del self.__params['site']

        if len(self.__params) > 0:
            for param in self.__params:
                if len(self.__params[param]) < 1:
                    continue
                outParams[param] = self.__params[param]
            return urlencode(outParams)
        return 'params=0'
