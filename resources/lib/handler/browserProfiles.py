# -*- coding: utf-8 -*-
# Python 3
"""Browser-Profile fuer den requestHandler.

Ein Profil ist ein User-Agent PLUS der Kopfsatz, den genau dieser Browser bei einem
Abruf wirklich schickt. Nur der UA allein reicht nicht mehr: Cloudflare vergleicht
inzwischen, ob der Rest zum behaupteten Browser passt — ein Chrome-UA ohne die
Sec-Fetch-Zeilen bekam bei moflix ab dem 29.09.2026 an der API eine Challenge.
Ein echter Browser schickt diese Zeilen seit Jahren bei jedem Abruf an eine sichere
Adresse (https) mit, das Fehlen war das Erkennungsmerkmal.

NUR FIREFOX, und seit dem 14.10.2026 GENAU EIN PROFIL: Firefox auf Windows. Chrome,
Edge und Opera sind seit dem 30.09.2026 bewusst draussen: Cloudflare prueft bei einem
Chromium-UA auch, ob die TLS-Verbindung wie Chrome aussieht — Kodis Python besteht das
nicht (am Geraet Challenge bei allen drei Chromium-Profilen, Firefox kam durch).
Safari ist draussen, weil es dafuer keinen echten Mitschnitt gibt und unbekannt ist, ob
Cloudflare dort ebenso prueft. Ein UA, dessen Pruefung wir nicht kennen, kommt nicht
ins Profil. Bis zum 13.10.2026 wuerfelte randomUA() je Abruf zwischen Windows, Linux
und macOS — raus, weil ein Spoof eine Identitaet ist und kein Zufallswert: ein echter
Browser wechselt seine Plattform nicht zwischen zwei Klicks, und gegenueber einer Seite
unterschieden sich die drei nur im UA-String (gleicher Kopfsatz, gleiches TLS).
Windows, weil es die haeufigste Firefox-Plattform ist.

Aufbau:
- Die Versionsnummer steht EINMAL unten; der UA-String wird daraus gebaut.
  Beim monatlichen UA-Durchgang aendert sich im Code meist nur diese Zahl — jede
  Kopfzeile wird dabei aber gegen einen frischen Mitschnitt und den Quelltext des
  Release-Tags (Fundstellen an den Zeilen) gehalten und ihr Quellenkommentar
  (Quelle, Datum) nachgezogen.
- Zwei Kopfsaetze in der Reihenfolge, wie Firefox sie schickt: PAGE fuer einen
  Seitenaufruf und API fuer einen fetch()-Abruf der Seite auf ihre eigene
  Schnittstelle. Quelle: echte Mitschnitte gegen einen lokalen Echo-Server —
  Firefox 155 (Playwright, 30.09.2026), das offizielle deutsche Firefox 157
  (05.10.2026), 158 (14.10.2026) und 159 (27.10.2026, auch die Navigation per
  Klick und Adresszeile ueber Marionette); jede Zeile
  unten traegt ihre Quelle. Referer und Connection
  stehen je Abruftyp verschieden (Seitenaufruf: Connection vor Referer, fetch():
  Referer vor Connection). Die Mitschnitte stammen von Linux und gelten fuer den
  Windows-UA: Firefox baut den Kopfsatz ohne Plattform-Weiche, die Plattform steht
  nur im UA-String. Quelltext am Tag FIREFOX_159_0_RELEASE am 31.10.2026 auf dem
  Weg der Kopfzeilen gelesen (nsHttpHandler.cpp, HttpBaseChannel.cpp, nsHttpChannel.cpp,
  SecFetch.cpp, LocaleService samt Rust-Teilen): Windows-Zweige gibt es nur im UA
  (fest "Windows NT 10.0; Win64; x64", kein eigenes Plattform-Token) und fuer das
  Windows-SSO, das ab Werk aus ist; "Prefer: safe" kommt nur bei eingeschaltetem
  Jugendschutz des Systems.
- Accept-Language ist die deutsche Voreinstellung ("de, en-US, en"; Quelltext
  locale_service_default_accept_languages: Sprache ohne Region plus "en-US, en");
  die Gewichte rechnet Firefox seit Version 147 in 0.1-Schritten
  (rust_prepare_accept_languages, bis 146 q=0.7/0.3) — die Zeile haengt damit an der
  Version und gehoert beim UA-Durchgang mitgeprueft.

Bewusste Abweichungen vom echten Firefox (Grund je Punkt):
- Accept-Encoding bleibt "gzip, deflate". An https-Adressen schickt Firefox
  "gzip, deflate, br, zstd", fuer br hat Python keinen Decoder (zstd erst ab 3.14),
  und ohne br gaebe es keine echte Firefox-Zeile; an http-Adressen schickt Firefox
  selbst "gzip, deflate" (all.js network.http.accept-encoding bzw. .secure).
- urllib ersetzt den Wert von Connection durch "close", stellt Host, Cookie und
  Content-Length selbst nach vorn und spricht nur HTTP/1.1. Content-Type steht bei einem
  POST ueber addParameters ganz vorn (den setzt urllib), bei method='POST' mit data und bei
  jspost als letzte Zeile (den haengt der requestHandler an); der TLS-Handshake ist
  der von Python, nicht der von Firefox. Die Werte stimmen trotzdem: gegen das offizielle
  deutsche Firefox 159 (Mitschnitte 31.10. und 01.11.2026, 17 Faelle samt Weiterleitungen) waren
  am 01.11.2026 alle gleich bis auf Reihenfolge, Connection, Accept-Encoding (oben) und den
  Accept des fetch()-Satzes (ACCEPT_API). Reihenfolge und Connection gaebe es nur mit einem Haken beim
  Senden (gebaut, gemessen und bewusst nicht uebernommen); gegen eine TLS-Pruefung gibt
  es im Addon keinen Hebel.

Was NICHT hierher gehoert: Sitzungslogik. Wo eine Freigabe am UA haengt (kinoger,
megakino, updateManager), haelt der Aufrufer den einmal geholten UA selbst ueber
seine Abrufe fest — mit EINEM Profil ist es ohnehin immer derselbe String —, und der
requestHandler liefert den passenden Kopfsatz zu diesem UA.
"""

