# -*- coding: utf-8 -*-
# Python 3

import re
import sys
import xbmc
import types
import xbmcgui
import os
import time
import json
import concurrent.futures
from resources.lib.handler.parameterHandler import ParameterHandler
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.handler.pluginHandler import cPluginHandler, STATUS_LABELS
from xbmc import executebuiltin
from resources.lib.gui.guiElement import cGuiElement
from resources.lib.gui.gui import cGui
from resources.lib.config import cConfig
from resources.lib.logger import logger
from resources.lib.tools import cParser, infoDialog
from resources.lib.cache import cCache
from xbmcvfs import translatePath

def _getResolver():
    """ResolveURL erst laden, wenn es wirklich gebraucht wird (Lazy Import).

    Der Import laedt alle Resolver-Plugins und kostet auf einer ARM-Box
    spuerbar Zeit; er lief bisher bei JEDEM Addon-Aufruf, auch bei reinen
    Listenansichten ohne Hoster. Gibt das Modul zurueck oder None, wenn
    ResolveURL fehlt/defekt ist (dann die gewohnte Fehlermeldung).
    """
    try:
        import resolveurl
        return resolveurl
    except ImportError:
        # Resolver Fehlermeldung (bei defekten oder nicht installierten Resolver)
        xbmcgui.Dialog().ok(cConfig().getLocalizedString(30119), cConfig().getLocalizedString(30120))
        return None



def viewInfo(params):
    from resources.lib.tmdb.info import WindowsBoxes
    parms = ParameterHandler()
    sCleanTitle = params.getValue('searchTitle')
    sMeta = parms.getValue('sMeta')
    sYear = parms.getValue('sYear')
    WindowsBoxes(sCleanTitle, sCleanTitle, sMeta, sYear)


