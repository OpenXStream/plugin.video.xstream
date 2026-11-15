
# -*- coding: utf-8 -*-
# Python 3

import os
import sys
import concurrent.futures
import xbmc
import xbmcgui
import xbmcplugin

from resources.lib import utils
from resources.lib.config import cConfig
from resources.lib.logger import logger
from resources.lib.gui.contextElement import cContextElement
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.handler.parameterHandler import ParameterHandler
from urllib.parse import quote_plus, urlencode


def _positiv(wert):
    """Staffel bzw. Folge der Site als Zahl ueber 0? Eine Nicht-Zahl (Doppelfolge '1-2', 'X1') zaehlt als keine —
    bis zum 02.11.2026 warf int()/float() darauf, und die ganze Liste brach mit einem Skriptfehler ab."""
    try:
        return float(wert) > 0
    except (TypeError, ValueError):
        return False


class cGui:

    # Unterdrueckt die "Keine Eintraege"-Meldung waehrend einer globalen Suche.
    # Klassenattribut, damit es fuer ALLE cGui-Instanzen gilt — die Worker-Threads
    # der globalen Suche legen sich jeweils eigene an.
    _globalSearch = False
    # Merker fuer den Notabschluss im Dispatch (siehe xstream.parseUrl).
    # _infoShown: es wurde eine "kein Inhalt"-Meldung ausgegeben.
    # _endSet:    das Verzeichnis wurde ordentlich abgeschlossen.
    # Beides Klassenattribute, weil eine Site-Funktion sich eine eigene
    # cGui-Instanz baut und der Dispatch sie nicht in der Hand hat.
    _infoShown = False
    _endSet = False
    # Merker "Inhaltsart gesetzt" (setView), aus demselben Grund ein Klassenattribut: die Site-Funktionen
    # setzen die Ansicht oft auf einer eigenen Instanz (cGui().setView('episodes')) und schliessen auf einer
    # anderen ab (cGui().setEndOfDirectory()). Als Instanz-Merker sah der Abschluss davon nichts und setzte
    # 'files' darueber — Kodi behaelt den letzten setContent-Aufruf, die Staffel- und Folgenlisten von neun Sites
    # kamen so bis zum 03.11.2026 als 'files' an — der Skin behandelte sie wie Dateien, nicht wie Staffeln bzw. Folgen.
    _viewSet = False
    # Eintraege, die auf den parallelen TMDB-Vorlauf warten (nur mit "TMDB Infos laden").
    # Klassenattribut wie _globalSearch: ein Kodi-Aufruf baut EIN Verzeichnis, und die
    # Site-Funktionen bauen sich unterwegs eigene cGui-Instanzen — abgeschlossen wird
    # ueber irgendeine davon (setEndOfDirectory), dort werden alle wartenden Eintraege
    # ausgegeben. Je Eintrag: (Instanz, GuiElement, Parameter-Kopie, bIsFolder, iTotal, isHoster)
    _pending = []
    # Obergrenze des TMDB-Vorlaufs je Liste: braucht eine Liste so viele Abfragen oder mehr,
    # bekommt sie als GANZE keine TMDB-Daten — A-Z- und Genre-Listen mit hunderten Eintraegen
    # (25.10.2026: burningseries T 1.179, netzkino Dramakino 240) kosten sonst je Eintrag einen TMDB-Abruf.
    # Gezaehlt wird im Vorlauf, nicht ueber die Listengroesse der Site (siehe __flushPending).
    # Die Sammelsuchen (globale Suche, Weitere Quellen) laufen ohne diese Grenze.
    META_LIMIT = 100
    # This class "abstracts" a list of xbmc listitems.
    def __init__(self):
        try:
            self.pluginHandle = int(sys.argv[1])
        except:
            self.pluginHandle = 0
        try:
            self.pluginPath = sys.argv[0]
        except:
            self.pluginPath = ''
        self.isMetaOn = cConfig().getSetting('TMDBMETA') == 'true'
        # for globalSearch or alterSearch
        self.globalSearch = False
        self._collectMode = False
        self.searchResults = []

    def addFolder(self, oGuiElement, params='', bIsFolder=True, iTotal=0, isHoster=False):
        # add GuiElement to Gui, adds listitem to a list
        # abort xbmc list creation if user requests abort
        if xbmc.Monitor().abortRequested():
            self.setEndOfDirectory(False)
            raise RuntimeError('UserAborted')
        # store result in list if we searched global for other sources
        if self._collectMode:
            import copy
            self.searchResults.append({'guiElement': oGuiElement, 'params': copy.deepcopy(params), 'isFolder': bIsFolder})
            return
        if self.isMetaOn:
            # Mit "TMDB Infos laden" wartet JEDER Eintrag bis setEndOfDirectory: dort holt
            # preloadMeta die TMDB-Daten aller Eintraege parallel, danach kommen sie in der
            # Reihenfolge des Aufrufs ins Verzeichnis. Bis zum 25.10.2026 fragte addFolder je
            # Eintrag einzeln nacheinander (DoH plus TMDB-Suche je Eintrag; megakino 20 Filme
            # 7,1 statt 2,8 s — parallel 1,0 statt 4,6 s fuer die 20 Abfragen). Kodi zeigt die
            # Liste ohnehin erst nach endOfDirectory. Die Parameter werden KOPIERT: viele Sites
            # fuellen einen ParameterHandler je Eintrag neu, beim spaeten Ausgeben truege sonst
            # jeder Eintrag die Werte des letzten.
            aParams = ParameterHandler.from_dict(params.to_dict()) if params != '' else ''
            cGui._pending.append((self, oGuiElement, aParams, bIsFolder, iTotal, isHoster))
            return
        self.__addItem(oGuiElement, params, bIsFolder, iTotal, isHoster)

    @staticmethod
    def preloadMeta(aJobs, iLimit=0):
        """TMDB-Daten mehrerer Eintraege parallel holen: aJobs = [(oGuiElement, tmdbID), ...].

        Je Eintrag ist getMeta eine TMDB-Abfrage (plus DoH-Abruf); nacheinander summiert sich
        das (gemessen rund 2,8 s fuer 20 Treffer, bei traegen Antworten mehr), parallel sind es
        rund 0,2 s. getMeta setzt selbst _isMetaSet, deshalb holt addFolder/__addItem danach
        nichts doppelt; ohne Medientyp oder mit gesetztem _isMetaSet wird nichts geholt.
        iLimit: braucht die Liste so viele Abfragen oder mehr, wird NICHTS geholt (0 = keine
        Grenze). Nutzer: setEndOfDirectory (Listen, mit META_LIMIT) und xstream._preloadMeta
        (globale Suche, Weitere Quellen, ohne Grenze).

        WICHTIG submit statt map: bei map fliegt die erste Exception beim Iterieren weiter und
        reisst den ganzen Vorlauf mit. Jedes Ergebnis wird deshalb einzeln abgefangen — ein
        gescheiterter Abruf darf die uebrigen Eintraege nicht mitreissen.
        """
        aNeeded = [(oElement, tmdbID) for oElement, tmdbID in aJobs
                   if getattr(oElement, '_mediaType', '') and not getattr(oElement, '_isMetaSet', False)]
        if not aNeeded:
            return
        if iLimit and len(aNeeded) >= iLimit:
            logger.info('TMDB-Vorlauf ausgelassen: %d Eintraege, Grenze %d' % (len(aNeeded), iLimit))
            return
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(aNeeded))) as executor:
                aFutures = [executor.submit(oElement.getMeta, oElement._mediaType, tmdbID or '')
                            for oElement, tmdbID in aNeeded]
                for oFuture in aFutures:
                    try:
                        oFuture.result()
                    except Exception:
                        pass
        except Exception as e:
            logger.error('Meta-Vorlauf fehlgeschlagen: %s' % e)

    def __flushPending(self, success):
        """Wartende Eintraege ausgeben (Vorlauf parallel, dann in Aufrufreihenfolge). Bei einem
        gescheiterten Verzeichnis (success False) verfallen sie — Kodi verwirft die Liste."""
        aPending, cGui._pending = cGui._pending, []
        if not aPending or not success:
            return
        # Die Grenze META_LIMIT zaehlt der Vorlauf selbst ueber die Eintraege, die eine Abfrage
        # brauchen — nicht ueber die Listengroesse, die die Site an addFolder gibt (iTotal): die
        # Suche von aniworld und burningseries meldet dort ihren ganzen Katalog (2.506 bzw.
        # 10.709, auch bei 3 Treffern), netzkino zaehlt vor dem Aussieben. Mit "iTotal < 100"
        # blieben diese Treffer ohne TMDB-Daten (gemessen 25.10.2026).
        cGui.preloadMeta([(oElement, aParams.getValue('tmdbID') if aParams != '' else '')
                          for oGui, oElement, aParams, bIsFolder, iTotal, isHoster in aPending], cGui.META_LIMIT)
        for oGui, oElement, aParams, bIsFolder, iTotal, isHoster in aPending:
            oGui.__addItem(oElement, aParams, bIsFolder, iTotal, isHoster)

    def __addItem(self, oGuiElement, params, bIsFolder, iTotal, isHoster):
        sUrl = self.__createItemUrl(oGuiElement, bIsFolder, params)
