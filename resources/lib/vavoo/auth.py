# -*- coding: utf-8 -*-
# Python 3
"""
Vavoo-Backend-Schicht — alles, was das Modul an EIN Backend bindet, steht in
DIESER Datei. Fuer einen Backend-Wechsel wird nur diese Datei angefasst: ACTIVE
auf einen anderen Profilnamen umlegen oder unter PROFILES einen Profilblock
ergaenzen und ACTIVE darauf zeigen lassen.

Ein Profil beschreibt das ganze Backend: Basisadresse, Katalog- und
Resolve-Endpunkt, die Abrufparameter und die Kopfzeilen, die das Backend
erwartet (apply()). vavoo.py liest nur die Exporte unten.

Aufbau seit dem 04.11.2026: Vavoos eigene Live-Schnittstelle "mhub" (Manifest
specVersion 2, https://geil.to/live/mhub-addon.json). Ihr echter
Client ist die Web-App des Betreibers, die Katalog und Stream-Adresse mit
einfachen GET-Abrufen laedt: kein Ping, keine Signatur, keine Geraete-Identity,
kein POST-Rumpf. Wir treten deshalb wie diese Web-App auf: das Browser-Profil
des requestHandlers (User-Agent und der restliche Kopfsatz kommen aus
browserProfiles) in seinem fetch()-Modus, mit der Seitenadresse als Referer.
Die Domain ist geil.to, dort laeuft die Web-App; sie fuehrt www.geil.to,
geil.app und geil.win als ihre eigenen Spiegel.

Das vorige Backend (vypn-Ping mit Signatur und persistenter Geraete-Identity,
in xStream bis zum 04.11.2026) ist samt allem, was es brauchte, ausgebaut; die
Datei <profile>/vavoo/device.json bleibt bei Bestandsinstallationen liegen.

Alle HTTP-Abrufe laufen ueber xStreams cRequestHandler (keine Abhaengigkeit von
'requests').
"""

ACTIVE = "mhub"

PROFILES = {
    "mhub": {
        # Schnittstelle gemessen am 22.10.2026, auf geil.to erneut am 04.11.2026
        # (Manifest, Katalog, Resolve).
        "base": "https://geil.to",                            # eigener Ursprung der Web-App, /live/* antwortet direkt (04.11.2026)
        "catalog_path": "/live/catalog/live/channels.json",   # GET -> {features, items, nextCursor}, 300 Eintraege je Seite
        "resolve_path": "/live/resolve",                      # GET -> {format, live, name, url}; unbekannte Kennung -> 404
        "group_param": "filter[group]",                       # Gross-/Kleinschreibung zaehlt: "germany" -> 0 Eintraege (04.11.2026)
        "cursor_param": "cursor",                             # nextCursor kommt als Text ('300', '600', ...), letzte Seite ohne
        "resolve_param": "url",                               # url des Katalogeintrags (https://geil.to/live/play/<id>)
        "accept": "application/json",                         # was fetch() der Web-App sendet (Mitschnitt 22.10.2026)
        "referer": "https://geil.to/",                        # die Seite, die den fetch() absetzen wuerde, gleicher Ursprung wie die API
    },
}

_P = PROFILES[ACTIVE]

# Exporte, die vavoo.py liest (damit im Abrufcode nichts hartkodiert steht).
BASE_URL      = _P["base"]
CATALOG_URL   = _P["base"] + _P["catalog_path"]
RESOLVE_URL   = _P["base"] + _P["resolve_path"]
GROUP_PARAM   = _P["group_param"]
CURSOR_PARAM  = _P["cursor_param"]
RESOLVE_PARAM = _P["resolve_param"]
REFERER       = _P["referer"]


def apply(oRequest):
    """Die Kopfzeilen des aktiven Backends an einem cRequestHandler setzen.

    Alles Uebrige (User-Agent, Accept-Language, Sec-Fetch-Zeilen, ...) ist das
    Browser-Profil des requestHandlers im fetch()-Modus — der Aufrufer liest die
    Antwort mit requestJson(), das diesen Modus waehlt.
    """
    oRequest.addHeaderEntry('Accept', _P["accept"])
    oRequest.addHeaderEntry('Referer', _P["referer"])
    return oRequest
