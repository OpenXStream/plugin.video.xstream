# -*- coding: utf-8 -*-
# Python 3

import xbmc
import xbmcgui
import hashlib
import re
import os
import threading

from xbmcvfs import translatePath
from resources.lib.config import cConfig
from urllib.parse import quote, unquote, quote_plus, unquote_plus, urlparse
from html.entities import name2codepoint
from difflib import SequenceMatcher
from functools import lru_cache
from os import path, chdir

# Aufgeführte Plattformen zum Anzeigen der Systemplattform
def platform():
    if xbmc.getCondVisibility('system.platform.android'):
        return 'Android'
    elif xbmc.getCondVisibility('system.platform.linux'):
        return 'Linux'
    elif xbmc.getCondVisibility('system.platform.linux.Raspberrypi'):
        return 'Linux/RPi'
    elif xbmc.getCondVisibility('system.platform.windows'):
        return 'Windows'
    elif xbmc.getCondVisibility('system.platform.uwp'):
        return 'Windows UWP'      
    elif xbmc.getCondVisibility('system.platform.osx'):
        return 'OSX'
    elif xbmc.getCondVisibility('system.platform.atv2'):
        return 'ATV2'
    elif xbmc.getCondVisibility('system.platform.ios'):
        return 'iOS'
    elif xbmc.getCondVisibility('system.platform.darwin'):
        return 'iOS'
    elif xbmc.getCondVisibility('system.platform.xbox'):
        return 'XBOX'
    elif xbmc.getCondVisibility('System.HasAddon(service.coreelec.settings)'):
        return 'CoreElec'
    elif xbmc.getCondVisibility('System.HasAddon(service.libreelec.settings)'):
        return 'LibreElec'
    elif xbmc.getCondVisibility('System.HasAddon(service.osmc.settings)'):
        return 'OSMC'


# Info Meldung im Kodi
def infoDialog(message, heading=cConfig().getAddonInfo('name'), icon='', time=5000, sound=False):
    if icon == '': icon = cConfig().getAddonInfo('icon')
    elif icon == 'INFO': icon = xbmcgui.NOTIFICATION_INFO
    elif icon == 'WARNING': icon = xbmcgui.NOTIFICATION_WARNING
    elif icon == 'ERROR': icon = xbmcgui.NOTIFICATION_ERROR
    xbmcgui.Dialog().notification(heading, message, icon, time, sound=sound)


# Lehnt ein Dienst den EIGENEN Schluessel ab (TMDB, 2Captcha), meldet das bei beiden dieselbe
# Einblendung: Ueberschrift der Dienst, Text der Grund, dieselben Strings (so entschieden am 01.11.2026).
# Hoechstens einmal je Dienst und Grund in einem Plugin-Aufruf — jeder Aufruf ist ein frischer
# Interpreter, die Menge lebt also einen Klick. Ohne die Grenze kaeme bei einer Liste mit TMDB
# Infos je Abfrage eine Einblendung; der Lock, weil der TMDB-Vorlauf bis zu 10 Threads hat.
_keyRejectedShown = set()
_keyRejectedLock = threading.Lock()


def keyRejected(sService, iReason):
    with _keyRejectedLock:
        if (sService, iReason) in _keyRejectedShown:
            return
        _keyRejectedShown.add((sService, iReason))
    infoDialog(cConfig().getLocalizedString(iReason), heading=sService, icon='ERROR', time=10000)