from urllib.parse import urlparse

# --- Versionsstand 27.10.2026 -------------------------------------------------
# Firefox liefert alle zwei Wochen dienstags: 159 am 27.10. um 14:00 UTC, 160 am
# 10.11. und 161 am 24.11. (Mozillas Release-Kalender whattrainisitnow.com,
# gelesen am 27.10.2026). Naechster Durchgang spaetestens Ende November, bei
# jedem Release davor auf die dann aktuelle Version mitziehen.
FIREFOX_MAJOR = 159  # Firefox 159.0, einziger Build (20261022150525) unter archive.mozilla.org releases/159.0, 27.10.2026

MODE_PAGE = 'page'  # Seitenaufruf im Browser (Adresszeile, Link, Formular)
MODE_API = 'api'    # fetch()/XHR der Seite auf ihre eigene Schnittstelle

ACCEPT_PAGE = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'  # Seitenaufruf, Firefox 159 de 27.10.2026 (157 und 158 gleich); Quelltext DocumentAcceptHeader() 31.10.2026
ACCEPT_API = 'application/json, text/plain, */*'  # axios-Satz; ein nacktes fetch() schickt */* (Firefox 159, 27.10.2026; Quelltext ACCEPT_HEADER_ALL), den Wert setzt das Skript der Seite
ACCEPT_ENCODING = 'gzip, deflate'  # an https schickt Firefox 159 'gzip, deflate, br, zstd' (27.10.2026), an http genau diesen Wert (all.js, 31.10.2026); siehe oben
ACCEPT_LANGUAGE = 'de,en-US;q=0.9,en;q=0.8'  # deutsche Voreinstellung, Firefox 159 de 27.10.2026; Quelltext 31.10.2026 (ab 147 in 0.1-Schritten, siehe oben)


