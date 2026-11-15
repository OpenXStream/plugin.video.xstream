# -*- coding: utf-8 -*-
# Python 3

from resources.lib.tools import cParser, cUtil
from resources.lib.config import cConfig
from resources.lib.logger import logger
from os import path

class cGuiElement:
    '''
    This class "abstracts" a xbmc listitem.
    Kwargs:
        sTitle    (str): title/label oft the GuiElement/listitem
        sSite     (str): siteidentifier of the siteplugin, which is called if the GuiElement is selected
        sFunction (str): name of the function, which is called if the GuiElement is selected
        These arguments are mandatory. If not given on init, they have to be set by their setter-methods, before the GuiElement is added to the Gui.
    '''
    DEFAULT_FOLDER_ICON = 'DefaultFolder.png'
    # Die Datei liegt seit der Umstellung auf den assets-Block unter resources/ —
    # der frueher hier stehende Pfad <addon>/fanart.jpg zeigte ins Leere, der Default
    # griff also nie und Kodi nahm das Fanart des Skins. getAddonInfo('fanart') liefert
    # genau den Pfad, den die addon.xml angibt.
    DEFAULT_FANART = cConfig().getAddonInfo('fanart') or path.join(cConfig().getAddonInfo('path'), 'resources', 'fanart.jpg')
    MEDIA_TYPES = ['movie', 'tvshow', 'season', 'episode']

    def __init__(self, sTitle: object = '', sSite: object = None, sFunction: object = None) -> None:
        # Die Felder sMediaUrl, sTitleSecond, sSubLanguage und sInfo sind seit dem 02.11.2026 raus: ihre Setter gingen
        # mit dem Totcode-Ausbau, kein Site-File und kein Core-Code setzte sie; from_dict liest aelter
        # zwischengespeicherte Suchergebnisse weiter ueber get() mit Vorgabe.
        self.__sType = 'video'
        self.__sTitle = cUtil.cleanse_text(sTitle)
        self.__sDescription = ''
        self.__sThumbnail = ''
        self.__sIcon = self.DEFAULT_FOLDER_ICON
        self.__aItemValues = {}
        self.__aProperties = {}
        self.__sFanart = self.DEFAULT_FANART
        self.__sSiteName = sSite
        self.__sFunctionName = sFunction
        self._sLanguage = ''
        self._sYear = ''
        self._sQuality = ''
        self._mediaType = ''
        self._season = ''
        self._episode = ''
        self._tmdbID = ''
        self._rating = ''
        self._isMetaSet = False

    def getType(self):
        # immer 'video' (der Setter dazu hatte nie einen Aufrufer und ist seit dem 02.11.2026 raus); gui.py nimmt den
        # Wert nur als Rueckfall fuer setMediaType, wenn weder _mediaType noch itemValues['mediaType'] etwas sagen
        return self.__sType

    def setSiteName(self, sSiteName):
        self.__sSiteName = sSiteName

    def getSiteName(self):
        return self.__sSiteName

    def setFunction(self, sFunctionName):
        self.__sFunctionName = sFunctionName

    def getFunction(self):
        return self.__sFunctionName

    def setTitle(self, sTitle):
        self.__sTitle = cUtil.cleanse_text(sTitle)

    def getTitle(self):
        # Vorab nur auf eine Klammer pruefen, das Muster darunter verlangt die vier
        # Ziffern. Der fruehere Vorab-Check auf " (19" / " (20" liess Jahre vor 1900 und
        # Titel ohne Leerzeichen vor der Klammer durch: die Jahreszahl wurde dann nicht
        # herausgeloest, unten aber bei jedem Aufruf erneut angehaengt — "Annie Oakley
        # (1894) (1894) (1894)" bei Internet Archive, "Police Squad!(1982) (1982)".
        if '(' in self.__sTitle:
            # Der Teil HINTER der Jahreszahl bleibt erhalten. Frueher nahm das Muster nur
            # den Text vor der Klammer, alles danach ging verloren: aus "Ranma 1/2 (2024)
            # 2nd Season Ger Dub" wurde "Ranma 1/2 (2024)" — dadurch hiessen Staffel 1 und
            # 2 im Menue identisch, und Fassungskennungen wie "Ger Sub" verschwanden
            # (30 Titel allein im animetoast-Index). Das Jahr haengt die Funktion unten
            # ohnehin wieder an, deshalb wird es hier nur herausgeloest.
            isMatch, aYear = cParser.parse(self.__sTitle, r'(.*?)\((\d{4})\)(.*)')
            if isMatch:
                self.__sTitle = (aYear[0][0].strip() + ' ' + aYear[0][2].strip()).strip()
                # Das Jahr aus dem Titel zaehlt nur, solange keines gesetzt ist: unten haengt die Funktion
                # _sYear wieder an, und bis zum 02.11.2026 las jeder weitere Aufruf genau dieses Jahr erneut
                # heraus und setzte es per setYear zurueck — ein Jahr von TMDB (getMeta, "TMDB Infos laden")
                # stand so nur bis zum naechsten getTitle in den Werten (02.11.2026).
                if not self._sYear:
                    self.setYear(aYear[0][1])
        if '*19' in self.__sTitle or '*20' in self.__sTitle:
            isMatch, aYear = cParser.parse(self.__sTitle, r'(.*?)\*(\d{4})\*')
            if isMatch:
                self.__sTitle = aYear[0][0]
                if not self._sYear:
                    self.setYear(aYear[0][1])
        if '*english*' in self.__sTitle.lower():
            isMatch, aLang = cParser.parse(self.__sTitle, r'(.*?)\*(.*?)\*')
            if isMatch:
                self.__sTitle = aLang[0][0]
                self.setLanguage('EN')
        if '*deutsch*' in self.__sTitle.lower():
            isMatch, aLang = cParser.parse(self.__sTitle, r'(.*?)\*(.*?)\*')
            if isMatch:
                self.__sTitle = aLang[0][0]
                self.setLanguage('DE')
        if 'English:' in self.__sTitle:
            self.__sTitle = self.__sTitle.replace('English:', '')
            self.setLanguage('EN')
        if 'Deutsch:' in self.__sTitle:
            self.__sTitle = self.__sTitle.replace('Deutsch:', '')
            self.setLanguage('DE')
        if '(omu)' in self.__sTitle.lower() or '*OmU*' in self.__sTitle:
            self.__sTitle = self.__sTitle.replace('(OmU) ', '')
            self.__sTitle = self.__sTitle.replace('(Omu) ', '')
            self.setLanguage('OmU')

        if self._sYear: self.__sTitle = self.__sTitle.strip() + ' (' + self._sYear + ')'
        return self.__sTitle.strip()

    def setMediaType(self, mediaType):
        '''
        Set mediatype for GuiElement
        Args:
            mediaType(str): 'movie'/'tvshow'/'season'/'episode'
        '''
        mediaType = mediaType.lower()
        if mediaType in self.MEDIA_TYPES:
            self._mediaType = mediaType
        else:
            logger.error('Unknown MediaType given for %s' % self.getTitle())

    def setSeason(self, season):
        self._season = season
        self.__aItemValues['season'] = str(season)

    def setEpisode(self, episode):
        self._episode = episode
        self.__aItemValues['episode'] = str(episode)

    def setTVShowTitle(self, tvShowTitle):
        self.__aItemValues['TVShowTitle'] = str(tvShowTitle)

    def setYear(self, year):
        try:
            year = int(year)
        except:
            logger.error('Year given for %s seems not to be a valid number' % self.getTitle())
            return False
        if len(str(year)) != 4:
            logger.error('Year given for %s has %s digits, required 4 digits' % (self.getTitle(), len(str(year))))
            return False
        if year > 0:
            self._sYear = str(year)
            self.__aItemValues['year'] = year
            return True
        else:
            logger.error('Year given for %s must be greater than 0' % self.getTitle())
            return False

    def setQuality(self, quality):
        try:
            if '2160' in quality:
                self._sQuality = '4K 2160p'
            elif '1440' in quality:
                self._sQuality = '2K 1440p'
            elif '1080' in quality:
                self._sQuality = 'HD 1080p'
            elif '720' in quality:
                self._sQuality = 'HD 720p'
            elif '480' in quality:
                self._sQuality = 'SD 480p'
            elif '360' in quality:
                self._sQuality = 'SD 360p'
            elif 'HD' in quality:
                self._sQuality = 'HD'
            elif 'BDRip' in quality:
                self._sQuality = 'BD Rip'
            elif 'WEBRip' in quality:
                self._sQuality = 'WEB Rip'
            elif 'TS.MD' in quality:
                self._sQuality = 'TS Mic'
            elif 'MD.TS' in quality:
                self._sQuality = 'TS Mic'
            elif 'TS.LD' in quality:
                self._sQuality = 'TS Line'
            elif 'LD.TS' in quality:
                self._sQuality = 'TS Line'
            elif 'TS' in quality:
                self._sQuality = 'TS'
        except:
            pass

    def setDescription(self, sDescription):
        sDescription = cUtil.cleanse_text(sDescription)
        self.__sDescription = sDescription
        self.__aItemValues['plot'] = sDescription

    def getDescription(self):
        if 'plot' not in self.__aItemValues:
            return self.__sDescription
        else:
            return self.__aItemValues['plot']

    def setThumbnail(self, sThumbnail):
        self.__sThumbnail = sThumbnail
        try:
            if sThumbnail.startswith('http'):
                self.__sFanart = sThumbnail
        except:
            pass
    def getThumbnail(self):
        return self.__sThumbnail

    def setIcon(self, sIcon):
        self.__sIcon = sIcon

    def getIcon(self):
        return self.__sIcon

    def setFanart(self, sFanart):
        self.__sFanart = sFanart

    def getFanart(self):
        return self.__sFanart

    def addItemValue(self, sItemKey, sItemValue):
        self.__aItemValues[sItemKey] = sItemValue

    def setItemValues(self, aValueList):
        self.__aItemValues = aValueList

    def getItemValues(self):
        self.__aItemValues['title'] = self.getTitle()
        if self.getDescription():
            self.__aItemValues['plot'] = self.getDescription()
        for sPropertyKey in self.__aProperties.keys():
            self.__aItemValues[sPropertyKey] = self.__aProperties[sPropertyKey]
        return self.__aItemValues

    def getItemProperties(self):
        for sItemValueKey in self.__aItemValues.keys():
            if not self.__aItemValues[sItemValueKey] == '':
                try:
                    self.__aProperties[sItemValueKey] = str(self.__aItemValues[sItemValueKey])
                except:
                    pass
        return self.__aProperties

    def setLanguage(self, sLang):
        self._sLanguage = str(sLang)

    def to_dict(self):
        """Serialize this GuiElement to a plain dict for caching."""
        return {
            'sType': self.__sType,
            'sTitle': self.__sTitle,
            'sDescription': self.__sDescription,
            'sThumbnail': self.__sThumbnail,
            'sIcon': self.__sIcon,
            'aItemValues': self.__aItemValues,
            'aProperties': self.__aProperties,
            'sFanart': self.__sFanart,
            'sSiteName': self.__sSiteName,
            'sFunctionName': self.__sFunctionName,
            'sLanguage': self._sLanguage,
            'sYear': self._sYear,
            'sQuality': self._sQuality,
            'mediaType': self._mediaType,
            'season': self._season,
            'episode': self._episode,
            'tmdbID': self._tmdbID,
            'rating': self._rating,
            'isMetaSet': self._isMetaSet,
        }

    @classmethod
    def from_dict(cls, data):
        """Reconstruct a GuiElement from a cached dict."""
        obj = cls()
        obj.__sType = data.get('sType', 'video')
        obj.__sTitle = data.get('sTitle', '')
        obj.__sDescription = data.get('sDescription', '')
        obj.__sThumbnail = data.get('sThumbnail', '')
        obj.__sIcon = data.get('sIcon', cls.DEFAULT_FOLDER_ICON)
        obj.__aItemValues = data.get('aItemValues', {})
        obj.__aProperties = data.get('aProperties', {})
        obj.__sFanart = data.get('sFanart', cls.DEFAULT_FANART)
        obj.__sSiteName = data.get('sSiteName', None)
        obj.__sFunctionName = data.get('sFunctionName', None)
        obj._sLanguage = data.get('sLanguage', '')
        obj._sYear = data.get('sYear', '')
        obj._sQuality = data.get('sQuality', '')
        obj._mediaType = data.get('mediaType', '')
        obj._season = data.get('season', '')
        obj._episode = data.get('episode', '')
        obj._tmdbID = data.get('tmdbID', '')
        obj._rating = data.get('rating', '')
        obj._isMetaSet = data.get('isMetaSet', False)
        return obj

    def getMeta(self, mediaType, tmdbID='', TVShowTitle='', season='', episode=''):
        '''
        Fetch metainformations for GuiElement.
        Args:
            mediaType(str): 'movie'/'tvshow'/'season'/'episode'
        Kwargs:
            tmdbID (str)        :
            TVShowTitle (str)   :

        TMDB-Werte ERSETZEN die der Seite (Cover, Hintergrund, Beschreibung, Bewertung, Genre,
        Jahr ...); was TMDB nicht liefert, bleibt von der Seite (Serienname, Staffel, Folge,
        Seitenwerte). Bis zum 25.10.2026 gab es dazu die Einstellung "TMDB Infos ueberschreiben
        Seiteninfos" (so entschieden: raus) — ihr Ersetzen-Zweig tauschte die GANZE Werteliste aus, an
        Folgen fehlte danach der Serienname (kein "Weitere Quellen", Kodi ohne Serientitel).
        '''
        if cConfig().getSetting('TMDBMETA') == 'false':
            return False
        if not self._mediaType:
            self.setMediaType(mediaType)
        if not season and self._season:
            season = self._season
        if not episode and self._episode:
            episode = self._episode
        if not self._mediaType:
            logger.error('Could not get MetaInformations for %s, mediaType not defined' % self.getTitle())
            return False
        from resources.lib.tmdb.api import cTMDB
        oMetaget = cTMDB()
        if not oMetaget:
            return False

        # Gesucht wird mit dem sauberen Titel der Seite: Sites legen ihn als 'originaltitle' ab, wenn
        # das Label einen Vorsatz traegt (aniworld/serienstream/burningseries bei Filmen in einer
        # Serie, "5 - Titel"), sonst zaehlt das Label. Mit dem Label fand TMDB bei den One-Piece-
        # Filmen von aniworld 13 von 22, mit dem Seitentitel 21 (25.10.2026). Derselbe Titel wird
        # unten als 'siteTitle' gesichert.
        sSiteTitle = self.__aItemValues.get('originaltitle', '') or self.getTitle()
        # Ohne die zweite TMDB-Abfrage je Titel (advanced): die Einstellung "Erweiterte Metadaten"
        # ist seit dem 25.10.2026 ausgebaut (so entschieden) — Besetzung, Laufzeit und Trailer-Link holt das
        # Fenster "TMDB Info" ohnehin selbst, die Listen brauchten damit doppelt so lange.
        if self._mediaType == 'movie':
            if self._sYear:
                meta = oMetaget.get_meta(self._mediaType, sSiteTitle, year=self._sYear)
            else:
                meta = oMetaget.get_meta(self._mediaType, sSiteTitle)
        elif self._mediaType == 'tvshow':
            if self._sYear:
                meta = oMetaget.get_meta(self._mediaType, sSiteTitle, year=self._sYear)
            else:
                meta = oMetaget.get_meta(self._mediaType, sSiteTitle)
        elif self._mediaType == 'season':
            meta = {}
        elif self._mediaType == 'episode':
            meta = oMetaget.get_meta_episodes(self._mediaType, TVShowTitle, tmdbID, str(season), str(episode))
        else:
            return False

        if not meta:
            # Abgefragt und nichts gefunden: der Merker wird trotzdem gesetzt, sonst fragt der
            # Vorlauf der Liste diese Eintraege nach der Sammelsuche (globale Suche, Weitere
            # Quellen) ein zweites Mal (25.10.2026: globale Suche 99 statt 91 Abfragen).
            self._isMetaSet = True
            return False

        if self._mediaType == 'season':
            meta = meta[0]

        aValues = dict(self.__aItemValues)
        # Den Titel der Seite als 'siteTitle' sichern, bevor TMDBs Originaltitel das Feld
        # 'originaltitle' fuellt: "Weitere Quellen" ist eine Seitensuche, und deutsche Seiten
        # fuehren den Verleihtitel, nicht den Titel aus dem Herkunftsland (25.10.2026, megakino
        # Filme: bei 7 von 20 weicht der TMDB-Originaltitel ab, alle 7 ohne Treffer, der
        # Seitentitel traf auf 3 bis 8 anderen Seiten). gui.__createContextMenu liest es.
        aValues['siteTitle'] = sSiteTitle
        aValues.update(meta)
        self.setItemValues(aValues)
        if 'cover_url' in meta:
            self.setThumbnail(meta['cover_url'])
        if 'backdrop_url' in meta:
            self.setFanart(meta['backdrop_url'])
        if 'title' in meta and episode:
            # Folgen-Label in der Hausform "S04E01 - Titel" (cParser.episodeLabel, eine Form auf
            # allen Sites) mit dem Folgentitel von TMDB — vorher "1. Titel".
            self.setTitle(cParser.episodeLabel(season, episode, meta['title']))
        if 'tmdb_id' in meta:
            self._tmdbID = meta['tmdb_id']
        if meta.get('year') and self._sYear:
            # Hatte die Seite ein Jahr, ersetzt TMDB es auch im Label: getTitle haengt _sYear an, sonst stuende
            # im Label 1986 und in den Werten (Kodi-Info, Trailer-Suche) 1984 (seit dem 02.11.2026). Ohne Jahr
            # der Seite bleibt das Label ohne Jahr — die Werte tragen das von TMDB.
            self._sYear = str(meta['year'])
        self._isMetaSet = True
        return meta
