# -*- coding: utf-8 -*-
# Python 3
"""Wrapper-Resolver fuer die meinecloud-Plattform (seit 09/2026 auch DEVIDEOSRC).

Mehrere DLE-Family-Sites verstecken Hoster hinter diesem Aggregator. Diese
Datei buendelt alle plattformspezifische Resolver-Logik (Filme + Serien)
zentral. Gehoert in resources/lib/wrappers/ — beim Hinzufuegen einer
weiteren Wrapper-Plattform: eigenes File im gleichen Ordner anlegen.

Hinweis: Die Plattform heisst technisch meinecloud. Sites labeln sie
unterschiedlich ('Sirius', 'meinecloud', 'Server 1' etc.) — alles dasselbe.
Seit 09/2026 tritt sie zusaetzlich als DEVIDEOSRC auf (devideosrc.co =
Hauptdomain laut eigener Doku, meinecloud.click = Embed-Domain, gleicher
Katalog, gleiche API). Der Wrapper erkennt beide Markennamen (isPlatformUrl).

═══════════════════════════════════════════════════════════════════
  WRAPPER-NUTZER — welche Sites importieren aus diesem File
═══════════════════════════════════════════════════════════════════

Eine zentrale Stelle fuer alle Sites die meinecloud-Funktionen importieren
— beim Hinzufuegen/Entfernen einer Site nur HIER aktualisieren.

  sites/hdfilme.py        — Filme Pattern A | Serien MERGE
  sites/streamcloud.py    — Filme Pattern D | Serien MC-ONLY
                            (Film/Serie-Erkennung ueber die Marker der
                            eigenen Detailseite, siehe dort _hasMeinecloudSerial)

Pattern-Legende:
  Filme  — Pattern A/B/C/D = unterschiedliche Site-HTML-Strukturen die
           alle in resolveMeinecloud() / expandHosterList() muenden
  Serien — drei Architekturen:
    MERGE     showSeasons + showEpisodes -> showHosters(hosterBlock +
              meinecloud_url). mc wird IMMER geladen und ist das
              Rueckgrat, native Hoster kommen dazu (buildMergedHosters);
              Staffeln/Episoden = Union beider Quellen.
    MC-ONLY   showSeasons + showEpisodes -> showHosters(meinecloud_url).
              Serien-Hoster kommen NUR von mc — natives data-num ist
              fuer mc-Serien tot; Nicht-mc-Serien laufen weiter ueber
              den nativen data-num-Pfad.
    FALLBACK  showSeasons + showEpisodes + showEpisodeHosters. Auf jeder
              Ebene erst natives DLE-Pattern, NUR bei 0 Treffern mc
              (resolveMeinecloudSerial). Liefert nativ irgendwas, wird
              mc gar nicht gefragt — KEIN Merge. Derzeit ohne Nutzer im
              Bestand; beschrieben fuer kuenftige Sites dieser Bauart.

═══════════════════════════════════════════════════════════════════
  Plattform-Schema seit dem Umbau vom 28.09.2026 (Token + JSON-API)
═══════════════════════════════════════════════════════════════════

Die Embed-Seiten der Plattform tragen keine Hoster mehr im HTML. Stattdessen:

    1. GET  <base>/movie/<imdb>  bzw.  <base>/serial/<imdb>
       Die Seite liefert im Inline-Skript ein Feld  token: "<b64>.<sig>"
       (Nutzlast base64: type|id|season|episode|ablauf; an Typ und ID
       gebunden, rund eine halbe Stunde gueltig — deshalb ohne Cache).
       devideosrc.co liefert seine Embed-Seiten aus einem Cache, deren
       Token schon abgelaufen sein kann (28.09.2026 gemessen: Serienseite
       4 min ueber der Zeit, Filmseite 45 s Rest; meinecloud.click frisch
       mit 10-28 min). Deshalb liest der Wrapper den Ablauf aus der
       Nutzlast und weicht bei abgelaufenem Token auf den Schwester-Host
       aus (_freshToken) — fuer Filme wie Serien.
    2. POST <base>/api/embed-links  mit JSON {type, id, token}
       Film   -> {"ok":true,"type":"movie","sources":[{name,url,rank},...]}
       Serie  -> {"ok":true,"type":"tv","tv":{"seasons":[{"season_number",
                  "episodes":[{"episode_number","title","description",
                  "sources":[{name,url},...]}]}]}}
       Alle Staffeln und Folgen in EINEM Aufruf. Eine tv-Anfrage fuer eine
       Film-ID (und umgekehrt) bekommt 403 — das ist die einzige Auskunft
       der Plattform darueber, ob es zu einer ID eine Serie gibt.

Die Adressen der Quellen kommen im Klartext; _decodeLink() bleibt trotzdem
davor, weil die Plattform ihre Adressen schon einmal (09/2026) ohne
Ankuendigung base64-kodiert ausgeliefert hat.

Die alten Wege — data-link-Listen im HTML, der Player mit
data-resolve-endpoint (/api/resolve) und der Serien-Check /serials.php —
existieren seit dem Umbau auf keinem der beiden Hosts mehr und sind hier
ausgebaut.

═══════════════════════════════════════════════════════════════════
  meinecloud (Filme — resolveMeinecloud)
═══════════════════════════════════════════════════════════════════

Eingang: Plattform-Adresse aus dem Site-HTML (Form: <host>/movie/<imdb>),
ueber isPlatformUrl erkannt. Host und IMDb-ID kommen aus dieser Adresse,
dann Schritt 1 und 2 von oben; Ausgang: Liste der Hoster-Adressen.

Trigger in Site (beide Markennamen, ein Check):
    from resources.lib.wrappers.meinecloud import resolveMeinecloud, isPlatformUrl
    if isPlatformUrl(sUrl):
        for resolved in resolveMeinecloud(sUrl, referer=URL_MAIN):
            ...

Pattern A — Standard:
    Im Hoster-Loop nach data-link-Match einen Expand-Block einbauen,
    Plattform-URLs durch resolveMeinecloud() expandieren, andere durchreichen.
    Beispiel: sites/hdfilme.py showHosters().
Pattern B — 2-Stage iframe:
    Site filtert das Plattform-iframe per isPlatformUrl und gibt die
    iframe-URL DIREKT in expandHosterList([hUrl]) — Laden und Aufloesen
    macht resolveMeinecloud() zentral. Derzeit ohne Nutzer im Bestand.
Pattern C — (URL, Name)-Tupel:
    Site nutzt re.findall mit Tupel-Capture. Resolved URLs haben keinen
    Site-Namen — Hostname als Fallback aus URL extrahieren.
    Beispiel: aktuell keine Site im Paket (zuletzt sites/kkiste.py).
Pattern D — Multi-Mode konvergent:
    Site hat mehrere Modi (Episode/Movie) die in einer gemeinsamen
    Hoster-Loop konvergieren. Expand-Block direkt nach `if isMatch:`,
    faengt alle Modi ab.
    Beispiel: sites/streamcloud.py showHosters().

Filter im Resolver:
    - Self-Refs auf die Plattform selbst (interne Links sind keine Streams)
    - Dubletten
Fehlerwege (alle -> [] mit Logzeile, kein Fenster — Hilfsabruf):
    - keine Antwort, Timeout, 4xx/5xx auf Seite oder API
    - Seite ohne Token (Seitenaufbau geaendert)
    - API meldet ok=false oder liefert keine Quellen

═══════════════════════════════════════════════════════════════════
  meinecloud (Serien — resolveMeinecloudSerial)
═══════════════════════════════════════════════════════════════════

Die Sites rendern Staffel/Episoden ihrer Plattform-Serien nicht mehr im
Detail-HTML; die Daten kommen von der Plattform.

Ablauf:
    0. IMDb-ID der Serie aus dem Site-HTML: platformImdbId() — zuerst `var imdb`
       des Plattform-Snippets (nur wenn dort eine tt-ID steht), sonst das Muster
       tt + 7 bis 9 Ziffern. Die Plattform fuehrt Titel ohne IMDb-Eintrag unter
       verlaengerten IDs (normale ID plus Anhang, z.B. tt39397536111); das Muster
       allein kuerzte sie und die Plattform fand nichts (gemessen 21.09.2026).
    1. Plattform-Host aus dem Site-HTML (_discoverPlatformBase): der erste
       Plattform-Link der Seite (Embed-Snippet: /embed/download, /movie,
       /serial); nennt die Seite keinen, der erste Host aus
       PLATFORM_SERIAL_HOSTS. Die uebrigen Hosts folgen als Ausweg.
    2. GET <base>/serial/<imdb> -> Token (frisch, sonst naechster Host);
       POST /api/embed-links type=tv.
    3. Ausgang: Liste von Dicts {season, episode, title, urls}, sortiert
       nach Staffel/Folge; urls = ALLE Quellen der Folge in API-Reihenfolge.
       403 der API = zu dieser ID gibt es keine Serie -> [].

Die Plattform liefert je Folge eine oder mehrere Quellen (Stand 03.10.2026:
Dropload, bei rund der Haelfte der spielbaren Folgen zusaetzlich Doodstream —
Stichprobe ueber 58 streamcloud-Serien). Die Sites reichen ALLE durch; fuer
den Weg ueber die Kodi-Parameterrunde gibt es packSourceUrls() /
unpackSourceUrls() (ein Parameter meinecloud_url, buildMergedHosters entpackt
ihn selbst).

═══════════════════════════════════════════════════════════════════
  meinecloud (Serien-Merge — buildMergedHosters)
═══════════════════════════════════════════════════════════════════

Fuer die MERGE-Sites: legt native Roh-data-links und die meinecloud-Adressen
einer Episode (alle Quellen) zu EINER deduplizierten Hoster-Liste zusammen
(native zuerst, interne Fake-Links raus). Leere Eingaben ok — kein Crash.
Details: Docstring von buildMergedHosters().
"""

