# -*- coding: utf-8 -*-
# AnimeToast - Anime-Streaming (Ger Dub / Ger Sub)
#
# Die Seite hat keine einheitliche Serienstruktur. showSeasons() erkennt DREI
# Seitentypen, in dieser Reihenfolge (Merkmale und Fallen stehen an den Funktionen):
#   1 Block  Hoster-Tabs mit S-Raster ("S1:E01-E20", ...), z.B. Bleach. Der S-Button
#            (?link=N) ist eine Block-Seite, deren #player-embed auf einen Arc-Post
#            mit den Einzelfolgen zeigt; erst die Folge traegt im #player-embed die
#            echte Hoster-URL -> ResolveURL. Ein Arc kann MEHRERE Staffeln in einem
#            Tab halten (One Piece Dub: 22 Staffeln in 7 Arcs); der S-Button zeigt dann
#            mitten hinein, _arcButtons() schneidet den Bereich der Staffel aus.
#            Serie -> Staffel -> Hoster -> Folgen -> Stream
#            (showSeasonHosters -> showEpisodes Fall A/B/C -> showHosters)
#   2 AJAX   simple-iframe-player: keine Buttons im HTML, Folgen und Hoster-URL
#            kommen per POST an admin-ajax.php, "Server" = Hoster.
#            Serie -> Server -> Folgen -> Stream (showAjaxServers/-Episodes/-Stream)
#   3 Lain   Hoster-Tabs tragen die Folgen-Buttons direkt, ?link=N rendert den
#            Embed server-seitig. Serie -> Hoster -> Folgen -> Stream
#            (showEpisodes ueber hosterTab -> showHosters). Sonderfall Range-Gateway:
#            ein "Ep.1-25"-Button, dessen Embed auf einen Arc-Post mit den Einzelfolgen
#            verweist. Steht er ALLEIN im Tab (Code Geass), werden die Arc-Folgen direkt
#            eingesetzt; steht er NEBEN anderen Buttons (One Piece: S-Block, Range und
#            Einzelfolgen in einem Tab), wird er ein Ordner auf den Block-Weg (Fall A).
#
# Hinter einem Range-Button liegt nicht immer ein Arc-Post: die Seite verlinkt dort auch
# Ordner-Seiten eines Hosters und Kurzlinks, aus denen nie ein Stream wird, und ganze
# Tabs gehoeren Hostern, die es nicht mehr gibt. Solche Tabs blendet _deadTabs() aus —
# entschieden wird ueber ResolveURL (nimmt es die Adresse?), nicht ueber eine Liste.
#
# Eine Staffelebene im Kodi-Sinn gibt es nicht: bei Typ 1 ist sie das S-Raster,
# sonst die Hoster-Auswahl — deshalb nirgends setSeason().

import re
import ast
import json
import concurrent.futures
import xbmcgui
import resolveurl as resolver

from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.config import cConfig
from resources.lib.gui.gui import cGui

from urllib.parse import quote as _quote, quote_plus as _quotePlus

try:
    from html import unescape as _unescape
except Exception:
    def _unescape(x):
        return x

SITE_IDENTIFIER = 'animetoast'
SITE_NAME = 'AnimeToast'
SITE_ICON = 'animetoast.png'

# Global-Search-Schalter
SITE_GLOBAL_SEARCH = True
if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'false':
    SITE_GLOBAL_SEARCH = False
    logger.info('-> [SitePlugin]: globalSearch for %s is deactivated.' % SITE_NAME)

# Domain Abfrage (Default ohne www; den echten Host mit/ohne www traegt der
# domainCheck selbst ein, er folgt dem Redirect und speichert die Domain).
DOMAIN = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '.domain', 'animetoast.cc')
# Treffer je Suchseite ueber die REST-API. 50 statt 20: die Antwort ist mit
# 21 KB kaum groesser, spart aber eine Folgeseite und einen Abruf (gemessen
# 1,20 s gegen 1,78 s). Die API deckelt bei 100.
API_PER_PAGE = 50
STATUS = cConfig().getSetting('plugin_' + SITE_IDENTIFIER + '_status')
ACTIVE = cConfig().getSetting('plugin_' + SITE_IDENTIFIER)
# Domain ohne fuehrendes www -> Basis fuer host-flexibles Link-Matching + "intern?"-Checks
# (www/non-www und Domain-Wechsel automatisch, nur das Setting aendern).
_BASE = re.sub(r'^www\.', '', DOMAIN)
_BASE_RE = re.escape(_BASE)

URL_MAIN = 'https://' + DOMAIN + '/'
URL_INDEX_DUB = URL_MAIN + 'a-z-index-dub/'
URL_INDEX_SUB = URL_MAIN + 'a-z-index-sub/'
URL_LATEST = URL_MAIN + 'latest-uploads/'

# --- Patterns ---------------------------------------------------------------
# Listing mit Thumb (Startseite, Latest, Season-Archiv; HTML-Suche nur als Fallback
# zur API): Poster-Anchor + img -> (url, titel, thumb)
_RE_ENTRY = re.compile(
    r'<a\s+href="(https?://[^/"]*%s/[a-z0-9][a-z0-9-]+/)"\s+title="([^"]+)">\s*<img[^>]+src="([^"]+)"' % _BASE_RE)
# A-Z-Index: flaches <li><a href="SLUG/">Titel</a>
_RE_AZ = re.compile(
    # Der Pfad darf neben Kleinbuchstaben/Ziffern/Bindestrich auch '%' und '_' tragen:
    # Titel mit Sonderzeichen stehen URL-kodiert in der Adresse ("C³" wird zu "c%c2%b3",
    # ebenso ∞ ♥ ★ ½ Ψ), und ein Titel fuehrt einen Unterstrich ("D_Cide Traumerei").
    # Ohne die beiden Zeichen fielen sie stumm aus dem Index — 24 im Sub-, 5 im Dub-Index.
    r'<li>\s*<a\s+href="(https?://[^/"]*%s/[a-z0-9][a-z0-9%%_-]+/)">\s*([^<]+?)\s*</a>' % _BASE_RE)
# A-Z-Index: die Seite gliedert ihn selbst in Abschnitte und beschriftet sie
# (0-9, A ... Z, #). Wir uebernehmen Gliederung UND Beschriftung von dort, statt
# eine eigene Buchstabenliste zu erfinden.
_RE_AZ_SECTION = re.compile(
    r'<div[^>]*class="letter-section"[^>]*id="letter-([^"]+)"[^>]*>\s*'
    r'<h2[^>]*>\s*<span>\s*([^<]+?)\s*</span>', re.DOTALL)