def _uaFirefox(sPlatform):
    # Form und fester Gecko-Trail 20100101: Mitschnitt Firefox 159 Linux, 27.10.2026; Quelltext 31.10.2026 nsHttpHandler.cpp
    # BuildUserAgent, LEGACY_UA_GECKO_TRAIL (nsRFPService.h), rv: und Firefox/ = MOZILLA_UAVERSION "<Hauptversion>.0"
    return 'Mozilla/5.0 (%s; rv:%d.0) Gecko/20100101 Firefox/%d.0' % (sPlatform, FIREFOX_MAJOR, FIREFOX_MAJOR)


PROFILES = (
    # Plattform-Token: Firefox-Quelltext nsHttpHandler.cpp OSCPU_WIN64 (Tag FIREFOX_159_0_RELEASE, 31.10.2026) — die
    # Windows-Version ist dort fest 10.0, auch Windows 11 meldet sich so; ein "Windows;" davor gibt es nicht (UA_SPARE_PLATFORM)
    {'key': 'firefox-windows', 'ua': _uaFirefox('Windows NT 10.0; Win64; x64')},
)

_BY_UA = dict((p['ua'], p) for p in PROFILES)


def randomUA():
    # Einstieg aller Aufrufer (cRequestHandler.RandomUA). Der Name stammt aus der Zeit mit mehreren
    # Profilen; seit dem 14.10.2026 gibt es genau eines, und das kommt immer (siehe Docstring oben).
    return PROFILES[0]['ua']


def profileForUA(sUA):
    """Das Profil zu einem UA-String, None bei einem fremden UA (bis zum 04.11.2026 die Vavoo-App-UAs)."""
    return _BY_UA.get(sUA)


def _fetchSite(sUrl, sReferer, bFromPage=False):
    """Sec-Fetch-Site so, wie Firefox ihn aus ausloesender Seite und Ziel bildet (SecFetch.cpp).

    Die ausloesende Seite ist hier der Referer. none gibt Firefox nur, wenn keine Seite
    den Abruf ausloest — der Nutzer ueber Adresszeile oder Lesezeichen, oder der Browser
    selbst (IsUserTriggeredForSecFetchSite, Quelltext 31.10.2026). Ohne Referer ist ein
    Seitenaufruf deshalb ein direkter Aufruf ueber die Adresszeile (none). Ein fetch()
    und ein POST kommen dagegen von einer Seite (bFromPage), none gibt es dort nicht —
    ohne Referer also same-origin: der Satz steht fuer den Abruf der Seite auf ihre
    eigene Schnittstelle bzw. ihr eigenes Formular (Suche). same-site
    (andere Subdomain derselben Domain) wird bewusst nicht unterschieden — dafuer
    braeuchte es die Public-Suffix-Liste; an allen 16 Seiten am 31.10.2026 ging
    kein Abruf mit Referer an eine andere Subdomain. Der einzige bekannte Fall, der
    IMDb-Abruf in trailer.py (www.imdb.com an caching.graphql.imdb.com), setzt same-site
    seit dem 01.11.2026 selbst (_IMDB_EXTRA; Mitschnitt Firefox 159 de: fetch() an die
    Schwester-Subdomain same-site, eine Weiterleitung dorthin dagegen cross-site wie hier).
    """
    if not sReferer:
        return 'same-origin' if bFromPage else 'none'
    if (urlparse(sReferer).hostname or '').lower() == (urlparse(sUrl).hostname or '').lower():
        return 'same-origin'
    return 'cross-site'