import base64
import json
import re
import time
from urllib.parse import urlparse

from resources.lib.handler.requestHandler import cRequestHandler, REQUEST_ERRORS
from resources.lib.logger import logger
from resources.lib.tools import cParser, cUtil


# ══════════════════════════════════════════════
#   meinecloud — gemeinsame Konstanten
# ══════════════════════════════════════════════

# Trigger-Substring fuer URL-Match. Bewusst nur 'meinecloud' (ohne TLD)
# — robust gegen TLD-Wechsel innerhalb der Plattform-Familie.
MEINECLOUD_TRIGGER = 'meinecloud'

# Zweiter Markenname derselben Plattform (Rebranding 09/2026): DEVIDEOSRC
# ist laut eigener Doku (devideosrc.co) die Hauptdomain, meinecloud.click
# die Embed-Domain — beide teilen Katalog und Hoster. Sites koennen also
# jederzeit auf devideosrc-Embeds umstellen; der Wrapper erkennt beide.
DEVIDEOSRC_TRIGGER = 'devideosrc'
PLATFORM_TRIGGERS = (MEINECLOUD_TRIGGER, DEVIDEOSRC_TRIGGER)

# Bekannte Hosts der Plattform, gleicher Katalog und gleiche API. Zuerst
# kommt immer der Host, den die Site nennt (Film-Adresse bzw. Snippet im
# Detail-HTML); die anderen sind der Ausweg, wenn dieser Host keine Seite,
# keinen Token oder nur einen abgelaufenen Token liefert (siehe Kopf). Ohne
# Nennung im Site-HTML beginnt der Serien-Resolver beim ersten Eintrag.
# Bewusste Ausnahme vom Kein-Hardcoding-Grundsatz: die Hosts sind
# Plattform-Eigenschaft (wie die Trigger selbst), nicht Seiteninhalt — die
# Discovery kann nur finden, was im Site-HTML steht, und genau das fehlte
# beim Umbau der Plattform (28.09.2026: keine Site nennt mehr den alten
# Check-Pfad).
PLATFORM_SERIAL_HOSTS = ('meinecloud.click', 'devideosrc.co')