class cParser:
    @staticmethod
    def _get_compiled_pattern(pattern, flags=0):
        return re.compile(pattern, flags)
    
    @staticmethod
    def _replaceSpecialCharacters(s):
        try:
            # Umlaute Unicode konvertieren
            for t in (('\\/', '/'), ('&amp;', '&'), ('\\u00c4', 'Ä'), ('\\u00e4', 'ä'),
                ('\\u00d6', 'Ö'), ('\\u00f6', 'ö'), ('\\u00dc', 'Ü'), ('\\u00fc', 'ü'),
                ('\\u00df', 'ß'), ('\\u2013', '-'), ('\\u00b2', '²'), ('\\u00b3', '³'),
                ('\\u00e9', 'é'), ('\\u2018', '‘'), ('\\u201e', '„'), ('\\u201c', '“'),
                ('\\u00c9', 'É'), ('\\u2026', '...'), ('\\u202f', 'h'), ('\\u2019', '’'),
                ('\\u0308', '̈'), ('\\u00e8', 'è'), ('#038;', ''), ('\\u00f8', 'ø'),
                ('／', '/'), ('\\u00e1', 'á'), ('&#8211;', '-'), ('&#8220;', '“'), ('&#8222;', '„'),
                ('&#8217;', '’'), ('&#8230;', '…'), ('\\u00bc', '¼'), ('\\u00bd', '½'), ('\\u00be', '¾'),
                ('\\u2153', '⅓'), ('\\u002A', '*')):
                s = s.replace(*t)

            # Umlaute HTML konvertieren
            for h in (('\\/', '/'), ('&#x26;', '&'), ('&#039;', "'"), ("&#39;", "'"),
                ('&#xC4;', 'Ä'), ('&#xE4;', 'ä'), ('&#xD6;', 'Ö'), ('&#xF6;', 'ö'),
                ('&#xDC;', 'Ü'), ('&#xFC;', 'ü'), ('&#xDF;', 'ß') , ('&#xB2;', '²'),
                ('&#xDC;', '³'), ('&#xBC;', '¼'), ('&#xBD;', '½'), ('&#xBE;', '¾'),
                ('&#8531;', '⅓'), ('&#8727;', '*')):
                s = s.replace(*h)
        except:
            pass
        return s

    @staticmethod
    def parseSingleResult(sHtmlContent, pattern, ignoreCase=False):
        if sHtmlContent:
            flags = re.S | re.M
            if ignoreCase:
                flags |= re.I

            matches = cParser._get_compiled_pattern(pattern, flags).search(sHtmlContent)
            
            if matches:
                if matches.lastindex is not None and matches.lastindex >= 1:
                    return True, cParser._replaceSpecialCharacters(matches.group(1))
                else:
                    # fallback to the entire match if no group was captured
                    return True, cParser._replaceSpecialCharacters(matches.group(0))
        return False, None
    
    @staticmethod
    def parse(sHtmlContent, pattern, iMinFoundValue=1, ignoreCase=False):
        if sHtmlContent:
            flags = re.DOTALL
            if ignoreCase:
                flags |= re.I

            aMatches = cParser._get_compiled_pattern(pattern, flags).findall(sHtmlContent)
            
            if len(aMatches) >= iMinFoundValue:
                if isinstance(aMatches[0], tuple):
                    aMatches = [tuple(cParser._replaceSpecialCharacters(x) if isinstance(x, str) and x is not None else '' for x in match) for match in aMatches]
                else:
                    aMatches = [cParser._replaceSpecialCharacters(x) if isinstance(x, str) and x is not None else '' for x in aMatches]
                
                return True, aMatches
        return False, None

    @staticmethod
    def search(pattern, sValue, ignoreCase=True):
        flags = 0
        if ignoreCase:
            flags = re.IGNORECASE
        return cParser._get_compiled_pattern(pattern, flags).search(sValue)

    @staticmethod
    def escape(sValue):
        return re.escape(sValue)

    @staticmethod
    def normalizeTitle(sTitle):
        """Titel fuer den Suchvergleich angleichen — EINE Wahrheit fuer alle Filter.

        Kleinschreibung; Punkte, Apostrophe und Sternchen fallen weg (S.W.A.T. ->
        swat, Grey's -> greys, M*A*S*H -> mash); alle anderen Nicht-Wortzeichen
        werden zu einem Leerzeichen (Spider-Man -> spider man, WALL·E -> wall e).
        Umlaute und ß werden umgeschrieben (König -> koenig, Straße -> strasse):
        die Seiten schreiben beides, der Nutzer tippt beides, und beide Seiten
        des Vergleichs bekommen dieselbe Form. Bis zum 11.09.2026 blieben sie
        stehen — „koenig" fand bei sechs Seiten 0 Titel, obwohl die Seiten welche
        mit „König" lieferten (nach der Umschrift 2 bis 20 je Seite). Das Ergebnis dient NUR dem
        Vergleich, angezeigt wird der Originaltitel. Bis zum 02.09.2026 stand
        diese Angleichung nur in xstream.searchAlter; die Site-Suchen verglichen
        zeichengenau, und „spider man" lieferte bei sechs Seiten 0 Treffer, obwohl
        jede davon Spider-Man-Titel fand (hdfilme 26, megakino 22 ...).
        """
        sTitle = str(sTitle).lower()
        for sUmlaut, sUmschrift in (('ä', 'ae'), ('ö', 'oe'), ('ü', 'ue'), ('ß', 'ss')):
            sTitle = sTitle.replace(sUmlaut, sUmschrift)
        sTitle = re.sub(r"[.'\u2019*`\u00b4]", '', sTitle)
        sTitle = re.sub(r'[^\w]+', ' ', sTitle)
        return re.sub(r'\s+', ' ', sTitle).strip()

    # --- Suchtitel: Zusaetze der Seiten, die nicht zum Titel gehoeren -------------------------
    # EINE Wahrheit fuer Weitere Quellen (xstream.searchAlter) und die TMDB-Namenssuche (Trailer,
    # TMDB-Info, Metadaten). Angezeigt wird immer der Originaltitel. Gemessen 29.09.2026 ueber alle
    # 17 Seiten (Listen Seite 1 und 2 am echten Dispatch, 52.142 Suchbegriffe): mit Zusatz fanden
    # die anderen Seiten und TMDB nichts oder das Falsche — „Game of Thrones | GoT" 0 statt 25
    # Treffer, „Rush (AUS)" bei TMDB eine andere Serie, „Die Odyssee *Subbed*" keine TMDB-ID.
    # Alternativname der Seite hinter „ | " (burningseries, 2.628 Titel): der erste Name bleibt.
    _RE_ALT_TITLE = re.compile(r'\s+\|\s+.*$')
    # Seiten-Anmerkung in Sternchen am Titelende: *Subbed*, *ENGLISH*, *2025*, *Gute Qualitaet*
    # (hdfilme, filmpalast). Nur mit Leerzeichen davor — „M*A*S*H" und „Thunderbolts*" bleiben.
    _RE_STAR_NOTE = re.compile(r'\s+\*[^*]{1,40}\*\s*$')
    # Sprach-Zusatz am Titelende: zwei Sprachpaare hintereinander („Jap Dub Ger Sub", „Ger Sub Ch
    # Dub", animetoast), eine Klammer mit hoechstens einem Wort vor Dub/Sub („(Subbed)", „(Italian
    # Dub)"), „(OmU)", und Ger/German + Dub/Sub mit oder ohne Klammer („Ger Sub", „[GerSub]").
    # Ein einzelnes nacktes Dub/Sub ohne Ger bleibt („Duckman … Das Sub" ist ein Folgentitel).
    _RE_LANG_NOTE = re.compile(r'(?:\s+[A-Z][a-z]{0,2}[\s-]+(?:Dub|Sub)(?:bed)?){2,}\s*$'
                               r'|\s*[\(\[]\s*(?:[^\W\d_]+[\s-]+)?(?:Dub|Sub)(?:bed)?\s*[\)\]]\s*$'
                               r'|\s*\(\s*OmU\s*\)\s*$'
                               r'|\s*[\(\[\*]?\bGer(?:man)?[\s-]*(?:Dub|Sub)(?:bed)?\b[\)\]\*]?\s*$', re.I)
    # Kuerzel-Klammer am Titelende aus 2-3 Grossbuchstaben, rund oder eckig: Land oder Format —
    # (US), (UK), (AUS), (ROK), (TV), (ONA), [OVA]. Gross/klein zaehlt: „(Un)Well" oder „(noch)" bleiben.
    _RE_CODE_NOTE = re.compile(r'\s*[\(\[][A-Z]{2,3}[\)\]]\s*$')
    # Typ-Angabe in Klammern am Titelende: (Zeichentrick), (Anime), (Live Action), (Serie),
    # (Realserie), (Filmreihe), (J-Drama)/(K-Drama) — 13 Titel bei burningseries, serienstream, einschalten.
    _RE_TYPE_NOTE = re.compile(r'\s*\(\s*(?:Zeichentrick|Anime|Live\s+Action|Serie|Realserie|Filmreihe|[A-Z]-Drama)\s*\)\s*$', re.I)
    # Staffel-/Folgen-Angabe der Seite in einer Klammer am Titelende, rund oder eckig:
    # „(nur aktuelle/verfuegbare Staffel/Folgen)" (serienstream, 14 Titel), „(Seasons 1 - 16)"
    # (streamcloud), „[2016 zw. s03/s04]" — mit dem Zusatz finden TMDB und die anderen Seiten
    # nichts. Eine Klammer ohne diese Woerter bleibt („(Live in 3D)", „(500) Days of Summer").
    _RE_SEASON_NOTE = re.compile(r'\s*[\(\[][^\(\)\[\]]*\b(?:Staffeln?|Folgen?|Seasons?|s\d{2})\b[^\(\)\[\]]*[\)\]]\s*$', re.I)
    # Jahr in Klammern am Titelende („Black Box *Subbed* (2026)", „Baki Ger Dub (2018)"): die
    # Ende-Regeln sehen sonst keinen Zusatz, weil das Jahr dahinter steht. Weitere Quellen
    # schneidet das Jahr vor dem Aufruf, die TMDB-Suche erst danach — deshalb hier abnehmen.
    _RE_YEAR_TAIL = re.compile(r'\s*\((?:19|20)\d{2}\)\s*$')
    # Fassungs-Angabe in runden oder eckigen Klammern, an beliebiger Stelle: eine Klammer fliegt,
    # sobald sie eines dieser zehn Woerter enthaelt, was sonst darin steht ist egal — „(Directors
    # Cut/Remastered)", „(Ulysses Cut)", „[Uncut]". „(Version 2)", „(Live in 3D)" und Titel ohne
    # Klammer („Uncut Gems", „Final Cut") bleiben. Eine strenge Wortliste je Klammer (39 Woerter)
    # fand am 29.09.2026 weniger und verpasste benannte Schnitte — nicht darauf zurueckbauen.
    _EDITION_WORDS = r'\b(?:uncut|unrated|extended|remastered|uncensored|theatrical|colorized|langfassung|cut|edition)\b'
    _RE_EDITION_NOTE = re.compile(r'\s*(?:\((?=[^()]*' + _EDITION_WORDS + r')[^()]{2,60}\)'
                                  r'|\[(?=[^\[\]]*' + _EDITION_WORDS + r')[^\[\]]{2,60}\])', re.I)

    @staticmethod
    def stripTitleNotes(sTitle):
        """Zusaetze der Seite aus einem SUCHtitel entfernen (Regeln oben). Mehrere Zusaetze am Ende
        („Spriggan (ONA) Ger Sub") werden nacheinander abgebaut. Ohne Treffer kommt der Titel
        zeichengleich zurueck, auch doppelte Leerzeichen bleiben — die Bereinigung darf keinen
        anderen Titel veraendern (Klassenmessung 29.09.2026).
        Steht hinter dem Zusatz noch ein Jahr in Klammern („Black Box *Subbed* (2026)", 193
        Begriffe am 01.10.2026), wird es fuer die Ende-Regeln abgenommen und faellt mit dem
        Zusatz: Weitere Quellen schneidet das Jahr ohnehin vorher, die TMDB-Suche bekommt es als
        eigenen Parameter. Ein Jahr ohne Zusatz davor bleibt stehen (zeichengleich).
        """
        sBody = cParser._RE_YEAR_TAIL.sub('', sTitle) if cParser._RE_YEAR_TAIL.search(sTitle) else sTitle
        sNew = cParser._RE_ALT_TITLE.sub('', sBody)
        for _ in range(3):
            sPrev = sNew
            for oRe in (cParser._RE_STAR_NOTE, cParser._RE_LANG_NOTE, cParser._RE_CODE_NOTE, cParser._RE_TYPE_NOTE, cParser._RE_SEASON_NOTE):
                sNew = oRe.sub('', sNew)
            if sNew == sPrev:
                break
        sNew = cParser._RE_EDITION_NOTE.sub('', sNew)
        if sNew == sBody:
            return sTitle
        # Besteht der Titel NUR aus einer Zusatz-Form, ist sie der Titel: „[REC] (2007)" (kellerkino)
        # traf die Kuerzel-Klammer und kam als leerer Suchtitel zurueck (02.10.2026)
        if not sNew.strip():
            return sTitle
        # ein durch den Schnitt verwaister Doppelpunkt faellt mit („Digimon Adventure: Ger Sub")
        return sNew.strip().rstrip(':').strip()

    # Englische Staffelformen („Season 2", „2nd Season", „Final Season", „Part 2" — gezaehlt
    # 10.09.2026 ueber 2.956 animetoast-Labels: 232 / 54 / 11 / 26) und die S01E02-Form. Nummern-
    # pflicht ausser bei „Final Season", damit „Season of the Witch" stehen bleibt; „Part N" trifft
    # auch Filmreihen („Deathly Hallows Part 2") und liefert dann die ganze Reihe — gewollt. Nicht
    # mitten in einer Klammer schneiden („Global GUTS (Nickelodeon GUTS Season 4)"), einen uebrig
    # bleibenden Doppelpunkt abwerfen („Attack on Titan: Final Season" → „Attack on Titan").
    _RE_SEASON_FORM = re.compile(r'^(.+?)\s*-?\s+(?:Season\s*\d+|\d+(?:st|nd|rd|th)\s+Season|Final\s+Season|Part\s*\d+)\b.*$', re.I)
    # Staffel UND Folge mit Nummer („S01 E01", „S29 E02", „S1 F7", „S01E03") — die Token in
    # stripSeasonForms kennen nur Staffeln mit fuehrender Null, „South Park S29 E02" blieb bis
    # zum 01.10.2026 als „South Park S29" stehen
    _RE_SEASON_EPISODE = re.compile(r'\s+S\d{1,3}\s*[EF]\d{1,4}\b.*$')

    @staticmethod
    def stripSeasonForms(sTitle):
        """Englische Staffelformen und die S01E02-Form aus einem SUCHtitel schneiden. Stand bis
        zum 29.09.2026 nur in searchAlter; die TMDB-Seriensuche fand deshalb z.B. „Kaiju No. 8 2nd
        Season" nicht (animetoast: 352 Seriennamen, burningseries 19 mit „S01 E01").
        """
        sNew = sTitle
        # Folgenkennung der Neue-Episoden-Listen („Dragon Ball Daima (S01E20) [DE]", serienstream) samt Rest
        sNew = re.sub(r'\s*\(S\d+E\d+\).*$', '', sNew)
        sCut = cParser._RE_SEASON_FORM.sub(r'\1', sNew).strip().rstrip(':').strip()
        if sCut and sCut.count('(') == sCut.count(')'):
            sNew = sCut
        sCut = cParser._RE_SEASON_EPISODE.sub('', sNew)
        if sCut == sNew:
            # nackte Staffel oder Folge wie bisher („Doctor Who S03", „Hogan Family S01-S06", „Serie E05")
            for token in (' S0', ' E0'):
                if token in sNew:
                    sCut = sNew.split(token)[0]
                    break
        if sCut != sNew:
            # nur hier den Trenner mitnehmen („Name - S01E01 - Folge" → „Name"), auch den Gedankenstrich
            # („Ip Man – Die Serie – S01 E10"); ein allgemeines rstrip('-') traefe Titel wie „GAMERA -Rebirth-"
            sNew = sCut.strip().rstrip('-–—:').strip()
        return sNew if sNew != sTitle else sTitle

    # Platzhalter-Titel der Seiten mit der Nummer der Folge: „Folge 5", „Episode 5", hdfilmes „Episoden 5"
    _RE_EPISODE_PLACEHOLDER = re.compile(r'^(?:folge|episoden?)\s*0*(\d+)$', re.I)

    @staticmethod
    def episodeLabel(season, episode, title='', fallback=None, altTitle=''):
        """Label eines Folgen-Eintrags — EINE Form auf allen Sites (seit dem 06.10.2026): „S01E05 - Titel",
        ohne Titel „S01E05". S/E ist Format wie „(3/12)" in cGui.pageInfo und braucht keinen String.

        Ein Platzhalter-Titel mit derselben Nummer („Folge 5" bei Folge 5) faellt weg, sonst stuende
        die Nummer doppelt da; „Episode 27" bei S02E05 bleibt (Gesamtzaehlung der Seite). Fuehrt die
        Seite einen zweiten Titel (deutsch und englisch bei aniworld und serienstream),
        kommt er als `altTitle` mit und springt ein, wenn der erste leer oder so ein Platzhalter ist —
        „Folge 03" neben „Zaht and Braham" ergab bis zum 05.11.2026 „S03E03" ohne Titel.
        Staffel 0 wird S00 (Specials). Ohne ganze Zahlen fuer Staffel und Folge wird nichts geraten:
        dann kommt `fallback` zurueck (die bisherige Form der Site, wo sie eine eigene hatte), sonst
        „Folge N - Titel".
        """
        try:
            iEpisode = int(str(episode).strip())
        except ValueError:
            iEpisode = None

        def _echt(sWert):
            # der Titel ohne den Platzhalter der eigenen Nummer
            sWert = str(sWert or '').strip()
            m = cParser._RE_EPISODE_PLACEHOLDER.match(sWert)
            return '' if m and int(m.group(1)) == iEpisode else sWert
        sTitle = _echt(title) or _echt(altTitle)
        try:
            iSeason = int(str(season).strip())
        except ValueError:
            iSeason = None
        if iSeason is not None and iEpisode is not None and iSeason >= 0 and iEpisode >= 0:
            sLabel = 'S%02dE%02d' % (iSeason, iEpisode)
        elif fallback is not None:
            return fallback
        else:
            sLabel = '%s %s' % (cConfig().getLocalizedString(30513), iEpisode if iEpisode is not None else str(episode).strip())
        return '%s - %s' % (sLabel, sTitle) if sTitle else sLabel

    @staticmethod
    def searchTitle(sSearchText, sTitle):
        """Titelfilter der Suchen: steht der Suchbegriff im Titel, beide normalisiert?

        Ersetzt das fruehere `cParser.search(cParser.escape(sSearchText), sName)`
        an allen Filterstellen. Normalisiert ist eine Obermenge des strikten
        Vergleichs — es faellt nur Interpunktion weg, jeder alte Treffer bleibt.
        Ein leerer Suchbegriff filtert nicht.
        """
        sNeedle = cParser.normalizeTitle(sSearchText)
        if not sNeedle:
            return True
        return sNeedle in cParser.normalizeTitle(sTitle)

    @staticmethod
    def getNumberFromString(sValue):
        aMatches = re.compile(r'\d+').findall(sValue)
        if len(aMatches) > 0:
            return int(aMatches[0])
        return 0

    @staticmethod
    def urlparse(sUrl):
        return urlparse(sUrl.replace('www.', '')).netloc.title()

    @staticmethod
    def urlDecode(sUrl):
        return unquote(sUrl)

    @staticmethod
    def urlEncode(sUrl, safe=''):
        return quote(sUrl, safe)

    @staticmethod
    def quote(sUrl):
        return quote(sUrl)

    @staticmethod
    def quotePlus(sUrl):
        return quote_plus(sUrl)