def parseUrl():
    if xbmc.getInfoLabel('Container.PluginName') == 'plugin.video.osmosis':
        sys.exit()

    params = ParameterHandler()
    logger.info(params.getAllParameters())

    # If no function is set, we set it to the default "load" function
    if params.exist('function'):
        sFunction = params.getValue('function')
        if sFunction == 'spacer':
            return True
        elif sFunction == 'clearCache':
            cRequestHandler('dummy').clearCache()
            return
        elif sFunction == 'viewInfo':
            viewInfo(params)
            return
        elif sFunction == 'playTrailer':
            from resources.lib.trailer import playTrailer
            try:
                # Map prefLanguage setting to language code
                _pref = cConfig().getSetting('prefLanguage') or '0'
                _kodi_lang = xbmc.getLanguage(xbmc.ISO_639_1) or 'de'
                _lang_map = {'0': _kodi_lang, '1': 'de', '2': 'en', '3': 'ja'}
                _pref_lang = _lang_map.get(_pref, _kodi_lang)
                playTrailer(
                    tmdb_id=params.getValue('tmdb_id') or '',
                    mediatype=params.getValue('mediatype') or 'movie',
                    title=params.getValue('title') or '',
                    year=params.getValue('year') or '',
                    poster=params.getValue('poster') or '',
                    pref_lang=_pref_lang,
                )
            except Exception:
                import traceback
                logger.error('Trailer error: %s' % traceback.format_exc())
                cGui.showError('Trailer', 'Trailer-Suche fehlgeschlagen')
            return
        elif sFunction == 'searchAlter':
            _searchAlterGuarded(params)
            return
        elif sFunction == 'searchTMDB':
            searchTMDB(params)
            return
        elif sFunction == 'manualResolverUpdate':
            xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
            try:
                from resources.lib import updateManager
                updateManager.manualResolverUpdate()
            finally:
                xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
            return
        elif sFunction == 'pluginInfo':
            cPluginHandler().pluginInfo()
            return
        elif sFunction == 'changelog':
            changelog_path = os.path.join(translatePath('special://home/addons/%s/' % cConfig().getAddonInfo('id')), 'changelog.txt')
            if not os.path.isfile(changelog_path):
                infoDialog(cConfig().getLocalizedString(30822), icon='INFO')
                return
            with open(changelog_path, 'r', encoding='utf-8') as f:
                text = f.read()
            if not text.strip():
                infoDialog(cConfig().getLocalizedString(30821), icon='INFO')
            else:
                xbmcgui.Dialog().textviewer('Changelog', text)
            return
        elif sFunction == 'domainCheck':
            xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
            try:
                manualDomainCheck()
            finally:
                xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
            return
            
    elif params.exist('remoteplayurl'):
        resolver = _getResolver()
        if not resolver:
            return
        try:
            remotePlayUrl = params.getValue('remoteplayurl')
            sLink = resolver.resolve(remotePlayUrl)
            if sLink:
                # Nicht per Textbefehl starten: eine Klammer oder ein Komma in
                # der aufgeloesten Adresse wuerde `PlayMedia(...)` zerreissen
                # und der Aufruf liefe ins Leere. Ueber die Player-Schnittstelle
                # wird die Adresse als Wert uebergeben, nicht als Text.
                xbmc.Player().play(sLink, xbmcgui.ListItem(path=sLink))
            else:
                logger.debug('Could not play remote url %s' % sLink)
        except resolver.resolver.ResolverError as e:
            logger.error('ResolverError: %s' % e)
        return
    else:
        sFunction = 'load'

    # Test if we should run a function on a special site
    if not params.exist('site'):
        # As a default if no site was specified, we run the default starting gui with all plugins
        showMainMenu(sFunction)
        return
    sSiteName = params.getValue('site')
    if params.exist('playMode'):
        from resources.lib.gui.hoster import cHosterGui
        url = False
        playMode = params.getValue('playMode')
        isHoster = params.getValue('isHoster')
        url = params.getValue('url')
        manual = params.exist('manual')

        hosterSelect = cConfig().getSetting('hosterSelect')
        if hosterSelect == 'Auto' and not manual:
            cHosterGui().streamAuto(playMode, sSiteName, sFunction)
        else:
            cHosterGui().stream(playMode, sSiteName, sFunction, url)
        return

    logger.debug("Call function '%s' from '%s'" % (sFunction, sSiteName))
    # If the hoster gui is called, run the function on it and return
    if sSiteName == 'cHosterGui':
        showHosterGui(sFunction)
    # If global search is called
    elif sSiteName == 'globalSearch':
        searchterm = False
        if params.exist('searchterm'):
            searchterm = params.getValue('searchterm')
            logger.debug('found searchTermin')
        searchGlobal(searchterm)
    # Vavoo TV (eigenstaendiger Live-TV Bereich, Logik in resources/lib/vavoo/)
    elif sSiteName == 'vavootv':
        from resources.lib.vavoo import vavoo as vavootv
        vavootv.dispatch(sFunction, params)
    # TMDB Browser (eigenstaendiger Discovery-Bereich, keine Site — Logik in resources/lib/tmdb/browser.py)
    elif sSiteName == 'tmdb_browser':
        from resources.lib.tmdb import browser
        getattr(browser, sFunction)()
    elif sSiteName == 'xStream':
        # Nur den Settings-Dialog oeffnen, KEIN endOfDirectory:
        # Kodi bleibt dadurch in der aktuellen Liste (gleiches Muster wie
        # domainCheck/manualResolverUpdate/pluginInfo). Das fruehere
        # setEndOfDirectory + Action(ParentDir) erzeugte ein leeres Verzeichnis,
        # wenn ParentDir nicht griff (z.B. Android).
        cGui().openSettings()
    # ResolveURL Einstellungen (Einstellungen-Ordner)
    elif sSiteName == 'resolver':
        resolver = _getResolver()
        if resolver:
            resolver.display_settings()
    # Manuelles ResolveURL Update (Einstellungen-Ordner)
    # Fallback-Pfad: greift nur wenn URL ohne function= konstruiert wird (cGuiElement ohne setFunction).
    # Aktuelle Buttons setzen beides, daher wird dieser Pfad praktisch nicht erreicht -
    # bleibt aber als defensive Absicherung fuer die Dispatcher-Konsistenz.
    elif sSiteName == 'manualResolverUpdate':
        xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
        try:
            from resources.lib import updateManager
            updateManager.manualResolverUpdate()
        finally:
            xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
    # Plugin Infos    
    elif sSiteName == 'pluginInfo':
        cPluginHandler().pluginInfo()
    # Changelog anzeigen    
    elif sSiteName == 'changelog':
        from resources.lib import tools
        tools.changelog()
    # Manueller Domain Check
    # Fallback-Pfad: greift nur wenn URL ohne function= konstruiert wird (cGuiElement ohne setFunction).
    # Aktuelle Buttons setzen beides, daher wird dieser Pfad praktisch nicht erreicht -
    # bleibt aber als defensive Absicherung fuer die Dispatcher-Konsistenz.
    elif sSiteName == 'domainCheck':
        xbmc.executebuiltin('ActivateWindow(busydialognocancel)')
        try:
            manualDomainCheck()
        finally:
            xbmc.executebuiltin('Dialog.Close(busydialognocancel)')
    # Unterordner der Einstellungen   
    elif sSiteName == 'settings':
        oGui = cGui()
        for folder in settingsGuiElements():
            oGui.addFolder(folder)
        oGui.setEndOfDirectory()
    else:
        # Else load any other site as plugin and run the function
        plugin = __import__(sSiteName, globals(), locals())
        function = getattr(plugin, sFunction, None)
        # Site und Funktion stammen aus der aufgerufenen Adresse. Ohne Pruefung
        # waere ueber getattr JEDER Name im Modul erreichbar — auch interne
        # Helfer wie _search oder _buildHosters und alles Importierte
        # (cRequestHandler, logger, cParser). Statt einer Liste mit ueber
        # fuenfzig Namen, die bei jedem neuen Site-File nachgepflegt werden
        # muesste, pruefen wir drei Eigenschaften: oeffentlich, aufrufbar,
        # und im Site-File SELBST definiert (nicht importiert).
        # `types.FunctionType` statt nur `callable`: eine Klasse im Modul waere
        # ebenfalls aufrufbar und kaeme sonst durch.
        if (function is None or sFunction.startswith('_')
                or not isinstance(function, types.FunctionType)
                or getattr(function, '__module__', None) != plugin.__name__):
            logger.error('Unerlaubte Funktion "%s" fuer Site "%s"' % (sFunction, sSiteName))
            return
        function()
        # NOTABSCHLUSS: hat die Funktion eine "kein Inhalt"-Meldung ausgegeben
        # und danach nur mit return aufgehoert, fehlt Kodi das Verzeichnis-Ende.
        # Es meldet dann "GetDirectory failed" und wirft den Nutzer aus dem
        # Addon zurueck — statt eine leere Liste mit der Meldung zu zeigen. Das
        # betraf ueber hundert Stellen in allen Site-Files; der Abschluss hier
        # deckt sie auf einmal ab, auch kuenftige.
        # ABSICHTLICH an die Meldung gekoppelt und nicht pauschal: ein STILL
        # abgebrochener Aufruf (Tastatur mit Zurueck verlassen) gibt keine
        # Meldung aus und soll weiterhin zurueckspringen (Jacks Entscheidung
        # vom 10.08.2026), nicht in einer leeren Liste enden.
        if cGui._infoShown and not cGui._endSet:
            cGui().setEndOfDirectory()


