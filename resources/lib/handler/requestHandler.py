# -*- coding: utf-8 -*-
# Python 3

import time
import xbmcgui
import re
import os
import hashlib
import json
import traceback
import ssl
import certifi
import socket
import zlib
import threading
import http.client

from resources.lib.config import cConfig
from resources.lib.handler import browserProfiles
from resources.lib.logger import logger
from resources.lib.cache import cCache
from resources.lib.tools import infoDialog
from xbmcvfs import translatePath

from urllib.parse import quote, urlencode, urlparse, quote_plus, urljoin
from urllib.error import HTTPError, URLError
from urllib.request import HTTPHandler, HTTPSHandler, Request, HTTPCookieProcessor, build_opener, urlopen, HTTPRedirectHandler
from http.cookiejar import LWPCookieJar, Cookie
from http.client import HTTPException
from contextlib import contextmanager
from functools import partial

# Rueckgabewerte von request() im Fehlerfall. request() wirft NICHT, sondern
# liefert einen dieser Klartexte zurueck. Bei einer HTML-Seite faellt das nicht
# weiter auf: ein Regex findet darin nichts, die Site zeigt eine leere Liste.
# Wer die Antwort dagegen als JSON auswertet, MUSS den Fehlerfall hier erkennen
# koennen — deshalb stehen die Texte an einer Stelle und werden unten in den
# Fehlerzweigen von hier genommen, statt sie doppelt zu pflegen.
ERR_UNREACHABLE = 'SEITE NICHT ERREICHBAR'
ERR_CLOUDFLARE = 'CLOUDFLARE-SCHUTZ AKTIV'
ERR_DDOS = 'DDOS GUARD SCHUTZ'
ERR_TIMEOUT = 'TIMEOUT'
ERR_URL = 'URL FEHLER'
REQUEST_ERRORS = (ERR_UNREACHABLE, ERR_CLOUDFLARE, ERR_DDOS, ERR_TIMEOUT, ERR_URL)

# DNS-Bypass: die per DoH aufgeloeste IP wird THREAD-LOKAL an den Hostnamen gebunden
# und beim Verbindungsaufbau von den eigenen Handlern unten benutzt. Frueher lief das
# ueber einen prozessweiten Tausch von socket.getaddrinfo — der leckte zwischen Threads
# (parallele Abrufe: checkDomain im Service, Prefetch der Sites, globale Suche): sobald
# ein Thread fertig war, verlor der naechste seine Zuordnung, und ein alter Patch blieb
# liegen (28.09.2026 am Code provoziert). Thread-lokal sieht jeder Thread nur seine
# eigene Zuordnung, nach dem Abruf ist sie weg. Die IP kommt je Abruf frisch aus
# __doh_request (bewusst kein Cache, siehe dort).
_dohPins = threading.local()


def _dohPin(host):
    # Liefert die gepinnte IP fuer 'host' (ohne Port, klein) oder None.
    host = (host or '').split(':')[0].lower()
    return getattr(_dohPins, 'ip_map', {}).get(host)


@contextmanager
def _doh_resolution(hostname, ip):
    """Bindet 'hostname' fuer die Dauer des Blocks im AKTUELLEN Thread an 'ip'.
    Ohne ip passiert nichts. Das TLS-Zertifikat bleibt gueltig, weil die Verbindung
    weiterhin den echten Hostnamen kennt (SNI + Cert-Hostname stimmen) — nur die
    TCP-Verbindung geht zur IP statt zur DNS-Antwort des Systems."""
    if not ip:
        yield
        return
    ip_map = getattr(_dohPins, 'ip_map', None)
    if ip_map is None:
        ip_map = _dohPins.ip_map = {}
    key = (hostname or '').lower()
    previous = ip_map.get(key)
    ip_map[key] = ip
    try:
        yield
    finally:
        if previous is None:
            ip_map.pop(key, None)
        else:
            ip_map[key] = previous


class _PinnedHTTPConnection(http.client.HTTPConnection):
    # Verbindet zur gepinnten IP, spricht die Gegenseite aber weiter mit dem Hostnamen an.
    def __init__(self, host, ip=None, **kwargs):
        super().__init__(host, **kwargs)
        self._pinned_ip = ip

    def connect(self):
        if not self._pinned_ip:
            return super().connect()
        self.sock = self._create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    # Wie oben, danach TLS mit server_hostname=Hostname: SNI und Zertifikatspruefung
    # laufen gegen den echten Namen, nicht gegen die IP.
    def __init__(self, host, ip=None, **kwargs):
        super().__init__(host, **kwargs)
        self._pinned_ip = ip

    def connect(self):
        if not self._pinned_ip:
            return super().connect()
        self.sock = self._create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        if self._tunnel_host:
            self._tunnel()
            server_hostname = self._tunnel_host
        else:
            server_hostname = self.host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)


class _PinnedHTTPHandler(HTTPHandler):
    # Ohne Pin fuer den Host verhaelt sich der Handler exakt wie HTTPHandler.
    def http_open(self, req):
        ip = _dohPin(req.host)
        if not ip:
            return super().http_open(req)
        return self.do_open(partial(_PinnedHTTPConnection, ip=ip), req)