def buildHeaders(sUA, sUrl, sReferer='', sMode=MODE_PAGE, bEncoding=True, bPost=False):
    """Der komplette Kopfsatz zu einem UA als geordnete Liste (Name, Wert).

    None, wenn der UA zu keinem Profil gehoert — dann bleibt der Aufrufer bei seinem
    bisherigen Satz. Die Sec-Fetch-Zeilen gehen wie im Browser nur an sichere Ziele
    (https bzw. localhost; SecFetch.cpp); Upgrade-Insecure-Requests (nur beim
    Seitenaufruf) und Priority gehen auch an unsichere. bPost: der Abruf geht als
    POST hinaus — dann ist Sec-Fetch-Site auch ohne Referer nie none (_fetchSite), und
    Origin kommt dazu wie bei fetch() an einen fremden Ursprung. sReferer ist die Adresse
    der ausloesenden Seite; als Referer geht hinaus, was _refererFor daraus macht (an
    fremde Urspruenge nur der Ursprung). Die Kopfzeilen weiterer Hops einer Weiterleitung
    bildet redirectHop.
    """
    if not profileForUA(sUA):
        return None
    bSecure = _secure(sUrl)
    bApi = (sMode == MODE_API)

    # Reihenfolge und Werte aller Zeilen: Mitschnitt des offiziellen deutschen Firefox 159 am 27.10.2026
    # (Seitenaufruf, Seitenaufruf mit Referer, fetch() auf die eigene Schnittstelle), gleich wie 155, 157 und 158;
    # Fundstellen im Quelltext (31.10.2026): UA bis Accept-Encoding AddStandardRequestHeaders, Connection BeginConnect,
    # Upgrade-Insecure-Requests und Sec-Fetch OnBeforeConnect, Priority SetupChannelForTransaction
    h = [('User-Agent', sUA), ('Accept', ACCEPT_API if bApi else ACCEPT_PAGE), ('Accept-Language', ACCEPT_LANGUAGE)]
    if bEncoding:
        h.append(('Accept-Encoding', ACCEPT_ENCODING))
    sRefOut = _refererFor(sReferer, sUrl) if sReferer else None
    aReferer = [('Referer', sRefOut)] if sRefOut else []
    # Origin bei jedem POST und bei fetch() an einen fremden Ursprung, Wert = Ursprung der ausloesenden Seite, ohne
    # Referer der eigene (Mitschnitt Firefox 159 de 31.10.2026: Formular-POST, fetch() POST, fetch() cross-origin;
    # Quelltext network.http.sendOriginHeader 2). Seitenaufruf: vor Connection, fetch(): hinter dem Referer.
    # Setzt die Site selbst einen, gewinnt ihrer (requestHandler).
    if bPost or (bApi and sReferer and _origin(sReferer) != _origin(sUrl)):
        if bApi:
            aReferer = aReferer + [('Origin', _origin(sReferer or sUrl))]
        else:
            h.append(('Origin', _origin(sReferer or sUrl)))
    aConnection = [('Connection', 'keep-alive')]  # Firefox 159, 27.10.2026; auf der Leitung steht close, urllib ersetzt den Wert
    # Firefox stellt die beiden je Abruftyp verschieden: fetch() Referer vor Connection,
    # Seitenaufruf Connection vor Referer (Mitschnitte 142, 155, 157, 158 und 159 gleich)
    h += (aReferer + aConnection) if bApi else (aConnection + aReferer)
    if bApi:
        if bSecure:
            # fetch(): Dest empty, Mode cors (Firefox 159, 27.10.2026), Site aus dem Referer, ohne Referer same-origin (_fetchSite)
            h += [('Sec-Fetch-Dest', 'empty'), ('Sec-Fetch-Mode', 'cors'), ('Sec-Fetch-Site', _fetchSite(sUrl, sReferer, True))]
        h.append(('Priority', 'u=4'))  # fetch() ohne Nutzereingabe, Firefox 159, 27.10.2026; aus einem Klick-Handler u=1 (FetchDriver.cpp)
    else:
        h.append(('Upgrade-Insecure-Requests', '1'))  # Seitenaufruf Firefox 159, 27.10.2026; Quelltext: jede Navigation, auch an http
        if bSecure:
            # Seitenaufruf: Dest document, Mode navigate, Site aus dem Referer, User ?1 = vom Nutzer ausgeloest
            # (Adresszeile/Klick; Firefox 159, 27.10.2026 — eine Skript-Navigation schickt kein Sec-Fetch-User);
            # Formular-POST per Klick auf derselben Seite: dieselben vier Zeilen mit same-origin (Firefox 159 de, 31.10.2026)
            h += [('Sec-Fetch-Dest', 'document'), ('Sec-Fetch-Mode', 'navigate'), ('Sec-Fetch-Site', _fetchSite(sUrl, sReferer, bPost)), ('Sec-Fetch-User', '?1')]
        h.append(('Priority', 'u=0, i'))  # Seitenaufruf Firefox 159, 27.10.2026
    return h