# Folgeseite (wp-pagenavi). Gemessen 02.09.2026: die Seite rendert auf keiner der hier
# geladenen Grid-Seiten eine Blaetter-Leiste — Latest sind feste 75 Eintraege (page/2
# liefert dieselben), Startseite und Season-Archive sind komplett. Nur die HTML-Suche
# (Fallback) hat Folgeseiten, und die belegt die Seite allein per <link rel="next"> im
# Head (siehe _RE_NEXT_HEAD) — die API-Suche blaettert ueber X-WP-TotalPages.
_RE_NEXT = re.compile(r'<a[^>]+class="[^"]*nextpostslink[^"]*"[^>]*href="([^"]+)"')
# Rueckfall nur fuer die HTML-Suche: die Seite rendert die Leiste dort nicht an jedem Tag
# (02.09.2026 fehlte sie, 04.09.2026 stand sie wieder), die Folgeseite steht aber immer als
# <link rel="next"> im Head (/search/<begriff>/page/N/, gemessen: liefert 20 weitere Treffer).
_RE_NEXT_HEAD = re.compile(r'<link[^>]+rel="next"[^>]+href="([^"]+)"')
# Hoster-Tabs -> (tabIndex, name)
_RE_TAB = re.compile(r'<a\s+data-toggle="tab"\s+href="#multi_link_tab(\d+)">\s*([^<]+?)\s*</a>')
# multilink-btn Buttons -> (href, innererInhalt)
_RE_BTN = re.compile(r'<a\s+class="multilink-btn[^"]*"\s*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
# ?link=N aus href
_RE_LINKNUM = re.compile(r'[?&]link=(\d+)')
# Player-Embed: echte Hoster-URL (Voe als <a href>, PlayN/Dood/Mp4 als <iframe src>)
_RE_EMBED = re.compile(r'id="player-embed"[^>]*>\s*(?:<a\s+href|<iframe[^>]*?\ssrc)="([^"]+)"')
# Tab-Pane-Splitter
_RE_TABSPLIT = re.compile(r'id="multi_link_tab(\d+)"')

# Zweiter Seiten-Typ: simple-iframe-player (Episoden/URLs via admin-ajax.php)
_RE_IFRAME_PLAYER = re.compile(r'class="simple-iframe-player"\s+data-title="([^"]+)"')
_RE_NONCE = re.compile(r'iframe_loader\s*=\s*\{[^}]*?"nonce":"([^"]+)"')
_RE_SERVER_SEL = re.compile(r'<select[^>]*class="server-select"[^>]*>(.*?)</select>', re.DOTALL)
_RE_OPTION = re.compile(r'<option\s+value="(\d+)"[^>]*>\s*([^<]*?)\s*</option>')

# Slugs, die in der A-Z-Liste KEINE Serien sind (Menue/Navi)
_AZ_SKIP = ('a-z-index', 'wochenplan', 'season-', 'latest-upload', 'privacy',
            'agb', 'index-', 'category', 'genre', 'datenschutz', 'impressum')

# Hoster-Tabs, die hier ausgeblendet werden (normalisierte Namen). Aktuell leer:
# PlayN/waaw bleibt drin, auch wenn dessen Captcha ueber ResolveURL evtl. nicht
# durchgeht (bewusste Entscheidung). Liste fuer kuenftige Faelle behalten — Tabs
# OHNE spielbares Ziel braucht sie nicht, die findet _deadTabs() selbst.
_SKIP_HOSTERS = ()


# --- Helfer -----------------------------------------------------------------
def _clean(s):
    # Tags raus, HTML-Entities aufloesen, Whitespace zusammenfassen.
    s = re.sub(r'<[^>]+>', '', s)
    s = _unescape(s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _hostOf(sUrl):
    # Hostname einer Adresse, klein und OHNE fuehrendes "www.". Das "www." muss weg:
    # isBlockedHoster fragt ResolveURL per Teilstring ("www.host.tld" steckt in keinem
    # "host.tld" -> gaelte als unbekannt), und als Anzeigename ergab es "Www".
    host = re.sub(r'^(?:https?:)?//', '', sUrl or '').split('/', 1)[0].lower()
    return re.sub(r'^www\.', '', host)


def _hosterName(sUrl):
    # Anzeigename aus der Domain (voe.sx -> "Voe"). Nur kosmetisch: aufgeloest wird
    # ueber die Adresse, und der Blocked-Check laeuft ueber den Host (_hostOf), nicht
    # ueber diesen Namensfetzen — als Teilstring rutschten sonst Zufallstreffer durch.
    host = _hostOf(sUrl)
    part = host.split('.')[0] if host else 'Hoster'
    return part.title()


def _normHoster(s):
    # Hoster-Namen vergleichbar machen: "Voe"/"VOE"/"Voe.sx" -> "voe". Noetig, weil
    # die Tab-Reihenfolge auf Serie und Arc abweicht -> Rueckfall in _arcButtons, wenn
    # die Link-Nummer des Zeigers im Arc fehlt, und fuer _SKIP_HOSTERS.
    s = (s or '').lower().strip()
    s = re.sub(r'\.(sx|com|net|to|sb|io|cc|me|stream|club|pro|live|fun|si|ws)$', '', s)
    return re.sub(r'[^a-z0-9]', '', s)


def _splitTabs(sHtml):
    # {tabIndex: chunkHtml} - Inhalt jeder Hoster-Tab-Pane. Split am Marker,
    # Chunk = alles bis zum naechsten Marker (multilink-btn gibt es nur hier).
    parts = _RE_TABSPLIT.split(sHtml)
    panes = {}
    for i in range(1, len(parts) - 1, 2):
        try:
            panes[int(parts[i])] = parts[i + 1]
        except ValueError:
            continue
    return panes


def _buttons(sChunk):
    # Liste (href, linkNum, label) aller multilink-btn im Chunk.
    out = []
    for href, inner in _RE_BTN.findall(sChunk):
        m = _RE_LINKNUM.search(href)
        if not m:
            continue
        out.append((href, int(m.group(1)), _clean(inner)))
    return out


def _requestUrl(sUrl):
    """Kodiert unmittelbar vor dem Abruf (Muster wie serienstream und movie2k).

    Die Seite verlinkt Titel mit Sonderzeichen kodiert im Pfad
    ('/c%c2%b3-cube-x-cursed-x-curious-ger-sub/'). Der Parameterweg jagt jeden Wert
    durch unquote_plus, aus '%c2%b3' wird dabei wieder '\u00b3' — und urllib bricht
    beim Abruf mit einem UnicodeEncodeError ab, der Nutzer sieht einen Skriptfehler.
    Betroffen sind 23 Titel im Sub- und 5 im Dub-Index (Ranma \u00bd, Cat's\u2665Eye,
    Madoka\u2606Magica ...). Kodiert wird NIE im Parameter, sondern nur hier; '%'
    bleibt in der safe-Liste, damit bereits kodierte Adressen nicht doppelt kodiert
    werden.
    """
    return _quote(sUrl, safe=':/?&=%#+')


def _slugOf(sUrl):
    # Erstes Pfad-Segment nach dem Host, domain-unabhaengig.
    m = re.search(r'https?://[^/]+/([^/?#]+)', sUrl or '')
    return m.group(1) if m else ''


def _cover(sHtml):
    # Serien-Poster aus dem og:image-Meta (WordPress/Yoast). Beide Attribut-
    # Reihenfolgen abdecken (property vor content und umgekehrt), sonst ''.
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', sHtml or '', re.I)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', sHtml or '', re.I)
    return m.group(1) if m else ''


def _embedUrl(sHtml):
    # Hoster-URL aus #player-embed (a href oder iframe src), sonst ''.
    m = _RE_EMBED.search(sHtml)
    return m.group(1) if m else ''


def _epNum(sLabel):
    # Episodennummer aus einem Folgen-Label, z.B. "Ep. 12" -> 12 (erste Zahl).
    m = re.search(r'(\d+)', sLabel or '')
    return int(m.group(1)) if m else None


def _seasonRange(sLabel):
    # Episoden-Range aus einem S-Block-Label, z.B. "S2:E21-41" -> (21, 41). Format
    # auf der Seite uneinheitlich (E-Prefix mal da, mal nicht) -> erste/letzte Zahl
    # NACH dem "Sn:". Die laufende Staffel fuehrt die Seite mit offenem Ende
    # ("S22:E1086-") -> (1086, None). Nicht erkennbar -> (None, None).
    m = re.search(r'S\d+:\D*(\d+)\D+(\d+)', sLabel or '')
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r'S\d+:\D*(\d+)\D*$', sLabel or '')
    return (int(m.group(1)), None) if m else (None, None)


def _isGatewayLabel(sLabel):
    # Beschriftung eines Buttons, der fuer MEHRERE Folgen steht: S-Block ("S21:E892-1072")
    # oder Bereich ("Ep.1-25", "E1073-1116"). Was dahinter liegt, zeigt erst sein Embed.
    return bool(re.match(r'S\d', sLabel or '') or re.search(r'\d+\s*-\s*\d+', sLabel or ''))


def _isPlayable(sUrl):
    """Kann aus dieser Embed-Adresse ein Stream werden? True / False / None (kein Befund).

    Intern (Arc-/Block-Link) zaehlt als spielbar — _deadTabs folgt einem Arc-Link vorher
    selbst einen Schritt; was danach noch intern ist, bleibt unentschieden und damit stehen.
    Extern entscheidet ResolveURL, und zwar an der ADRESSE, nicht nur an der Domain:
    die Ordner-Seite eines Hosters traegt eine bekannte Domain und ist trotzdem kein
    Video. None heisst "nichts gesehen" (Abruf gescheitert, kein Embed) — daraus wird
    nie ein Ausblenden.
    """
    if not sUrl:
        return None
    if _BASE in sUrl:
        return True
    if cConfig().isBlockedHoster(_hostOf(sUrl))[0]:
        return False
    try:
        return bool(resolver.HostedMediaFile(url=sUrl).valid_url())
    except Exception:
        return None


def _deadTabs(dTabBtns):
    """Tabs, hinter denen NACHWEISLICH nichts Spielbares liegt -> set der Schluessel.

    dTabBtns: {schluessel: [(href, linkNum, label), ...]}. Geprueft wird der ERSTE
    Button jedes Tabs (ein paralleler Durchgang); nur wo der tot ist, in einem zweiten
    Durchgang auch der LETZTE. Ausgeblendet wird erst, wenn beide tot sind — ein Tab
    mit toten und lebenden Folgen bleibt stehen (One Piece Dub "V": vorn tote Kurzlinks,
    hinten spielbare Folgen).
    Zeigt ein Button auf einen internen Arc-Post (Range-Gateway), wird EIN Schritt gefolgt
    (wie in showHosters) und die Folge DORT bewertet — sonst blieben Tabs stehen, deren Arc
    nur tote Folgen traegt (ToastP). "Letzter Button" ist bei einem Gateway mit einem einzigen
    Button der letzte Button des Arc-Tabs.
    Gemessen 20.09.2026 ueber die ganze Seite: die Regel trifft 983 Tabs auf 820 Serien-Seiten
    (abgeschaltete Hoster, Ordner-Seiten, Kurzlinks; 28 davon erst hinter einem Arc), der
    zweite Durchgang rettet zwei gemischte Tabs; bei den gaengigen Hostern stimmten erster
    und letzter Button in 1.596 von 1.596 gemessenen Tabs ueberein.
    Hilfsabrufe: still (ignoreErrors), und ein gescheiterter Abruf blendet nichts aus.
    Die Threads HOLEN nur; bewertet wird danach im Hauptthread, damit ResolveURL und
    die Kodi-Einstellungen nicht aus Worker-Threads angefasst werden.
    """
    def _fetch(sHref):
        # -> (Embed, Arc-Adresse, Arc-HTML); die beiden letzten nur, wenn gefolgt wurde.
        try:
            sEmbed = _embedUrl(cRequestHandler(_requestUrl(sHref), ignoreErrors=True).request() or '')
            if sEmbed and _BASE in sEmbed:
                sArcHtml = cRequestHandler(_requestUrl(sEmbed), ignoreErrors=True).request() or ''
                return _embedUrl(sArcHtml), sEmbed, sArcHtml
            return sEmbed, '', ''
        except Exception:
            return '', '', ''

    def _round(dUrls):
        if not dUrls:
            return {}
        aKeys = list(dUrls)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(aKeys))) as oPool:
            aFound = list(oPool.map(_fetch, [dUrls[k] for k in aKeys]))
        return dict((k, (_isPlayable(f[0]), f[1], f[2])) for k, f in zip(aKeys, aFound))

    dFirst = _round(dict((k, b[0][0]) for k, b in dTabBtns.items() if b))
    aSuspect = [k for k, v in dFirst.items() if v[0] is False]
    dLastUrls = {}
    for k in aSuspect:
        if len(dTabBtns[k]) > 1:
            dLastUrls[k] = dTabBtns[k][-1][0]
        elif dFirst[k][1]:
            aArcBtns, iPos = _arcPane(dFirst[k][2], dFirst[k][1])
            if aArcBtns and len(aArcBtns) > 1:
                dLastUrls[k] = aArcBtns[-1][0]
    dLast = _round(dLastUrls)
    return set(k for k in aSuspect if k not in dLast or dLast[k][0] is False)