class _PinnedHTTPSHandler(HTTPSHandler):
    # Ohne Pin fuer den Host verhaelt sich der Handler exakt wie HTTPSHandler. Nur der
    # SSL-Kontext wird durchgereicht — check_hostname kennt HTTPSConnection ab Python 3.12
    # nicht mehr als Argument, und wir setzen es ohnehin im Kontext.
    def https_open(self, req):
        ip = _dohPin(req.host)
        if not ip:
            return super().https_open(req)
        return self.do_open(partial(_PinnedHTTPSConnection, ip=ip), req, context=self._context)


class RedirectFilter(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        if cConfig().getSetting('bypassDNSlock', 'false') != 'true':
            if 'notice.cuii' in newurl:
                xbmcgui.Dialog().ok(cConfig().getLocalizedString(30265), cConfig().getLocalizedString(30260) + '\n' + cConfig().getLocalizedString(30261))
                return None
        return HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, hdrs, newurl)


class _NoRedirect(HTTPRedirectHandler):
    # Folgt Redirects NICHT: redirect_request gibt None zurueck, wodurch urllib die
    # 3xx-Antwort als HTTPError durchreicht -> dort steht der Location-Header.
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        return None

class cRequestHandler:
    # useful for e.g. tmdb request where multiple requests are made within a loop
    persistent_openers = {}

    @staticmethod
    def RandomUA():
        # Einstieg fuer alle Aufrufer (Sites, trailer.py, updateManager): der User-Agent
        # eines zufaelligen Browser-Profils. Die Profile samt Kopfsaetzen und die
        # Versionspflege stehen in browserProfiles.py.
        return browserProfiles.randomUA()

    def __init__(self, sUrl, caching=True, ignoreErrors=False, method='GET', data=None, compression=True, jspost=False, ssl_verify=False, cookies=True):
        self._sUrl = self.__cleanupUrl(sUrl)
        self._sRealUrl = ''
        self._USER_AGENT = self.RandomUA()
        self._aParameters = {}
        self._headerEntries = {}
        self._profilePath = translatePath(cConfig().getAddonInfo('profile'))
        self._cachePath = ''
        self._cookiePath = ''
        self._Status = ''
        self._Protection = ''  # 'cf' / 'ddos', sobald ein Schutzsystem erkannt wurde
        self._mode = browserProfiles.MODE_PAGE  # Seitenaufruf; requestJson() schaltet auf API
        self._sResponseHeader = ''
        self._ssl_verify = ssl_verify
        self.ignoreDiscard(False)
        self.ignoreExpired(False)
        self.caching = caching
        self.method = method
        self.data = data
        self.ignoreErrors = ignoreErrors
        self.compression = compression
        self.jspost = jspost
        # cookies=False: sitzungslose Anfrage. Es wird kein Cookie mitgeschickt und
        # keines gespeichert; der Opener kommt ohne Cookie-Verarbeitung und landet
        # nicht in persistent_openers. Zweck: parallele Folgeseiten einer Suche.
        # DLE-Seiten binden die Sitzung an ein PHPSESSID-Cookie, und PHP sperrt
        # die Sitzung je Anfrage — parallele Abrufe mit demselben Cookie werden
        # serverseitig NACHEINANDER abgearbeitet (kkiste: vier Seiten 5,3 s mit,
        # 2,1 s ohne Cookie; hdfilme 4,1 s gegen 1,6 s, gemessen 02.09.2026).
        self.cookies = cookies
        self.cacheTime = int(cConfig().getSetting('cacheTime', 1)) * 3600  # Stunden * 3600 = Sekunden
        self.requestTimeout = int(cConfig().getSetting('requestTimeout', 10))
        self.bypassDNSlock = (cConfig().getSetting('bypassDNSlock', 'false') == 'true')
        self.removeBreakLines(True)
        self.removeNewLines(True)
        self.__setDefaultHeader()
        self.__setCachePath()
        self.__setCookiePath()
        self.isMemoryCacheActive = (cConfig().getSetting('volatileHtmlCache', 'false') == 'true')
        if self.isMemoryCacheActive:
            self._memCache = cCache()
        
        socket.setdefaulttimeout(self.requestTimeout)

    def getStatus(self):
        return self._Status

    def getProtection(self):
        """'cf' bei einer Cloudflare-Sperre, 'ddos' bei DDoS-Guard, sonst ''.

        Der Domain-Check braucht die Unterscheidung: im Status steht nur der
        HTTP-Code, und der ist bei beiden Systemen 403.
        """
        return self._Protection

    def requestJson(self):
        """request() mit JSON-Auswertung — liefert None statt eine Exception zu werfen.

        Sites, die eine JSON-Schnittstelle abfragen, duerfen `json.loads` NICHT
        direkt auf `request()` anwenden: im Fehlerfall kommt von dort ein
        Klartext aus REQUEST_ERRORS zurueck, und `json.loads` wirft darauf einen
        JSONDecodeError. Der Nutzer sah deshalb einen Skriptfehler, obwohl der
        Handler den Fehler bereits gemeldet hatte — bei jedem 4xx/5xx, jedem
        Timeout und jeder Sperre. Mit None greifen stattdessen die vorhandenen
        `if not jSearch`-Pruefungen der Site-Files, und der Nutzer bekommt die
        gewohnte Meldung.

        Kaputtes JSON einer erreichbaren Seite faellt gleich mit ab: es knallte
        bisher an genau derselben Stelle.
        """
        self._mode = browserProfiles.MODE_API  # fetch() der Seite auf ihre Schnittstelle
        sContent = self.request()
        if not sContent or sContent in REQUEST_ERRORS:
            return None
        try:
            return json.loads(sContent)
        except ValueError as e:
            logger.error(' -> [requestHandler]: kein gueltiges JSON (%s) Url: %s' % (e, self._sUrl))
            return None

    def removeNewLines(self, bRemoveNewLines):
        self.__bRemoveNewLines = bRemoveNewLines

    def removeBreakLines(self, bRemoveBreakLines):
        self.__bRemoveBreakLines = bRemoveBreakLines

    def addHeaderEntry(self, sHeaderKey, sHeaderValue):
        self._headerEntries[sHeaderKey] = sHeaderValue

    def getHeaderEntry(self, sHeaderKey):
        if sHeaderKey in self._headerEntries:
            return self._headerEntries[sHeaderKey]

    def addParameters(self, key, value, Quote=False):
        self._aParameters[key] = value if not Quote else quote(str(value))

    def getResponseHeader(self):
        return self._sResponseHeader

    def getRealUrl(self):
        return self._sRealUrl

    def getRequestUri(self):
        return self._sUrl + '?' + urlencode(self._aParameters)

    def __setDefaultHeader(self):
        # Beim Anlegen steht nur der UA fest. Der restliche Kopfsatz entsteht erst beim
        # Abruf (__buildHeaders), weil eine Site den UA bis dahin noch ueberschreiben
        # kann (Sitzungs-UA bei kinoger und megakino) — und der Satz muss zu dem UA
        # passen, der wirklich rausgeht.
        self.addHeaderEntry('User-Agent', self._USER_AGENT)

    def __legacyHeaders(self, sUA):
        # Der Kopfsatz von vor den Browser-Profilen, unveraendert: gilt fuer jeden UA,
        # der zu keinem Profil gehoert (die Vavoo-App-UAs), damit sich dort nichts
        # bewegt. Firefox-typische Zeilen, dazu Keep-Alive, das kein Browser sendet.
        aHeaders = [('User-Agent', sUA),
                    ('Accept-Language', 'de,en-US;q=0.7,en;q=0.3'),
                    ('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8')]
        if self.compression:
            aHeaders.append(('Accept-Encoding', 'gzip, deflate'))
        aHeaders += [('Connection', 'keep-alive'), ('Keep-Alive', 'timeout=5')]
        return aHeaders

    def __buildHeaders(self):
        """Der Kopfsatz, der wirklich auf die Leitung geht — als geordnete Liste.

        Grundlage ist das Browser-Profil zu dem UA, der JETZT gesetzt ist (Default
        oder von der Site ueberschrieben). Den Modus bestimmt der Aufruf: requestJson(),
        X-Requested-With, jspost oder ein JSON-Rumpf heissen "fetch() der Seite",
        alles andere ist ein Seitenaufruf; Sec-Fetch-Site ergibt sich aus dem Referer.
        Was die Site selbst gesetzt hat, gewinnt — unabhaengig von der Schreibweise
        (burningseries setzt seine Namen klein), neue Zeilen kommen hinten dran.
        """
        aSite = list(self._headerEntries.items())
        sUA = self._USER_AGENT
        sReferer = ''
        sMode = self._mode
        if self.jspost:
            sMode = browserProfiles.MODE_API
        for key, value in aSite:
            sKey = key.lower()
            if sKey == 'user-agent':
                sUA = value
            elif sKey == 'referer':
                sReferer = value
            elif sKey == 'x-requested-with' or (sKey == 'content-type' and 'json' in value.lower()):
                sMode = browserProfiles.MODE_API
        self._USER_AGENT = sUA  # DDoS-Guard- und Blazingfast-Weg nehmen denselben UA
        aHeaders = browserProfiles.buildHeaders(sUA, self._sUrl, sReferer, sMode, self.compression)
        if aHeaders is None:
            aHeaders = self.__legacyHeaders(sUA)
        aOut = []
        dIndex = {}
        for key, value in aHeaders:
            dIndex[key.lower()] = len(aOut)
            aOut.append([key, value])
        for key, value in aSite:
            sKey = key.lower()
            if sKey in dIndex:
                aOut[dIndex[sKey]][1] = value
            else:
                dIndex[sKey] = len(aOut)
                aOut.append([key, value])
        return [(key, value) for key, value in aOut]

    @staticmethod
    def __getDefaultHandler(ssl_verify):
        if ssl_verify:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            ssl_context.check_hostname = True
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            return [_PinnedHTTPSHandler(context=ssl_context)]
        else:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            return [_PinnedHTTPSHandler(context=ssl_context)]

    @staticmethod
    def __cleanupUrl(url):
        return url
    
    def request(self):
        if self.caching and self.cacheTime > 0  and self.method == 'GET' and self.data is None:
            if self.isMemoryCacheActive:
                sContent = self.__readVolatileCache(self.getRequestUri(), self.cacheTime)
            else:
                sContent = self.__readPersistentCache(self.getRequestUri())
            if sContent:
                self._Status = '200'
                return sContent
        else:
            logger.info('-> [requestHandler]: read html for %s' % self.getRequestUri())

        # DNS-Bypass global ueber Setting (kein per-Site-Flag mehr)
        if self.bypassDNSlock:
            ip_override = self.__doh_request(self._sUrl)
        else:
            ip_override = None
        _doh_host = urlparse(self._sUrl).hostname

        cookieJar = LWPCookieJar(filename=self._cookiePath)
        try:
            cookieJar.load(ignore_discard=self.__bIgnoreDiscard, ignore_expires=self.__bIgnoreExpired)
        except Exception as e:
            logger.debug(e)
        
        domain = urlparse(self._sUrl).netloc
        if not self.cookies:
            handlers = self.__getDefaultHandler(self._ssl_verify)
            handlers += [_PinnedHTTPHandler(), RedirectFilter()]
            opener = build_opener(*handlers)
        elif domain in cRequestHandler.persistent_openers:
            opener = cRequestHandler.persistent_openers[domain]
        else:
            handlers = self.__getDefaultHandler(self._ssl_verify)        
            handlers += [_PinnedHTTPHandler(), HTTPCookieProcessor(cookiejar=cookieJar), RedirectFilter()]
            opener = build_opener(*handlers)
            cRequestHandler.persistent_openers[domain] = opener

        if self.method == 'POST':
            if self.data is not None:
                if isinstance(self.data, dict):
                    # Default: form data
                    sParameters = urlencode(self.data).encode()
                elif isinstance(self.data, str):
                    sParameters = self.data.encode()
                else:
                    sParameters = self.data
            else:
                sParameters = None
        else:
            sParameters = json.dumps(self._aParameters).encode() if self.jspost else urlencode(self._aParameters, True).encode()
            if len(sParameters) == 0:
                sParameters = None
        
        oRequest = Request(self._sUrl, sParameters if sParameters and len(sParameters) > 0 else None)

        for key, value in self.__buildHeaders():
            oRequest.add_header(key, value)
        
        if self.method == 'POST' and 'Content-Type' not in self._headerEntries:
            oRequest.add_header('Content-Type', 'application/x-www-form-urlencoded')
        elif self.jspost:
            oRequest.add_header('Content-Type', 'application/json')
        
        if self.cookies:
            cookieJar.add_cookie_header(oRequest)
        
        try:
            with _doh_resolution(_doh_host, ip_override):
                oResponse = opener.open(oRequest)
            # Auch das LESEN der Antwort gehoert in den Schutz: stockt der Body (Lese-Timeout)
            # oder bricht die Verbindung mittendrin ab (IncompleteRead, Reset), greifen dieselben
            # Zweige wie beim Verbindungsaufbau. Belegt im Audit 04.09.2026: 9 von ~9.200 Klicks
            # endeten so als Skriptfehler, weil read() bis dahin hinter dem try stand.
            self._sResponseHeader = oResponse.info()
            content_encoding = self._sResponseHeader.get('Content-Encoding', '').lower()
            if content_encoding:
                raw_content = oResponse.read()
                if content_encoding == 'gzip':
                    decompressed = zlib.decompress(raw_content, wbits=zlib.MAX_WBITS | 16)
                elif content_encoding == 'deflate':
                    decompressed = zlib.decompress(raw_content, wbits=-zlib.MAX_WBITS)
                else:
                    decompressed = raw_content
                sContent = decompressed.decode('utf-8', 'replace')
            else:
                sContent = oResponse.read().decode('utf-8', 'replace')
        except HTTPError as e:
            if e.code >= 400:
                self._Status = str(e.code)
                data = e.fp.read()
                # ERKENNUNG DER SCHUTZSYSTEME — Merkmale statt Namensraten.
                # Frueher galt JEDER 4xx als Cloudflare-Sperre, sobald irgendwo in den
                # Headern das Wort "cloudflare" stand. Bei einer Seite hinter Cloudflare
                # steht es aber IMMER drin (server: cloudflare, dazu ein report-to auf
                # a.nel.cloudflare.com) — auch in einer voellig harmlosen 404. Gemessen
                # am 25.08.: 10 von 18 Seiten, jede tote Adresse wurde dem Nutzer als
                # Sperre gemeldet. Merkmal ist deshalb `cf-mitigated`: den Header setzt
                # Cloudflare nur, wenn es tatsaechlich eingegriffen hat (hdfilme:
                # 403 + cf-mitigated: challenge; alle gemessenen 404 ohne).
                # DDoS-Guard wiederum wurde NIE erkannt: geprueft wurde auf 'DDOS-GUARD'
                # in Grossbuchstaben, die Sperrseite schreibt aber 'DDoS-Guard'. Der
                # server-Header ist hier das verlaessliche Merkmal (aniworld:
                # 403 + server: ddos-guard).
                sBody = str(data).lower()
                sServer = (e.headers.get('server') or '').lower()
                aHeaderNames = set(k.lower() for k in e.headers.keys())
                isDdosGuard = 'ddos-guard' in sServer or 'ddos-guard' in sBody
                isCloudflare = ('cf-mitigated' in aHeaderNames
                                or (e.code in (403, 503) and ('just a moment' in sBody or 'cf_chl' in sBody)))
                self._Protection = 'ddos' if isDdosGuard else ('cf' if isCloudflare else '')
                if isDdosGuard:
                    # Der Bypass lief wegen der Gross-/Kleinschreibung oben noch nie.
                    # Deshalb mit Netz: scheitert er, gibt es die Meldung statt eines
                    # Absturzes mitten im Abruf.
                    try:
                        opener = build_opener(HTTPCookieProcessor(cookieJar))
                        opener.addheaders = [('User-agent', self._USER_AGENT), ('Referer', self._sUrl)]
                        response = opener.open('https://check.ddos-guard.net/check.js')
                        content = response.read().decode('utf-8', 'replace')
                        url2 = re.findall("Image.*?'([^']+)'; new", content)
                        if not url2:
                            raise ValueError('kein Check-Pfad in check.js')
                        url3 = urlparse(self._sUrl)
                        url3 = '%s://%s/%s' % (url3.scheme, url3.netloc, url2[0])
                        opener = build_opener(HTTPCookieProcessor(cookieJar))
                        opener.addheaders = [('User-agent', self._USER_AGENT), ('Referer', self._sUrl)]
                        opener.open(url3).read()
                        opener = build_opener(HTTPCookieProcessor(cookieJar))
                        opener.addheaders = [('User-agent', self._USER_AGENT), ('Referer', self._sUrl)]
                        oResponse = opener.open(self._sUrl, sParameters if sParameters else None)
                    except Exception as ddosError:
                        oResponse = None
                        logger.error(' -> [requestHandler]: DDoS-Guard bypass failed (%s) Url: %s' % (ddosError, self._sUrl))
                    if not oResponse:
                        if not self.ignoreErrors:
                            infoDialog(cConfig().getLocalizedString(30875), icon='WARNING', time=10000)
                        logger.error(' -> [requestHandler]: Failed DDoS-Guard active: ' + self._sUrl)
                        return ERR_DDOS
                elif isCloudflare:
                    if not self.ignoreErrors:
                        infoDialog(cConfig().getLocalizedString(30829), icon='WARNING', time=10000)
                    logger.error(' -> [requestHandler]: Failed Cloudflare active: ' + self._sUrl)
                    return ERR_CLOUDFLARE
                else:
                    if not self.ignoreErrors:
                        xbmcgui.Dialog().ok('xStream', cConfig().getLocalizedString(30259) + ' {0} {1}'.format(self._sUrl, str(e)))
                    # Den Fehlertext des Servers mitschreiben: er steht ohnehin schon in
                    # `data` und beantwortet oft direkt, WAS er beanstandet hat. Aus der
                    # blossen Statuszahl war das nicht zu erkennen - am 31.08.2026 kam
                    # von vavoo.to minutenlang ein 400, und erst der Body verriet
                    # {"error":"Validation error"}. Gekuerzt und einzeilig, damit eine
                    # HTML-Fehlerseite das Log nicht flutet.
                    sErrorBody = ''
                    try:
                        sErrorBody = ' '.join(data.decode('utf-8', 'replace').split())[:200]
                    except Exception:
                        pass
                    logger.error(' -> [requestHandler]: HTTPError ' + str(e) + ' Url: ' + self._sUrl
                                 + ((' Body: ' + sErrorBody) if sErrorBody else ''))
                    return ERR_UNREACHABLE
            else:
                if not self.ignoreErrors:
                    xbmcgui.Dialog().ok('xStream', cConfig().getLocalizedString(30259) + ' {0} {1}'.format(self._sUrl, str(e)))
                logger.error(' -> [requestHandler]: HTTPError ' + str(e) + ' Url: ' + self._sUrl)
                return ERR_UNREACHABLE
        except (socket.timeout, TimeoutError):
            # Der Server hat die Verbindung angenommen und dann nicht geantwortet.
            # Seit Python 3.10 IST socket.timeout dasselbe wie TimeoutError und faellt
            # damit durch URLError/HTTPException hindurch — vorher flog der Fall als
            # unbehandelte Exception aus request() heraus und Kodi zeigte einen
            # Skriptfehler. Status -1 (kein gueltiger HTTP-Code) heisst fuer den
            # Domain-Check: langsam, aber nicht tot.
            self._Status = '-1'
            if not self.ignoreErrors:
                # Als Einblendung statt als Fenster (Jacks Entscheidung 25.08.): ein
                # Timeout trifft bei einer langsamen Seite gleich mehrere Abrufe
                # hintereinander — ein Fenster je Abruf wuerde die Oberflaeche
                # blockieren. Im Menue steht die Seite ausserdem als "Timeout", und die
                # vollstaendige Adresse steht in der Logzeile darunter.
                infoDialog('%s %s' % (cConfig().getLocalizedString(30872), urlparse(self._sUrl).hostname or self._sUrl),
                           icon='ERROR', time=8000)
            logger.error(' -> [requestHandler]: Timeout Url: ' + self._sUrl)
            return ERR_TIMEOUT
        except URLError as e:
            # Die Verbindung kam gar nicht zustande. Ein Fall ist dabei eindeutig:
            # sagt der DNS "Name unbekannt" (gaierror -2 / WSAHOST_NOT_FOUND 11001),
            # existiert die Domain nicht mehr — das ist offline, nicht bloss gestoert.
            # Eine voruebergehende Aufloesungsstoerung meldet dagegen gaierror -3
            # (EAI_AGAIN), ein toter Server errno 111/104; die bleiben ohne Status und
            # gelten als unklar.
            # Der Domain-Check liest das aus (STATUS_OFFLINE_DNS bzw. keine Verbindung).
            reason = getattr(e, 'reason', None)
            if isinstance(reason, socket.gaierror) and reason.errno in (-2, 11001):
                self._Status = '-5'
            if not self.ignoreErrors:
                xbmcgui.Dialog().ok('xStream', str(e.reason))
            logger.error(' -> [requestHandler]: URLError ' + str(e.reason) + ' Url: ' + self._sUrl)
            return ERR_URL
        except HTTPException as e:
            if not self.ignoreErrors:
                xbmcgui.Dialog().ok('xStream', str(e))
            logger.error(' -> [requestHandler]: HTTPException ' + str(e) + ' Url: ' + self._sUrl)
            return ERR_TIMEOUT
        except OSError as e:
            # Verbindung waehrend des Lesens weg (Reset, EOF) — kein URLError, sonst ungefangen
            if not self.ignoreErrors:
                xbmcgui.Dialog().ok('xStream', str(e))
            logger.error(' -> [requestHandler]: OSError ' + str(e) + ' Url: ' + self._sUrl)
            return ERR_URL

        if 'lazingfast' in sContent:
            bf = cBF().resolve(self._sUrl, sContent, cookieJar, self._USER_AGENT, sParameters)
            if bf:
                sContent = bf
            else:
                logger.error(' -> [requestHandler]: Failed Blazingfast active: ' + self._sUrl)

        if self.cookies:
            try:
                cookieJar.save(ignore_discard=self.__bIgnoreDiscard, ignore_expires=self.__bIgnoreExpired)
            except Exception as e:
                logger.error(' -> [requestHandler]: Failed save cookie: %s' % e)

        self._sRealUrl = oResponse.geturl()
        self._Status = oResponse.getcode() if self._sUrl == self._sRealUrl else '301'

        if self.__bRemoveNewLines:
            sContent = sContent.replace('\n', '').replace('\r\t', '')
        if self.__bRemoveBreakLines:
            sContent = sContent.replace('&nbsp;', '')

        if self.caching and self.cacheTime > 0 and self.method == 'GET' and self.data is None:
            if self.isMemoryCacheActive:
                self.__writeVolatileCache(self.getRequestUri(), sContent)
            else:
                self.__writePersistentCache(self.getRequestUri(), sContent)

        return sContent

    def getRedirectUrl(self):
        # Loest EINEN Redirect-Hop auf und liefert NUR das Location-Ziel zurueck,
        # ohne die Zielseite selbst zu laden. Noetig fuer Hoster, deren Embed-Seite
        # hinter Cloudflare liegt (z.B. DoodStream): ein GET auf die Seite
        # loest den CF-Block aus. Das Redirect-Ziel liefert die Quell-Seite (URL_MAIN)
        # selbst aus, die Embed-Seite wird hier gar nicht kontaktiert; ResolveURL holt die
        # Seite spaeter mit eigener Logik. Nutzt bewusst dieselbe DoH/Cookie/UA-Basis
        # wie request(), aber KEINE persistent_openers (No-Follow darf den Cache nicht
        # verseuchen, sonst wuerden normale Requests derselben Domain nicht mehr folgen).
        if self.bypassDNSlock:
            ip_override = self.__doh_request(self._sUrl)
        else:
            ip_override = None
        _doh_host = urlparse(self._sUrl).hostname

        cookieJar = LWPCookieJar(filename=self._cookiePath)
        try:
            cookieJar.load(ignore_discard=self.__bIgnoreDiscard, ignore_expires=self.__bIgnoreExpired)
        except Exception as e:
            logger.debug(e)

        handlers = self.__getDefaultHandler(self._ssl_verify)
        handlers += [_PinnedHTTPHandler(), HTTPCookieProcessor(cookiejar=cookieJar), _NoRedirect()]
        opener = build_opener(*handlers)

        # POST-Bodies werden mitgeschickt, wenn der Aufrufer method='POST' gesetzt hat.
        # Gebraucht fuer Freigabe-Formulare, deren Antwort NUR aus dem Location-Header
        # besteht (serienstream-Captcha-Gate: POST auf /r -> 302 auf die Hoster-Adresse).
        sParameters = None
        if self.method == 'POST' and self.data is not None:
            if isinstance(self.data, dict):
                sParameters = urlencode(self.data).encode()
            elif isinstance(self.data, str):
                sParameters = self.data.encode()
            else:
                sParameters = self.data

        oRequest = Request(self._sUrl, sParameters)
        for key, value in self.__buildHeaders():
            oRequest.add_header(key, value)
        if sParameters and 'Content-Type' not in self._headerEntries:
            oRequest.add_header('Content-Type', 'application/x-www-form-urlencoded')
        cookieJar.add_cookie_header(oRequest)

        sLocation = ''
        try:
            with _doh_resolution(_doh_host, ip_override):
                oResponse = opener.open(oRequest)
            sLocation = oResponse.geturl()  # kein Redirect gekommen (z.B. direkt 200) -> finale URL
        except HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                sLocation = e.headers.get('Location', '')
            else:
                logger.error(' -> [requestHandler]: getRedirectUrl HTTPError %s Url: %s' % (str(e), self._sUrl))
        except (URLError, HTTPException) as e:
            logger.error(' -> [requestHandler]: getRedirectUrl Fehler %s Url: %s' % (str(e), self._sUrl))

        if sLocation:
            sLocation = urljoin(self._sUrl, sLocation)  # relative Location -> absolut
        return sLocation

    def __setCookiePath(self):
        cookieFile = os.path.join(self._profilePath, 'cookies')
        if not os.path.exists(cookieFile):
            os.makedirs(cookieFile)
        if 'dummy' not in self._sUrl:
            cookieFile = os.path.join(cookieFile, urlparse(self._sUrl).netloc.replace('.', '_') + '.txt')
            if not os.path.exists(cookieFile):
                open(cookieFile, 'w').close()
            self._cookiePath = cookieFile

    def getCookie(self, sCookieName, sDomain=''):
        cookieJar = LWPCookieJar()
        try:
            cookieJar.load(self._cookiePath, self.__bIgnoreDiscard, self.__bIgnoreExpired)
        except Exception as e:
            logger.error(e)
        for entry in cookieJar:
            if entry.name == sCookieName:
                if sDomain == '':
                    return entry
                elif entry.domain == sDomain:
                    return entry
        return False

    def setCookie(self, oCookie):
        cookieJar = LWPCookieJar()
        try:
            cookieJar.load(self._cookiePath, self.__bIgnoreDiscard, self.__bIgnoreExpired)
            cookieJar.set_cookie(oCookie)
            cookieJar.save(self._cookiePath, self.__bIgnoreDiscard, self.__bIgnoreExpired)
        except Exception as e:
            logger.error(e)

    def ignoreDiscard(self, bIgnoreDiscard):
        self.__bIgnoreDiscard = bIgnoreDiscard

    def ignoreExpired(self, bIgnoreExpired):
        self.__bIgnoreExpired = bIgnoreExpired

    def __doh_request(self, url, doh_server="https://cloudflare-dns.com/dns-query"):
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname
        # Bewusst NICHT gecacht: DDoS-Guard-Edges rotieren, eine im RAM-Cache
        # festgehaltene IP koennte innerhalb der TTL sterben -> immer frisch aufloesen.
        params = urlencode({"name": hostname, "type": "A"})
        doh_url = f"{doh_server}?{params}"
        req = Request(doh_url)
        req.add_header("Accept", "application/dns-json")

        try:
            response = urlopen(req, timeout=5)
            response_text = response.read().decode("utf-8", "replace")
            dns_response = json.loads(response_text)
            if "Answer" not in dns_response:
                raise Exception("Invalid DNS response")
            # Ersten echten A-Record (type 1) aus der Answer-Liste nehmen statt stur [0]:
            # bei CNAME-Ketten kann die IP erst weiter hinten stehen, [0] waere dann der CNAME.
            ip_address = next((a["data"] for a in dns_response["Answer"] if a.get("type") == 1), None)
            if not ip_address:
                raise Exception("No A record in DNS answer")
            return ip_address
        except Exception as e:
            logger.error(' -> [requestHandler]: DNS query failed: %s' % e)
            return None

    def __setCachePath(self):
        cache = os.path.join(self._profilePath, 'htmlcache')
        if not os.path.exists(cache):
            os.makedirs(cache)
        self._cachePath = cache

    def __readPersistentCache(self, url):
        h = hashlib.md5(url.encode('utf8')).hexdigest()
        cacheFile = os.path.join(self._cachePath, h)
        fileAge = self.getFileAge(cacheFile)
        if 0 < fileAge < self.cacheTime:
            # Vorbelegen: schlaegt das Lesen fehl, war `content` frueher gar
            # nicht zugewiesen — die Pruefung darunter warf dann einen
            # UnboundLocalError und der ganze Seitenaufruf brach ab.
            content = None
            try:
                with open(cacheFile, 'rb') as f:
                        content = f.read().decode('utf8')
            except Exception:
                logger.error(' -> [requestHandler]: Could not read Cache')
                # Beschaedigte Datei wegraeumen, sonst scheitert jeder weitere
                # Aufruf an derselben Stelle.
                try:
                    os.remove(cacheFile)
                except Exception:
                    pass
            if content:
                logger.info(' -> [requestHandler]: read html for %s from cache' % url)
                return content
        return None

    def __writePersistentCache(self, url, content):
        try:
            h = hashlib.md5(url.encode('utf8')).hexdigest()
            with open(os.path.join(self._cachePath, h), 'wb') as f:
                f.write(content.encode('utf8'))
        except Exception:
            logger.error(' -> [requestHandler]: Could not write Cache')

    def __writeVolatileCache(self, url, content):
        self._memCache.set(hashlib.md5(url.encode('utf8')).hexdigest(), content)

    def __readVolatileCache(self, url, cache_time):
        entry = self._memCache.get(hashlib.md5(url.encode('utf8')).hexdigest(), cache_time)
        if entry:
            logger.info('-> [requestHandler]: read html for %s from cache' % url)
        return entry

    @staticmethod
    def getFileAge(cacheFile):
        try:
            return time.time() - os.stat(cacheFile).st_mtime
        except Exception:
            return 0

    def dropCacheEntry(self):
        """Den Cache-Eintrag DIESER Adresse verwerfen (RAM-Cache und Datei).

        Fuer Antworten, die mit Status 200 kommen und trotzdem nicht der Inhalt
        sind — die Pruefseite eines vorgeschalteten WAF etwa. request() hat sie
        beim Eintreffen wie jede 200er-Antwort gecacht; bliebe sie liegen, bekaeme
        jeder weitere Aufruf die alte Pruefseite mit ihrer laengst verbrauchten
        Aufgabe aus dem Cache statt einer frischen vom Server. Der Aufrufer
        erkennt die Seite am Inhalt und ruft danach diese Methode.
        Nicht verwechseln mit clearCache(): das leert den GANZEN Cache.
        """
        sKey = hashlib.md5(self.getRequestUri().encode('utf8')).hexdigest()
        if self.isMemoryCacheActive:
            # cCache kennt kein Loeschen; ein leerer Wert zaehlt beim Lesen als
            # Fehltreffer (request() prueft `if sContent`) und wird vom naechsten
            # Abruf ueberschrieben.
            self._memCache.set(sKey, '')
        try:
            os.remove(os.path.join(self._cachePath, sKey))
        except OSError:
            pass

    def clearCache(self, silent=False):
        if self.isMemoryCacheActive:
            self._memCache.clear()
        cRequestHandler.persistent_openers.clear()
        
        # Persistenten Cache aufraeumen: NUR abgelaufene Dateien loeschen.
        # Der Lesepfad prueft ohnehin `0 < fileAge < cacheTime`, abgelaufene Eintraege
        # werden also nie benutzt — der Wisch dient allein dem Plattenplatz. Frische
        # Dateien zu behalten spart nach dem taeglichen Aufraeumen den kompletten
        # Kaltstart: sonst muss jeder erste Aufruf des Tages ins Netz.
        # Grenze = das Maximum aus der Nutzereinstellung und den 48 Stunden, die
        # einzelne Site-Plugins setzen. Aelteres kann nie mehr ein Treffer sein.
        maxAge = max(int(cConfig().getSetting('cacheTime', 12)), 48) * 3600
        cutoff = time.time() - maxAge
        removed = 0
        try:
            for entry in os.scandir(self._cachePath):
                try:
                    if entry.is_file() and entry.stat().st_mtime < cutoff:
                        os.remove(entry.path)
                        removed += 1
                except OSError:
                    pass
        except OSError as e:
            logger.error(' -> [requestHandler]: clearCache failed: %s' % e)
        logger.info(' -> [requestHandler]: cache cleanup, %d abgelaufene Dateien entfernt' % removed)
        if not silent and removed:
            infoDialog(cConfig().getLocalizedString(30405), icon='INFO')