# So viele Sekunden muss ein Token beim POST mindestens noch gelten.
_TOKEN_MARGIN = 30

# JSON-API der Plattform (Schema siehe Kopf).
EMBED_API_PATH = '/api/embed-links'

# Token im Inline-Skript der Embed-Seite:  token: "<b64>.<sig>"
_RE_TOKEN = re.compile(r"token\s*:\s*[\"']([^\"']{16,})[\"']")
# Erster Plattform-Host im Site-HTML (Embed-Snippet der Seite).
_RE_PLATFORM_HOST = re.compile(r'https?://([a-z0-9.-]*(?:%s)[a-z0-9.-]*)' % '|'.join(re.escape(t) for t in PLATFORM_TRIGGERS), re.I)
_RE_IMDB = re.compile(r'tt\d+')


def isPlatformUrl(sUrl):
    """True, wenn die URL zur meinecloud/devideosrc-Plattform gehoert.

    Ersetzt den reinen MEINECLOUD_TRIGGER-Substring-Check ueberall dort, wo
    beide Markennamen erkannt werden muessen — in den internen Helpern und
    in den Site-Files, die selbst pruefen. Es gibt keinen
    Substring, der in beiden Markennamen steckt, deshalb eine Funktion statt
    einer zweiten Konstante.
    """
    return bool(sUrl) and any(t in sUrl for t in PLATFORM_TRIGGERS)


