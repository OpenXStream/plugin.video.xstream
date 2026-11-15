# -*- coding: utf-8 -*-
# Python 3

import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qsl

import certifi
import xbmc
from resources.lib.gui.gui import cGui
from resources.lib.config import cConfig
from resources.lib.logger import logger

# Dateiendungen, bei denen die Adresse sicher kein HLS ist: dort entfaellt die
# Inhaltspruefung, der native Player spielt die Datei.
_NO_HLS_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.webm', '.mov', '.flv')
# Dateiendungen, unter denen Hoster ihre Playlists fuehren: dort ist es HLS, die
# Inhaltspruefung entfaellt. Grund: scheiterte die Pruefung an einer langsamen
# Antwort, ging die Playlist an den nativen Player, Kodis Demuxer las sie als
# Textvideo, das sofort endet — und das zaehlte als Start, der Auto-Modus blieb
# stehen (`master.txt`, 28.10.2026).
_HLS_EXTENSIONS = ('.txt',)


# Kodi-Optionen in der Pipe hinter der Adresse (CurlFile), keine Kopfzeilen: der Player
# nimmt sie fuer sich, der Vorabruf laesst sie weg; alles andere geht als Kopfzeile mit.
_PIPE_OPTIONS = ('verifypeer', 'seekable', 'connection-timeout', 'failonerror', 'redirect-limit', 'encoding',
                 'acceptencoding', 'noshout', 'accept-charset', 'sslcipherlist', 'postdata', 'active-remote',
                 'ipversion', 'auth')
_sslContexts = {}


def _sslContext():
    """TLS-Kontext des Vorabrufs, einmal je Prozess: Zertifikatspruefung mit den Zertifikaten aus
    certifi wie beim requestHandler — derselbe Speicher auf jeder Plattform, unabhaengig davon,
    was Kodi dem Python mitgibt."""
    oContext = _sslContexts.get('certifi')
    if oContext is None:
        oContext = ssl.create_default_context(cafile=certifi.where())
        _sslContexts['certifi'] = oContext
    return oContext


def _probe(url, headerString):
    """Ein Abruf der Adresse: mit den Headern der Pipe, nur der Anfang (1 KB), Frist = die
    Einstellung „Timeout fuer Anfragen" (bis zum 05.11.2026 feste 6 s nur fuer die
    Inhaltspruefung). Rueckgabe (antwortet, Anfang, Vermerk fuer die Logzeile).

    Antwortet heisst: Inhalt innerhalb der Frist, oder ein 4xx — den meldet der Server
    selbst, der Player scheitert daran schnell. Keine Antwort heisst Zeitablauf, keine
    Verbindung oder ein Serverfehler (5xx): der Player wuerde an derselben Adresse nur
    warten — Kodi 22 fragt sie vorab selbst ab, im Oberflaechen-Thread und ohne unsere
    Header, bis zu dreimal 20 s; danach wartet InputStream Adaptive bis zu einer halben
    Minute auf die Playlist, und ein Stopp in dieser Zeit hing Kodi ganz (gemessen 04. und
    05.11.2026 an einem Hoster mit Aussetzern, am Geraet und unter Kodi 22).
    Nur der Anfang wird gelesen — ueber den cRequestHandler kaeme die ganze Antwort, bei
    einem MP4 ohne Endung der ganze Film.
    """
    if not url.lower().startswith(('http://', 'https://')):
        return True, b'', 'nur bei http'
    headers = {k: v for k, v in parse_qsl(headerString) if k.lower() not in _PIPE_OPTIONS} if headerString else {}
    if not any(key.lower() == 'user-agent' for key in headers):
        # Ohne User-Agent in der Pipe ruft Kodi mit seinem eigenen ab (ISA ueber Kodis
        # Dateizugriff); der Abruf fragt mit demselben, damit der Server beide gleich
        # behandelt (gemessen 15.10.2026).
        headers['User-Agent'] = xbmc.getUserAgent()
    start = time.time()
    try:
        request = urllib.request.Request(url, headers=headers)
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_sslContext()))
        with opener.open(request, timeout=int(cConfig().getSetting('requestTimeout', 10))) as response:
            head = response.read(1024)
    except urllib.error.HTTPError as e:
        if e.code >= 500:
            return False, b'', 'HTTP %d nach %.2f s' % (e.code, time.time() - start)
        return True, b'', 'HTTP %d' % e.code
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLError):
            # Der Server hat geantwortet, nur die TLS-Verhandlung scheitert (meist ein Zertifikat,
            # das nicht zu unserem Speicher passt). Das entscheidet der Player: Kodi prueft selbst,
            # ausser die Pipe traegt verifypeer=false (23 Resolver setzen das, VOE darunter). Der
            # Vorabruf darf nicht strenger sein als der Player, sonst sperrte er solche Hoster aus.
            return True, b'', 'TLS %s' % type(e.reason).__name__
        return False, b'', '%s nach %.2f s' % (type(e.reason).__name__, time.time() - start)
    except Exception as e:
        return False, b'', '%s nach %.2f s' % (type(e).__name__, time.time() - start)
    return True, head, '%.2f s' % (time.time() - start)