class cBF:
    def resolve(self, url, html, cookie_jar, user_agent, sParameters):
        page = urlparse(url).scheme + '://' + urlparse(url).netloc
        j = re.compile('<script[^>]src="([^"]+)').findall(html)
        if j:
            opener = build_opener(HTTPCookieProcessor(cookie_jar))
            opener.addheaders = [('User-agent', user_agent), ('Referer', url)]
            opener.open(page + j[0])
        a = re.compile(r'xhr\.open\("GET","([^,]+)",').findall(html)
        if a:
            import random
            aespage = page + a[0].replace('" + ww +"', str(random.randint(700, 1500)))
            opener = build_opener(HTTPCookieProcessor(cookie_jar))
            opener.addheaders = [('User-agent', user_agent), ('Referer', url)]
            html = opener.open(aespage).read().decode('utf-8', 'replace')
            cval = self.aes_decode(html)
            cdata = re.compile('cookie="([^="]+).*?domain[^>]=([^;]+)').findall(html)
            if cval and cdata:
                c = Cookie(version=0, name=cdata[0][0], value=cval, port=None, port_specified=False, domain=cdata[0][1], domain_specified=True, domain_initial_dot=False, path="/", path_specified=True, secure=False, expires=time.time() + 21600, discard=False, comment=None, comment_url=None, rest={})
                cookie_jar.set_cookie(c)
                opener = build_opener(HTTPCookieProcessor(cookie_jar))
                opener.addheaders = [('User-agent', user_agent), ('Referer', url)]
                return opener.open(url, sParameters if sParameters else None).read().decode('utf-8', 'replace')

    @staticmethod
    def aes_decode(html):
        try:
            import pyaes
            keys = re.compile(r'toNumbers\("([^"]+)"').findall(html)
            if keys:
                from binascii import hexlify, unhexlify
                msg = unhexlify(keys[2])
                key = unhexlify(keys[0])
                iv = unhexlify(keys[1])
                decrypter = pyaes.Decrypter(pyaes.AESModeOfOperationCBC(key, iv))
                plain_text = decrypter.feed(msg)
                plain_text += decrypter.feed()
                return hexlify(plain_text).decode()
        except Exception as e:
            logger.error(e)