def platformImdbId(sHtml):
    """IMDb-ID fuer den Serienweg aus dem Site-HTML: zuerst `var imdb`, sonst das Muster.

    Die Site-Files lasen die ID bis 21.09.2026 mit dem Muster tt + 7 bis 9 Ziffern
    (erster Treffer der Seite). Die Plattform fuehrt aber Titel ohne IMDb-Eintrag
    unter einer verlaengerten ID (eine fremde IMDb-Nummer plus Anhang 111/112/113,
    z.B. tt39397536111); das Muster schnitt sie ab, der Check in
    resolveMeinecloudSerial fand unter der gekuerzten ID nichts, und die Serie
    oeffnete leer — gemessen an streamcloud (5 von 6.121 Serien) und hdfilme
    (1 von 3.912). Das Einbett-Snippet der Plattform, aus dem
    _discoverMeinecloudBase die Basis-Adresse liest, traegt die volle ID in
    `var imdb`; die Serienerkennung der Sites liest sie dort ebenfalls —
    Erkennung und Aufloesung sehen so dieselbe ID.

    Nur eine tt-ID aus `var imdb` zaehlt: native Serien fuehren dort einen Text
    (hdfilme 3.316 von 3.912), manche Seiten 'N/A' oder einen Tippfehler wie
    'tt14226626h' — dann greift wie bisher der erste Treffer des Musters.

    Args:
        sHtml: Site-HTML der Serien-Detailseite

    Returns:
        'tt<Ziffern>' oder '' wenn nichts gefunden — der Caller ueberspringt dann
        den meinecloud-Weg wie bisher.
    """
    if not sHtml:
        return ''
    m = re.search(r"var imdb = '(tt\d+)'", sHtml)
    if m:
        return m.group(1)
    m = re.search(r'(tt\d{7,9})', sHtml)
    return m.group(1) if m else ''


# Hoster-URLs ohne Media-ID. Manche Sites lassen leere Platzhalter im HTML
# stehen (beobachtet auf hdfilme: 'https://voe.sx/e/', '//mixdrop.co/e/',
# '//dr0pstream.com/embed-.html'). Die landen sonst als tote, nicht
# abspielbare Eintraege in der Hoster-Liste. Greift nur wenn nach dem
# Hoster-Praefix wirklich NICHTS mehr kommt — echte IDs bleiben unberuehrt.
# movie|serial sind die meinecloud-eigenen Formen: ein ID-loser Platzhalter
# ('meinecloud.click/movie/') wuerde sonst abgerufen und der 404 dem Nutzer
# als Fehlerfenster gezeigt (beobachtet auf einem verwaisten hdfilme-Beitrag).
EMPTY_ID_PATTERN = re.compile(r'/(?:e|d|f|v|embed|embed-|movie|serial)/?(?:\.html)?$', re.I)


def _decodeLink(sValue):
    """Eine Hoster-Adresse der Plattform normalisieren: base64 dekodieren, Klartext durchreichen.

    Die Plattform hat im 09/2026 begonnen, die data-link-Werte base64-kodiert
    auszuliefern ('Ly9kcjBwc3RyZWFtLmNvbS9lL3M4b252eHQ4cmx2aQ==' statt
    '//dr0pstream.com/e/s8onvxt8rlvi'). Kodierte Werte kommen NICHT durch
    buildHosterFromUrl() und die Hosterliste bleibt leer — Symptom an allen
    mc-Sites: 'kein einziger Hoster mehr, obwohl die Seite welche zeigt'.

    Die Umstellung laeuft nur teilweise: am 08.09.2026 lieferten die
    movie-Seiten base64, die serial-Seiten noch Klartext. Deshalb wird nicht
    blind dekodiert, sondern nur, wenn der Wert keine Adresse ist UND die
    Dekodierung eine ergibt. Alles andere bleibt unveraendert — auch bei einem
    Rueckbau der Plattform oder gemischten Listen aendert sich damit nichts.

    Args:
        sValue: rohe Adresse aus der API (frueher der data-link-Wert aus dem Markup)

    Returns:
        str: die Adresse (dekodiert oder unveraendert). Nie None.
    """
    if not sValue:
        return sValue
    sTrimmed = sValue.strip()
    if sTrimmed.startswith('//') or sTrimmed.lower().startswith('http'):
        return sValue
    try:
        # Padding ergaenzen: die Plattform liefert es zwar mit, aber ein
        # fehlendes '=' wuerde sonst eine gueltige Adresse verwerfen.
        sDecoded = base64.b64decode(sTrimmed + '=' * (-len(sTrimmed) % 4)).decode('utf-8', 'ignore').strip()
    except Exception:
        return sValue
    if sDecoded.startswith('//') or sDecoded.lower().startswith('http'):
        return sDecoded
    return sValue