def _arcPane(sArcHtml, sArcUrl, sHosterName=''):
    """Tab eines Arc-Posts, auf den ein Gateway zeigt -> (Buttons des Tabs, Position des Ziels).

    Gewaehlt wird ueber die LINK-NUMMER aus sArcUrl (?link=N) — sie ist der Zeiger der Seite
    selbst und trifft auch, wo ein Arc zwei Tabs desselben Hosters fuehrt (zwei Uploads, Boku
    no Hero Academia). Nur wenn die Nummer im Arc fehlt, entscheidet wie frueher der
    Hoster-Name (die Tab-Reihenfolge weicht zwischen Serie und Arc ab). Gemessen 20.09.2026
    ueber alle 732 Gateways: Nummer und Name treffen 726-mal denselben Tab.
    Kein Treffer -> (None, 0).
    """
    panes = _splitTabs(sArcHtml)
    m = _RE_LINKNUM.search(sArcUrl or '')
    if m:
        iLink = int(m.group(1))
        for idx in sorted(panes.keys()):
            aBtns = _buttons(panes[idx])
            aNums = [b[1] for b in aBtns]
            if iLink in aNums:
                return aBtns, aNums.index(iLink)
    if sHosterName:
        for i, n in _RE_TAB.findall(sArcHtml):
            if int(i) in panes and _normHoster(_clean(n)) == _normHoster(sHosterName):
                return _buttons(panes[int(i)]), 0
    return None, 0


def _arcButtons(sArcUrl, sHosterName, sLabel='', bAllIfNoMatch=False):
    """Folgen-Buttons hinter einem Gateway (Range- oder S-Block-Button der Serien-Seite).

    sArcUrl ist das Ziel des Gateways: ein Arc-Post samt ?link=N; den Tab waehlt _arcPane
    (Link-Nummer, sonst Hoster-Name).

    Ausschnitt: gelistet wird AB dem Ziel-Button. Bei einem S-Block-Label mit Bereich
    ("S07:E196-228" = 33 Folgen) endet die Liste nach so vielen Folgen — ein Arc kann
    mehrere Staffeln in einem Tab halten. Alle 124 S-Buttons der Seite geprueft: die
    Laenge aus dem Label trifft exakt den Zeiger der naechsten Staffel. Bei einfachen
    Bereichen ("Ep.1-12+OVA") wird NICHT gerechnet, sonst fiele der Zusatz weg.
    Die Beschriftungen bleiben die des Arcs ("Ep. 53"), umnummeriert wird nichts.
    """
    arcHtml = cRequestHandler(_requestUrl(sArcUrl)).request()
    aBtns, iPos = _arcPane(arcHtml, sArcUrl, sHosterName)
    if aBtns is None:
        return _buttons(arcHtml) if bAllIfNoMatch else []
    iEnd = len(aBtns)
    lo, hi = _seasonRange(sLabel)
    if lo is not None and hi is not None and hi >= lo:
        iEnd = min(iEnd, iPos + (hi - lo + 1))
    return aBtns[iPos:iEnd]


# --- Menue ------------------------------------------------------------------
def load():
    logger.info('Load %s' % SITE_NAME)
    xbmcgui.Window(10000).clearProperty('xstream.%s.lastSearchText' % SITE_IDENTIFIER)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30554), SITE_IDENTIFIER, 'showNews'))
    cGui().addFolder(cGuiElement('Seasons', SITE_IDENTIFIER, 'showSeasonArchive'))
    cGui().addFolder(cGuiElement('Index', SITE_IDENTIFIER, 'showIndexMenu'))
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30520), SITE_IDENTIFIER, 'showSearch'))
    cGui().setEndOfDirectory()


def showIndexMenu():
    # 'Index' -> Untermenue Ger Sub / Ger Dub (beide oeffnen den A-Z-Index via showAZ).
    # Reihenfolge wie in der Navigation der Seite: dort steht "A-Z Index Sub" vor "Dub".
    params = ParameterHandler()
    params.setParam('sUrl', URL_INDEX_SUB)
    cGui().addFolder(cGuiElement('Ger Sub', SITE_IDENTIFIER, 'showAZ'), params)
    params.setParam('sUrl', URL_INDEX_DUB)
    cGui().addFolder(cGuiElement('Ger Dub', SITE_IDENTIFIER, 'showAZ'), params)
    cGui().setEndOfDirectory()


def showNews():
    # Kategorie 'Neues': Kuerzlich hinzugefuegt (latest-uploads)
    # + Update/Upgrade (Startseite; deren Abschnitte heissen dort "Letzte Updates" und
    # "Dub Upgrade"). Beide nutzen das normale Grid.
    params = ParameterHandler()
    params.setParam('sUrl', URL_LATEST)
    cGui().addFolder(cGuiElement(cConfig().getLocalizedString(30562), SITE_IDENTIFIER, 'showEntries'), params)
    params.setParam('sUrl', URL_MAIN)
    cGui().addFolder(cGuiElement('Update/Upgrade', SITE_IDENTIFIER, 'showEntries'), params)
    cGui().setEndOfDirectory()


# --- Listen -----------------------------------------------------------------
def _searchNorm(sText):
    """Vergleichsform: Satzzeichen werden zu Leerzeichen, Mehrfach-Leerzeichen fallen weg.

    Sonst findet der Wortgrenzen-Vergleich Titel nicht, die die Seite mit
    Doppelpunkt oder Bindestrich schreibt — "re zero" traf "Re:Zero" nicht.
    """
    return re.sub(r'\s+', ' ', re.sub(r'[^0-9A-Za-zÀ-ÿ]+', ' ', sText or '')).strip()


def _titleStem(sTitle):
    """Serienstamm eines Eintragstitels — Staffel- und Fassungszusatz abgeschnitten.

    animetoast fuehrt jede Staffel und jede Fassung als eigenen Eintrag
    ("Shingeki no Kyojin Season 2 Ger Dub"). Der Stamm bindet sie wieder
    zusammen, damit der Suchfilter unten nicht einzelne Staffeln herausreisst.
    """
    sStem = re.sub(r'\s+(Ger\s+(Dub|Sub)|Staffel\s*\d+|Season\s*\d+|\d+(st|nd|rd|th)\s+Season'
                   r'|Movie|OVA|Special)\b.*$', '', sTitle or '', flags=re.I)
    return _searchNorm(sStem).lower()


def _searchHit(sSearchText, sTitle, sBlock):
    """Trifft der Suchbegriff diesen Eintrag wirklich?

    Die WordPress-Suche der Seite durchsucht den ganzen Beitrag als Teilstring.
    Deshalb spuelt sie bei kurzen Begriffen Unmengen hoch, die nichts mit dem
    Gesuchten zu tun haben: "lain" trifft jede Beschreibung mit "villainess"
    (gemessen 2 richtige unter 20), "ai" traf 20 von 20 falsch.

    Geprueft wird deshalb auf WORTGRENZE — und zwar im GANZEN Eintragsblock,
    nicht nur im Titel. Der Block fuehrt neben der deutschen Beschreibung auch
    die Alternativtitel (japanisch, englisch, chinesisch). Nur im Titel zu
    suchen wuerde die halbe Seite unbrauchbar machen: animetoast fuehrt
    romanisiert japanische Titel, "attack on titan" stand in 0 von 14 Titeln
    und "koenig" in 0 von 20 — ueber den Block sind es 8 bzw. 3 echte Treffer.
    """
    sNeedle = _searchNorm(sSearchText)
    if not sNeedle:
        return True
    return bool(re.search(r'\b%s\b' % re.escape(sNeedle), _searchNorm(sBlock), re.I))