def _secure(sUrl):
    """Bekommt diese Adresse Sec-Fetch-Zeilen? Firefox schickt sie nur an vertrauenswuerdige Ziele (SecFetch.cpp,
    potentially trustworthy): https, localhost, 127.0.0.1 — gilt im ersten Abruf und auf jedem Hop."""
    p = urlparse(sUrl)
    return p.scheme == 'https' or (p.hostname or '') in ('localhost', '127.0.0.1')


def _origin(sUrl):
    """Ursprung einer Adresse wie im Origin-Kopf: Schema://Host[:Port], Standard-Port ohne Angabe."""
    p = urlparse(sUrl)
    port = p.port
    if port in (None, {'http': 80, 'https': 443}.get(p.scheme)):
        return '%s://%s' % (p.scheme, (p.hostname or '').lower())
    return '%s://%s:%d' % (p.scheme, (p.hostname or '').lower(), port)


def _refererFor(sReferer, sUrl):
    """Referer, wie Firefox ihn nach der Standard-Policy strict-origin-when-cross-origin schickt: an den eigenen
    Ursprung voll, an einen fremden nur der Ursprung mit /, von https nach http keiner (None). Gilt fuer den ersten
    Abruf (buildHeaders) wie fuer jeden Hop einer Weiterleitung (redirectHop) — Mitschnitt Firefox 159 de: fetch()
    cross-origin (08) und Klick cross-site (11) am 31.10.2026, Klick an die Schwester-Subdomain (S3) am 01.11.2026.
    Eine Seite mit eigener Referrer-Policy ist eine Ausnahme, die das Site-File traegt: serienstream setzt no-referrer,
    sein Hoster-Weg gibt deshalb gar keinen Referer mit (getHosterUrl, _passRedirectGate; live 01.11.2026). Die MC-Serien
    von hdfilme und streamcloud (Referer = Serienseite an die Plattform) haben keine (Header, meta, iframe geprueft
    01.11.2026)."""
    if _origin(sReferer) == _origin(sUrl):
        return sReferer
    if urlparse(sReferer).scheme == 'https' and urlparse(sUrl).scheme != 'https':
        return None
    return _origin(sReferer) + '/'