def _fixScheme(sUrl):
    """Protokoll-relative URL (//host/...) auf https: normalisieren.

    Eine Stelle fuer den Schema-Fix, genutzt von buildHosterFromUrl() (dort
    fuer die ausgelieferte URL) und von expandHosterList() (dort nur als
    Dedup-Vergleichsschluessel). Grund: meinecloud liefert //host/x, Sites
    liefern https://host/x — ohne Normalisierung gelten beide als
    verschieden und dieselbe Datei landet zweimal in der Hoster-Liste.
    """
    return ('https:' + sUrl) if sUrl.startswith('//') else sUrl


def _platformBase(sUrl):
    """Schema und Host einer Plattform-Adresse ('https://host'), '' wenn keine."""
    sUrl = _fixScheme(sUrl or '')
    if not isPlatformUrl(sUrl):
        return ''
    oParts = urlparse(sUrl)
    if not oParts.hostname:
        return ''
    return '%s://%s' % (oParts.scheme or 'https', oParts.hostname)


def _discoverPlatformBase(sHtml):
    """Plattform-Host fuer den Serien-Resolver: der erste Plattform-Link im
    Site-HTML, sonst der erste Host aus PLATFORM_SERIAL_HOSTS (Begruendung dort)."""
    m = _RE_PLATFORM_HOST.search(sHtml or '')
    if m:
        return 'https://' + m.group(1)
    return 'https://' + PLATFORM_SERIAL_HOSTS[0]


def _embedPage(sBase, sKind, sImdb, referer=''):
    """Embed-Seite der Plattform laden (Film: movie, Serie: serial) -> HTML oder ''.

    Ohne Cache, weil der Token der Seite nur kurz gilt; ohne Fehlerfenster,
    weil das ein Hilfsabruf ist — der Nutzer hat die Plattform nicht angeklickt.
    """
    sUrl = '%s/%s/%s' % (sBase, sKind, sImdb)
    try:
        oRequest = cRequestHandler(sUrl, caching=False, ignoreErrors=True)
        if referer:
            oRequest.addHeaderEntry('Referer', referer)
        sHtml = oRequest.request()
        if not sHtml or sHtml in REQUEST_ERRORS:
            logger.info('wrappers.meinecloud: keine Antwort von %s (Status %s)' % (sUrl, oRequest.getStatus()))
            return ''
        return sHtml
    except Exception as e:
        logger.error('wrappers.meinecloud: %s bei %s' % (e, sUrl))
    return ''


def _embedToken(sHtml):
    """Token aus dem Inline-Skript der Embed-Seite, '' wenn keiner da ist."""
    m = _RE_TOKEN.search(sHtml or '')
    return m.group(1) if m else ''


def _tokenFresh(sToken):
    """True, wenn der Ablauf in der Token-Nutzlast noch mindestens _TOKEN_MARGIN
    Sekunden hin ist; ohne lesbare Nutzlast True (dann entscheidet die API)."""
    try:
        sRaw = (sToken or '').split('.', 1)[0]
        aParts = base64.b64decode(sRaw + '=' * (-len(sRaw) % 4)).decode('utf-8', 'replace').split('|')
        return int(aParts[4]) > int(time.time()) + _TOKEN_MARGIN
    except Exception:
        return True


def _hostOrder(sFirst):
    """Reihenfolge der Plattform-Hosts: der genannte zuerst, dann die uebrigen aus PLATFORM_SERIAL_HOSTS."""
    aOrder = [sFirst] if sFirst else []
    for sHost in PLATFORM_SERIAL_HOSTS:
        if 'https://' + sHost not in aOrder:
            aOrder.append('https://' + sHost)
    return aOrder


def _freshToken(aBases, sKind, sImdb, referer=''):
    """Embed-Seite auf den Hosts der Reihe nach holen, bis ein gueltiger Token da ist.

    Returns: (base, token, seitenadresse) oder ('', '', '') — jeder Abbruch steht im Log.
    """
    for sBase in aBases:
        sPageUrl = '%s/%s/%s' % (sBase, sKind, sImdb)
        sHtml = _embedPage(sBase, sKind, sImdb, referer)
        if not sHtml:
            continue
        sToken = _embedToken(sHtml)
        if not sToken:
            logger.info('wrappers.meinecloud: kein Token auf %s (Seitenaufbau geaendert?)' % sPageUrl)
            continue
        if not _tokenFresh(sToken):
            logger.info('wrappers.meinecloud: Token von %s schon abgelaufen (gecachte Seite), naechster Host' % sPageUrl)
            continue
        return sBase, sToken, sPageUrl
    return '', '', ''