#kasi
        try:
            if params.exist('trumb'): oGuiElement.setIcon(params.getValue('trumb'))
        except:
            pass

        listitem = self.createListItem(oGuiElement)
        if not bIsFolder and cConfig().getSetting('hosterSelect') == 'List':
            bIsFolder = True
        if isHoster:
            bIsFolder = False
        listitem = self.__createContextMenu(oGuiElement, listitem, bIsFolder, sUrl)
        if not bIsFolder:
            listitem.setProperty('IsPlayable', 'true')
        xbmcplugin.addDirectoryItem(self.pluginHandle, sUrl, listitem, bIsFolder, iTotal)

    def addNextPage(self, site, function, params='', sPageInfo=''):
        # sPageInfo haengt die Seitenlage an den Weiter-Eintrag ("… (3/12)").
        # Sie kommt NUR mit, wenn die Seite ihre letzte Seitenzahl selbst nennt —
        # geraten wird nichts, und ohne die Angabe sieht der Eintrag aus wie immer.
        sTitle = cConfig().getLocalizedString(30279)
        if sPageInfo:
            sTitle += ' %s' % sPageInfo
        guiElement = cGuiElement(sTitle, site, function)
        self.addFolder(guiElement, params)

    @staticmethod
    def pageInfo(iCurrent, iLast):
        # "(3/12)" fuer den Weiter-Eintrag; leer, wenn die Seitenzahl unbekannt
        # oder unplausibel ist. Der Schraegstrich ist wie die Klammern reines
        # Format und braucht keine Uebersetzung — deshalb kein Anzeigetext.
        try:
            iCurrent, iLast = int(iCurrent), int(iLast)
        except (TypeError, ValueError):
            return ''
        if iLast < 2 or iCurrent < 1 or iCurrent > iLast:
            return ''
        return '(%d/%d)' % (iCurrent, iLast)

    def createListItem(self, oGuiElement):
        itemValues = oGuiElement.getItemValues()
        itemTitle = oGuiElement.getTitle()
        infoString = ''
        if self.globalSearch:
            infoString += ' %s' % oGuiElement.getSiteName()
        if oGuiElement._sLanguage != '':
            infoString += ' (%s)' % oGuiElement._sLanguage
        if oGuiElement._sQuality != '':
            infoString += ' [%s]' % oGuiElement._sQuality
        if infoString:
            infoString = '[I]%s[/I]' % infoString
        itemValues['title'] = itemTitle + infoString
        if 'plot' not in itemValues or itemValues['plot'] == '':
            itemValues['plot'] = ' ' #kasi Alt 255
        listitem = xbmcgui.ListItem(itemTitle + infoString)
        self.setInfoTagVideo(oGuiElement, listitem)

        # Site-Logo als Default: nackte Menue-Eintraege (kein eigenes Thumbnail, Icon
        # noch DefaultFolder) bekommen das Logo der Site aus art/sites/<SITE_IDENTIFIER>.png
        # statt des weissen Default-Ordners. Greift bewusst NICHT bei Items mit echtem
        # Poster/Thumbnail oder bereits gesetztem Icon (z.B. ueber den trumb-Hook).
        sIcon = oGuiElement.getIcon()
        sThumb = oGuiElement.getThumbnail()
        sSite = oGuiElement.getSiteName()
        if sSite and not sThumb and sIcon == cGuiElement.DEFAULT_FOLDER_ICON:
            sSiteLogo = os.path.join(cConfig().getAddonInfo('path'), 'resources', 'art', 'sites', '%s.png' % sSite)
            if os.path.exists(sSiteLogo):
                sIcon = sSiteLogo
                sThumb = sSiteLogo
        listitem.setArt({'icon': sIcon, 'thumb': sThumb, 'poster': sThumb, 'fanart': oGuiElement.getFanart()})
        aProperties = oGuiElement.getItemProperties()
        if len(aProperties) > 0:
            for sPropertyKey in aProperties.keys():
                listitem.setProperty(sPropertyKey, aProperties[sPropertyKey])
        return listitem

    @staticmethod
    def _resolveVideoMediaType(oGuiElement, itemValues):
        """Korrekter Kodi-Medientyp fuer setMediaType.
        Die Basis uebergab getType() (sType, immer 'video' — einen Setter dazu rief
        nie jemand, er ist seit dem 02.11.2026 raus) und vertaggte damit Filme/Serien
        falsch; den Typ setzt nur setMediaType('movie'). Reihenfolge: echtes
        _mediaType, dann itemValues['mediaType']; sonst Rueckfall auf getType()
        (altes Verhalten), damit Nicht-Video-Eintraege wie Menue-/Ordnerpunkte
        unveraendert bleiben."""
        media_type = (getattr(oGuiElement, '_mediaType', '') or '').lower()
        if media_type in ('movie', 'tvshow', 'season', 'episode', 'musicvideo'):
            return media_type
        mv = itemValues.get('mediaType')
        if mv:
            return str(mv).lower()
        return oGuiElement.getType()

    def setInfoTagVideo(self, oGuiElement, listitem):
        itemValues = oGuiElement.getItemValues()
        vtag = listitem.getVideoInfoTag()
        
        vtag.setMediaType(self._resolveVideoMediaType(oGuiElement, itemValues))
        
        # Bewusst kein vtag.setTitle: der Titel steht bereits als Label des ListItems
        # (Originalbegruendung: der Infostring ginge beim erneuten Setzen verloren).
        if 'plot' in itemValues:
            try:
                vtag.setPlot(itemValues['plot'])
            except: pass
        if 'year' in itemValues:
            try:
                vtag.setYear(int(itemValues['year']))
            except: pass
        if 'season' in itemValues:
            try:
                vtag.setSeason(int(itemValues['season']))
            except: pass
        if 'episode' in itemValues:
            try:
                vtag.setEpisode(int(itemValues['episode']))
            except: pass
        if 'TVShowTitle' in itemValues:
            try:
                vtag.setTvShowTitle(itemValues['TVShowTitle'])
            except: pass
        if 'cast' in itemValues:
            try:
                vtag.setCast([xbmc.Actor(cast[0], cast[1], thumbnail=cast[2]) for cast in itemValues['cast']])
            except: pass
        if 'countries' in itemValues:
            try:
                vtag.setCountries(itemValues['countries'])
            except: pass
        if 'country' in itemValues:
            try:
                vtag.setCountries([itemValues['country']])
            except: pass
        if 'dateadded' in itemValues:
            try:
                vtag.setDateAdded(itemValues['dateadded'])
            except: pass
        if 'directors' in itemValues:
            try:
                vtag.setDirectors(itemValues['directors'])
            except: pass
        if 'duration' in itemValues:
            # minuten in sekunden umrechnen
            try:
                vtag.setDuration(int(itemValues['duration']) * 60)
            except: pass
        if 'rating' in itemValues:
            try:
                vtag.setRating(float(itemValues['rating']))
            except: pass
        if 'genre' in itemValues:
            try:
                sGenre = itemValues.get('genre') or itemValues.get('genres') or ''
                if sGenre:
                    vtag.setGenres(sGenre.split(' / '))
            except: pass
        if 'imdb_id' in itemValues:
            try:
                vtag.setUniqueID(str(itemValues['imdb_id']), 'imdb')
            except: pass
        if 'tmdb_id' in itemValues:
            try:
                vtag.setUniqueID(str(itemValues['tmdb_id']), 'tmdb')
            except: pass
        if 'originaltitle' in itemValues:
            try:
                vtag.setOriginalTitle(itemValues['originaltitle'])
            except: pass
        if 'trailer' in itemValues:
            try:
                vtag.setTrailer(itemValues['trailer'])
            except: pass
        if 'tagline' in itemValues:
            try:
                vtag.setTagLine(itemValues['tagline'])
            except: pass
        # Bewusst kein vtag.setStudios (Originalbegruendung: Kodi sucht sonst Bilder
        # der Studios und schreibt Fehler ins Logfile).
        if 'premiered' in itemValues:
            try:
                vtag.setPremiered(itemValues['premiered'])
            except: pass    


    def __createContextMenu(self, oGuiElement, listitem, bIsFolder, sUrl):
        contextmenus = []
        itemValues = oGuiElement.getItemValues()
        contextitem = cContextElement()
        # Sauberer Titel fuer Trailer, TMDB-Info und Weitere Quellen: ein Film — auch einer, den
        # eine Seite innerhalb einer Serie fuehrt — sucht mit seinem Filmtitel (Sites legen ihn
        # als 'originaltitle' ab, wenn das Label einen Vorsatz traegt, etwa "5 - Titel" bei
        # aniworld/serienstream/burningseries); Staffeln und Folgen suchen mit der Serie
        # (TVShowTitle); alles andere mit dem Titel des Eintrags. Mit "TMDB Infos laden" steht in
        # 'originaltitle' der Originaltitel von TMDB — den Titel der Seite sichert getMeta vorher
        # als 'siteTitle' (Grund dort), der geht vor.
        if oGuiElement._mediaType == 'movie':
            _cleanTitle = itemValues.get('siteTitle', '') or itemValues.get('originaltitle', '') or oGuiElement.getTitle()
        else:
            _cleanTitle = itemValues.get('TVShowTitle', '') or oGuiElement.getTitle()
        # 1. Trailer
        if oGuiElement._mediaType in ('movie', 'tvshow'):
            contextitem.setTitle(cConfig().getLocalizedString(30027))  # Trailer Funktion
            trailerParams = {
                'function': 'playTrailer',
                'title': _cleanTitle,
                'year': oGuiElement._sYear or str(itemValues.get('year', '')),
                'mediatype': oGuiElement._mediaType,
                'poster': oGuiElement.getThumbnail(),
            }
            if 'tmdb_id' in itemValues and itemValues['tmdb_id']:
                trailerParams['tmdb_id'] = str(itemValues['tmdb_id'])
            trailerUrl = "%s?%s" % (self.pluginPath, urlencode(trailerParams))
            contextmenus += [(contextitem.getTitle(), "RunPlugin(%s)" % trailerUrl)]
            # Trailer-URL als ListItem-Property setzen damit Skins
            # den Trailer auch in Widgets anzeigen koennen
            listitem.setProperty('trailer', trailerUrl)
        # 2. TMDB Info
        if oGuiElement._mediaType == 'movie' or oGuiElement._mediaType == 'tvshow':
            contextitem.setTitle(cConfig().getLocalizedString(30239))   # TMDB Info
            searchParams = {'searchTitle': _cleanTitle, 'sMeta': oGuiElement._mediaType, 'sYear': oGuiElement._sYear}
            # Bekannte TMDB-ID mitgeben wie beim Trailer: das Fenster zeigt dann genau den Film des
            # Eintrags mit einem Aufruf statt einer Namenssuche plus Details. Bis zum 25.10.2026 las
            # es ListItem.Property(TmdbId), die niemand setzt (unsere Property heisst tmdb_id).
            if 'tmdb_id' in itemValues and itemValues['tmdb_id']:
                searchParams['tmdb_id'] = str(itemValues['tmdb_id'])
            contextmenus += [(contextitem.getTitle(), "RunPlugin(%s?function=viewInfo&%s)" % (self.pluginPath, urlencode(searchParams),),)]
        # 3. Hoster wählen
        if not bIsFolder and cConfig().getSetting('hosterSelect') == 'Auto':
            contextitem.setTitle(cConfig().getLocalizedString(30149))   # select Hoster
            contextmenus += [(contextitem.getTitle(), "RunPlugin(%s&playMode=play&manual=1)" % (sUrl,),)]
        # 4. Weitere Quellen — nur fuer echte Titel: Film und Serie, Staffel und Folge mit Seriennamen.
        # Bis 29.09.2026 hing der Punkt an JEDEM Eintrag und suchte dann dessen Label: Menue-Eintraege
        # („Neues", „Suche"), Hoster („VOE (DE) [720p]") und animetoasts Hoster-Tabs („Voe") auf allen
        # 14 geprueften Seiten; echte Titel tragen dort ueberall movie, tvshow, season oder episode.
        if oGuiElement._mediaType in ('movie', 'tvshow') or (oGuiElement._mediaType in ('season', 'episode') and itemValues.get('TVShowTitle')):
            contextitem.setTitle(cConfig().getLocalizedString(30243))   # Weitere Quellen
            searchParams = {'searchTitle': _cleanTitle}
            if 'imdb_id' in itemValues:
                searchParams['searchImdbID'] = itemValues['imdb_id']
            contextmenus += [(contextitem.getTitle(), "Container.Update(%s?function=searchAlter&%s)" % (self.pluginPath, urlencode(searchParams),),)]
        # 5. Rest
        if oGuiElement._mediaType == 'season' or oGuiElement._mediaType == 'episode':
            contextitem.setTitle(cConfig().getLocalizedString(30241))   # Info
            contextmenus += [(contextitem.getTitle(), cConfig().getLocalizedString(30242),)]    # Action(Info)
        # „Zur Abspielliste hinzufuegen" ist seit dem 01.11.2026 raus (so entschieden): der Eintrag legte den Stream-Link
        # schon beim Hinzufuegen fest, und beim Abspielen aus der Liste liefen weder Ausweich-Hoster noch die
        # Player-Ueberwachung mit (hoster.play, cPlayer.startPlayer).
        listitem.addContextMenuItems(contextmenus)
        return listitem

    def setEndOfDirectory(self, success=True, pUpdateListing=False, pCacheToDisc=True):
        self.__flushPending(success)
        # mark the listing as completed, this is mandatory
        cGui._endSet = True
        if not cGui._viewSet:
            self.setView('files')
        xbmcplugin.setPluginCategory(self.pluginHandle, "")
        # add some sort methods, these will be available in all views
        xbmcplugin.addSortMethod(self.pluginHandle, xbmcplugin.SORT_METHOD_UNSORTED)
        xbmcplugin.addSortMethod(self.pluginHandle, xbmcplugin.SORT_METHOD_VIDEO_RATING)
        xbmcplugin.addSortMethod(self.pluginHandle, xbmcplugin.SORT_METHOD_LABEL)
        xbmcplugin.addSortMethod(self.pluginHandle, xbmcplugin.SORT_METHOD_DATE)
        xbmcplugin.addSortMethod(self.pluginHandle, xbmcplugin.SORT_METHOD_PROGRAM_COUNT)
        xbmcplugin.addSortMethod(self.pluginHandle, xbmcplugin.SORT_METHOD_VIDEO_RUNTIME)
        xbmcplugin.addSortMethod(self.pluginHandle, xbmcplugin.SORT_METHOD_GENRE)
        xbmcplugin.endOfDirectory(self.pluginHandle, succeeded=success, updateListing=pUpdateListing, cacheToDisc=pCacheToDisc)

    def setView(self, content='movies'):
        # set the listing to a certain content, makes special views available
        # see https://docs.kodi.tv/d1/d32/group__python__xbmcplugin.html — setContent (read 14.10.2026)
        # (seasons is also supported but not listed)
        # Die Ansicht selbst waehlt der Skin bzw. der Nutzer im Seitenmenue; den Reiter "Ansichten"
        # (feste Ansichtsnummern je Inhalt) gibt es seit dem 01.11.2026 nicht mehr (so entschieden).
        content = content.lower()
        supportedViews = ['files', 'songs', 'artists', 'albums', 'movies', 'tvshows', 'seasons', 'episodes', 'musicvideos']
        if content in supportedViews:
            cGui._viewSet = True
            xbmcplugin.setContent(self.pluginHandle, content)

    def updateDirectory(self):
        xbmc.executebuiltin("Container.Refresh")

    def __createItemUrl(self, oGuiElement, bIsFolder, params=''):
        if params == '':
            params = ParameterHandler()
        # Ab hier auf einer KOPIE arbeiten: die folgenden Werte gehoeren nur zu diesem
        # einen Listeneintrag. Direkt ins Params-Objekt des Aufrufers geschrieben, erbt
        # sie jeder weitere Eintrag derselben Liste — ein Film setzt MovieTitle, thumb,
        # mediaType und year, die danach gelistete Serie bekommt sie mit (falsches Jahr,
        # fremdes Poster). getParameterAsUri() loescht ausserdem title/site/function und
        # veraenderte damit bisher ebenfalls das Objekt des Aufrufers.
        # Ein 'trumb' aus dem Klick (das Bild des Eintrags, der hierher fuehrte) kommt nicht
        # mit: die Adresse unten traegt 'trumb' ausdruecklich mit dem Bild DIESES Eintrags.
        # Mit beiden stand der Parameter doppelt in der Adresse, beim Lesen gewann der
        # letzte (parse_qsl) — und der Icon-Hook in addFolder/addDir gab jedem Kind das
        # Bild des Grosseltern-Eintrags statt das des Elternteils (22.10.2026:
        # kellerkino, streamcloud, serienstream in jeder Liste hinter einem Bild-Eintrag).
        params = ParameterHandler.from_dict({k: v for k, v in params.to_dict().items() if k != 'trumb'})
        itemValues = oGuiElement.getItemValues()
        if 'tmdb_id' in itemValues and itemValues['tmdb_id']:
            params.setParam('tmdbID', itemValues['tmdb_id'])
        elif oGuiElement._mediaType in ('movie', 'tvshow'):
            # Filme und Serien tragen nur ihre EIGENE TMDB-ID. Eine geerbte gehoert zum Eintrag
            # davor: zur Serie bei deren Filmliste (AniWorld, BurningSeries und SerienStream fuehren
            # sie als Staffel 0) und zum TMDB-Browser-Eintrag bei Weitere Quellen, dessen Treffer
            # auch Fortsetzungen und Namensvettern sind (der Filter dort prueft nur, ob der Titel
            # enthalten ist). Mit der ID der Serie oder eines anderen Films stuende an der
            # Wiedergabe (hoster._setVideoInfo) eine falsche TMDB-ID. Staffeln, Folgen und Hoster erben
            # weiter, die ID ihrer Serie. getParameterAsUri laesst den leeren Wert weg.
            params.setParam('tmdbID', '')
        if 'TVShowTitle' in itemValues and itemValues['TVShowTitle']:
            params.setParam('TVShowTitle', itemValues['TVShowTitle'])
        if 'season' in itemValues and _positiv(itemValues['season']):
            params.setParam('season', itemValues['season'])
        if 'episode' in itemValues and _positiv(itemValues['episode']):
            params.setParam('episode', itemValues['episode'])
        if not bIsFolder:
            params.setParam('MovieTitle', oGuiElement.getTitle())
            thumbnail = oGuiElement.getThumbnail()
            if thumbnail:
                params.setParam('thumb', thumbnail)
            if oGuiElement._mediaType:
                params.setParam('mediaType', oGuiElement._mediaType)
            elif 'TVShowTitle' in itemValues and itemValues['TVShowTitle']:
                params.setParam('mediaType', 'tvshow')
            if 'season' in itemValues and _positiv(itemValues['season']):
                params.setParam('mediaType', 'season')
            # Jede Folge mit einer Nummer ist eine Folge — auch eine Doppelfolge ('1-2') oder 'X1', deren Nummer oben
            # nicht als Zahl mitgeht; bis zum 02.11.2026 blieb so ein Eintrag beim Typ seiner Staffel ('season') und
            # die Wiedergabe trug den falschen Medientyp (02.11.2026)
            if 'episode' in itemValues and str(itemValues['episode']).strip():
                params.setParam('mediaType', 'episode')
            # Pass imdb_id and year for Trakt.TV scrobbling
            if 'imdb_id' in itemValues and itemValues['imdb_id']:
                params.setParam('imdb_id', itemValues['imdb_id'])
            if 'year' in itemValues and itemValues['year']:
                params.setParam('year', itemValues['year'])
        sParams = params.getParameterAsUri()
        try:
            if params.getValue('sUrl').startswith("plugin://"):
                return  params.getValue('sUrl')
        except: pass
        if len(oGuiElement.getFunction()) == 0:
            sUrl = "%s?site=%s&title=%s&%s" % (self.pluginPath, oGuiElement.getSiteName(), quote_plus(oGuiElement.getTitle()), sParams)
        else:
            #kasi
            # Die Bild-Adresse MUSS kodiert werden, genau wie der Titel daneben:
            # enthaelt sie ein ? oder & (etwa ?format=webp), zerreisst sie sonst
            # die Parameterliste dieser Adresse — im Log steht derselbe Parameter
            # dann doppelt und der Eintrag laesst sich nicht abspielen. Der
            # ParameterHandler dekodiert beim Lesen automatisch ueber parse_qsl.
            sUrl = "%s?site=%s&function=%s&title=%s&trumb=%s&%s" % (self.pluginPath, oGuiElement.getSiteName(), oGuiElement.getFunction(), quote_plus(oGuiElement.getTitle()), quote_plus(str(oGuiElement.getThumbnail() or '')), sParams)
            if not bIsFolder:
                sUrl += '&playMode=play'
        return sUrl

    @staticmethod
    def showKeyBoard(sDefaultText="", sHeading=""):
        oKeyboard = xbmc.Keyboard(sDefaultText, sHeading)
        oKeyboard.doModal()
        if oKeyboard.isConfirmed():
            # Randstaendige Leerzeichen abschneiden: sie gehen sonst sowohl in die
            # Suchadresse der Seite als auch in den Titelfilter ein und kosten
            # Treffer, ohne dass der Nutzer den Grund sieht. Gemessen mit
            # " star wars " gegen "star wars": kinoger 0 statt 12, moflix 0 statt 6,
            # megakino 2 statt 14, global 166 statt 234. Der Fix sitzt bewusst
            # HIER und nicht in den Site-Files — die Tastatur ist die eine Stelle,
            # durch die jeder Sucheinstieg laeuft. Besteht die
            # Eingabe nur aus Leerzeichen, bleibt es beim bisherigen False.
            sSearchText = oKeyboard.getText().strip()
            if len(sSearchText) > 0:
                return sSearchText
        return False

    @staticmethod
    def showNumpad(defaultNum="", numPadTitle=cConfig().getLocalizedString(30251)):
        defaultNum = str(defaultNum)
        dialog = xbmcgui.Dialog()
        num = dialog.numeric(0, numPadTitle, defaultNum)
        return num

    @staticmethod
    def openSettings():
        cConfig().showSettingsWindow()

    @staticmethod
    def showError(sTitle, sDescription, iSeconds=0):
        # Die allgemeinen Hoster-Meldungen „Kein Hosterlink uebergeben" (30134) und „Stream nicht verfuegbar //
        # Link defekt" (30135) entfallen wie die Leer-Meldungen in showInfo, wenn der requestHandler in diesem
        # Klick schon einen Abruffehler gemeldet hat (Einblendung bei Cloudflare, DDoS-Guard, Timeout): die Site
        # fand den Link nicht, WEIL ihr Abruf scheiterte — sonst zwei Hinweise fuer einen Klick (filmo 26.10.2026).
        # Im Hosterlink-Schritt zeigt der requestHandler kein Fenster (hoster.py, quietWindows), dann kommt sie.
        if sDescription in (cConfig().getLocalizedString(30134), cConfig().getLocalizedString(30135)):
            rh = sys.modules.get('resources.lib.handler.requestHandler')
            if rh is not None and rh.errorShown():
                logger.info('Hoster-Meldung entfaellt: der Abruffehler wurde schon gemeldet')
                return
        if iSeconds == 0:
            iSeconds = 1000
        else:
            iSeconds = iSeconds * 1000
        xbmc.executebuiltin("Notification(%s,%s,%s,%s)" % (str(sTitle), (str(sDescription)), iSeconds, cConfig().getAddonInfo('icon')))

    @staticmethod
    def showInfo(sTitle='xStream', sDescription=cConfig().getLocalizedString(30253), iSeconds=0):
        # Waehrend einer globalen Suche wird nichts gemeldet: dort laufen bis zu zehn
        # Seiten parallel, und jede ohne Treffer wuerde eine eigene Benachrichtigung
        # ausloesen — obwohl direkt danach die Trefferliste der uebrigen erscheint.
        # Der Schutz sitzt bewusst HIER und nicht bei den Aufrufern: es gibt ueber
        # hundert showInfo-Aufrufe in den Site-Files. (Fund von Sascha/KUS)
        if cGui._globalSearch:
            return
        cGui._infoShown = True
        # Hat der requestHandler in diesem Klick schon einen Abruffehler gemeldet (Einblendung bei
        # Cloudflare/DDoS-Guard/Timeout, Fenster bei 4xx/5xx), entfallen die beiden Leer-Meldungen
        # „Kein Eintrag gefunden" (30253) und „Stream // Hoster nicht verfuegbar" (30141) — sonst zwei
        # Hinweise fuer einen Klick, wie beim Sprach-Hinweis bis zum 10.09.2026. Eigene Texte kommen
        # immer; _infoShown bleibt gesetzt, der Notabschluss im Dispatch gilt weiter. Ein stiller Abruf
        # (ignoreErrors, Folgeseiten der Suche) setzt den Merker nicht, dort bleibt die Leer-Meldung.
        if sDescription in (cConfig().getLocalizedString(30253), cConfig().getLocalizedString(30141)):
            rh = sys.modules.get('resources.lib.handler.requestHandler')
            if rh is not None and rh.errorShown():
                logger.info('Leer-Meldung entfaellt: der Abruffehler wurde schon gemeldet')
                return
        if iSeconds == 0:
            iSeconds = 1000
        else:
            iSeconds = iSeconds * 1000
        xbmc.executebuiltin("Notification(%s,%s,%s,%s)" % (str(sTitle), (str(sDescription)), iSeconds, cConfig().getAddonInfo('icon')))

    @staticmethod
    def showLanguage():
        # Der Hinweis fordert dazu auf, die Sprachauswahl zu aendern — das ergibt nur
        # Sinn, wenn ueberhaupt eine Sprache eingeschraenkt ist. Steht die Einstellung
        # auf "Alle" (Werksdefault 0; ungesetzt liefert getSetting einen Leerstring),
        # liegt es NICHT an der Sprache: der Titel hat schlicht keine Hoster. Dann wird
        # hier NICHTS gemeldet: alle Aufrufer mit "Alle" sind Hoster-Funktionen, und
        # hoster.py meldet die leere Liste selbst (30141) — bis zum 10.09.2026 kam
        # hier zusaetzlich "Kein Eintrag gefunden", also zwei Einblendungen fuer einen
        # Klick. Listenfunktionen rufen showLanguage nur mit gesetzter Sprache.
        # Geprueft wird auf die drei echten Sprachwerte statt auf "0", weil beide
        # Schreibweisen fuer "Alle" vorkommen.
        if cConfig().getSetting('prefLanguage') not in ('1', '2', '3'):
            return
        xbmcgui.Dialog().ok('xStream', cConfig().getLocalizedString(30823))