class cUtil:
    @staticmethod
    def removeHtmlTags(sValue, sReplace=''):
        return re.compile(r'<.*?>').sub(sReplace, sValue)

    @staticmethod
    def unescape(text):
        def fixup(m):
            text = m.group(0)
            if not text.endswith(';'): text += ';'
            if text[:2] == '&#':
                try:
                    if text[:3] == '&#x':
                        return chr(int(text[3:-1], 16))
                    else:
                        return chr(int(text[2:-1]))
                except ValueError:
                    pass
            else:
                try:
                    text = chr(name2codepoint[text[1:-1]])
                except KeyError:
                    pass
            return text

        if isinstance(text, str):
            try:
                text = text.decode('utf-8')
            except Exception:
                try:
                    text = text.decode('utf-8', 'ignore')
                except Exception:
                    pass
        return re.compile('&(\\w+;|#x?\\d+;?)').sub(fixup, text.strip())

    @staticmethod
    def cleanse_text(text):
        if text is None: text = ''
        text = cUtil.removeHtmlTags(text)
        return text

    @staticmethod
    @lru_cache(maxsize=200000)
    def get_seq_match_ratio(token1, token2):
        return SequenceMatcher(None, token1, token2).ratio()
    
    @staticmethod
    def isSimilarByToken(sSearch, sText, threshold=0.9):
        tokens_sSearch = sSearch.split()
        tokens_sText = sText.split()

        if not tokens_sSearch:
            return False

        best_ratios = [
            max(cUtil.get_seq_match_ratio(token, token2) for token2 in tokens_sText)
            for token in tokens_sSearch
        ]
        return (sum(best_ratios) / len(best_ratios)) >= threshold

def getDNS(dns):
    status = 'Beschäftigt'
    loop = 1
    while status == 'Beschäftigt':
        if loop == 20:
            break
        status = xbmc.getInfoLabel(dns)
        xbmc.sleep(20)
        loop += 1
    return status

def getRepofromAddonsDB(addonID):
    from sqlite3 import dbapi2 as database
    from glob import glob
    chdir(path.join(translatePath('special://database/')))
    addonsDB = path.join(translatePath('special://database/'), sorted(glob("Addons*.db"), reverse=True)[0])
    dbcon = database.connect(addonsDB)
    dbcur = dbcon.cursor()
    select = ("SELECT origin FROM installed WHERE addonID = '%s'") % addonID
    dbcur.execute(select)
    match = dbcur.fetchone()
    dbcon.close()
    if match and len(match) > 0:
         repo = match[0]
    else:
        repo = ''
    return repo