def _filterSearch(sSearchText, aEntries):
    """Suchtreffer filtern, ohne Staffeln derselben Serie zu verlieren.

    Zweiter Durchgang ueber den Serienstamm: nicht jede Staffel fuehrt den
    Alternativtitel im Text. Bei "attack on titan" steht "Attack on Titan" nur
    in den Bloecken von Staffel 1 und den Final Seasons — Season 2 und 3 waeren
    ohne diesen Durchgang herausgefallen, obwohl es dieselbe Serie ist
    (gemessen 8 statt 14 Treffer). Ueber vierzehn gepruefte Begriffe holt der
    Stamm-Durchgang genau einen Eintrag zusaetzlich herein, und auch der gehoert
    zur selben Serie.

    aEntries: Liste von (sUrl, sTitle, sThumb, sBlock).
    """
    aHits = [e for e in aEntries if _searchHit(sSearchText, e[1], e[3])]
    if not aHits:
        return aHits
    aStems = {_titleStem(e[1]) for e in aHits}
    aStems.discard('')
    return [e for e in aEntries if e in aHits or _titleStem(e[1]) in aStems]


def showEntries(entryUrl=False, sGui=False, sSearchText=False):
    # Grid-Listing mit Thumbnails (Startseite, Latest, Season-Archiv; HTML-Suche nur
    # als Fallback zur API). Weiter-Eintrag nur bei wp-pagenavi-Link (siehe _RE_NEXT).
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl:
        entryUrl = params.getValue('sUrl')
    if not sSearchText:
        # Beim Klick auf "Naechste Seite" ruft Kodi die Funktion neu auf, der
        # Suchbegriff steht dann nur noch im Parameter. Ohne ihn liefe Seite 2
        # ungefiltert und zeigte wieder die Volltext-Treffer der Seite.
        sSearchText = params.getValue('sSearchText') or False
    oRequest = cRequestHandler(_requestUrl(entryUrl), ignoreErrors=(sGui is not False))
    if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'true':
        oRequest.cacheTime = 60 * 60 * 6
    sHtmlContent = oRequest.request()
    aResult = _RE_ENTRY.findall(sHtmlContent)
    if not aResult:
        if not sGui:
            oGui.showInfo()
        return
    if sSearchText:
        # Je Eintrag den zugehoerigen Markup-Block mitnehmen — dort stehen
        # Beschreibung und Alternativtitel, auf denen der Filter arbeitet.
        aBlocks = re.split(r'(?=<div id="post-\d+")', sHtmlContent)
        aWithBlock = []
        for sUrl, sTitle, sThumb in aResult:
            sBlock = next((b for b in aBlocks if sUrl in b), sTitle)
            # Vor der Blaetter-Leiste abschneiden und auf Eintragslaenge kappen: die
            # Leiste steht im LETZTEN Block und traegt die Adresse der Folgeseite, in
            # der der SUCHBEGRIFF selbst steckt ("?s=lain&paged=2"). Ohne den Schnitt
            # zieht jeder Eintrag, dessen Adresse dort mitsteht, faelschlich einen
            # Treffer — bei "lain" waren es 4 statt 2.
            sBlock = re.split(r'wp-pagenavi|nextpostslink', sBlock)[0][:6000]
            aWithBlock.append((sUrl, sTitle, sThumb, sBlock))
        aResult = [(u, t, th) for u, t, th, _ in _filterSearch(sSearchText, aWithBlock)]
        if not aResult:
            if not sGui:
                oGui.showInfo()
            return
    total = len(aResult)
    seen = set()
    for sUrl, sTitle, sThumb in aResult:
        if sUrl in seen:
            continue
        seen.add(sUrl)
        sTitle = _clean(sTitle)
        oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        oGuiElement.setThumbnail(sThumb)
        params.setParam('entryUrl', sUrl)
        params.setParam('sName', sTitle)
        oGui.addFolder(oGuiElement, params, True, total)
    if not sGui:
        m = _RE_NEXT.search(sHtmlContent)
        if not m and sSearchText:
            m = _RE_NEXT_HEAD.search(sHtmlContent)
        if m:
            params.setParam('sUrl', m.group(1))
            if sSearchText:
                params.setParam('sSearchText', sSearchText)
            oGui.addNextPage(SITE_IDENTIFIER, 'showEntries', params)
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()


def _azSections(sHtmlContent):
    """Buchstaben-Abschnitte des Index in Seitenreihenfolge: [(key, Anzeigename, Inhalt)].

    Der Inhalt wird auf die <ul> des Abschnitts begrenzt: hinter dem LETZTEN Abschnitt
    steht die Sidebar "Zuletzt Hinzugefuegt" (7 Links, je nach Tag auch Titel des
    anderen Index), deren Links sonst mit in die Titelliste rutschen — wie viele,
    haengt vom Tagesinhalt ab (gemessen 3 bis 5 im Sub-, 2 im Dub-Index).
    """
    aTreffer = list(_RE_AZ_SECTION.finditer(sHtmlContent))
    aOut = []
    for i, m in enumerate(aTreffer):
        iEnde = aTreffer[i + 1].start() if i + 1 < len(aTreffer) else len(sHtmlContent)
        sBlock = sHtmlContent[m.end():iEnde]
        # Nur die <ul> des Abschnitts (Sidebar-Grenze, siehe Docstring).
        mList = re.search(r'<ul[^>]*>(.*?)</ul>', sBlock, re.DOTALL)
        aOut.append((m.group(1), _clean(m.group(2)), mList.group(1) if mList else ''))
    return aOut


def _azTitles(sBlock, seen):
    """Titel eines Abschnitts als (url, name); Menue-/Navi-Links und Dubletten raus."""
    aItems = []
    for sUrl, sTitle in _RE_AZ.findall(sBlock):
        slug = _slugOf(sUrl)
        # Menue- und Navi-Adressen beginnen MIT diesen Kennungen (season-winter-2026,
        # a-z-index-sub, latest-uploads). Frueher wurde irgendwo im Slug gesucht — damit
        # traf "season-" auch jeden Serientitel, der eine zweite Staffel fuehrt
        # ("3d-kanojo-real-girl-2nd-season-ger-sub"). Im Sub-Index sind so 226 Titel
        # unsichtbar geworden, im Dub-Index 116, fast durchweg Folgestaffeln.
        if any(slug.startswith(b) for b in _AZ_SKIP) or sUrl in seen:
            continue
        seen.add(sUrl)
        sName = _clean(sTitle)
        if not sName:
            # Die Seite fuehrt im "#"-Abschnitt Beitraege ganz ohne Linktext (im Ger-Sub-
            # Index ueber 500). Sie sind dort auch im Browser unsichtbar, und ein Name
            # existiert nirgends: die Detailseiten melden im <title> "Ohne Titel",
            # og:title und twitter:title sind leer, einen Player-Titel gibt es nicht —
            # es laesst sich also nichts nachladen. Deshalb werden sie ausgelassen,
            # statt hunderte namenlose Zeilen ins Menue zu schreiben.
            continue
        aItems.append((sUrl, sName))
    # Sortiert wird NICHT: die Liste bleibt in der Reihenfolge der Seite (Jacks
    # Entscheidung). Die Seite ordnet nach der ADRESSE, nicht nach dem Titel — Namen
    # mit Sonderzeichen tragen die im Slug kodiert ("c%c2%b3-cube-...") und stehen
    # deshalb am Ende ihres Buchstabens ("C³ - Cube x Cursed" hinter "Cyberpunk",
    # "I★Chu" hinter "Izure"). Das ist auf der Website genauso und bleibt so.
    return aItems


def showAZ(entryUrl=False, sGui=False, sSearchText=False):
    """A-Z-Index: erst die Buchstabenauswahl der Seite, dann die Titel des Abschnitts.

    Frueher wurde der ganze Index zu EINER Liste zusammengezogen — bei "Ger Sub" sind
    das ueber 2700 Eintraege, und der "#"-Abschnitt landete als Schwanz dahinter, wo ihn
    praktisch niemand findet. Die Seite gliedert selbst nach Buchstaben und beschriftet
    die Abschnitte; genau diese Gliederung wird hier uebernommen, damit sie sich
    mitaendert, wenn die Seite ihre Einteilung anpasst.
    """
    oGui = sGui if sGui else cGui()
    params = ParameterHandler()
    if not entryUrl:
        entryUrl = params.getValue('sUrl')
    sLetter = params.getValue('sLetter')
    oRequest = cRequestHandler(_requestUrl(entryUrl), ignoreErrors=(sGui is not False))
    if cConfig().getSetting('global_search_' + SITE_IDENTIFIER) == 'true':
        oRequest.cacheTime = 60 * 60 * 6
    sHtmlContent = oRequest.request()
    aSections = _azSections(sHtmlContent)
    if not aSections:
        if not sGui:
            oGui.showInfo()
        return

    # Ohne gewaehlten Abschnitt die Buchstabenauswahl zeigen. In der globalen Suche
    # (sGui) wird uebersprungen: dort werden Titel erwartet, keine Menueebene.
    if not sLetter and not sGui:
        for sKey, sName, sBlock in aSections:
            # Gezaehlt wird nur, um leere Abschnitte zu ueberspringen — die Zahl steht
            # bewusst NICHT im Label: sie waere hier zwar gratis (die Seite liefert den
            # ganzen Index auf einmal), aber andere Seiten mit Volllisten haetten sie
            # dann genauso zu Recht, und das wollen wir nicht anfangen.
            if not _azTitles(sBlock, set()):
                continue
            p = ParameterHandler()
            p.setParam('sUrl', entryUrl)
            p.setParam('sLetter', sKey)
            oGui.addFolder(cGuiElement(sName, SITE_IDENTIFIER, 'showAZ'), p, True, len(aSections))
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()
        return

    seen = set()
    items = []
    for sKey, sName, sBlock in aSections:
        if sLetter and sKey != sLetter:
            continue
        items += _azTitles(sBlock, seen)
    if not items:
        if not sGui:
            oGui.showInfo()
        return
    total = len(items)
    for sUrl, sTitle in items:
        oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        params.setParam('entryUrl', sUrl)
        params.setParam('sName', sTitle)
        oGui.addFolder(oGuiElement, params, True, total)
    if not sGui:
        oGui.setView('tvshows')
        oGui.setEndOfDirectory()