def _isHls(head):
    # HLS am Inhalt erkennen: eine Playlist beginnt mit #EXTM3U. Der Content-Type reicht
    # nicht, die Hoster liefern Playlists auch als text/plain (gemessen 15.10.2026).
    return head.lstrip(b'\xef\xbb\xbf \r\n\t').startswith(b'#EXTM3U')


def probeStream(link):
    """Vorab-Abruf vor einer Hoster-Wiedergabe (seit dem 05.11.2026, wie bei Live-TV): antwortet
    die Adresse nicht (_probe), startet der Player gar nicht — der Aufrufer meldet es, im
    Auto-Modus kommt der naechste Hoster. Rueckgabe (antwortet, Anfang fuer applyIsa)."""
    url, _sep, headerString = link.partition('|')
    bAnswered, head, how = _probe(url, headerString)
    if bAnswered:
        logger.info('-> [player]: Vorabruf %s: %s' % (how, url))
    else:
        logger.error('-> [player]: Adresse antwortet nicht (%s), kein Start: %s' % (how, url))
    return bAnswered, head


def applyIsa(list_item, link, head=None):
    # HLS laeuft ueber InputStream Adaptive (ISA), sobald das Addon installiert
    # und aktiv ist; sonst bleibt alles beim nativen Player, auch das ListItem.
    # Grund: Kodis eigener Demuxer (FFmpeg) weist Playlists und Segmente mit
    # fremder Dateiendung ab (.js, .txt, .woff2 — so tarnen Hoster wie Gupload,
    # Vidara, Playmate, GXPlayer oder Moflix-Stream ihre Streams), ISA liest
    # sie. Kein eigener Schalter und keine Versionsabfrage: ist ISA da, wird es
    # genutzt, ist es weg oder aus, laeuft es wie vorher.
    # Rueckgabe: die Adresse fuer play() und ob ISA greift.
    # Die Log-Zeile nennt die Adresse ohne die Header der Pipe.
    # head: der Anfang der Antwort aus dem Vorab-Abruf (probeStream), damit eine Adresse
    # ohne bekannte Endung nicht ein zweites Mal abgerufen wird; ohne ihn (Live-TV, das
    # vorher selbst abruft) prueft der Helfer den Inhalt bei Bedarf selbst — ein Fehler
    # der Pruefung zaehlt dann wie bisher als „kein HLS", die Adresse geht nativ.
    url, _sep, headerString = link.partition('|')
    if not xbmc.getCondVisibility('System.AddonIsEnabled(inputstream.adaptive)'):
        logger.info('-> [player]: ISA nicht aktiv, Wiedergabe nativ: %s' % url)
        return link, False
    if '.m3u8' in link or url.lower().split('?')[0].endswith(_HLS_EXTENSIONS):
        isHls, how = True, 'Endung'
    elif url.lower().split('?')[0].endswith(_NO_HLS_EXTENSIONS):
        isHls, how = False, 'Endung'
    elif head is not None:
        isHls, how = _isHls(head), 'Inhalt'
    else:
        bAnswered, head, how = _probe(url, headerString)
        isHls, how = (_isHls(head), 'Inhalt, ' + how) if bAnswered else (False, 'Pruefung ' + how)
    if not isHls:
        logger.info('-> [player]: kein HLS (%s), Wiedergabe nativ: %s' % (how, url))
        return link, False
    # Pfad ohne Pipe: neuere ISA schneidet die Pipe selbst ab, aeltere reicht
    # sie an Kodis Dateizugriff weiter, der die Header nur fuer den ersten
    # Playlist-Abruf setzt — Child-Playlist und Segmente bekaemen sie nicht
    # (ISA-Quelltext, 15.10.2026).
    list_item.setPath(url)
    list_item.setProperty('inputstream', 'inputstream.adaptive')
    if headerString:
        # Kodi reicht an ISA nur Properties durch, die ISA selbst anmeldet;
        # jede ISA-Generation kennt eine andere Auswahl (ISA-Quelltext,
        # 15.10.2026). Derselbe Header-String steht deshalb in allen vier:
        # - manifest_headers / stream_headers: Playlists bzw. Segmente, ueberall
        # - common_headers: nur neuere ISA, dort an jeden Abruf, auch an den
        #   AES-Schluessel
        # - license_key "|Header": aeltere ISA holt den AES-Schluessel nur mit
        #   den Headern aus dem Teil nach der Pipe; ohne license_type startet
        #   keine DRM-Sitzung, neuere ISA ueberspringt die Property still.
        # Belegt an LuluStream: der Schluessel-Abruf ohne Header endet mit 403,
        # mit dieser Form spielt der Hoster auf beiden ISA-Generationen
        # (gemessen 15.10.2026).
        list_item.setProperty('inputstream.adaptive.manifest_headers', headerString)
        list_item.setProperty('inputstream.adaptive.stream_headers', headerString)
        list_item.setProperty('inputstream.adaptive.common_headers', headerString)
        list_item.setProperty('inputstream.adaptive.license_key', '|' + headerString)
    list_item.setMimeType('application/vnd.apple.mpegurl')
    list_item.setContentLookup(False)
    logger.info('-> [player]: HLS (%s), Wiedergabe ueber ISA: %s' % (how, url))
    return url, True