def redirectHop(sOldUrl, sNewUrl, sReferer, sSite, sOrigin, bCors, bPost, bPostHop=False):
    """Was Firefox fuer den naechsten Hop einer Weiterleitung neu bildet: {Kopfzeile: Wert}, None = weglassen.

    Eingaben vom bisherigen Hop: Referer, Sec-Fetch-Site, Origin, bCors = Sec-Fetch-Mode cors (fetch() der Seite;
    an http-Ziele ohne Sec-Fetch zaehlt ein Abruf wie eine Navigation), bPost = er ging als POST hinaus, bPostHop = der
    Hop selbst geht als POST hinaus (307/308 auf einen POST, seit dem 02.11.2026 im requestHandler nachgebaut).
    urllib kopiert die Kopfzeilen des ersten Abrufs unveraendert auf jeden Hop und schickt jeden weiteren als GET
    (nach einem POST bei 301/302/303 wie Firefox; einem 307/308 auf einen POST folgt erst der RedirectFilter, als POST).
    Firefox (Mitschnitt 159 de, Faelle 10 und 12 vom 31.10.2026, 13-17 vom 01.11.2026): Klick auf eine Weiterleitung
    zu einem fremden Host = Sec-Fetch-Site cross-site und als Referer nur noch der Ursprung; Adresszeile auf eine
    Weiterleitung = none bleibt none, ohne Referer. same-origin nur, solange jeder Hop beim Ursprung des ersten
    bleibt (SecFetch.cpp IsSameOrigin prueft die ganze Kette). Referer nach der Standard-Policy
    strict-origin-when-cross-origin: fremder Ursprung = nur der Ursprung, von https nach http keiner.
    Origin: eine GET-Navigation hat keinen, auch nach einem Formular-POST (17). fetch() schickt ihn auf jedem Hop,
    sobald der Abruf den Ursprung der Seite verlassen hat (13, 14), nach einem Hop von fremdem Boden zu einem
    anderen Ursprung als "null" (16, Fetch-Standard: tainted origin); fetch() POST auf eine Weiterleitung beim
    eigenen Ursprung: ohne (15), fetch() vom eigenen Ursprung auf eine zu einem fremden: mit (18).
    Ein Hop zu einem nicht vertrauenswuerdigen Ziel (http, nicht localhost) traegt KEINE Sec-Fetch-Zeilen — Firefox 159 de
    01.11.2026, Klick und fetch() auf eine Weiterleitung zu einem http-Host (19, 20); Upgrade-Insecure-Requests und Priority
    bleiben. Wo Origin auf dem Hop steht, regelt der requestHandler (RedirectFilter)."""
    dOut = {}
    sOld, sNew = _origin(sOldUrl), _origin(sNewUrl)
    if sSite and sSite != 'none':
        dOut['Sec-Fetch-Site'] = 'same-origin' if sSite == 'same-origin' and sNew == sOld else 'cross-site'
    if sReferer and _origin(sReferer) != sNew:
        dOut['Referer'] = _refererFor(sReferer, sNewUrl)
    sSeite = sOrigin or sOld  # ohne Origin war der Abruf bis hierher same-origin
    # Ein POST traegt Origin auch beim eigenen Ursprung; ob er schon fremden Boden betreten hat, zeigt dann der
    # bisherige Hop (sOld). fetch() POST an einen fremden Ursprung, dessen 302 zurueck zur Seite fuehrt, schickt
    # Origin: null (Firefox 159 de, gemessen 02.11.2026) — bis dahin fiel Origin hier weg
    if bCors and (sOrigin == 'null' or (sOrigin and (not bPost or sOld != sSeite)) or sNew != sSeite):
        bTainted = sOrigin == 'null' or (sNew != sOld and sSeite != sOld)
        dOut['Origin'] = 'null' if bTainted else sSeite
    elif bPostHop:
        # Der Hop bleibt ein POST und traegt Origin wie jeder POST: den Ursprung der Seite — "null" erst, wenn die
        # Kette schon auf fremdem Boden war und den Ursprung erneut wechselt (Fetch-Standard redirect-taint, gelesen
        # 02.11.2026: der erste Wechsel vom eigenen Ursprung weg verdirbt den Origin nicht; dieselbe Formel wie im
        # cors-Zweig, der am Mitschnitt haengt), und bei einem Hop von https auf http (Referrer-Policy
        # strict-origin-when-cross-origin, Schritt „append a request Origin header"). Kein Mitschnitt fuer den
        # POST-Hop — beim naechsten UA-Durchgang als Fall 21 mitschneiden.
        bTainted = sOrigin == 'null' or (sNew != sOld and sSeite != sOld)
        bAbstieg = sSeite.lower().startswith('https://') and not sNewUrl.lower().startswith('https://')
        dOut['Origin'] = 'null' if (bTainted or bAbstieg) else sSeite
    else:
        dOut['Origin'] = None
    if not _secure(sNewUrl):
        for sKey in ('Sec-Fetch-Dest', 'Sec-Fetch-Mode', 'Sec-Fetch-Site', 'Sec-Fetch-User'):
            dOut[sKey] = None
    return dOut