def _embedLinks(sBase, sType, sId, sToken, referer=''):
    """POST /api/embed-links -> Antwort-Dict mit ok=True, sonst None (steht im Log).

    403 heisst: zu dieser ID gibt es den angefragten Typ nicht (tv-Anfrage fuer
    einen Film und umgekehrt) oder der Token passt nicht mehr.
    """
    sUrl = sBase + EMBED_API_PATH
    try:
        oRequest = cRequestHandler(sUrl, caching=False, ignoreErrors=True, method='POST',
                                   data=json.dumps({'type': sType, 'id': sId, 'token': sToken}))
        oRequest.addHeaderEntry('Content-Type', 'application/json')
        oRequest.addHeaderEntry('Origin', sBase)
        if referer:
            oRequest.addHeaderEntry('Referer', referer)
        oData = oRequest.requestJson()
        if oData is None:
            logger.info('wrappers.meinecloud: keine JSON-Antwort fuer %s/%s (Status %s)' % (sType, sId, oRequest.getStatus()))
            return None
        if not isinstance(oData, dict) or not oData.get('ok'):
            sError = oData.get('error') if isinstance(oData, dict) else 'kein Objekt'
            logger.info('wrappers.meinecloud: API lehnt %s/%s ab (%s)' % (sType, sId, sError))
            return None
        return oData
    except Exception as e:
        logger.error('wrappers.meinecloud: %s bei %s' % (e, sUrl))
    return None


def _sourceUrls(aSources):
    """Hoster-Adressen aus einer 'sources'-Liste der API: normalisiert
    (_decodeLink), ohne Plattform-Self-Refs, ohne Dubletten, in API-Reihenfolge."""
    aOut = []
    for oSource in aSources or []:
        if not isinstance(oSource, dict):
            continue
        sUrl = _decodeLink((oSource.get('url') or '').strip())
        if not sUrl or isPlatformUrl(sUrl) or sUrl in aOut:
            continue
        aOut.append(sUrl)
    return aOut


# ══════════════════════════════════════════════
#   meinecloud — Filme
# ══════════════════════════════════════════════

def resolveMeinecloud(sUrl, referer=''):
    """Plattform-Adresse eines Films (<host>/movie/<imdb>) -> Liste der Hoster-Adressen.

    Fehlerwege liefern [] und eine Logzeile, nie ein Fenster (siehe Kopf).
    """
    try:
        sBase = _platformBase(sUrl)
        m = _RE_IMDB.search(sUrl or '')
        if not sBase or not m:
            logger.info('wrappers.meinecloud: keine Plattform-Adresse mit IMDb-ID: %s' % sUrl)
            return []
        sImdb = m.group(0)
        sBase, sToken, sPageUrl = _freshToken(_hostOrder(sBase), 'movie', sImdb, referer)
        if not sToken:
            return []
        oData = _embedLinks(sBase, 'movie', sImdb, sToken, sPageUrl)
        aUrls = _sourceUrls((oData or {}).get('sources'))
        if not aUrls:
            logger.info('wrappers.meinecloud: keine Hoster fuer %s' % sImdb)
        return aUrls
    except Exception as e:
        logger.error('wrappers.meinecloud: %s bei %s' % (e, sUrl))
    return []


def expandHosterList(aRawUrls, referer=''):
    """Hoster-Liste expandieren: meinecloud-URLs durch resolveMeinecloud() ersetzen,
    andere durchreichen. Mit Dedup ueber alle Treffer.

    Dedup vergleicht schema-normalisiert (siehe _fixScheme) — //host/x und
    https://host/x zaehlen als derselbe Hoster. Ausgeliefert wird die
    Original-URL unveraendert; den Schema-Fix macht buildHosterFromUrl().

    Args:
        aRawUrls: Liste roher data-link URLs aus Site-HTML
        referer: optional Referer fuer den meinecloud-Request

    Returns:
        list[str]: deduplizierte Liste aller realen Hoster-URLs
                   (kann protokoll-relativ sein — Caller macht Schema-Fix
                   typischerweise via buildHosterFromUrl()).
    """
    seen = set()
    expanded = []
    for sUrl in aRawUrls or []:
        if not sUrl:
            continue
        # ID-lose Platzhalter sofort verwerfen — VOR dem meinecloud-Zweig:
        # ein leerer mc-Link ('meinecloud.click/movie/') liefe sonst als
        # Netzabruf auf einen sicheren 404 und zeigte dem Nutzer ein
        # Fehlerfenster. Fuer die uebrigen Hoster ist es derselbe Filter,
        # der bisher erst in buildHosterFromUrl() griff.
        if EMPTY_ID_PATTERN.search(sUrl):
            continue
        if isPlatformUrl(sUrl):
            for sResolvedUrl in resolveMeinecloud(sUrl, referer=referer):
                if sResolvedUrl and _fixScheme(sResolvedUrl) not in seen:
                    seen.add(_fixScheme(sResolvedUrl))
                    expanded.append(sResolvedUrl)
        elif _fixScheme(sUrl) not in seen:
            seen.add(_fixScheme(sUrl))
            expanded.append(sUrl)
    return expanded