class XstreamPlayer(xbmc.Player):
    # Ein Exemplar je Abspielversuch. Als Erfolg zaehlt nur onAVStarted (Bild
    # und Ton laufen). onPlayBackStarted taugt dafuer nicht: Kodi meldet es
    # schon beim Oeffnen der Datei, auch wenn das Oeffnen danach scheitert
    # (VideoPlayer::OpenFile). Ein Fehlstart endet mit onPlayBackStopped
    # (Fehler beim Oeffnen) oder onPlayBackEnded (Stream ohne Inhalt, etwa eine
    # leere Playlist) — jeweils ohne onAVStarted davor.
    def __init__(self, *args, **kwargs):
        xbmc.Player.__init__(self, *args, **kwargs)
        self.streamFinished = False
        self.avStarted = False
        logger.debug('player instance created')

    def onPlayBackStarted(self):
        logger.debug('starting Playback')

    def onAVStarted(self):
        if self.streamFinished:
            return
        logger.debug('AV started')
        self.avStarted = True

    def onPlayBackStopped(self):
        self._finish('Playback stopped')

    def onPlayBackEnded(self):
        self._finish('Playback completed')

    def onPlayBackError(self):
        # Einen Fehlstart meldet Kodi an Python als onPlayBackStopped
        # (CApplicationPlayerCallback::OnPlayBackError); dieser Rueckruf kommt
        # dort derzeit nicht an. Er bleibt als Absicherung, falls sich das
        # aendert.
        self._finish('Playback error')

    def _finish(self, message):
        # Ist dieser Versuch schon beendet, gehoeren weitere Meldungen zu einer
        # spaeteren Wiedergabe (die Exemplare leben bis zum Skriptende, siehe
        # cPlayer._players) und werden hier nicht mehr gewertet.
        if self.streamFinished:
            return
        logger.debug(message)
        if not self.avStarted:
            logger.error('Kodi failed to open stream')
        self.streamFinished = True