def _statusMarker(sText):
    """Statustext fuers Hauptmenue: [Text] in der Schriftfarbe des Skins.

    Bewusst OHNE Faerbung: jeder feste Farbwert hat einen Skin, dessen
    Hintergrund ihn schluckt (Blau und Rot auf dem Estuary-Blau, Gelb auf hellen
    Skins) — und geschluckt wird dann das Wort selbst, also die Information. In
    der Textfarbe des Skins bleibt es ueberall lesbar; die eckigen Klammern heben
    es von den nackten Seitennamen ab, in derselben Form wie die
    Qualitaetskennung [HD] in den Titellisten. Kodi laesst Klammerpaare, die kein
    Markup-Tag sind, woertlich stehen. Gilt fuer alle Zustaende gleich, damit
    keine Rangfolge entsteht, die es nicht gibt.
    """
    return ' [%s]' % sText


def _siteStatusSuffix(sPluginId):
    """Status hinter dem Site-Namen im Hauptmenue — NUR bei Problemen.

    Der Statuscode steht schon in den Settings: cPluginHandler.checkDomain()
    schreibt ihn beim Kodi-Start (service.py, silent) und bei jedem manuellen
    Domain-Check. Hier wird nur gelesen, die Anzeige kostet also keinen Request.

    Bewusst wird NUR markiert, was nicht in Ordnung ist. Eine erreichbare Seite
    bekommt gar kein Suffix — das haelt die Liste ruhig. Ohne Status (Check
    abgeschaltet oder Service noch nicht durch) wird ebenfalls nichts angezeigt,
    weil "unbekannt" keine Warnung rechtfertigt.

    Die Zuordnung Wert -> Text steht in STATUS_LABELS (pluginHandler), damit
    Hauptmenue und Support-Info dieselbe Tabelle benutzen. Alles, was dort nicht
    steht, ist ein echter HTTP-Code: unter 400 in Ordnung, darueber ein Problem.
    """
    sStatus = cConfig().getSetting('plugin_' + sPluginId + '_status', '')
    if not sStatus:
        return ''                                   # nie geprueft -> keine Aussage
    sStatus = sStatus.strip()
    if sStatus in STATUS_LABELS:
        return _statusMarker(cConfig().getLocalizedString(STATUS_LABELS[sStatus]))
    try:
        iStatus = int(sStatus)
    except ValueError:
        return ''                                   # unbrauchbarer Wert -> keine Aussage
    if 200 <= iStatus < 400:
        return ''                                   # erreichbar -> Normalfall, nichts anzeigen
    if iStatus == 403:
        # 403 ohne erkanntes Schutzsystem: die Seite antwortet und sperrt uns aus,
        # nennt aber keinen Grund, den wir auswerten koennten.
        return _statusMarker(cConfig().getLocalizedString(30878))               # Blockiert
    return _statusMarker(cConfig().getLocalizedString(30870))                   # Offline


def showMainMenu(sFunction):
    ART = os.path.join(cConfig().getAddonInfo('path'), 'resources', 'art')
    addon_id = cConfig().getAddonInfo('id')
    start_time = time.time()
    # timeout for the startup status check  to make sure all is done
    while (startupStatus := cCache().get(addon_id + '_main', -1)) != 'finished' and time.time() - start_time <= 16:
        time.sleep(0.2)
    
    # Clear cached search texts so next search opens fresh keyboard
    xbmcgui.Window(10000).clearProperty('xstream.globalSearchText')
    xbmcgui.Window(10000).clearProperty('xstream.globalSearchResults')
    xbmcgui.Window(10000).clearProperty('xstream.alterSearchTitle')
    xbmcgui.Window(10000).clearProperty('xstream.alterSearchResults')
    xbmcgui.Window(10000).clearProperty('xstream.tmdb_browser.personQuery')

    oGui = cGui()

    # Vavoo TV ganz oben (ueber der globalen Suche), wenn aktiviert
    if cConfig().getSetting('vavooTvEnabled') == 'true':
        oGui.addFolder(vavooTvGuiElement())

    # Globale Suche fest an erster Stelle (nach Vavoo, kein Toggle mehr)
    oGui.addFolder(globalSearchGuiElement())

    # TMDB Browser fest direkt darunter (kein Toggle mehr)
    oGui.addFolder(tmdbBrowserGuiElement())

    oPluginHandler = cPluginHandler()
    aPlugins = oPluginHandler.getAvailablePlugins()
    if not aPlugins:
        logger.debug('No activated Plugins found')
        oGui.openSettings()
        oGui.updateDirectory()
    else:
        for aPlugin in sorted(aPlugins, key=lambda k: k['id']):
            oGuiElement = cGuiElement()
            oGuiElement.setTitle(aPlugin['name'] + _siteStatusSuffix(aPlugin['id']))
            oGuiElement.setSiteName(aPlugin['id'])
            oGuiElement.setFunction(sFunction)
            if 'icon' in aPlugin and aPlugin['icon']:
                oGuiElement.setThumbnail(aPlugin['icon'])
            oGui.addFolder(oGuiElement)

    # Einstellungen als Ordner mit Untereinstellungen (fester Bestandteil — kein Toggle mehr)
    oGuiElement = cGuiElement()
    oGuiElement.setTitle(cConfig().getLocalizedString(30041))
    oGuiElement.setSiteName('settings')
    oGuiElement.setFunction('showSettingsFolder')
    oGuiElement.setThumbnail(os.path.join(ART, 'settings.png'))
    oGui.addFolder(oGuiElement)
    oGui.setEndOfDirectory(pCacheToDisc=False) # caching will break global search!
