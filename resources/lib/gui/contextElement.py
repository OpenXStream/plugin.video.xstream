# -*- coding: utf-8 -*-
# Python 3


class cContextElement:
    # Nur noch der Titeltraeger fuer die festen Kontextmenue-Eintraege in gui.__createContextMenu (Trailer, TMDB Info,
    # Hoster waehlen, Weitere Quellen, Info). Site-eigene Kontextelemente gibt es seit dem 02.11.2026 nicht mehr:
    # addContextItem hatte keinen Aufrufer, die Liste in cGuiElement blieb immer leer, und Funktion/Site/Datei/
    # Parameter dieses Elements las niemand (02.11.2026).
    def __init__(self):
        self.__sTitle = ''

    def setTitle(self, sTitle):
        self.__sTitle = sTitle

    def getTitle(self):
        return self.__sTitle
