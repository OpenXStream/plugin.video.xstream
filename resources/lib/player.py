# -*- coding: utf-8 -*-
# Python 3

import xbmc
from resources.lib.gui.gui import cGui
from resources.lib.config import cConfig
from resources.lib.logger import logger

class XstreamPlayer(xbmc.Player):
    def __init__(self, *args, **kwargs):
        xbmc.Player.__init__(self, *args, **kwargs)
        self.streamFinished = False
        self.streamSuccess = True
        self.playedTime = 0
        self.totalTime = 999999
        logger.debug('player instance created')

    def onPlayBackStarted(self):
        logger.debug('starting Playback')
        try:
            self.totalTime = self.getTotalTime()
        except:
            self.totalTime = 999999

    def onPlayBackStopped(self):
        logger.debug('Playback stopped')
        if self.playedTime == 0 and self.totalTime == 999999:
            self.streamSuccess = False
            logger.error('Kodi failed to open stream')
        self.streamFinished = True

    def onPlayBackEnded(self):
        logger.debug('Playback completed')
        if self.playedTime == 0 and self.totalTime == 999999:
            self.streamSuccess = False
        self.streamFinished = True

    def onPlayBackError(self):
        # Kann Kodi den Stream nicht oeffnen (Netzwerk, toter Link), meldet der
        # Player NUR onPlayBackError — kein Stopped und kein Ended. Ohne diesen
        # Handler bleibt streamFinished False, die Warteschleife in startPlayer()
        # endet nie und der Auto-Modus wechselt nicht zum naechsten Hoster.
        # Belegt am Kodi-Quelltext (VideoPlayer::OnExit, Kodi 21/22): bei
        # m_error wird genau dieser Callback aufgerufen.
        logger.error('Kodi failed to open stream (onPlayBackError)')
        self.streamSuccess = False
        self.streamFinished = True



class cPlayer:
    def clearPlayList(self):
        oPlaylist = self.__getPlayList()
        oPlaylist.clear()

    def __getPlayList(self):
        return xbmc.PlayList(xbmc.PLAYLIST_VIDEO)

    def addItemToPlaylist(self, oGuiElement):
        oListItem = cGui().createListItem(oGuiElement)
        self.__addItemToPlaylist(oGuiElement, oListItem)

    def __addItemToPlaylist(self, oGuiElement, oListItem):
        oPlaylist = self.__getPlayList()
        oPlaylist.add(oGuiElement.getMediaUrl(), oListItem)

    def startPlayer(self):
        logger.debug('start player')
        xbmcPlayer = XstreamPlayer()
        monitor = xbmc.Monitor()
        while (not monitor.abortRequested()) and (not xbmcPlayer.streamFinished):
            if xbmcPlayer.isPlayingVideo():
                try:
                    xbmcPlayer.playedTime = xbmcPlayer.getTime()
                except RuntimeError:
                    pass  # Wiedergabe endete zwischen isPlayingVideo() und getTime()
            # Kurzes Intervall: ein Fehlstart (onPlayBackError) wird schnell
            # erkannt, damit der Auto-Modus ohne lange Wartezeit zum naechsten
            # Hoster wechselt. Bei laufender Wiedergabe kostet das nichts.
            monitor.waitForAbort(1)
        return xbmcPlayer.streamSuccess