def buildHosterFromUrl(sUrl, sQuality='720', includeQualitySuffix=True):
    """Aus einer Hoster-URL ein Standard-Hoster-Dict bauen.

    Macht alle Standard-Schritte:
        - YouTube-Trailer skippen
        - Schema-Fix (//host/... -> https:)
        - Hostname-Extract als Name
        - Blocked-Hoster-Check (xStream Settings)
        - Quality-Suffix optional

    Args:
        sUrl: Hoster-URL (kann protokoll-relativ sein)
        sQuality: Quality-String fuer Anzeige + Hoster-Dict
        includeQualitySuffix: True -> 'Name [I][720p][/I]', False -> nur 'Name'

    Returns:
        dict mit 'link', 'name', 'displayedName', 'quality' — oder None
        wenn URL geskippt werden soll (YouTube/Blocked/leer/ungueltig).
    """
    if not sUrl:
        return None
    if 'youtube' in sUrl:
        return None
    if EMPTY_ID_PATTERN.search(sUrl):
        return None
    sUrl = _fixScheme(sUrl)
    try:
        sName = cParser.urlparse(sUrl).split('.')[0].strip()
    except Exception:
        sName = ''
    if not sName:
        return None
    try:
        from resources.lib.config import cConfig
        if cConfig().isBlockedHoster(sName)[0]:
            return None
    except Exception:
        pass
    if includeQualitySuffix:
        displayedName = '%s [I][%sp][/I]' % (sName, sQuality)
    else:
        displayedName = sName
    return {
        'link': sUrl,
        'name': sName,
        'displayedName': displayedName,
        'quality': sQuality,
    }


# Mehrere Quellen einer Folge gehen als EIN Parameter (meinecloud_url) durch die
# Kodi-Runde (getParameterAsUri -> plugin-URL -> parse_qsl). Trenner ist der
# Zeilenumbruch: er steht in keiner Adresse und ueberlebt urlencode/parse_qsl
# als %0A. Ein alter Favorit mit nur einer Adresse entpackt zu einer Liste mit
# einem Eintrag — der Parametername bleibt deshalb bewusst meinecloud_url.
SOURCE_SEPARATOR = '\n'


def packSourceUrls(aUrls):
    """Adressen einer Folge -> ein Parameterwert (Trenner SOURCE_SEPARATOR)."""
    return SOURCE_SEPARATOR.join(sUrl for sUrl in (aUrls or []) if sUrl)


def unpackSourceUrls(sValue):
    """Parameterwert aus packSourceUrls -> Liste der Adressen (leer -> [])."""
    return [sUrl.strip() for sUrl in (sValue or '').split(SOURCE_SEPARATOR) if sUrl.strip()]