# --- Season-Archiv (Jahr -> Season -> Grid) ---------------------------------
# Die Season-Navi steckt komplett im Mega-Menue der Startseite (server-gerendert);
# wir parsen sie live -> neue Seasons erscheinen von selbst, nichts hardgecodet.
# Jede Season ist eine eigene Archiv-Seite mit demselben Grid wie 'Update/Upgrade'.
_RE_SEASON = re.compile(r'%s/season-(winter|fruehling|sommer|herbst)-(\d{4})/' % _BASE_RE)
_SEASON_LABELS = (('winter', 'Winter'), ('fruehling', 'Frühling'),
                  ('sommer', 'Sommer'), ('herbst', 'Herbst'))


def _seasonMap():
    # {jahr(int): set(saison-slug)} aus der Startseiten-Navi.
    sHtmlContent = cRequestHandler(URL_MAIN).request()
    out = {}
    for saison, jahr in _RE_SEASON.findall(sHtmlContent):
        out.setdefault(int(jahr), set()).add(saison)
    return out


def showSeasonArchive():
    # Ebene 1: Jahre, neueste zuerst.
    oGui = cGui()
    seasons = _seasonMap()
    if not seasons:
        oGui.showInfo()
        oGui.setEndOfDirectory()
        return
    params = ParameterHandler()
    years = sorted(seasons.keys(), reverse=True)
    total = len(years)
    for jahr in years:
        oGuiElement = cGuiElement(str(jahr), SITE_IDENTIFIER, 'showSeasonArchiveYear')
        params.setParam('seasonYear', str(jahr))
        oGui.addFolder(oGuiElement, params, True, total)
    oGui.setView('seasons')
    oGui.setEndOfDirectory()


def showSeasonArchiveYear():
    # Ebene 2: vorhandene Seasons des Jahres (Winter -> Fruehling -> Sommer -> Herbst).
    # Jede Season -> showEntries auf der Season-Archiv-Seite (Grid wie 'Update/Upgrade').
    params = ParameterHandler()
    jahr = params.getValue('seasonYear')
    oGui = cGui()
    have = _seasonMap().get(int(jahr), set()) if jahr else set()
    rows = [(slug, label) for slug, label in _SEASON_LABELS if slug in have]
    if not rows:
        oGui.showInfo()
        oGui.setEndOfDirectory()
        return
    total = len(rows)
    for slug, label in rows:
        oGuiElement = cGuiElement('%s %s' % (label, jahr), SITE_IDENTIFIER, 'showEntries')
        oGuiElement.setMediaType('season')
        params.setParam('sUrl', '%sseason-%s-%s/' % (URL_MAIN, slug, jahr))
        oGui.addFolder(oGuiElement, params, True, total)
    oGui.setView('seasons')
    oGui.setEndOfDirectory()


# --- Serie -> Seitentyp -> Staffel/Hoster -> Folgen (Typ 1 und 3; Typ 2 unten) --
def showSeasons():
    # Seitentyp erkennen (Reihenfolge wie im Dateikopf): erst das S-Raster eines
    # Block-Hosters (Typ 1), sonst simple-iframe-player (Typ 2), sonst die Tabs
    # mit Folgen-Buttons (Typ 3, Lain).
    params = ParameterHandler()
    entryUrl = params.getValue('entryUrl')
    sName = params.getValue('sName')
    sHtmlContent = cRequestHandler(_requestUrl(entryUrl)).request()
    panes = _splitTabs(sHtmlContent)
    cover = _cover(sHtmlContent)
    params.setParam('sCover', cover)  # Serien-Poster nach unten durchreichen

    seasonBtns = []
    for idx in sorted(panes.keys()):
        blockBtns = [b for b in _buttons(panes[idx]) if re.match(r'S\d', b[2])]
        if len(blockBtns) >= 2:
            seasonBtns = blockBtns
            break

    # Kein Staffel-Raster gefunden.
    if not seasonBtns:
        # Zweiter Seiten-Typ: simple-iframe-player (AJAX) -> Server = Hoster.
        mPlayer = _RE_IFRAME_PLAYER.search(sHtmlContent)
        if mPlayer:
            showAjaxServers(entryUrl, sHtmlContent, mPlayer.group(1), sName)
            return
        # Dritter Typ (Lain): Tabs tragen die Episoden-Buttons direkt (kein Arc-Post,
        # ?link=N rendert den Embed server-seitig). -> Hoster = Tabs, je Hoster die
        # Folgen DES TABS.
        tabHosters = {}
        for i, n in _RE_TAB.findall(sHtmlContent):
            tabHosters[int(i)] = _clean(n)
        dTabBtns = {}
        for idx in sorted(panes.keys()):
            btns = _buttons(panes[idx])
            if btns and _normHoster(tabHosters.get(idx, '')) not in _SKIP_HOSTERS:
                dTabBtns[idx] = btns
        # Tabs ohne spielbares Ziel (abgeschalteter Hoster, Ordner-Seite, Kurzlink) gar
        # nicht erst anbieten — sie endeten bisher in Folgen, die nur eine Fehlermeldung
        # bringen. Bleibt dadurch nichts uebrig, kommt die normale Kein-Eintrag-Meldung.
        aDead = _deadTabs(dTabBtns)
        if aDead:
            logger.info('-> [%s]: Tabs ohne spielbares Ziel ausgeblendet: %s'
                        % (SITE_NAME, ', '.join(tabHosters.get(idx, 'Hoster %d' % idx) for idx in sorted(aDead))))
        hosterRows = [(tabHosters.get(idx, 'Hoster %d' % idx), idx)
                      for idx in sorted(dTabBtns.keys()) if idx not in aDead]
        oGui = cGui()
        if hosterRows:
            total = len(hosterRows)
            for name, idx in hosterRows:
                oGuiElement = cGuiElement(name, SITE_IDENTIFIER, 'showEpisodes')
                oGuiElement.setMediaType('season')
                if sName: oGuiElement.setTVShowTitle(sName)   # Weitere Quellen sucht die Serie, nicht den Tab
                oGuiElement.setThumbnail(cover)
                params.setParam('entryUrl', entryUrl)
                params.setParam('sName', sName)
                params.setParam('hosterTab', str(idx))
                params.setParam('hosterName', name)
                oGui.addFolder(oGuiElement, params, True, total)
            oGui.setView('seasons')
            oGui.setEndOfDirectory()
            return
        oGui.showInfo()
        oGui.setEndOfDirectory()
        return

    oGui = cGui()
    total = len(seasonBtns)
    for pos, (href, linkNum, label) in enumerate(seasonBtns):
        oGuiElement = cGuiElement(label, SITE_IDENTIFIER, 'showSeasonHosters')
        oGuiElement.setMediaType('season')
        if sName: oGuiElement.setTVShowTitle(sName)
        oGuiElement.setThumbnail(cover)
        params.setParam('entryUrl', entryUrl)
        params.setParam('sName', sName)
        params.setParam('seasonPos', str(pos))
        params.setParam('seasonLabel', label)
        oGui.addFolder(oGuiElement, params, True, total)
    oGui.setView('seasons')
    oGui.setEndOfDirectory()