class cPlayer:
    # Alle Player-Exemplare eines Skriptlaufs bleiben bis zum Skriptende
    # erhalten. Grund ist Kodis neue SWIG-Python-Anbindung (sie loeste die
    # Groovy-erzeugte ab): beim Freigeben eines Exemplars einer
    # xbmc.Player-Unterklasse gibt sie den Verweis auf die Klasse nicht frei.
    # Die Klasse und alles, was ueber ihr Modul erreichbar ist (bis zum
    # Addon-Objekt in cConfig), ueberlebt dann das Skriptende — im Kodi-Log
    # "left several classes in memory ... Addon", und der Speicher waechst mit
    # jeder Wiedergabe. Werden die Exemplare erst beim Abbau des Interpreters
    # frei, raeumt Kodi sie mit dem Rest ab. Ueber Aufrufe hinweg waechst die
    # Liste nicht: Kodi startet xStream je Aufruf in einem frischen Interpreter.
    # Dasselbe Muster gilt fuer den Trailer-Player (trailer.py, _TrailerPlayer)
    # und das Info-Fenster (tmdb/info.py, WindowsBoxes).
    _players = []

    def startPlayer(self, isa=False, untilAv=False):
        # isa: der Versuch laeuft ueber InputStream Adaptive, dessen eigenes
        # Fehlerfenster wird geschlossen (unten). untilAv: nur bis zum ersten
        # Bild warten statt bis zum Ende der Wiedergabe — fuer Live-TV, wo das
        # Skript sonst beim Umschalten bis zum Stopp offen bliebe (gemessen
        # 15.10.2026). Der Rueckgabewert bleibt in beiden Faellen avStarted.
        logger.debug('start player')
        xbmcPlayer = XstreamPlayer()
        cPlayer._players.append(xbmcPlayer)
        monitor = xbmc.Monitor()
        while (not monitor.abortRequested()) and (not xbmcPlayer.streamFinished) \
                and not (untilAv and xbmcPlayer.avStarted):
            # Die Rueckrufe laufen waehrend waitForAbort; die Schleife merkt
            # das Ende eines Versuchs erst, wenn der Aufruf zurueckkehrt. Ein
            # kurzer Takt haelt die Wartezeit bis zum naechsten Hoster klein
            # und kostet waehrend der Wiedergabe nichts Messbares.
            monitor.waitForAbort(0.25)
            # Neuere ISA zeigt bei einer fehlenden oder leeren Playlist ein
            # eigenes OK-Fenster, waehrend der Player noch oeffnet; bis jemand
            # OK drueckt, haengt das Oeffnen. Es wird geschlossen, solange der
            # Player oeffnet (isPlaying) und noch kein Bild da ist. Kodis
            # eigenes "Wiedergabe fehlgeschlagen" kommt erst nach dem Stopp
            # und bleibt wie bisher stehen. Die Beschriftung wird nicht
            # gelesen: ein frisch geoeffnetes Fenster traegt fuer einen
            # Bildaufbau noch die des vorigen (gemessen 15.10.2026).
            if isa and not xbmcPlayer.avStarted and not xbmcPlayer.streamFinished \
                    and xbmc.getCondVisibility('Window.IsActive(okdialog)') and xbmcPlayer.isPlaying():
                xbmc.executebuiltin('Dialog.Close(okdialog,true)')
        return xbmcPlayer.avStarted