def settingsGuiElements():
    ART = os.path.join(cConfig().getAddonInfo('path'), 'resources', 'art')

    # Reihenfolge im Einstellungen-Ordner: Info, dann die beiden Aktionen
    # (Domain Check, ResolveURL Update), zuletzt die beiden Einstellungsdialoge.

    # GUI Plugin Informationen
    oGuiElement = cGuiElement()
    oGuiElement.setTitle(cConfig().getLocalizedString(30267))
    oGuiElement.setSiteName('pluginInfo')
    oGuiElement.setFunction('pluginInfo')
    oGuiElement.setThumbnail(os.path.join(ART, 'plugin_info.png'))
    PluginInfo = oGuiElement

    # GUI Manueller Domain Check
    oGuiElement = cGuiElement()
    oGuiElement.setTitle(cConfig().getLocalizedString(30818))
    oGuiElement.setSiteName('domainCheck')
    oGuiElement.setFunction('domainCheck')
    oGuiElement.setThumbnail(os.path.join(ART, 'domain_check.png'))
    DomainCheck = oGuiElement

    # GUI ResolveURL Update
    oGuiElement = cGuiElement()
    oGuiElement.setTitle(cConfig().getLocalizedString(30121))
    oGuiElement.setSiteName('manualResolverUpdate')
    oGuiElement.setFunction('manualResolverUpdate')
    oGuiElement.setThumbnail(os.path.join(ART, 'resolveurl_update.png'))
    DevUpdateMan = oGuiElement

    # GUI xStream Einstellungen
    oGuiElement = cGuiElement()
    oGuiElement.setTitle(cConfig().getLocalizedString(30042))
    oGuiElement.setSiteName('xStream')
    oGuiElement.setFunction('display_settings')
    oGuiElement.setThumbnail(os.path.join(ART, 'xstream_settings.png'))
    xStreamSettings = oGuiElement

    # GUI ResolveURL Einstellungen
    oGuiElement = cGuiElement()
    oGuiElement.setTitle(cConfig().getLocalizedString(30043))
    oGuiElement.setSiteName('resolver')
    oGuiElement.setFunction('display_settings')
    oGuiElement.setThumbnail(os.path.join(ART, 'resolveurl_settings.png'))
    resolveurlSettings = oGuiElement

    return PluginInfo, DomainCheck, DevUpdateMan, xStreamSettings, resolveurlSettings


def manualDomainCheck():
    cPluginHandler().checkDomain()
    # Plugin-Daten aktualisieren mit neuen Domains
    cPluginHandler().getAvailablePlugins()


def globalSearchGuiElement():
    ART = os.path.join(cConfig().getAddonInfo('path'), 'resources', 'art')

    oGuiElement = cGuiElement()
    oGuiElement.setTitle(cConfig().getLocalizedString(30040))
    oGuiElement.setSiteName('globalSearch')
    oGuiElement.setFunction('globalSearch')
    oGuiElement.setThumbnail(os.path.join(ART, 'search.png'))
    return oGuiElement


def tmdbBrowserGuiElement():
    ART = os.path.join(cConfig().getAddonInfo('path'), 'resources', 'art')

    # Create a gui element for TMDB-based discovery (Bridge zu searchAlter / 'Weitere Quellen')
    oGuiElement = cGuiElement()
    oGuiElement.setTitle('TMDB Browser')
    oGuiElement.setSiteName('tmdb_browser')
    oGuiElement.setFunction('load')
    oGuiElement.setThumbnail(os.path.join(ART, 'tmdb_browser.png'))
    return oGuiElement


def vavooTvGuiElement():
    ART = os.path.join(cConfig().getAddonInfo('path'), 'resources', 'art')

    # Eigenstaendiger Live-TV Menuepunkt (Vavoo). Laedt direkt in die Laenderliste.
    # Eigene Logik in resources/lib/vavoo/, Dispatch ueber site=vavootv in parseUrl().
    oGuiElement = cGuiElement()
    oGuiElement.setTitle(cConfig().getLocalizedString(30842))
    oGuiElement.setSiteName('vavootv')
    oGuiElement.setFunction('load')
    oGuiElement.setThumbnail(os.path.join(ART, 'vavoo.png'))
    return oGuiElement


def showHosterGui(sFunction):
    from resources.lib.gui.hoster import cHosterGui
    oHosterGui = cHosterGui()
    function = getattr(oHosterGui, sFunction)
    function()
    return True


def _serializeSearchResults(results):
    """Serialize search results list to a JSON string for Window property caching."""
    serialized = []
    for result in results:
        serialized.append({
            'guiElement': result['guiElement'].to_dict(),
            'params': result['params'].to_dict() if hasattr(result['params'], 'to_dict') else {},
            'isFolder': result['isFolder'],
        })
    return json.dumps(serialized, ensure_ascii=False)


def _deserializeSearchResults(data):
    """Reconstruct search results list from a cached JSON string."""
    results = []
    for entry in json.loads(data):
        results.append({
            'guiElement': cGuiElement.from_dict(entry['guiElement']),
            'params': ParameterHandler.from_dict(entry['params']),
            'isFolder': entry['isFolder'],
        })
    return results