def showSeasonHosters():
    # Fuer die gewaehlte Staffel je Hoster den passenden Block-Button anbieten.
    params = ParameterHandler()
    entryUrl = params.getValue('entryUrl')
    sName = params.getValue('sName')
    seasonPos = params.getValue('seasonPos')
    seasonLabel = params.getValue('seasonLabel') or ''
    blockUrl = params.getValue('blockUrl')

    sUrl = entryUrl if entryUrl else blockUrl
    sHtmlContent = cRequestHandler(_requestUrl(sUrl)).request()
    panes = _splitTabs(sHtmlContent)
    cover = params.getValue('sCover') or _cover(sHtmlContent)
    hosterNames = {}
    for i, n in _RE_TAB.findall(sHtmlContent):
        hosterNames[int(i)] = _clean(n)

    lo, hi = _seasonRange(seasonLabel)  # Episoden-Range der Staffel (hi None = offenes Ende), sonst (None, None)

    oGui = cGui()
    rows = []  # (label, name, blockUrl|False, hosterTab|False, epRange|False)
    dCheck = {}  # hosterTab -> Buttons der Einzelfolgen-Hoster dieser Staffel (fuer _deadTabs)
    for idx in sorted(panes.keys()):
        btns = _buttons(panes[idx])
        if not btns:
            continue
        name = hosterNames.get(idx, 'Hoster %d' % idx)
        if _normHoster(name) in _SKIP_HOSTERS:
            continue  # aktuell keine geskippt (siehe _SKIP_HOSTERS)
        blockBtns = [b for b in btns if re.match(r'S\d', b[2])]
        if blockBtns:
            # Block-Hoster: den seasonPos-ten S-Block-Button nehmen.
            try:
                href = blockBtns[int(seasonPos)][0]
            except (IndexError, ValueError):
                continue
            label = ('%s - %s' % (seasonLabel, name)) if seasonLabel else name
            rows.append((label, name, href, False, False))
        else:
            # Per-Episode-Hoster (z.B. FMoon): keine S-Bloecke, sondern Einzelfolgen.
            # Auf die Episoden-Range der Staffel eingrenzen wenn erkennbar, sonst alle.
            epNums = [n for n in (_epNum(b[2]) for b in btns) if n is not None]
            if lo is not None and epNums:
                inRange = [n for n in epNums if n >= lo and (hi is None or n <= hi)]
                if not inRange:
                    continue  # Hoster hat in dieser Staffel keine Folgen
                label = '%s (Ep. %d-%d)' % (name, min(inRange), max(inRange))
                rows.append((label, name, False, str(idx), '%d-%s' % (lo, hi if hi is not None else '')))
                dCheck[str(idx)] = [b for b in btns if _epNum(b[2]) in inRange]
            else:
                label = '%s (Ep. %d-%d)' % (name, min(epNums), max(epNums)) if epNums else name
                rows.append((label, name, False, str(idx), False))
                dCheck[str(idx)] = btns

    # Einzelfolgen-Hoster ohne spielbares Ziel ausblenden (wie in showSeasons). Die
    # S-Block-Zeilen brauchen die Pruefung nicht: ihr Ziel ist ein interner Arc-Post.
    aDead = _deadTabs(dCheck)
    if aDead:
        logger.info('-> [%s]: Tabs ohne spielbares Ziel ausgeblendet: %s'
                    % (SITE_NAME, ', '.join(hosterNames.get(int(k), k) for k in sorted(aDead))))
        rows = [r for r in rows if r[3] not in aDead]

    if not rows:
        oGui.showInfo()
        oGui.setEndOfDirectory()
        return

    total = len(rows)
    for label, name, href, hosterTab, epRange in rows:
        oGuiElement = cGuiElement(label, SITE_IDENTIFIER, 'showEpisodes')
        oGuiElement.setMediaType('season')
        if sName: oGuiElement.setTVShowTitle(sName)
        oGuiElement.setThumbnail(cover)
        params.setParam('sName', sName)
        params.setParam('hosterName', name)
        params.setParam('entryUrl', sUrl)
        params.setParam('blockUrl', href if href else '')
        params.setParam('hosterTab', hosterTab if hosterTab else '')
        params.setParam('epRange', epRange if epRange else '')
        oGui.addFolder(oGuiElement, params, True, total)
    oGui.setView('seasons')
    oGui.setEndOfDirectory()


def showEpisodes():
    # Vier Faelle (Lain zuerst, dann die Block-Seite A/B/C):
    # Lain : hosterTab gesetzt -> Folgen = Buttons des Tabs (Episoden inline auf der Serie);
    #        ein Gateway-Button neben anderen Buttons wird ein Ordner auf Fall A.
    # A    : Block-Seite -> Embed = Arc-Post. Arc holen, Tab ueber die Link-Nummer des Zeigers
    #        (sonst per Hoster-Namen), bei S-Block-Labels nur der Bereich der Staffel (_arcButtons).
    # B    : Embed direkt Hoster-URL -> eine einzelne Folge.
    # C    : Fallback - Folgen-Buttons auf der Block-Seite selbst (anderer Slug/Ep.).
    # In allen Faellen nur setEpisode, KEIN setSeason: die Staffelebene ist bei
    # animetoast zweckentfremdet (dort stehen Hoster-Gruppen, keine echten Staffeln),
    # eine Staffelnummer waere schlicht falsch.
    params = ParameterHandler()
    hosterTab = params.getValue('hosterTab')
    blockUrl = params.getValue('blockUrl')
    entryUrl = params.getValue('entryUrl')
    sName = params.getValue('sName')
    hosterName = params.getValue('hosterName') or ''
    cover = params.getValue('sCover') or ''
    oGui = cGui()

    # Lain-Stil: Folgen sind die Buttons des gewaehlten Tabs (?link=N rendert den Embed).
    if hosterTab is not False and hosterTab != '':
        epRange = params.getValue('epRange')
        sHtmlContent = cRequestHandler(_requestUrl(entryUrl)).request()
        panes = _splitTabs(sHtmlContent)
        try:
            epBtns = _buttons(panes[int(hosterTab)])
        except (KeyError, ValueError):
            epBtns = []
        # Range-Gateway (z.B. Code Geass Voe/Dood): manche Hoster-Tabs tragen nur
        # EINEN Range-Button ("Ep.1-25"), der per #player-embed auf einen Arc-Post
        # mit den echten Einzelfolgen zeigt. -> Gateway folgen, im Arc den Tab ueber die
        # Link-Nummer des Zeigers (sonst per Namen) waehlen, dessen Folgen uebernehmen
        # (_arcButtons). Findet sich kein interner Arc/Hoster (echte 1-Stream-Range),
        # bleibt der Button wie er ist.
        # Greift NICHT bei Plain-Per-Ep-Hostern (PlayN) - deren Labels sind Einzelfolgen.
        if len(epBtns) == 1 and re.search(r'\d+\s*-\s*\d+', epBtns[0][2]):
            arcUrl = _embedUrl(cRequestHandler(_requestUrl(epBtns[0][0]), caching=False).request())
            if arcUrl and _BASE in arcUrl and _slugOf(arcUrl) != _slugOf(entryUrl):
                arcBtns = _arcButtons(arcUrl, hosterName, epBtns[0][2])
                if arcBtns:
                    epBtns = arcBtns
        if epRange:
            # Per-Episode-Hoster aus dem Staffel-Flow -> auf die Staffel-Range eingrenzen
            # ("1086-" = offenes Ende der laufenden Staffel).
            try:
                sLo, sHi = epRange.split('-', 1)
                rlo, rhi = int(sLo), (int(sHi) if sHi else None)
                epBtns = [b for b in epBtns
                          if _epNum(b[2]) is not None and _epNum(b[2]) >= rlo
                          and (rhi is None or _epNum(b[2]) <= rhi)]
            except (ValueError, TypeError):
                pass
        if not epBtns:
            oGui.showInfo()
            oGui.setEndOfDirectory()
            return
        total = len(epBtns)
        bMulti = total > 1
        for pos, (href, linkNum, label) in enumerate(epBtns):
            epLabel = label if label else ('%s %d' % (cConfig().getLocalizedString(30513), pos + 1))
            # Gateway-Button NEBEN anderen Buttons (One Piece: "S21:E892-1072" und
            # "E1073-1116" vor den Einzelfolgen; zwei "Ep.1-13" als zwei Uploads): zeigt
            # sein Embed auf einen Arc-Post, wird er ein ORDNER auf den Block-Weg (Fall A)
            # statt einer Folge, die nur die erste Datei des Arcs spielt. Alles andere
            # (Sammel-Datei "Sp.1-4" direkt beim Hoster) bleibt eine Folge. Hilfsabruf: still.
            if bMulti and _isGatewayLabel(label):
                sTarget = _embedUrl(cRequestHandler(_requestUrl(href), ignoreErrors=True).request() or '')
                if sTarget and _BASE in sTarget and _slugOf(sTarget) != _slugOf(entryUrl):
                    oFolder = cGuiElement(epLabel, SITE_IDENTIFIER, 'showEpisodes')
                    oFolder.setMediaType('season')
                    oFolder.setThumbnail(cover)
                    if sName: oFolder.setTVShowTitle(sName)
                    oFolderParams = ParameterHandler()
                    oFolderParams.setParam('entryUrl', entryUrl)
                    oFolderParams.setParam('sName', sName)
                    oFolderParams.setParam('hosterName', hosterName)
                    oFolderParams.setParam('sCover', cover)
                    oFolderParams.setParam('blockUrl', href)
                    oFolderParams.setParam('seasonLabel', label)
                    oFolderParams.setParam('hosterTab', '')
                    oFolderParams.setParam('epRange', '')
                    oGui.addFolder(oFolder, oFolderParams, True, total)
                    continue
            oGuiElement = cGuiElement(epLabel, SITE_IDENTIFIER, 'showHosters')
            oGuiElement.setMediaType('episode')
            iEpisode = _epNum(epLabel)
            if iEpisode is not None:
                oGuiElement.setEpisode(iEpisode)
            if sName: oGuiElement.setTVShowTitle(sName)
            oGuiElement.setThumbnail(cover)
            params.setParam('folgeUrl', href)
            params.setParam('sName', sName)
            oGui.addFolder(oGuiElement, params, False, total)
        oGui.setView('episodes')
        oGui.setEndOfDirectory()
        return

    sHtmlContent = cRequestHandler(_requestUrl(blockUrl)).request()
    embedUrl = _embedUrl(sHtmlContent)

    # Fall A: interner Arc-Link (anderer Post als die Block-Seite).
    if embedUrl and _BASE in embedUrl and _slugOf(embedUrl) != _slugOf(blockUrl):
        # Tab ueber die Link-Nummer des Zeigers, Ausschnitt ueber das Staffel-Label
        # (Begruendung und Messung in _arcButtons); ohne jeden Treffer wie bisher alle
        # Buttons des Arc-Posts.
        epBtns = _arcButtons(embedUrl, hosterName, params.getValue('seasonLabel') or '', bAllIfNoMatch=True)
        if epBtns:
            total = len(epBtns)
            for pos, (href, linkNum, label) in enumerate(epBtns):
                epLabel = label if label else ('%s %d' % (cConfig().getLocalizedString(30513), pos + 1))
                oGuiElement = cGuiElement(epLabel, SITE_IDENTIFIER, 'showHosters')
                oGuiElement.setMediaType('episode')
                oGuiElement.setThumbnail(cover)
                iEpisode = _epNum(epLabel)
                if iEpisode is not None:
                    oGuiElement.setEpisode(iEpisode)
                if sName: oGuiElement.setTVShowTitle(sName)
                params.setParam('folgeUrl', href)
                params.setParam('sName', sName)
                oGui.addFolder(oGuiElement, params, False, total)
            oGui.setView('episodes')
            oGui.setEndOfDirectory()
            return

    # Fall B: Embed ist direkt eine Hoster-URL -> eine einzelne Folge, als EIN abspielbarer
    # Eintrag. Frueher stand hier ein direkter Aufruf von showHosters(): der gibt die
    # Hosterliste nur ZURUECK und baut kein Verzeichnis, der Ordner blieb leer. Aufgefallen
    # ist es nie, weil kein S-Button der Seite direkt auf einen Hoster zeigt (gemessen
    # 20.09.2026: 124 von 124 intern); der Weg ist fuer den Fall da, dass es kommt.
    if embedUrl and _BASE not in embedUrl:
        sLabel = (params.getValue('seasonLabel') or hosterName or sName
                  or '%s 1' % cConfig().getLocalizedString(30513))
        oGuiElement = cGuiElement(sLabel, SITE_IDENTIFIER, 'showHosters')
        oGuiElement.setMediaType('episode')
        if sName: oGuiElement.setTVShowTitle(sName)
        oGuiElement.setThumbnail(cover)
        params.setParam('folgeUrl', blockUrl)
        params.setParam('sName', sName)
        oGui.addFolder(oGuiElement, params, False, 1)
        oGui.setView('episodes')
        oGui.setEndOfDirectory()
        return

    # Fall C (Fallback): Folgen-Buttons auf der Block-Seite selbst.
    curSlug = _slugOf(blockUrl)
    epBtns = []
    for href, linkNum, label in _buttons(sHtmlContent):
        slug = _slugOf(href)
        if (slug and slug != curSlug) or re.match(r'(?i)ep\.?\s*\d', label):
            epBtns.append((href, linkNum, label))
    if epBtns:
        total = len(epBtns)
        for pos, (href, linkNum, label) in enumerate(epBtns):
            epLabel = label if label else ('%s %d' % (cConfig().getLocalizedString(30513), pos + 1))
            oGuiElement = cGuiElement(epLabel, SITE_IDENTIFIER, 'showHosters')
            oGuiElement.setMediaType('episode')
            iEpisode = _epNum(epLabel)
            if iEpisode is not None:
                oGuiElement.setEpisode(iEpisode)
            if sName: oGuiElement.setTVShowTitle(sName)
            oGuiElement.setThumbnail(cover)
            params.setParam('folgeUrl', href)
            params.setParam('sName', sName)
            oGui.addFolder(oGuiElement, params, False, total)
        oGui.setView('episodes')
        oGui.setEndOfDirectory()
        return

    oGui.showInfo()
    oGui.setEndOfDirectory()