def buildMergedHosters(aNativeRawUrls, mcUrls='', referer='', sQuality='720'):
    """Kombiniert native Hoster-URLs mit den meinecloud-Adressen einer Episode zu
    einer deduplizierten Hoster-Dict-Liste ("mc plus deren").

    Hintergrund: Bei Serien die BEIDE Quellen tragen (native DLE-Hoster + meinecloud)
    liefert der native Weg mehrere Hoster pro Episode, meinecloud eine oder mehrere
    Quellen. Diese Funktion legt beide zusammen — native zuerst (i.d.R. mehr/bessere
    Hoster), die meinecloud-Adressen als zusaetzliche Eintraege, Duplikate (gleiche
    finale URL) raus.

    Args:
        aNativeRawUrls: Liste roher data-link URLs aus dem nativen Site-HTML
                        (koennen meinecloud-Wrapper-URLs sein -> werden expandiert,
                        koennen protokoll-relativ sein). Leer/None -> nur meinecloud.
        mcUrls:         meinecloud-Adressen der Episode: Liste ODER der gepackte
                        Parameterwert aus packSourceUrls (String, auch eine
                        einzelne Adresse). Leer -> nur native.
        referer:        Referer fuer den meinecloud-Expand-Request.
        sQuality:       Quality-String fuer die Hoster-Dicts.

    Returns:
        list[dict]: deduplizierte Hoster-Dicts (Schema wie buildHosterFromUrl).
                    Kann leer sein (kein Crash).
    """
    hosters = []
    seen = set()
    # Native zuerst — meinecloud-Wrapper expandieren, interne /vod/-Links filtern.
    for sUrl in expandHosterList(aNativeRawUrls or [], referer=referer):
        # Interne Site-URLs (z.B. /vod/vpn.html) raus — aber NICHT protokoll-relative
        # (//host/...) die sind externe Hoster.
        if sUrl.startswith('/') and not sUrl.startswith('//'):
            continue
        hoster = buildHosterFromUrl(sUrl, sQuality=sQuality, includeQualitySuffix=True)
        if hoster and hoster['link'] not in seen:
            seen.add(hoster['link'])
            hosters.append(hoster)
    # meinecloud-Adressen als zusaetzliche Hoster (String = gepackter Parameter)
    aMcUrls = unpackSourceUrls(mcUrls) if isinstance(mcUrls, str) else list(mcUrls or [])
    for sUrl in aMcUrls:
        hoster = buildHosterFromUrl(sUrl, sQuality=sQuality, includeQualitySuffix=True)
        if hoster and hoster['link'] not in seen:
            seen.add(hoster['link'])
            hosters.append(hoster)
    return hosters


# ══════════════════════════════════════════════
#   meinecloud — Serien
# ══════════════════════════════════════════════

def _apiEpisodes(oTv):
    """'tv'-Objekt der API -> Episoden-Dicts der Sites, sortiert nach Staffel/Folge.

    Folgen ohne Quelle fallen weg (die Sites zeigen nur Abspielbares);
    season/episode sind int, weil die Sites damit rechnen ('%dx%d').
    """
    aEpisodes = []
    for oSeason in (oTv or {}).get('seasons') or []:
        if not isinstance(oSeason, dict):
            continue
        try:
            iSeason = int(oSeason.get('season_number'))
        except (TypeError, ValueError):
            continue
        for oEpisode in oSeason.get('episodes') or []:
            if not isinstance(oEpisode, dict):
                continue
            try:
                iEpisode = int(oEpisode.get('episode_number'))
            except (TypeError, ValueError):
                continue
            aUrls = _sourceUrls(oEpisode.get('sources'))
            if not aUrls:
                continue
            aEpisodes.append({
                'season':  iSeason,
                'episode': iEpisode,
                'title':   cUtil.unescape((oEpisode.get('title') or '').strip()),
                'urls':    aUrls,
            })
    aEpisodes.sort(key=lambda oEp: (oEp['season'], oEp['episode']))
    return aEpisodes


def resolveMeinecloudSerial(sImdbId, referer='', siteHtml=None):
    """Serien-Daten der Plattform zu einer IMDb-ID -> Episoden-Dicts (Ablauf siehe Kopf).

    Args:
        sImdbId:  'tt1234567' oder '1234567'
        referer:  Referer fuer die Plattform-Abrufe (Adresse der Site-Seite)
        siteHtml: Detail-HTML der Site — daraus kommt der Plattform-Host
    Returns:
        [] wenn die Plattform keine Serie zu dieser ID kennt oder nicht
        antwortet (Logzeile, kein Fenster).
    """
    try:
        sImdbId = str(sImdbId or '').strip()
        if sImdbId.startswith('tt'):
            sImdbId = sImdbId[2:]
        if not sImdbId.isdigit():
            logger.info('wrappers.meinecloud_serial: ungueltige IMDb-ID "%s"' % sImdbId)
            return []
        sImdb = 'tt' + sImdbId
        sBase, sToken, sPageUrl = _freshToken(_hostOrder(_discoverPlatformBase(siteHtml)), 'serial', sImdb, referer)
        if not sToken:
            return []
        oData = _embedLinks(sBase, 'tv', sImdb, sToken, sPageUrl)
        if not oData:
            return []
        aEpisodes = _apiEpisodes(oData.get('tv'))
        logger.info('wrappers.meinecloud_serial: %d Folgen fuer %s' % (len(aEpisodes), sImdb))
        return aEpisodes
    except Exception as e:
        logger.error('wrappers.meinecloud_serial: %s bei %s' % (e, sImdbId))
    return []
