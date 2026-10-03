# -*- coding: utf-8 -*-
# Python 3
"""Browser-Profile fuer den requestHandler.

Ein Profil ist ein User-Agent PLUS der Kopfsatz, den genau dieser Browser bei einem
Abruf wirklich schickt. Nur der UA allein reicht nicht mehr: Cloudflare vergleicht
inzwischen, ob der Rest zum behaupteten Browser passt — ein Chrome-UA ohne die
Sec-Fetch-Zeilen bekam bei moflix ab dem 29.09.2026 an der API eine Challenge.
Ein echter Browser schickt diese Zeilen seit Jahren bei jedem Abruf mit, das
Fehlen war das Erkennungsmerkmal.

NUR FIREFOX, auf Windows, Linux und macOS. Chrome, Edge und Opera sind seit dem
30.09.2026 bewusst draussen: Cloudflare prueft bei einem Chromium-UA auch, ob die
TLS-Verbindung wie Chrome aussieht — Kodis Python besteht das nicht (an Jacks Geraet
Challenge bei allen drei Chromium-Profilen, Firefox kam durch). Safari ist draussen,
weil es dafuer keinen echten Mitschnitt gibt und unbekannt ist, ob Cloudflare dort
ebenso prueft. Ein UA, dessen Pruefung wir nicht kennen, kommt nicht in den Wuerfel.

Aufbau:
- Die Versionsnummer steht EINMAL unten; die drei UA-Strings werden daraus gebaut.
  Beim monatlichen UA-Durchgang aendert sich nur diese Zahl.
- Zwei Kopfsaetze in der Reihenfolge, wie Firefox sie schickt: PAGE fuer einen
  Seitenaufruf und API fuer einen fetch()-Abruf der Seite auf ihre eigene
  Schnittstelle. Quelle: echter Mitschnitt von Firefox 155 (Playwright), Stand
  30.09.2026; die Zeilen sind seit Firefox 128 unveraendert. Alle drei Plattformen
  schicken denselben Satz, nur der UA-String unterscheidet sich.
- Firefox meldet auf jedem Mac fest "Intel Mac OS X 10.15", auch auf Apple Silicon —
  Absicht von Mozilla, nicht "korrigieren".

Bewusste Abweichungen vom echten Firefox, weil Kodis Python sie nicht kann:
- Accept-Encoding bleibt "gzip, deflate" — fuer br und zstd gibt es keinen Decoder.
- urllib erzwingt "Connection: close" und spricht nur HTTP/1.1; der TLS-Handshake ist
  der von Python, nicht der von Firefox. Fuer die bekannten Pruefungen ist das egal,
  gegen eine TLS-Pruefung gaebe es im Addon keinen Hebel.

Was NICHT hierher gehoert: ein fester UA je Sitzung. Den bekommt eine Site nur in
ihrem eigenen Site-File, wenn ihre Freigabe am UA haengt (kinoger, megakino) — der
requestHandler liefert dann den passenden Kopfsatz zu diesem UA.
"""

from random import choice
from urllib.parse import urlparse

# --- Versionsstand 30.09.2026 -------------------------------------------------
# Firefox liefert alle zwei Wochen dienstags (158 am 13.10., 159 am 27.10.).
# Naechster Durchgang spaetestens Ende Oktober, bei jedem Release davor mitziehen.
FIREFOX_MAJOR = 157

MODE_PAGE = 'page'  # Seitenaufruf im Browser (Adresszeile, Link, Formular)
MODE_API = 'api'    # fetch()/XHR der Seite auf ihre eigene Schnittstelle

ACCEPT_PAGE = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
ACCEPT_API = 'application/json, text/plain, */*'
ACCEPT_ENCODING = 'gzip, deflate'
ACCEPT_LANGUAGE = 'de,en-US;q=0.7,en;q=0.3'  # deutsche Voreinstellung von Firefox


def _uaFirefox(sPlatform):
    return 'Mozilla/5.0 (%s; rv:%d.0) Gecko/20100101 Firefox/%d.0' % (sPlatform, FIREFOX_MAJOR, FIREFOX_MAJOR)


PROFILES = (
    {'key': 'firefox-windows', 'ua': _uaFirefox('Windows NT 10.0; Win64; x64')},
    {'key': 'firefox-linux', 'ua': _uaFirefox('X11; Linux x86_64')},
    {'key': 'firefox-mac', 'ua': _uaFirefox('Macintosh; Intel Mac OS X 10.15')},
)

_BY_UA = dict((p['ua'], p) for p in PROFILES)


def randomUA():
    return choice(PROFILES)['ua']


def profileForUA(sUA):
    """Das Profil zu einem UA-String, None bei einem fremden UA (z.B. die Vavoo-App-UAs)."""
    return _BY_UA.get(sUA)


def _fetchSite(sUrl, sReferer):
    """Sec-Fetch-Site so, wie ein Browser ihn aus Referer und Ziel bildet.

    Ohne Referer ist es ein direkter Aufruf (none). same-site (andere Subdomain
    derselben Domain) wird bewusst nicht unterschieden — dafuer braeuchte es die
    Public-Suffix-Liste, und keine unserer Seiten wechselt die Subdomain.
    """
    if not sReferer:
        return 'none'
    if (urlparse(sReferer).hostname or '').lower() == (urlparse(sUrl).hostname or '').lower():
        return 'same-origin'
    return 'cross-site'


def buildHeaders(sUA, sUrl, sReferer='', sMode=MODE_PAGE, bEncoding=True):
    """Der komplette Kopfsatz zu einem UA als geordnete Liste (Name, Wert).

    None, wenn der UA zu keinem Profil gehoert — dann bleibt der Aufrufer bei seinem
    bisherigen Satz. Die Sec-Fetch-Zeilen gehen wie im Browser nur an sichere Ziele
    (https bzw. localhost); Upgrade-Insecure-Requests und Priority dagegen immer.
    """
    if not profileForUA(sUA):
        return None
    parsed = urlparse(sUrl)
    bSecure = parsed.scheme == 'https' or (parsed.hostname or '') in ('localhost', '127.0.0.1')
    bApi = (sMode == MODE_API)

    h = [('User-Agent', sUA), ('Accept', ACCEPT_API if bApi else ACCEPT_PAGE), ('Accept-Language', ACCEPT_LANGUAGE)]
    if bEncoding:
        h.append(('Accept-Encoding', ACCEPT_ENCODING))
    if sReferer:
        h.append(('Referer', sReferer))
    h.append(('Connection', 'keep-alive'))
    if bApi:
        if bSecure:
            h += [('Sec-Fetch-Dest', 'empty'), ('Sec-Fetch-Mode', 'cors'), ('Sec-Fetch-Site', _fetchSite(sUrl, sReferer))]
        h.append(('Priority', 'u=4'))
    else:
        h.append(('Upgrade-Insecure-Requests', '1'))
        if bSecure:
            h += [('Sec-Fetch-Dest', 'document'), ('Sec-Fetch-Mode', 'navigate'), ('Sec-Fetch-Site', _fetchSite(sUrl, sReferer)), ('Sec-Fetch-User', '?1')]
        h.append(('Priority', 'u=0, i'))
    return h