def showHosters():
    # Folgen-Seite holen, echte Hoster-URL aus #player-embed -> ResolveURL.
    params = ParameterHandler()
    folgeUrl = params.getValue('folgeUrl') or params.getValue('entryUrl') or params.getValue('sUrl')
    sHosterUrl = _embedUrl(cRequestHandler(_requestUrl(folgeUrl), caching=False).request())
    # Interner Arc-/Block-Link -> einen Schritt folgen, dort den echten Embed lesen.
    if sHosterUrl and _BASE in sHosterUrl:
        sHosterUrl = _embedUrl(cRequestHandler(_requestUrl(sHosterUrl), caching=False).request())
    hosters = []
    if sHosterUrl and _BASE not in sHosterUrl:
        sName = _hosterName(sHosterUrl)
        if not cConfig().isBlockedHoster(_hostOf(sHosterUrl))[0]:
            hosters.append({'link': [sHosterUrl, sName], 'name': sName,
                            'displayedName': sName, 'quality': '720', 'languageCode': ''})
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


def getHosterUrl(hUrl=False):
    # Das Framework uebergibt den 'link'-Wert des Hosters = [url, name]
    # (ueber Parameter ggf. als String-Repr) -> echte Hoster-URL herausziehen.
    if isinstance(hUrl, str):
        try:
            hUrl = ast.literal_eval(hUrl)
        except (ValueError, SyntaxError):
            pass
    sUrl = hUrl[0] if isinstance(hUrl, (list, tuple)) else hUrl
    return [{'streamUrl': sUrl, 'resolved': False}]


# --- Zweiter Seiten-Typ: simple-iframe-player (AJAX) ------------------------
# Hier steht nichts im HTML; Episoden + Hoster-URL kommen per POST an
# admin-ajax.php (action=get_episode_data). "Server" = Hoster. Nonce wird
# jedes Mal frisch von der Serien-Seite gescrapt (laeuft ab, nie hardcoden).
def _ajaxEpisodeData(nonce, title, server, episode=None):
    oRequest = cRequestHandler(URL_MAIN + 'wp-admin/admin-ajax.php', caching=False)
    oRequest.addParameters('action', 'get_episode_data')
    oRequest.addParameters('title', title)
    oRequest.addParameters('server', server)
    if episode is not None:
        oRequest.addParameters('episode', str(episode))
    oRequest.addParameters('nonce', nonce)
    # requestJson() liefert None bei Sentinel, leerer Antwort und kaputtem JSON; die
    # Aufrufer lesen direkt mit .get(), deshalb hier auf ein leeres Dict abbiegen.
    return oRequest.requestJson() or {}


def showAjaxServers(entryUrl, sHtmlContent, title, sName):
    # Server-Dropdown -> jeder Server ist ein Hoster -> showAjaxEpisodes.
    sel = _RE_SERVER_SEL.search(sHtmlContent)
    servers = _RE_OPTION.findall(sel.group(1)) if sel else []
    oGui = cGui()
    if not servers:
        oGui.showInfo()
        oGui.setEndOfDirectory()
        return
    params = ParameterHandler()
    cover = _cover(sHtmlContent)
    params.setParam('sCover', cover)  # Serien-Poster nach unten durchreichen
    total = len(servers)
    for value, label in servers:
        name = 'Server %s' % (label or value)
        oGuiElement = cGuiElement(name, SITE_IDENTIFIER, 'showAjaxEpisodes')
        oGuiElement.setMediaType('season')
        if sName: oGuiElement.setTVShowTitle(sName)
        oGuiElement.setThumbnail(cover)
        params.setParam('entryUrl', entryUrl)
        params.setParam('ajaxTitle', title)
        params.setParam('server', value)
        params.setParam('sName', sName)
        oGui.addFolder(oGuiElement, params, True, total)
    oGui.setView('seasons')
    oGui.setEndOfDirectory()


def showAjaxEpisodes():
    # Episodenliste des gewaehlten Servers via AJAX. Nonce frisch scrapen.
    params = ParameterHandler()
    entryUrl = params.getValue('entryUrl')
    title = params.getValue('ajaxTitle')
    server = params.getValue('server')
    sName = params.getValue('sName')
    cover = params.getValue('sCover') or ''
    sHtmlContent = cRequestHandler(_requestUrl(entryUrl)).request()
    oGui = cGui()
    mNonce = _RE_NONCE.search(sHtmlContent)
    if not mNonce:
        oGui.showInfo()
        oGui.setEndOfDirectory()
        return
    data = _ajaxEpisodeData(mNonce.group(1), title, server)
    episodes = data.get('data', {}).get('episodes', []) if data.get('success') else []
    if not episodes:
        oGui.showInfo()
        oGui.setEndOfDirectory()
        return
    total = len(episodes)
    for ep in episodes:
        epNum = str(ep.get('number', ''))
        epLabel = ep.get('title') or ('%s %s' % (cConfig().getLocalizedString(30513), epNum))
        oGuiElement = cGuiElement(epLabel, SITE_IDENTIFIER, 'showAjaxStream')
        oGuiElement.setMediaType('episode')
        if sName: oGuiElement.setTVShowTitle(sName)
        oGuiElement.setThumbnail(cover)
        params.setParam('entryUrl', entryUrl)
        params.setParam('ajaxTitle', title)
        params.setParam('server', server)
        params.setParam('episode', epNum)
        params.setParam('sName', sName)
        oGui.addFolder(oGuiElement, params, False, total)
    oGui.setView('episodes')
    oGui.setEndOfDirectory()


