# -*- coding: utf-8 -*-
# Python 3
#
# 24.01.23 - Heptamer: Korrektur getpriorities (nun werden alle Hoster gelesen und sortiert)
# 22.12.24 - Heptamer: m3u8 und mpd Files - MimeType für native Kodi Wiedergabe

import re

import xbmc
import xbmcgui 
import xbmcplugin
from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import quietWindows
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.gui.gui import cGui
from resources.lib.config import cConfig
from resources.lib.captcha.captcha_schemas import clear_gate
from resources.lib.player import cPlayer, applyIsa, probeStream
from resources.lib.logger import logger



def _quality_to_res(value):
    # Hoster-'quality' ist je nach Site ein roher String ('1080p', '1080', 'HD', '4K' ...).
    # Robust auf eine Pixelhoehe zum Sortieren abbilden; nicht-aufloesende Labels -> 0.
    s = str(value).lower()
    if '2160' in s or '4k' in s: return 2160
    if '1440' in s or '2k' in s: return 1440
    if '1080' in s: return 1080
    if '720' in s: return 720
    if '480' in s: return 480
    if '360' in s: return 360
    if '240' in s: return 240
    m = re.search(r'(\d{3,4})', s)
    return int(m.group(1)) if m else 0


class cHosterGui:
    def __init__(self):
        self.dialog = False
        self._attempts = 0  # Uebergaben an den Player in diesem Lauf (Auto-Modus: je Hoster eine)
        self._isa = False   # der laufende Versuch spielt ueber InputStream Adaptive (player.applyIsa)
        self._gemeldet = False  # eine Hoster-Meldung (_melden) kam in diesem Lauf schon

    def _melden(self, iText, iSeconds):
        # Hoster-Meldung als Einblendung, mit Merker fuer streamAuto: hat am Ende kein Hoster gespielt und kam bis dahin
        # keine Meldung, sagt streamAuto es einmal (30141). Bis zum 02.11.2026 blieb xStream stumm, wenn jede Hosterlink-
        # Funktion ohne Link zurueckkam (toter Hoster, stiller Abruf) — der Nutzer sah nur Kodis eigenes Fenster
        # „Wiedergabe fehlgeschlagen" (02.11.2026 nachgestellt).
        self._gemeldet = True
        cGui().showError('xStream', cConfig().getLocalizedString(iText), iSeconds)

    def _resolveWithCaptcha(self, resolver, mediaUrl):
        # Normalfall ist ein einziger resolve()-Aufruf. Steht auf der
        # Hoster-Seite ein Gate, das ResolveURL nicht kennt (Cloudflare Turnstile
        # bei Dropload/dr0pstream seit 09/2026 — in reinem Python nicht loesbar),
        # findet es dort keinen Stream. Dann prueft clear_gate (die Gate-Muster
        # in captcha_schemas.py) die Seite EINMAL, raeumt das erkannte Gate, und
        # _resolveAfterCaptcha loest neu auf (hoechstens zwei Abrufe, kein
        # zweites Gate); das Freigabe-Cookie liegt danach im Jar von ResolveURLs
        # Net, deshalb bekommt der unveraenderte Resolver die Playerseite. Ohne
        # Schalter oder hinterlegten Schluessel kostet der Weg nichts, dann wird
        # die Seite nicht geladen.
        try:
            link = resolver.resolve(mediaUrl)
        except resolver.resolver.ResolverError:
            if not clear_gate(mediaUrl):
                raise
            return self._resolveAfterCaptcha(resolver, mediaUrl)
        if link is False and clear_gate(mediaUrl):
            link = self._resolveAfterCaptcha(resolver, mediaUrl)
        return link

    def _resolveAfterCaptcha(self, resolver, mediaUrl):
        # Nach dem Raeumen liefert die Hoster-Seite den Player nicht immer beim
        # ERSTEN Abruf, obwohl das Freigabe-Cookie sitzt (gemessen 08.09.2026:
        # derselbe Aufruf mal Formular, mal Player). Ein zweiter Versuch kostet
        # keine weitere Captcha-Loesung, nur einen Seitenabruf.
        try:
            link = resolver.resolve(mediaUrl)
        except resolver.resolver.ResolverError:
            link = False
        if link:
            return link
        return resolver.resolve(mediaUrl)

    def _hosterLink(self, function, link):
        # Die Hosterlink-Funktion der Site (getHosterUrl). Bei filmo, aniworld, serienstream und burningseries
        # ruft sie selbst ab (Weiterleitung, Token); scheitert so ein Abruf, liefert sie keinen Link, und
        # _getInfoAndResolve meldet das mit EINER Einblendung (30134); liefert eine Site gar nichts, bleibt der Hoster
        # still, und streamAuto sagt es am Ende einmal, wenn keiner gespielt hat. Das Fehlerfenster des requestHandlers
        # (Adresse + Fehlertext) bleibt hier deshalb aus — es stand sonst zusaetzlich da und blockierte im
        # Auto-Modus je totem Hoster einmal (filmo 26.10.2026: zwei VOE-Links, zwei Fenster); die Adresse steht
        # weiter im Log. Seitenabrufe davor (Hosterliste) laufen weiter mit Fenster.
        with quietWindows():
            return function(link)

    def _getInfoAndResolve(self, siteResult):
        params = ParameterHandler()
        mediaUrl = params.getValue('sMediaUrl')
        fileName = params.getValue('MovieTitle')
        try:
            try:
                import resolveurl as resolver
            except:
                import urlresolver as resolver
            if siteResult:
                mediaUrl = siteResult.get('streamUrl', False)
                mediaId = siteResult.get('streamID', False)
                if mediaUrl:
                    logger.info('-> [hoster]: resolve: ' + mediaUrl)
                    link = mediaUrl if siteResult['resolved'] else self._resolveWithCaptcha(resolver, mediaUrl)
                elif mediaId:
                    logger.info('-> [hoster]: resolve: hoster: %s - mediaID: %s' % (siteResult['host'], mediaId))
                    link = resolver.HostedMediaFile(host=siteResult['host'].lower(), media_id=mediaId).resolve()
                else:
                    self._melden(30134, 5)
                    return False
            elif mediaUrl:
                logger.info('-> [hoster]: resolve: ' + mediaUrl)
                link = self._resolveWithCaptcha(resolver, mediaUrl)
            else:
                self._melden(30134, 5)
                return False
        except resolver.resolver.ResolverError as e:
            logger.error('-> [hoster]: ResolverError: %s' % e)
            self._melden(30135, 7)
            return False
        if link is False:
            # ResolveURL liefert False OHNE ResolverError, wenn kein Resolver auf die
            # Adresse passt (z.B. eine neue Hoster-Domain, die Gujal noch nicht kennt)
            # oder der zustaendige Resolver ohne Ausnahme leer ausgeht. Frueher blieb
            # das komplett stumm: der Nutzer klickte und es passierte sichtbar nichts
            # (01.09.2026, filmpalast/VIDARA auf einer Spiegeldomain). Gleiche
            # Einblendung wie beim ResolverError, damit der Auto-Weg wie bisher je
            # totem Hoster nur eine Einblendung zeigt und kein Fenster.
            logger.error('-> [hoster]: no resolver result for %s' % mediaUrl)
            bKnown = bool(mediaUrl) and resolver.HostedMediaFile(url=mediaUrl).valid_url()
            self._melden(30135 if bKnown else 30144, 7)
            return False
        if link is not False:
            data = {'title': fileName, 'season': params.getValue('season'), 'episode': params.getValue('episode'), 'showTitle': params.getValue('TVShowTitle'), 'thumb': params.getValue('thumb'), 'link': link, 'imdb_id': params.getValue('imdb_id'), 'tmdb_id': params.getValue('tmdbID'), 'year': params.getValue('year'), 'mediaType': params.getValue('mediaType')}
            return data
        return False

    def play(self, siteResult=False):
        logger.info('-> [hoster]: attempt to play file')
        data = self._getInfoAndResolve(siteResult)
        if not data:
            return False
        # Vorab-Abruf der Stream-Adresse (player.probeStream, seit dem 05.11.2026): antwortet
        # sie nicht, startet der Player nicht — eine Einblendung statt Kodis Wartezeit, im
        # Auto-Modus kommt der naechste Hoster; das Fortschrittsfenster bleibt solange offen.
        bAnswered, head = probeStream(data['link'])
        if not bAnswered:
            self._melden(30921, 7)
            return False
        if self.dialog:
            try:
                self.dialog.close()
            except:
                pass

        logger.info('-> [hoster]: play file link: ' + str(data['link']))
        list_item = xbmcgui.ListItem(path=data['link'])
        # MimeType setzen damit Kodi das Format nativ erkennt
        if '.m3u8' in data['link']:
            list_item.setMimeType('application/vnd.apple.mpegurl')
            list_item.setContentLookup(False)
        # HLS ueber InputStream Adaptive, wenn es aktiv ist; die Adresse kommt
        # dann ohne Pipe zurueck, die Header stehen am ListItem.
        data['link'], self._isa = applyIsa(list_item, data['link'], head)

        if 'youtube' in data['link']:
            import time
            time.sleep(1)
        if data['thumb']:
            list_item.setArt({'thumb': data['thumb']})

        self._setVideoInfo(list_item.getVideoInfoTag(), data)

        list_item.setProperty('IsPlayable', 'true')
        if self._attempts:
            # Ausweich-Hoster im Auto-Modus: Kodis Fenster "Wiedergabe nicht
            # moeglich" des vorigen Hosters hat streamAuto schon geschlossen;
            # hier noch einmal, falls Kodi es erst danach gezeichnet hat — es
            # bliebe sonst vor der neuen Wiedergabe stehen, bis der Nutzer OK
            # drueckt.
            xbmc.executebuiltin('Dialog.Close(okdialog,true)')
        # Den Plugin-Handle nimmt Kodi nur EINMAL an: nach dem ersten
        # setResolvedUrl gibt er ihn frei, jeder weitere Aufruf verpufft ohne
        # Meldung, und startPlayer() wartete dann vergeblich. Jeder weitere
        # Hoster startet deshalb direkt ueber den Player.
        if cGui().pluginHandle > 0 and not self._attempts:
            xbmcplugin.setResolvedUrl(cGui().pluginHandle, True, list_item)
        else:
            xbmc.Player().play(data['link'], list_item)
        self._attempts += 1
        return cPlayer().startPlayer(isa=self._isa)

    def _setVideoInfo(self, vtag, data):
        """Medientyp, Titel, Serie mit Staffel und Folge, Jahr und IDs auf dem ListItem der Wiedergabe (play)."""
        # Korrekten MediaType setzen (movie, episode statt video). Trakt bestimmt den Typ bei
        # Plugin-Wiedergaben selbst aus Staffel und Folge (Quelle unten).
        if data.get('showTitle') and data.get('episode'):
            vtag.setMediaType('episode')
        elif data.get('mediaType') in ('movie', 'episode', 'tvshow', 'season'):
            vtag.setMediaType(data['mediaType'])
        else:
            vtag.setMediaType('video')
        if data.get('title'):
            try:
                vtag.setTitle(str(data['title']))
            except: pass
        if data.get('showTitle'):
            try:
                vtag.setTvShowTitle(data['showTitle'])
            except: pass
            if data.get('season'):
                try:
                    vtag.setSeason(int(data['season']))
                except: pass
            if data.get('episode'):
                try:
                    vtag.setEpisode(int(data['episode']))
                except: pass
        # Jahr, IMDb- und TMDB-ID setzen: wer die IDs der Wiedergabe liest, findet den Titel damit
        # direkt (mdblist und OpenSubtitles laut Heptamers Changelog vom 01.11.2026). Trakt liest
        # bei Plugin-Wiedergaben keine IDs, nur Titel, Jahr, Staffel und Folge (script.trakt,
        # kodiUtilities.getInfoLabelDetails, Master f8f4ad9 vom 26.10.2026, gelesen 01.11.2026).
        # Die IMDb-ID bleibt die Standard-ID: VideoPlayer.IMDBNumber liefert die Standard-ID, mit
        # TMDB als Standard stuende dort eine TMDB-Nummer (Kodi 21.3 VideoGUIInfo.cpp und
        # VideoInfoTag.cpp, gelesen 01.11.2026).
        if data.get('year'):
            try:
                vtag.setYear(int(data['year']))
            except: pass
        if data.get('imdb_id'):
            try:
                vtag.setUniqueID(str(data['imdb_id']), 'imdb', True)
            except: pass
        # Die TMDB-ID kommt als Parameter tmdbID mit, wenn der Eintrag eine traegt (TMDB Infos
        # laden) — keine eigene TMDB-Abfrage. Gesetzt wird sie nur, wo sie sicher zum Titel
        # gehoert: beim Film seine eigene (geerbte nimmt gui.__createItemUrl Filmen und Serien
        # ab), bei der Folge einer echten Staffel die ID der Serie, wie bei Heptamer. Ohne
        # Staffel (Staffel 0, Specials) passt die Zaehlung der Seite nicht sicher zu TMDB. Die Staffel kommt als
        # Text; '0' ist nicht leer und lief bis zum 02.11.2026 deshalb als „mit Staffel" durch.
        sMediaType = vtag.getMediaType()
        sSeason = str(data.get('season') or '')
        if data.get('tmdb_id') and (sMediaType == 'movie' or (sMediaType == 'episode' and sSeason.isdecimal() and int(sSeason) > 0)):
            try:
                vtag.setUniqueID(str(data['tmdb_id']), 'tmdb')
            except: pass

    def _dedupeHosters(self, hosterList):
        """Doppelte Hoster-Eintraege entfernen — zentral fuer ALLE Sites.

        Greift unabhaengig davon, ob eine Site meinecloud nutzt: Dubletten
        entstehen auch wenn eine Site denselben Link zweimal im HTML listet.
        Reihenfolge bleibt erhalten — der erste Treffer gewinnt.

        Vergleichsschluessel = normalisierte URL + Hoster-Name + Sprache:
        gleiche Adresse bei anderem Hoster-Namen oder anderer Sprache ist
        keine Dublette. Die fruehere Begruendung, aniworld/serienstream
        truegen fuer alle Hoster einer Folge dasselbe Weiterleitungsziel,
        trifft heute nicht zu (gemessen 14.10.2026: eine aniworld-Folge
        12 Hoster mit 12 verschiedenen Zielen, serienstream 3 mit 3) — der
        Schluessel bleibt so, weil er mit eigenen Zielen nichts kostet.
        Schema-normalisiert (//host/x == https://host/x), damit dieselbe
        Datei aus zwei Quellen mit gleichem Namen als eine zaehlt.

        Verschiedene Links beim selben Hoster (andere Media-ID) bleiben
        bewusst stehen: das sind eigene Uploads und dienen als Ausweich-
        moeglichkeit wenn einer tot ist.
        """
        seen = set()
        result = []
        for hoster in hosterList:
            try:
                link = hoster['link']
                # aniworld/serienstream/animetoast/burningseries: link = [url, name]
                if isinstance(link, list):
                    link = link[0] if link else ''
                if isinstance(link, str) and link.startswith('//'):
                    link = 'https:' + link
                key = (link, hoster.get('name', ''), hoster.get('languageCode', ''))
            except Exception:
                result.append(hoster)
                continue
            if not link:
                result.append(hoster)
                continue
            if key in seen:
                logger.info('-> [hoster]: doppelter Hoster verworfen: %s' % link)
                continue
            seen.add(key)
            result.append(hoster)
        return result

    def __getPriorities(self, hosterList, filter=True):
        # Hoster pruefen und sortieren (Reihenfolge: siehe sort_key unten).
        ranking = []

        # Import resolver module once (Python caches modules, re-importing in loop has no effect)
        try:
            import resolveurl as resolver_module
        except:
            import urlresolver as resolver_module

        for hoster in hosterList:
            # accept hoster which is marked as resolveable by sitePlugin
            if hoster.get('resolveable', False):
                ranking.append([0, hoster])
                continue

            try:
                # link kann [url, name] sein (aniworld/serienstream/animetoast/burningseries)
                link = hoster['link'][0] if isinstance(hoster['link'], list) else hoster['link']
                hmf = resolver_module.HostedMediaFile(url=link)
            except Exception as e:
                logger.error('-> [hoster]: getPriorities HostedMediaFile error: %s' % e)
                continue

            if not hmf.valid_url():
                hmf = resolver_module.HostedMediaFile(host=hoster['name'].lower(), media_id='dummy')

            resolvers = hmf.get_resolvers()
            if resolvers:
                priority = None
                for res in resolvers:
                    # prefer individual hoster priority over universal (debrid) priority
                    if not res.isUniversal():
                        priority = res._get_priority()
                        break
                    if priority is None:
                        priority = res._get_priority()
                if priority is not None:
                    ranking.append([priority, hoster])
            elif not filter:
                ranking.append([999, hoster])

        # Combined sort: Language (asc) -> Quality (desc) -> Resolver Priority (asc)
        has_language = any('languageCode' in hoster[1] for hoster in ranking)

        def sort_key(item):
            priority, hoster = item

            # 1) Language: ascending (lower code = preferred). Default 999 if no languageCode.
            lang = hoster.get('languageCode', 999) if has_language else 0

            # 2) Quality: hosters with quality info ranked higher than those without,
            #    untereinander absteigend nach Qualitaet (hoechste zuerst).
            has_qual = 'quality' in hoster
            if has_qual:
                qual_match = 0
                qual_value = -_quality_to_res(hoster['quality'])  # negativ = absteigend
            else:
                # No quality info: sort after hosters with known quality
                qual_match = 2
                qual_value = 0

            # 3) Resolver priority: ascending (lower = better)
            res_prio = priority

            return (lang, qual_match, qual_value, res_prio)

        try:
            ranking = sorted(ranking, key=sort_key)
        except Exception as e:
            logger.error('-> [hoster]: getPriorities sort error: %s' % e)

        return [hoster for _, hoster in ranking]

    def stream(self, playMode, siteName, function, url):
        self.dialog = xbmcgui.DialogProgress()
        self.dialog.create('xStream', cConfig().getLocalizedString(30138))
        self.dialog.update(5, cConfig().getLocalizedString(30139))
        plugin = __import__(siteName, globals(), locals())
        function = getattr(plugin, function)
        self.dialog.update(10, cConfig().getLocalizedString(30140))
        if url:
            siteResult = self._hosterLink(function, url)  # Hoster-Eintrag der Listenansicht
        else:
            siteResult = function()
        self.dialog.update(40)
        if not siteResult:
            self.dialog.close()
            cGui().showInfo('xStream', cConfig().getLocalizedString(30141))
            return
        if not type(siteResult) is list:
            temp = [siteResult]
            siteResult = temp
        # field "name" marks hosters
        if 'name' in siteResult[0]:
            functionName = siteResult[-1]
            del siteResult[-1]
            if not siteResult:
                self.dialog.close()
                cGui().showInfo('xStream', cConfig().getLocalizedString(30142))
                return

            # Dubletten raus bevor sortiert/angezeigt wird (gilt fuer alle Sites)
            siteResult = self._dedupeHosters(siteResult)

            self.dialog.update(60, cConfig().getLocalizedString(30143))
            # Hoster-Liste immer pruefen und sortieren. Das war frueher das
            # Setting 'presortHoster' (Default an); im Auto-Modus lief die
            # Sortierung ohnehin immer, jetzt ist das Verhalten ueberall gleich.
            siteResult = self.__getPriorities(siteResult)
            if not siteResult:
                self.dialog.close()
                cGui().showInfo('xStream', cConfig().getLocalizedString(30144))
                return False
            self.dialog.update(90)
            # Ungekuerzt: die Einstellung „Max Hoster Eintraege" (nur Liste und Dialog, Standard 100, die laengsten Listen
            # haben rund 8 Hoster) gibt es seit dem 01.11.2026 nicht mehr (so entschieden) — die besten stehen nach der Sortierung oben
            if cConfig().getSetting('hosterSelect') == 'List':
                self.showHosterFolder(siteResult, siteName, functionName)
                return
            if len(siteResult) > 1:
                siteResult = self._chooseHoster(siteResult)
                if not siteResult:
                    return
            else:
                siteResult = siteResult[0]
            logger.info(siteResult['link'])
            function = getattr(plugin, functionName)
            siteResult = self._hosterLink(function, siteResult['link'])
            if not type(siteResult) is list:
                temp = [siteResult]
                siteResult = temp
        if len(siteResult) > 1:
            siteResult = self._choosePart(siteResult)
            if not siteResult:
                logger.info('-> [hoster]: no part selected')
                return
        else:
            siteResult = siteResult[0]

        self.dialog = xbmcgui.DialogProgress()
        self.dialog.create('xStream', cConfig().getLocalizedString(30145))
        self.dialog.update(95, cConfig().getLocalizedString(30146))
        # ResolveURL reicht beim LETZTEN Resolver seiner Liste die Original-Exception
        # durch (hmf.py: log + raise) statt sie in einen ResolverError zu wandeln.
        # Ohne dieses Netz landet z.B. ein urllib HTTPError als Kodi-Skriptfehler
        # beim Nutzer. Bewusst NUR hier und nicht in _getInfoAndResolve: der
        # Auto-Weg (streamAuto -> __autoEnqueue) faengt selbst ab und probiert den
        # naechsten Hoster - dort wuerde eine Meldung je totem Hoster aufpoppen.
        # Es gibt nur noch Abspielen: playMode 'enqueue' (Zur Abspielliste hinzufuegen) ist seit dem
        # 01.11.2026 raus, ein Aufruf aus einem noch zwischengespeicherten Kontextmenue spielt deshalb ab.
        try:
            self.play(siteResult)
        except Exception as e:
            logger.error('-> [hoster]: %s: %s' % (type(e).__name__, e))
            if self.dialog:
                try:
                    self.dialog.close()
                except Exception:
                    pass
            cGui().showError('xStream', cConfig().getLocalizedString(30135), 7)

    def streamAuto(self, playMode, siteName, function):
        logger.info('-> [hoster]: auto stream initiated')
        self.dialog = xbmcgui.DialogProgress()
        self.dialog.create('xStream', cConfig().getLocalizedString(30138))
        self.dialog.update(5, cConfig().getLocalizedString(30139))
        plugin = __import__(siteName, globals(), locals())
        function = getattr(plugin, function)
        self.dialog.update(10, cConfig().getLocalizedString(30140))
        siteResult = function()
        if not siteResult:
            self.dialog.close()
            cGui().showInfo('xStream', cConfig().getLocalizedString(30141))
            return False
        if not type(siteResult) is list:
            temp = [siteResult]
            siteResult = temp
        # field "name" marks hosters
        if 'name' in siteResult[0]:
            self.dialog.update(90, cConfig().getLocalizedString(30143))
            functionName = siteResult[-1]
            del siteResult[-1]
            # Dubletten raus bevor sortiert/abgespielt wird (gilt fuer alle Sites)
            siteResult = self._dedupeHosters(siteResult)
            if siteName.startswith('dummy'):
                hosters = siteResult
            else:
                hosters = self.__getPriorities(siteResult)
            if not hosters:
                self.dialog.close()
                cGui().showInfo('xStream', cConfig().getLocalizedString(30144))
                return False
            # Im Auto-Modus wird BEWUSST nicht gekuerzt (schon vor dem Ausbau von maxHoster): er probiert
            # die Hoster der Reihe nach durch bis einer spielt, eine Begrenzung
            # nimmt ihm nur Ausweichkandidaten. Die frueher hier stehende Kuerzung
            # war ohnehin wirkungslos - sie traf siteResult, durchlaufen wird hosters.
            check = False
            self.dialog.create('xStream', cConfig().getLocalizedString(30147))
            total = len(hosters)
            for count, hoster in enumerate(hosters):
                if self.dialog.iscanceled() or xbmc.Monitor().abortRequested() or check: return
                if self._attempts:
                    # Ein Hoster wurde schon an den Player uebergeben und ist
                    # durchgefallen. Liess sich seine Adresse nicht oeffnen,
                    # zeigt Kodi das Fenster "Wiedergabe nicht moeglich" und
                    # wartet auf OK. Weil noch ein Hoster folgt, geht es sofort
                    # zu und blitzt nur kurz auf; play() schliesst es vor der
                    # Uebergabe ein zweites Mal, falls Kodi es erst nach diesem
                    # Aufruf zeichnet. Nach dem letzten Hoster bleibt es stehen.
                    xbmc.executebuiltin('Dialog.Close(okdialog,true)')
                percent = (count + 1) * 100 // total
                try:
                    logger.info('-> [hoster]: try hoster %s' % hoster['name'])
                    self.dialog.create('xStream', cConfig().getLocalizedString(30147))
                    self.dialog.update(percent, cConfig().getLocalizedString(30147) + ' %s' % hoster['name'])
                    function = getattr(plugin, functionName)
                    siteResult = self._hosterLink(function, hoster['link'])
                    check = self.__autoEnqueue(siteResult, playMode)
                    if check:
                        return True
                except:
                    self.dialog.update(percent, cConfig().getLocalizedString(30148) % hoster['name'])
                    logger.error('-> [hoster]: playback with hoster %s failed' % hoster['name'])
            # Kein Hoster hat gespielt. Kam ein Hoster bis zum Player, steht Kodis Fenster „Wiedergabe nicht moeglich" (oben);
            # gab es je totem Hoster eine Einblendung (_melden) oder eine des requestHandlers, reicht das. Blieb alles
            # still — jede Hosterlink-Funktion kam ohne Link zurueck —, sagt es diese eine Einblendung; Kodi zeigt fuer
            # den nicht aufgeloesten Eintrag danach sein eigenes Fenster (seit dem 02.11.2026).
            self.dialog.close()
            if not self._attempts and not self._gemeldet:
                cGui().showInfo('xStream', cConfig().getLocalizedString(30141))
            return False

    def _chooseHoster(self, siteResult):
        dialog = xbmcgui.Dialog()
        titles = []
        for result in siteResult:
            if 'displayedName' in result:
                titles.append(str(result['displayedName']))
            else:
                titles.append(str(result['name']))
        index = dialog.select(cConfig().getLocalizedString(30149), titles)
        if index > -1:
            siteResult = siteResult[index]
            return siteResult
        else:
            logger.info('-> [hoster]: no hoster selected')
            return False

    def _choosePart(self, siteResult):
        self.dialog = xbmcgui.Dialog()
        titles = []
        for result in siteResult:
            titles.append(str(result['title']))
        index = self.dialog.select(cConfig().getLocalizedString(30150), titles)
        if index > -1:
            siteResult = siteResult[index]
            return siteResult
        else:
            return False

    def showHosterFolder(self, siteResult, siteName, functionName):
        oGui = cGui()
        total = len(siteResult)
        params = ParameterHandler()
        for hoster in siteResult:
            if 'displayedName' in hoster:
                name = hoster['displayedName']
            else:
                name = hoster['name']
            oGuiElement = cGuiElement(name, siteName, functionName)
            oGuiElement.setThumbnail(str(params.getValue('thumb')))
            params.setParam('url', hoster['link'])
            params.setParam('isHoster', 'true')
            oGui.addFolder(oGuiElement, params, iTotal=total, isHoster=True)
        oGui.setEndOfDirectory()

    def __autoEnqueue(self, partList, playMode):
        # Spielt den Link, den die Hosterlink-Funktion der Site liefert; False laesst streamAuto den
        # naechsten Hoster nehmen. Weitere Teile eines Mehrteilers kamen bis zum 01.11.2026 in die
        # Abspielliste — der Weg ist mit „Zur Abspielliste hinzufuegen" raus; jede Site liefert genau
        # einen Link (alle 16 Hosterlink-Funktionen gezaehlt, 01.11.2026). playMode spielt keine Rolle
        # mehr, es gibt nur noch Abspielen (siehe stream).
        if not partList:
            return False
        try:
            if not self.play(partList[0]):
                return False
        except:
            return False
        logger.info('-> [hoster]: autoEnqueue successful')
        return True