def _completedOrAborted(futures, dialog):
    """Fertige Aufgaben liefern und dabei regelmaessig auf Abbruch pruefen.

    `as_completed` gibt erst etwas zurueck, wenn eine Seite geantwortet hat —
    eine Abbruchpruefung INNERHALB dieser Schleife kommt also gar nicht dran,
    solange alle Seiten noch laden. Bei einer traegen Seite wartet der Nutzer
    dann bis zu deren Zeitlimit, obwohl er laengst abgebrochen hat.

    Deshalb hier `wait()` mit kurzem Zeitfenster: alle 0,3 Sekunden wird
    geprueft, ob abgebrochen wurde, unabhaengig davon ob schon etwas fertig ist.
    Der Generator endet dann sofort; der Aufrufer erkennt den Abbruch an
    `dialog.iscanceled()`.
    """
    aPending = set(futures)
    while aPending:
        if dialog.iscanceled():
            return
        aDone, aPending = concurrent.futures.wait(
            aPending, timeout=0.3, return_when=concurrent.futures.FIRST_COMPLETED)
        for oFuture in aDone:
            yield oFuture


def _preloadMeta(aResults):
    """Metadaten aller Treffer vorab parallel holen.

    Die Anzeigeschleife ruft ueber `addFolder` fuer JEDEN Treffer `getMeta` auf,
    und das ist je Eintrag eine TMDB-Abfrage. Nacheinander summiert sich das:
    gemessen rund 2,8 s fuer 20 Treffer, bei traegen Antworten deutlich mehr.
    Parallel sind es 0,2 s.

    `getMeta` setzt dabei selbst `_isMetaSet`, deshalb ueberspringt `addFolder`
    den Abruf danach komplett — es wird nichts doppelt geholt.

    WICHTIG `submit` statt `map`: bei `map` fliegt die erste Exception beim
    Iterieren weiter und reisst den ganzen Vorlauf mit. Jedes Ergebnis wird
    deshalb einzeln abgefangen. Nebeneffekt, der ein bestehendes Problem loest:
    vorher brach ein einzelner fehlgeschlagener Abruf die komplette
    Anzeigeschleife ab, die restlichen Treffer erschienen dann gar nicht.
    """
    aNeeded = [r['guiElement'] for r in aResults
               if getattr(r['guiElement'], '_mediaType', '')
               and not getattr(r['guiElement'], '_isMetaSet', False)]
    if not aNeeded:
        return
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(aNeeded))) as executor:
            aFutures = [executor.submit(oElement.getMeta, oElement._mediaType, mode='add')
                        for oElement in aNeeded]
            for oFuture in aFutures:
                try:
                    oFuture.result()
                except Exception:
                    pass        # ein gescheiterter Abruf darf die uebrigen nicht mitreissen
    except Exception as e:
        logger.error('Meta-Vorlauf fehlgeschlagen: %s' % e)


def _canGoBack(params):
    """Darf Kodi nach dem Abbruch eine Ebene zurueckspringen?

    `setEndOfDirectory(False)` meldet einen gescheiterten Aufruf — Kodi geht
    dann von selbst zurueck, statt ein leeres Verzeichnis anzuzeigen. Das ist
    das angenehmere Verhalten, setzt aber voraus, dass es ueberhaupt eine Ebene
    darueber GIBT.

    Kommt der Aufruf aus einem VERZEICHNIS (Hauptmenue, TMDB-Browser-Liste),
    ist das der Fall. Kommt er aus dem KONTEXTMENUE („Weitere Quellen"), nicht —
    Kodi wirft den Nutzer dann komplett aus dem Addon. Genau das ist am 10.08
    passiert, als hier pauschal False stand.

    Unterschieden wird am `site`-Parameter: Verzeichniseintraege bekommen ihn
    ueber `__createItemUrl` mitgegeben, das Kontextmenue baut seine URL von Hand
    und ohne. `searchAlter` ist die einzige Funktion mit beiden Aufrufwegen.
    """
    return bool(params.getValue('site'))


def _abortSearch(executor, futures, oGui, bCanGoBack=False):
    """Suche abbrechen, ohne auf die laufenden Threads zu warten.

    Ein `return` aus dem `with`-Block heraus ruft `shutdown(wait=True)` auf —
    Python wartet dann auf ALLE zehn Suchthreads, obwohl der Nutzer schon
    abgebrochen hat. Bei langsamen Seiten haengt das Skript dadurch weiter,
    und Kodi bricht es womoeglich mitten im Aufraeumen ab.

    Deshalb hier: noch nicht gestartete Aufgaben verwerfen, dann ohne Warten
    beenden. Bereits laufende Threads laufen zu Ende — abbrechen kann Python
    sie nicht —, aber das Skript kehrt sofort zurueck.

    Den Dialog schliesst der aufrufende finally-Zweig, nicht diese Funktion.

    Ob Kodi danach zurueckspringt oder ein leeres Verzeichnis zeigt, entscheidet
    `bCanGoBack` — siehe `_canGoBack` oben.
    """
    for oFuture in futures:
        oFuture.cancel()
    try:
        executor.shutdown(wait=False)
    except Exception:
        pass
    oGui.setEndOfDirectory(not bCanGoBack)


def searchGlobal(sSearchText=False):
    """Globale Suche — setzt das Sammel-Flag in jedem Fall zurueck.

    Das Flag unterdrueckt waehrend der Suche die "Keine Eintraege"-Meldung
    der einzelnen Seiten. Frueher wurde es nur auf den regulaeren Wegen
    zurueckgesetzt: brach die Suche mit einer Ausnahme ab, blieb es gesetzt
    und die Meldung fehlte anschliessend auch bei normalen Aufrufen.
    """
    try:
        return _searchGlobal(sSearchText)
    finally:
        cGui._globalSearch = False