def showAjaxStream():
    # Hoster-URL der gewaehlten Folge via AJAX -> ResolveURL. Nonce frisch scrapen.
    params = ParameterHandler()
    entryUrl = params.getValue('entryUrl')
    title = params.getValue('ajaxTitle')
    server = params.getValue('server')
    episode = params.getValue('episode')
    sHtmlContent = cRequestHandler(_requestUrl(entryUrl)).request()
    hosters = []
    mNonce = _RE_NONCE.search(sHtmlContent)
    if mNonce:
        data = _ajaxEpisodeData(mNonce.group(1), title, server, episode)
        sHosterUrl = data.get('data', {}).get('url', '') if data.get('success') else ''
        if sHosterUrl:
            sName = _hosterName(sHosterUrl)
            if not cConfig().isBlockedHoster(_hostOf(sHosterUrl))[0]:
                hosters.append({'link': [sHosterUrl, sName], 'name': sName,
                                'displayedName': sName, 'quality': '720', 'languageCode': ''})
    if hosters:
        hosters.append('getHosterUrl')
    return hosters


# --- Suche ------------------------------------------------------------------
def showSearch():
    win = xbmcgui.Window(10000)
    key = 'xstream.%s.lastSearchText' % SITE_IDENTIFIER
    sSearchText = win.getProperty(key)
    if not sSearchText:
        sSearchText = cGui().showKeyBoard(sHeading='AnimeToast Suche')
        if not sSearchText:
            return
        win.setProperty(key, sSearchText)
    _search(False, sSearchText)
    cGui().setEndOfDirectory()


def _siteAnswered(oRequest):
    """Hat die Seite ueberhaupt mit einem HTTP-Status geantwortet?

    Entscheidet, ob der Fallback auf die HTML-Suche sinnvoll ist. Ein echter
    Status — auch 404 oder 400 — heisst: der Server lebt, nur die REST-Route
    liefert nichts. Dann lohnt der zweite Weg. Kein Status oder ein negativer
    Eigencode (-1 Timeout, -5 Domain existiert nicht) heisst: die Seite ist nicht
    erreichbar, ein zweiter Versuch braechte nichts.
    """
    try:
        return int(oRequest.getStatus()) > 0
    except (TypeError, ValueError):
        return False


def _totalPages(oRequest):
    """Seitenzahl aus dem Antwort-Header der REST-API.

    X-WP-TotalPages ist ein Merkmal der QUELLE — anders als eine Trefferzahl
    belegt es eine Folgeseite wirklich. Fehlt der Header, gibt es keinen
    Weiter-Eintrag statt einen zu raten.
    """
    try:
        return int(oRequest.getResponseHeader().get('X-WP-TotalPages') or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def _fetchMedia(aIds):
    """Cover aller Treffer einer Seite in EINEM Sammelabruf.

    Der Weg ueber `_embed=1` haette dieselben Bilder gebracht, kostet aber den
    vollen Beitragstext je Treffer — gemessen 739 KB gegen 9,9 KB. Mehrere
    Staffeln teilen sich oft ein Cover, deshalb werden die IDs entdoppelt.
    """
    aIds = sorted({int(i) for i in aIds if i})
    if not aIds:
        return {}
    sUrl = ('%swp-json/wp/v2/media?include=%s&per_page=100&_fields=id,source_url'
            % (URL_MAIN, ','.join(str(i) for i in aIds)))
    aMedia = cRequestHandler(_requestUrl(sUrl), ignoreErrors=True).requestJson()
    if not isinstance(aMedia, list):
        return {}
    return dict((m.get('id'), m.get('source_url') or '')
                for m in aMedia if isinstance(m, dict))


def _searchApi(oGui, sSearchText, sGui=False):
    """Suche ueber die REST-API der Seite statt ueber ?s=.

    Grund: beide Wege haben VERSCHIEDENE Suchindizes. Gemessen 31.08.2026 —
    "ranma" liefert ueber ?s= fuenf Treffer, von denen KEINER Ranma ist (nur
    Fairy Ranmaru, Appare-Ranman), waehrend die API alle vier Ranma-Beitraege
    findet, obwohl sie im A-Z-Index stehen. Ebenso "yuru camp" (0 gegen 4) und
    "madoka" (1 gegen 5). Ueber sieben Vergleichsbegriffe verliert die API
    KEINEN Treffer der HTML-Suche.

    Rueckgabe: True wenn die Ausgabe hier erledigt ist, False wenn der Aufrufer
    auf die HTML-Suche zurueckfallen soll.
    """
    params = ParameterHandler()
    iPage = int(params.getValue('iPage') or 1)
    sUrl = ('%swp-json/wp/v2/posts?search=%s&per_page=%d&page=%d'
            '&_fields=id,link,title,excerpt,featured_media'
            % (URL_MAIN, _quotePlus(sSearchText), API_PER_PAGE, iPage))
    # ignoreErrors: ueber den Fehlfall wird hier selbst entschieden. Ohne das
    # kaeme bei abgeschalteter REST-Route ein Fehlerfenster, obwohl der
    # Fallback danach sauber liefert.
    oRequest = cRequestHandler(_requestUrl(sUrl), ignoreErrors=True)
    aPosts = oRequest.requestJson()

    # None = kein brauchbares JSON. Leere LISTE dagegen heisst schlicht: keine
    # Treffer — die beiden duerfen nicht verwechselt werden.
    if aPosts is None:
        if _siteAnswered(oRequest):
            return False
        if not sGui:
            oGui.showInfo()
        return True
    if not isinstance(aPosts, list):
        return False

    # Der Filter arbeitet weiter auf Titel PLUS Beschreibungstext: dort stehen
    # die Alternativtitel. Der excerpt ist dafuer gleichwertig zum frueheren
    # Markup-Block — "attack on titan" trifft ueber beide 8 von 14.
    aEntries = []
    for p in aPosts:
        sTitle = _clean((p.get('title') or {}).get('rendered', ''))
        sLink = p.get('link') or ''
        if not sTitle or not sLink:
            continue
        sBlock = '%s %s' % (sTitle, _clean((p.get('excerpt') or {}).get('rendered', '')))
        aEntries.append((sLink, sTitle, p.get('featured_media') or 0, sBlock))

    aHits = _filterSearch(sSearchText, aEntries)
    if not aHits:
        if not sGui:
            oGui.showInfo()
        return True

    dThumbs = _fetchMedia([e[2] for e in aHits])
    total = len(aHits)
    seen = set()
    for sLink, sTitle, iMedia, _sBlock in aHits:
        if sLink in seen:
            continue
        seen.add(sLink)
        oGuiElement = cGuiElement(sTitle, SITE_IDENTIFIER, 'showSeasons')
        oGuiElement.setMediaType('tvshow')
        oGuiElement.setThumbnail(dThumbs.get(iMedia, ''))
        # Adresse ROH weitergeben: der Parameterweg jagt jeden Wert durch
        # unquote_plus, kodiert wird erst unmittelbar vor dem Abruf.
        params.setParam('entryUrl', sLink)
        params.setParam('sName', sTitle)
        oGui.addFolder(oGuiElement, params, True, total)

    iTotal = _totalPages(oRequest)
    if not sGui and iPage < iTotal:
        params.setParam('iPage', iPage + 1)
        params.setParam('sSearchText', sSearchText)
        # Seitenlage am Weiter-Eintrag: die REST-API nennt ihre letzte Seite selbst
        # (X-WP-TotalPages). Die HTML-Suche (Fallback, showEntries) bleibt ohne Angabe,
        # dort belegt die Seite nur die Folgeseite, kein Ende.
        oGui.addNextPage(SITE_IDENTIFIER, 'showSearchEntries', params, cGui.pageInfo(iPage, iTotal))
    return True


def showSearchEntries():
    """Folgeseite der API-Suche (Weiter-Eintrag)."""
    params = ParameterHandler()
    sSearchText = params.getValue('sSearchText')
    if not sSearchText:
        return
    oGui = cGui()
    if not _searchApi(oGui, sSearchText):
        showEntries(URL_MAIN + '?s=' + _quotePlus(sSearchText), oGui, sSearchText)
        return
    oGui.setView('tvshows')
    oGui.setEndOfDirectory()


def _search(oGui, sSearchText):
    # Aufrufkonvention wie in showEntries: showSearch() ruft mit False auf, die
    # globale Suche uebergibt ihr eigenes GUI-Objekt.
    sGui = oGui
    oGui = sGui if sGui else cGui()
    # Erst die REST-API (findet mehr, Begruendung in _searchApi), sonst der
    # alte Weg ueber ?s=Begriff (Grid-Layout -> showEntries).
    if _searchApi(oGui, sSearchText, sGui):
        return
    sUrl = URL_MAIN + '?s=' + _quotePlus(sSearchText)
    showEntries(sUrl, sGui, sSearchText)