def _searchGlobal(sSearchText=False):
    oGui = cGui()
    # Global Search aktiv — unterdrueckt die "Keine Eintraege"-Meldung je Seite
    cGui._globalSearch = True
    oGui.globalSearch = True
    win = xbmcgui.Window(10000)

    if not sSearchText:
        # Check if we have a cached search text (e.g. coming back from playback)
        sSearchText = win.getProperty('xstream.globalSearchText')

        if sSearchText:
            # We have a cached search term — try to load cached results
            cachedResults = win.getProperty('xstream.globalSearchResults')
            if cachedResults:
                try:
                    results = _deserializeSearchResults(cachedResults)
                    total = len(results)
                    _preloadMeta(results)
                    for result in sorted(results, key=lambda k: k['guiElement'].getSiteName()):
                        oGui.addFolder(result['guiElement'], result['params'], bIsFolder=result['isFolder'], iTotal=total)
                    cGui._globalSearch = False
                    oGui.setView()
                    oGui.setEndOfDirectory()
                    return True
                except Exception:
                    import traceback
                    logger.error('Search cache restore failed: %s' % traceback.format_exc())
                    # Cache broken — fall through to fresh search
                    win.clearProperty('xstream.globalSearchResults')

        if not sSearchText:
            sSearchText = oGui.showKeyBoard(sHeading=cConfig().getLocalizedString(30280))
        if not sSearchText:
            # Abbruch/leere Eingabe: KEIN endOfDirectory, sonst landet man
            # in einem leeren Verzeichnis - Kodi bleibt so in der aktuellen Liste.
            cGui._globalSearch = False
            return True

    # New search — clear old cached results
    win.clearProperty('xstream.globalSearchResults')
    win.setProperty('xstream.globalSearchText', sSearchText)

    oGui._collectMode = True

    aPlugins = cPluginHandler().getAvailablePlugins()
    dialog = xbmcgui.DialogProgress()
    dialog.create(cConfig().getLocalizedString(30122), cConfig().getLocalizedString(30123))

    numPlugins = len(aPlugins)
    searchablePlugins = [pluginEntry for pluginEntry in aPlugins if pluginEntry['globalsearch'] not in ['false', '']]

    def worker(pluginEntry):
        logger.debug('Searching for %s at %s' % (sSearchText, pluginEntry['id']))
        _pluginSearch(pluginEntry, sSearchText, oGui)
        return pluginEntry['name']

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
    try:
        future_to_plugin = {executor.submit(worker, pluginEntry): pluginEntry for pluginEntry in searchablePlugins}

        for count, future in enumerate(_completedOrAborted(future_to_plugin, dialog)):
            pluginEntry = future_to_plugin[future]
            if dialog.iscanceled():
                _abortSearch(executor, future_to_plugin, oGui, True)
                return
            try: pluginName = future.result()
            except Exception as e:
                pluginName = pluginEntry['name']
                logger.error(f"Fehler bei Plugin {pluginName}: {str(e)}")
            progress = (count + 1) * 50 // len(searchablePlugins)
            dialog.update(progress, pluginName + cConfig().getLocalizedString(30125))
        if dialog.iscanceled():
            _abortSearch(executor, future_to_plugin, oGui, True)
            return
        executor.shutdown(wait=True)
    finally:
        # Der Dialog muss auch dann weg, wenn oben etwas schiefgeht — sonst
        # bleibt der Fortschrittsbalken stehen, bis Kodi ihn selbst aufraeumt.
        dialog.close()

    # Cache the results for re-use when navigating back
    try:
        win.setProperty('xstream.globalSearchResults', _serializeSearchResults(oGui.searchResults))
    except Exception:
        import traceback
        logger.error('Search cache save failed: %s' % traceback.format_exc())

    oGui._collectMode = False
    total = len(oGui.searchResults)
    if not total:
        # Waehrend des Sammelns sind die Meldungen der einzelnen Seiten bewusst
        # unterdrueckt (siehe cGui.showInfo). Liefert am Ende keine Seite etwas,
        # stand hier ein leeres Verzeichnis ohne jeden Hinweis (Audit 01.09.2026).
        # Der Schutz wird deshalb vor der Meldung zurueckgenommen.
        cGui._globalSearch = False
        oGui.showInfo()
    _preloadMeta(oGui.searchResults)
    dialog = xbmcgui.DialogProgress()
    dialog.create(cConfig().getLocalizedString(30126), cConfig().getLocalizedString(30127))

    try:
        for count, result in enumerate(sorted(oGui.searchResults, key=lambda k: k['guiElement'].getSiteName()), 1):
            if dialog.iscanceled():
                oGui.setEndOfDirectory(False)   # aus dem Menue aufgerufen — Kodi springt zurueck
                return
            oGui.addFolder(result['guiElement'], result['params'], bIsFolder=result['isFolder'], iTotal=total)
            dialog.update(count * 100 // total, str(count) + cConfig().getLocalizedString(30128) + str(total) + ': ' + result['guiElement'].getTitle())
    finally:
        # Auch hier gilt: das return oben darf den Dialog nicht stehen lassen.
        dialog.close()
    oGui.setView()
    oGui.setEndOfDirectory()
    return True

def _normalizeSearchTitle(sTitle):
    """Titel fuer den Vergleich in searchAlter angleichen.

    Delegiert an cParser.normalizeTitle (tools.py) — dort stehen die Regeln; dieselbe
    Angleichung gilt seit dem 02.09.2026 auch fuer die Titelfilter der Site-Suchen.
    Anlass: der Filter hier verglich zeichengenau — "iZombie" aus dem TMDb-Browser
    fand serienstreams "IZombie" nicht, "Dr. House" nicht "Dr House", "Spider-Man"
    nicht "Spider Man". Gemessen am 01.09.2026 ueber 13 Titel: 595 Treffer mit dem
    alten Vergleich, 736 mit dem normalisierten — ohne Verlust, die alte Menge bleibt
    enthalten. Das Ergebnis dient NUR dem Vergleich, angezeigt wird der Originaltitel.
    """
    return cParser.normalizeTitle(sTitle)


def _searchAlterGuarded(params):
    """searchAlter mit Sicherheitsnetz fuer den Sammel-Schutz.

    cGui._globalSearch ist ein KLASSENattribut und lebt laenger als der Aufruf.
    Bricht die Suche mit einer Ausnahme ab, bliebe es gesetzt und die Meldung
    „Es wurde kein Eintrag gefunden" fehlte anschliessend auch bei normalen
    Aufrufen. Gleiches Muster wie bei der globalen Suche.
    """
    try:
        return searchAlter(params)
    finally:
        cGui._globalSearch = False


def searchAlter(params):
    """Weitere Quellen: denselben Titel auf allen aktivierten Seiten suchen.

    Der Sammel-Schutz (cGui._globalSearch) wird wie bei der globalen Suche
    gesetzt: waehrend gesammelt wird, meldet keine einzelne Seite ihren
    Nulltreffer. Sonst stand die Meldung "Es wurde kein Eintrag gefunden" ueber
    einer Liste mit Treffern — belegt am 01.09.2026 mit 14 Treffern aus fuenf
    Seiten. Zurueckgesetzt wird im finally des Aufrufers _searchAlterGuarded.
    """
    searchTitle = params.getValue('searchTitle')
    searchImdbId = params.getValue('searchImdbID')
    cGui._globalSearch = True

    # Klammer-Jahr vom Titel abschneiden (Jahr wird nicht mehr gefiltert)
    if ' (19' in searchTitle or ' (20' in searchTitle:
        isMatch, aYear = cParser.parse(searchTitle, r'(.*?) \((\d{4})\)')
        if isMatch:
            searchTitle = aYear[0][0]

    # Zusaetze aus dem Listen-Label abschneiden, sonst suchen die Seiten damit:
    # Staffelkennung in beiden Formen der Seiten ("Name - Staffel 3" bei hdfilme,
    # kkiste, kinoger, megakino; "Name - 2 Staffel" bei megakino), die Folgenkennung
    # "(S05E01) [DE]" der Neuste-Episoden-Liste von serienstream (Ger-Dub/Sub und die S01E02-Form
    # erledigen die Helfer darunter). Mindestens ein Zeichen bleibt stehen, ein nacktes "Staffel 1" wird
    # nicht leer; \b verhindert, dass "Staffeln" trifft. Vorher standen hier die Tokens
    # ' - Staffel' und ' Staffel': bei "The Gentlemen - 2 Staffel" blieb "The Gentlemen - 2"
    # und Weitere Quellen fand 3 statt 27 Treffer, bei "Fauda (S05E01) [DE]" 0 statt 4
    # (gemessen 08.09.2026 ueber 9.569 Kontexttitel aller Seiten und Ebenen).
    searchTitle = re.sub(r'^(.+?)\s*-?\s*(?:\d+\s*Staffel\b|Staffel\s*\d+|\(S\d+E\d+\)).*$', r'\1', searchTitle).strip()
    # Englische Staffelformen samt S01E02, danach die Zusaetze der Seite (Alternativname hinter „ | ",
    # Sternchen-Anmerkung, Sprach-, Kuerzel-, Typ- und Fassungs-Klammer) — in DIESER Reihenfolge, sonst
    # bleibt bei „… Gaiden (TV) 2nd Season Ger Sub" das „(TV)" stehen, das erst der Staffelschnitt ans Ende
    # bringt. Beides steht EINMAL in cParser, die TMDB-Namenssuche (Trailer, TMDB-Info) nutzt dieselben Helfer.
    searchTitle = cParser.stripSeasonForms(searchTitle)
    searchTitle = cParser.stripTitleNotes(searchTitle)
    oGui = cGui()
    oGui.globalSearch = True
    win = xbmcgui.Window(10000)

    # Cache prüfen: gleicher Titel wie letztes Mal?
    cachedTitle = win.getProperty('xstream.alterSearchTitle')
    if cachedTitle == searchTitle:
        cachedResults = win.getProperty('xstream.alterSearchResults')
        if cachedResults:
            try:
                results = _deserializeSearchResults(cachedResults)
                total = len(results)
                _preloadMeta(results)
                for result in sorted(results, key=lambda k: k['guiElement'].getSiteName()):
                    oGui.addFolder(result['guiElement'], result['params'], bIsFolder=result['isFolder'], iTotal=total)
                oGui.setView()
                oGui.setEndOfDirectory()
                return True
            except Exception:
                import traceback
                logger.error('Alter search cache restore failed: %s' % traceback.format_exc())
                win.clearProperty('xstream.alterSearchResults')

    # Neuer Titel oder kein Cache — neue Suche starten
    win.clearProperty('xstream.alterSearchResults')
    win.setProperty('xstream.alterSearchTitle', searchTitle)

    oGui._collectMode = True
    aPlugins = cPluginHandler().getAvailablePlugins()

    dialog = xbmcgui.DialogProgress()
    dialog.create(cConfig().getLocalizedString(30122), cConfig().getLocalizedString(30123))

    searchablePlugins = [
        pluginEntry for pluginEntry in aPlugins
        if pluginEntry['globalsearch'] not in ['false', '']
    ]

    def worker(pluginEntry):
        logger.debug('Searching for ' + searchTitle + pluginEntry['id'])
        _pluginSearch(pluginEntry, searchTitle, oGui)
        return pluginEntry['name']

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
    try:
        future_to_plugin = {executor.submit(worker, plugin): plugin for plugin in searchablePlugins}

        for count, future in enumerate(_completedOrAborted(future_to_plugin, dialog)):
            plugin = future_to_plugin[future]
            if dialog.iscanceled():
                _abortSearch(executor, future_to_plugin, oGui, _canGoBack(params))
                return
            try:
                name = future.result()
            except Exception as e:
                name = plugin['name']
                logger.error(f"Fehler bei Plugin {name}: {str(e)}")
            dialog.update((count + 1) * 50 // len(searchablePlugins) + 50, name + cConfig().getLocalizedString(30125))
        if dialog.iscanceled():
            _abortSearch(executor, future_to_plugin, oGui, _canGoBack(params))
            return
        executor.shutdown(wait=True)
    finally:
        dialog.close()

    # Ergebnisse filtern — angeglichen auf beiden Seiten, siehe _normalizeSearchTitle.
    # Der Filter bleibt als Sicherung gegen unscharfe Serverantworten (bei „Léon"
    # liefern die Seiten 110 Rohtreffer bis hin zu Napoleon, 17 tragen den Titel).
    sNormSearch = _normalizeSearchTitle(searchTitle)
    filteredResults = []
    for result in oGui.searchResults:
        guiElement = result['guiElement']
        logger.debug('Site: %s Titel: %s' % (guiElement.getSiteName(), guiElement.getTitle()))
        if sNormSearch not in _normalizeSearchTitle(guiElement.getTitle()):
            continue
        if searchImdbId and guiElement.getItemProperties().get('imdbID') != searchImdbId:
            continue
        filteredResults.append(result)

    try:
        win.setProperty('xstream.alterSearchResults', _serializeSearchResults(filteredResults))
    except Exception:
        import traceback
        logger.error('Alter search cache save failed: %s' % traceback.format_exc())

    oGui._collectMode = False
    # Sammeln ist durch: ab hier darf wieder gemeldet werden. Bleibt am Ende
    # nichts uebrig, kommt die Meldung von uns — waehrend des Sammelns haette
    # sie ueber einer Liste mit Treffern gestanden.
    cGui._globalSearch = False
    total = len(filteredResults)
    if not total:
        oGui.showInfo()
    _preloadMeta(filteredResults)
    for result in sorted(filteredResults, key=lambda k: k['guiElement'].getSiteName()):
        oGui.addFolder(result['guiElement'], result['params'], bIsFolder=result['isFolder'], iTotal=total)

    oGui.setView()
    oGui.setEndOfDirectory()
    # Ein `Container.Update` OHNE Adresse stand hier: Kodi wies ihn bei jeder
    # Suche als ungueltig ab („container.update called with invalid number of
    # parameters") und tat nichts — die Liste steht mit setEndOfDirectory.
    return True

def searchTMDB(params):
    sSearchText = params.getValue('searchTitle')
    oGui = cGui()
    oGui.globalSearch = True
    oGui._collectMode = True

    if not sSearchText:
        oGui.setEndOfDirectory()
        return True

    aPlugins = cPluginHandler().getAvailablePlugins()

    dialog = xbmcgui.DialogProgress()
    dialog.create(cConfig().getLocalizedString(30122), cConfig().getLocalizedString(30123))

    searchablePlugins = [
        pluginEntry for pluginEntry in aPlugins
        if pluginEntry['globalsearch'] != 'false'
    ]

    def worker(pluginEntry):
        logger.debug('Searching for %s at %s' % (sSearchText, pluginEntry['id']))
        _pluginSearch(pluginEntry, sSearchText, oGui)
        return pluginEntry['name']

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=10)
    try:
        future_to_plugin = {executor.submit(worker, plugin): plugin for plugin in searchablePlugins}

        for count, future in enumerate(_completedOrAborted(future_to_plugin, dialog)):
            plugin = future_to_plugin[future]
            if dialog.iscanceled():
                _abortSearch(executor, future_to_plugin, oGui)
                return
            try:
                name = future.result()
            except Exception as e:
                name = plugin['name']
                logger.error(f"Fehler bei Plugin {name}: {str(e)}")
            dialog.update((count + 1) * 50 // len(searchablePlugins) + 50, name + cConfig().getLocalizedString(30125))
        if dialog.iscanceled():
            _abortSearch(executor, future_to_plugin, oGui)
            return
        executor.shutdown(wait=True)
    finally:
        dialog.close()

    oGui._collectMode = False
    total = len(oGui.searchResults)
    _preloadMeta(oGui.searchResults)

    dialog = xbmcgui.DialogProgress()
    dialog.create(cConfig().getLocalizedString(30126), cConfig().getLocalizedString(30127))

    try:
        for count, result in enumerate(sorted(oGui.searchResults, key=lambda k: k['guiElement'].getSiteName()), 1):
            if dialog.iscanceled():
                oGui.setEndOfDirectory()
                return
            oGui.addFolder(result['guiElement'], result['params'], bIsFolder=result['isFolder'], iTotal=total)
            dialog.update(count * 100 // total, str(count) + cConfig().getLocalizedString(30128) + str(total) + ': ' + result['guiElement'].getTitle())
    finally:
        # Auch hier gilt: das return oben darf den Dialog nicht stehen lassen.
        dialog.close()
    oGui.setView()
    oGui.setEndOfDirectory()
    return True


def _pluginSearch(pluginEntry, sSearchText, oGui):
    try:
        plugin = __import__(pluginEntry['id'], globals(), locals())
        function = getattr(plugin, '_search')
        function(oGui, sSearchText)
    except Exception:
        logger.error(pluginEntry['name'] + ': search failed')
        import traceback
        logger.error(traceback.format_exc())
