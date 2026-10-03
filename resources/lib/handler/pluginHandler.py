# -*- coding: utf-8 -*-
# Python 3

import json
import os
import sys
import time
import xbmc

from resources.lib.config import cConfig
from resources.lib.logger import logger
from resources.lib import utils
from resources.lib.handler.requestHandler import cRequestHandler
from urllib.parse import urlparse
from xbmcgui import Dialog
from xbmcvfs import translatePath
from resources.lib.tools import platform, infoDialog, getDNS, getRepofromAddonsDB


# Eigencodes im Statusfeld `plugin_<site>_status`. Es haelt normalerweise den
# HTTP-Code der Startseite; die Lagen, die KEINEN aussagekraeftigen Code haben,
# bekommen einen eigenen negativen Wert (kein gueltiger HTTP-Code, deshalb
# kollisionsfrei). Die Anzeige-Zuordnung steht in STATUS_LABELS darunter.
STATUS_TIMEOUT = '-1'      # Server nimmt an und antwortet nicht (langsam, nicht tot)
STATUS_DDOS = '-2'         # DDoS-Guard-Sperre erkannt
STATUS_NO_CONNECT = '-3'   # gar keine Antwort: Verbindungsabbruch, DNS, TLS
STATUS_CLOUDFLARE = '-4'   # Cloudflare-Challenge erkannt
STATUS_OFFLINE_DNS = '-5'  # Domain existiert nicht mehr (DNS: Name unbekannt)
STATUS_UNKNOWN = '0'       # unerwarteter Fehler, Lage unbekannt

# Anzeige-Tabelle fuer die Eigencodes: Wert -> String-ID des Anzeigetexts. Beide
# Anzeigen — das Hauptmenue (xstream.py:_siteStatusSuffix) und die Support-Info
# (__getPluginDataIndex) — lesen diese Tabelle, damit ein neuer Wert nur an EINER
# Stelle gepflegt wird. Echte HTTP-Codes stehen bewusst nicht drin, die werden
# nach Bereich bewertet. Farben gibt es bewusst keine (Begruendung bei
# xstream.py:_statusMarker).
STATUS_LABELS = {
    STATUS_TIMEOUT:     30872,   # Timeout
    STATUS_DDOS:        30876,   # DDoS-Guard
    STATUS_NO_CONNECT:  30877,   # Verbindungsfehler
    STATUS_CLOUDFLARE:  30869,   # CloudFlare
    STATUS_OFFLINE_DNS: 30870,   # Offline — die Domain gibt es nicht mehr
    STATUS_UNKNOWN:     30879,   # Unbekannter Fehler
}

ADDON_PATH = translatePath(os.path.join('special://home/addons/', '%s'))


# ═══════════════════════════════════════════════════════════════════════
#   Wrong-Domain-Erkennung
# ═══════════════════════════════════════════════════════════════════════
#
# Domains auf die Sites NICHT redirecten sollen — wenn der Domain-Check
# einen Redirect dahin sieht, wird der Eintrag verworfen statt gespeichert.
# Zwei Listen:
#   - WRONG_DOMAINS_EXACT: nur exakte Domain-Matches (kein Pattern-Block,
#     verhindert Falsch-Positives wie z.B. "mysite-maps.cc" wo der Substring
#     in einem legit Hostname auftaucht)
#   - WRONG_DOMAIN_PATTERNS: Substring-Match — fuer DNS-Block-Familien wo
#     ALLE Subdomains/Variationen geblockt werden sollen.

WRONG_DOMAINS_EXACT = (
    'site-maps.cc',                    # Generischer Stub-Page Redirect
)

WRONG_DOMAIN_PATTERNS = (
    'cuii.info',                       # CUII DNS-Sperre Deutschland
    'drei.at',                         # Drei.at DNS-Sperre Oesterreich
    'magenta',                         # Magenta DNS-Sperre
    'telekom',                         # Telekom DNS-Sperre
    'vodafone',                        # Vodafone DNS-Sperre
    'alliance4creativity',             # ACE Anti-Piracy Takedown
    'streamingunity',                  # Streamingunity-Familie
)


def _isWrongDomain(domain):
    """Pruefen ob eine Domain als wrongDomain gilt.

    Returns True bei exaktem Match in WRONG_DOMAINS_EXACT oder bei
    Substring-Match in WRONG_DOMAIN_PATTERNS.
    """
    if not domain:
        return False
    if domain in WRONG_DOMAINS_EXACT:
        return True
    for pat in WRONG_DOMAIN_PATTERNS:
        if pat in domain:
            return True
    return False


class cPluginHandler:
    def __init__(self):
        self.rootFolder = translatePath(cConfig().getAddonInfo('path'))
        self.profilePath = translatePath(cConfig().getAddonInfo('profile'))
        self.pluginDBFile = os.path.join(self.profilePath, 'pluginDB')

        logger.debug('profile folder: %s' % self.profilePath)
        logger.debug('root folder: %s' % self.rootFolder)
        self.defaultFolder = os.path.join(self.rootFolder, 'sites')
        logger.debug('default sites folder: %s' % self.defaultFolder)


    def getAvailablePlugins(self):
        pluginDB = self.__getPluginDB()
        update = False
        fileNames = self.__getFileNamesFromFolder(self.defaultFolder)
        for fileName in fileNames:
            plugin = {'name': '', 'identifier': '', 'icon': '', 'domain': '', 'globalsearch': '', 'modified': 0}
            if fileName in pluginDB:
                plugin.update(pluginDB[fileName])
            try:
                modTime = os.path.getmtime(os.path.join(self.defaultFolder, fileName + '.py'))
            except OSError:
                modTime = 0
            try:
                globalSearchStatus = cConfig().getSetting('global_search_' + fileName)
            except Exception:
                globalSearchStatus = ''
            # Site-Datei nur NEU einlesen (importieren), wenn sie neu ist, sich
            # geaendert hat oder das Global-Search-Setting vom gespeicherten Wert
            # abweicht. Das Setting ist ein Boolean-String ('true'/'false'), also
            # IMMER gesetzt — die alte Bedingung `or globalSearchStatus` war damit
            # immer wahr und importierte bei JEDEM Menue-Aufruf alle Site-Files neu
            # (spuerbar auf schwachen Boxen). Verglichen wird deshalb der Wert.
            if (fileName not in pluginDB or modTime > plugin['modified']
                    or (globalSearchStatus and globalSearchStatus != plugin.get('globalsearch'))):
                logger.debug('load plugin Informations for ' + str(fileName))
                pluginData = self.__getPluginData(fileName, self.defaultFolder)
                if pluginData:
                    pluginData['globalsearch'] = globalSearchStatus
                    pluginData['modified'] = modTime # Wenn Datei (Zeitstempel) verändert, werden die Daten aktualisiert
                    pluginDB[fileName] = pluginData
                    update = True
        # check pluginDB for obsolete entries
        deletions = []
        for pluginID in pluginDB:
            if pluginID not in fileNames:
                deletions.append(pluginID)
        for id in deletions:
            del pluginDB[id]
        if update or deletions:
            self.__updatePluginDB(pluginDB)
            logger.debug('PluginDB informations updated.')
        return self.getAvailablePluginsFromDB()


    def getAvailablePluginsFromDB(self):
        plugins = []
        iconFolder = os.path.join(self.rootFolder, 'resources', 'art', 'sites')
        pluginDB = self.__getPluginDB()
        # PluginID = Siteplugin Name
        for pluginID in pluginDB:
            plugin = pluginDB[pluginID]
            pluginSettingsName = 'plugin_%s' % pluginID
            plugin['id'] = pluginID
            if 'icon' in plugin:
                plugin['icon'] = os.path.join(iconFolder, plugin['icon'])
            else:
                plugin['icon'] = ''
            if cConfig().getSetting(pluginSettingsName) == 'true':
                plugins.append(plugin)
        return plugins


    def __updatePluginDB(self, data):
        if not os.path.exists(self.profilePath):
            os.makedirs(self.profilePath)
        file = open(self.pluginDBFile, 'w')
        json.dump(data, file)
        file.close()


    def __getPluginDB(self):
        if not os.path.exists(self.pluginDBFile):
            return dict()
        file = open(self.pluginDBFile, 'r')
        try:
            data = json.load(file)
        except ValueError:
            logger.error('pluginDB seems corrupt, creating new one')
            data = dict()
        file.close()
        return data

    def __getFileNamesFromFolder(self, sFolder):
        aNameList = []
        items = os.listdir(sFolder)
        for sItemName in items:
            if sItemName.endswith('.py'):
                sItemName = os.path.basename(sItemName[:-3])
                aNameList.append(sItemName)
        return aNameList


    def __getPluginData(self, fileName, defaultFolder):
        pluginData = {}
        if not defaultFolder in sys.path: sys.path.append(defaultFolder)
        try:
            plugin = __import__(fileName, globals(), locals())
            pluginData['name'] = plugin.SITE_NAME
        except Exception as e:
            logger.error("Can't import plugin: %s" % fileName)
            return False
        try:
            pluginData['identifier'] = plugin.SITE_IDENTIFIER
        except Exception:
            pass
        try:
            pluginData['icon'] = plugin.SITE_ICON
        except Exception:
            pass
        try:
            pluginData['domain'] = plugin.DOMAIN
        except Exception:
            pass
        try:
            pluginData['globalsearch'] = plugin.SITE_GLOBAL_SEARCH
        except Exception:
            pluginData['globalsearch'] = True
            pass
        return pluginData


    def __getPluginDataIndex(self, fileName, defaultFolder):
        pluginData = {}
        if not defaultFolder in sys.path: sys.path.append(defaultFolder)
        try:
            plugin = __import__(fileName, globals(), locals())
            pluginData['name'] = plugin.SITE_NAME
        except Exception as e:
            logger.error("Can't import plugin: %s" % fileName)
            # Kaputte Site nicht verschlucken, sondern in der Support-Info sichtbar machen
            pluginData['name'] = fileName
            pluginData['broken'] = True
            return pluginData
        try:
            pluginData['active'] = plugin.ACTIVE
        except Exception:
            pass
        try:
            pluginData['domain'] = plugin.DOMAIN
        except Exception:
            pass
        try:
            # AUS DEN SETTINGS, nicht aus plugin.STATUS: das Site-File liest seinen
            # Wert beim Import einmal ein: laeuft der Domain-Check danach, zeigte die
            # Support-Info in derselben Kodi-Sitzung weiter den alten Stand.
            sIdent = str(getattr(plugin, 'SITE_IDENTIFIER', '') or fileName)
            sStatus = (cConfig().getSetting('plugin_' + sIdent + '_status', '') or '').strip()
            if not sStatus:
                sStatus = str(getattr(plugin, 'STATUS', '') or '').strip()
            pluginData['status'] = sStatus
            if sStatus in STATUS_LABELS:
                # Eigencodes (Timeout, DDoS-Guard, Verbindungsfehler, Cloudflare,
                # unbekannter Fehler) — dieselbe Tabelle wie im Hauptmenue.
                pluginData['status'] = sStatus + ' - ' + cConfig().getLocalizedString(STATUS_LABELS[sStatus])
            elif sStatus.lstrip('-').isdigit():
                # Vergleich als ZAHL. Vorher wurden Strings verglichen ('403' <= s <= '503'),
                # dabei fiel jeder Code ueber 503 durch (z.B. Cloudflares 520) und zeigte
                # im Support-Text nur die nackte Zahl.
                iStatus = int(sStatus)
                # Kurz und mit denselben Woertern wie im Hauptmenue (xstream.py:
                # _siteStatusSuffix): 200 Online, 3xx Umleitung, 403 Blockiert, sonst Offline.
                if iStatus == 200:
                    pluginData['status'] = sStatus + ' - ' + cConfig().getLocalizedString(30868)
                elif 300 <= iStatus < 400:
                    pluginData['status'] = sStatus + ' - ' + cConfig().getLocalizedString(30428)
                elif iStatus == 403:
                    pluginData['status'] = sStatus + ' - ' + cConfig().getLocalizedString(30878)
                elif iStatus >= 400:
                    pluginData['status'] = sStatus + ' - ' + cConfig().getLocalizedString(30870)
        except Exception:
            pass
        try:
            pluginData['globalsearch'] = plugin.SITE_GLOBAL_SEARCH
        except Exception:
            pluginData['globalsearch'] = True
            pass
        return pluginData


    def __getPluginDataDomain(self, fileName, defaultFolder):
        pluginDataDomain = {}
        if not defaultFolder in sys.path: sys.path.append(defaultFolder)
        try:
            plugin = __import__(fileName, globals(), locals())
            pluginDataDomain['identifier'] = plugin.SITE_IDENTIFIER
        except Exception as e:
            logger.error("Can't import plugin: %s" % fileName)
            return False
        try:
            pluginDataDomain['domain'] = plugin.DOMAIN
        except Exception:
            pass
        return pluginDataDomain

    def pluginInfo(self):
        list_of_plugins = []
        fileNames = self.__getFileNamesFromFolder(self.defaultFolder)
        for fileName in fileNames:
            pluginData = self.__getPluginDataIndex(fileName, self.defaultFolder)
            list_of_plugins.append(pluginData)
        # Eine kompakte Zeile pro Indexseite: Name:  aktiv | Domain | Status | Suche: an
        AKTIV = cConfig().getLocalizedString(30418)    # aktiviert
        INAKTIV = cConfig().getLocalizedString(30419)  # deaktiviert
        def _onoff(v):
            return AKTIV if str(v).lower() == 'true' else INAKTIV
        # alphabetisch nach Name sortieren (os.listdir liefert ungeordnet)
        valid_plugins = sorted((d for d in list_of_plugins if d), key=lambda d: d.get('name', '').lower())
        lines = []
        for d in valid_plugins:
            if d.get('broken'):
                lines.append(d.get('name', '?') + ':  ' + cConfig().getLocalizedString(30437))
                continue
            parts = [_onoff(d.get('active', True))]
            if d.get('domain'):
                parts.append(str(d['domain']))
            if d.get('status'):
                parts.append(str(d['status']))
            parts.append(cConfig().getLocalizedString(30426) + ' ' + _onoff(d.get('globalsearch', True)))
            lines.append(d.get('name', '?') + ':  ' + ' | '.join(parts))
        list_of_PluginData = '\n\n'.join(lines)
        if cConfig().getSetting('githubUpdateResolver') == 'true':  # Resolver Update An/Aus
            UPDATERU = cConfig().getLocalizedString(30418)  # aktiviert
        else:
            UPDATERU = cConfig().getLocalizedString(30419)  # deaktiviert
        if cConfig().getSetting('bypassDNSlock') == 'true':  # DNS Bypass
            BYPASS = cConfig().getLocalizedString(30418)  # Aktiv
        else:
            BYPASS = cConfig().getLocalizedString(30419)  # Inaktiv
        # xStream-Repo (falls als eigenes Repo installiert) fuer den xStream-Teil
        repoXstream = ''
        try:
            if os.path.exists(ADDON_PATH % 'repository.xstream'):
                repoXstream = cConfig('repository.xstream').getAddonInfo('name') + ':  ' + cConfig('repository.xstream').getAddonInfo('id') + ' - ' + cConfig('repository.xstream').getAddonInfo('version') + '\n'
        except:
            pass

        Dialog().textviewer(cConfig().getLocalizedString(30265),
            cConfig().getLocalizedString(30413) + '\n'  # Geräte Informationen
            + 'Kodi Version:  ' + xbmc.getInfoLabel('System.BuildVersion')[:4] + ' (Code Version: ' + xbmc.getInfoLabel('System.BuildVersionCode') + ')' + '\n'
            + cConfig().getLocalizedString(30266) + '   {0}'.format(platform().title()) + '\n'  # System Plattform
            + '\n'
            + cConfig().getLocalizedString(30414) + '\n'  # Plugin Informationen
            # --- xStream ---
            + cConfig().getAddonInfo('name') + ' Version:  ' + cConfig().getAddonInfo('version') + '\n'
            + cConfig().getLocalizedString(30435) + ' ' + getRepofromAddonsDB(cConfig().getAddonInfo('id')) + '\n'  # xStream: installiert aus Repository
            + repoXstream
            + '\n'
            # --- ResolveURL ---
            + cConfig('script.module.resolveurl').getAddonInfo('name') + ' Version:  ' + cConfig('script.module.resolveurl').getAddonInfo('version') + '\n'
            + cConfig('script.module.resolveurl').getAddonInfo('name') + ' Update:  ' + UPDATERU + '\n'
            + '\n'
            + cConfig().getLocalizedString(30420) + '\n'  # DNS Informationen
            + cConfig().getLocalizedString(30417) + ' ' + BYPASS + '\n'  # xStream DNS Bypass aktiv/inaktiv
            + cConfig().getLocalizedString(30434) + ' 1: ' + getDNS('Network.DNS1Address') + '\n' # DNS Nameserver 1
            + cConfig().getLocalizedString(30434) + ' 2: ' + getDNS('Network.DNS2Address') + '\n' # DNS Nameserver 2
            + '\n'
            + cConfig().getLocalizedString(30422) + '\n'  # Indexseiten Informationen
            + list_of_PluginData
            )

    # Überprüfung des Domain Namens. Leite um und hole neue URL und schreibe in die settings.xml. Bei nicht erreichen der Seite deaktiviere Globale Suche bis zum nächsten Start und überprüfe erneut.
    # show_notify=False fuer silent Auto-Check (service.py beim Startup),
    # show_notify=True (Default) fuer manuellen Button-Click mit User-Feedback.
    def checkDomain(self, show_notify=True):
        import threading
        logger.debug('Query status code of the provider')
        fileNames = self.__getFileNamesFromFolder(self.defaultFolder)
        threads = []
        for fileName in fileNames:
            try:
                # Eine gespeicherte FALSCHE Domain (Sperr- oder Parkseite, Listen oben)
                # VOR dem Import des Site-Files leeren, damit der Check in derselben
                # Sitzung auf den Default des Files zurueckfaellt und _checkdomain
                # eine neue Spiegel-Domain finden kann. Der Import ist der Grund fuer
                # die Reihenfolge: das Site-File liest beim Import `plugin_<site>.domain`
                # und uebernimmt den gespeicherten Wert als DOMAIN — wer erst danach
                # leert, hat keinen Default mehr, sondern dieselbe falsche Domain, und
                # fragt sie erneut an; antwortet die Parkseite mit 200, steht sie
                # danach wieder im Setting (nachgestellt 01.10.2026 mit site-maps.cc).
                # Der Dateiname ist der SITE_IDENTIFIER (Klassen-Audit).
                if _isWrongDomain(cConfig().getSetting('plugin_' + fileName + '.domain')):
                    cConfig().setSetting('plugin_' + fileName + '.domain', '')
                    cConfig().setSetting('plugin_' + fileName + '_status', '')
                    logger.debug('wrongDomain cleared for %s, checking the default domain' % fileName)
                pluginDataDomain = self.__getPluginDataDomain(fileName, self.defaultFolder)
                provider = pluginDataDomain['identifier']
                _domain = pluginDataDomain['domain']
                domain = cConfig().getSetting('plugin_' + provider + '.domain', _domain)
                base_link = 'https://' + domain + '/'  # URL_MAIN — alle Sites nutzen https; http triggert Cloudflare-Block

                if cConfig().getSetting('plugin_' + provider) == 'false':
                    cConfig().setSetting('global_search_' + provider, 'false')
                    cConfig().setSetting('plugin_' + provider + '_checkdomain', 'false')
                    cConfig().setSetting('plugin_' + provider + '.domain', '')
                    cConfig().setSetting('plugin_' + provider + '_status', '')
                    
                if cConfig().getSetting('plugin_' + provider + '_checkdomain') == 'true':
                    t = threading.Thread(target=self._checkdomain, args=(provider, base_link), name=fileName)
                    # daemon: ein noch laufender Check-Thread (haengende Verbindung)
                    # darf den Kodi-Shutdown nicht blockieren.
                    t.daemon = True
                    threads += [t]
                    t.start()
            except Exception:
                pass

        # Gesamt-Zeitdeckel statt unbegrenztem Warten: die Abrufe laufen PARALLEL
        # und haben je ihren eigenen Socket-Timeout (requestTimeout, Default 10 s).
        # Bleibt ein einzelner Thread darueber hinaus haengen (Verbindung offen,
        # keine Antwort), wuerde ein `join()` ohne Frist das ganze checkDomain()
        # und damit das Menue einfrieren — auf schwachen Boxen als Aufhaenger
        # sichtbar. Deshalb wird nur so lange gewartet, bis das Budget aufgebraucht
        # ist; danach kehrt die Funktion zurueck und das Menue reagiert wieder.
        # Ein noch laufender Thread schreibt sein Ergebnis (thread-sicher) spaeter
        # nach, oder der naechste Check korrigiert die Domain — beides harmlos.
        # Das Budget liegt ueber dem Socket-Timeout, damit ein normaler Lauf (alle
        # Domains antworten in der Zeit) NIE abgeschnitten wird.
        deadline = time.time() + max(int(cConfig().getSetting('requestTimeout', 10)), 10) + 5
        for t in threads:
            remaining = deadline - time.time()
            if remaining <= 0:
                logger.debug('checkDomain: Zeitbudget erreicht, restliche Domain-Checks laufen im Hintergrund weiter')
                break
            t.join(remaining)

        logger.debug('Domains for all available Plugins updated')
        if threads and show_notify:
            infoDialog(cConfig().getLocalizedString(30820), sound=False, icon='INFO', time=6000)


    def _checkdomain(self, provider, base_link):
        try:
            oRequest = cRequestHandler(base_link, caching=False, ignoreErrors=True)
            oRequest.request()
            # Der Status ist LEER, wenn gar keine HTTP-Antwort zustande kam:
            # Verbindungsabbruch, DNS-Fehler, TLS-Abbruch. int('') warf hier bis
            # zum 01.09.2026 einen ValueError, der im blinden `except` unten landete
            # und dort die Domain aus den Settings loeschte — belegt an Jacks Geraet
            # fuer streamcloud und burningseries. "Keine Verbindung" ist aber wie ein
            # Timeout eine unklare Lage und kein Beleg, dass die Seite tot ist:
            # Domain und globale Suche bleiben deshalb unangetastet, STATUS_NO_CONNECT
            # weist die Lage im Menue aus.
            sStatus = str(oRequest.getStatus() or '').strip()
            if sStatus == STATUS_OFFLINE_DNS:
                # Der DNS kennt den Namen nicht: die Domain existiert nicht mehr.
                # Das ist der einzige verbindungslose Fall, den wir sicher deuten
                # koennen — deshalb offline und globale Suche aus. Die eingetragene
                # Adresse bleibt trotzdem stehen: eine kurze Stoerung beim Anbieter
                # sieht genauso aus, und der naechste Check korrigiert sich selbst.
                cConfig().setSetting('plugin_' + provider + '_status', STATUS_OFFLINE_DNS)
                cConfig().setSetting('global_search_' + provider, 'false')
                logger.debug('Domain unknown (DNS) ' + provider + ': - ' + base_link)
                return
            if not sStatus.lstrip('-').isdigit():
                cConfig().setSetting('plugin_' + provider + '_status', STATUS_NO_CONNECT)
                logger.debug('No connection ' + provider + ': - ' + base_link)
                return
            status_code = int(sStatus)
            # Im Status steht sonst der HTTP-Code, und der ist bei Cloudflare wie bei
            # DDoS-Guard eine 403 — im Hauptmenue stand deshalb bisher auch bei einer
            # DDoS-Guard-Sperre "CloudFlare", und ein 403 ohne erkennbares Schutzsystem
            # (Sperre, Geoblock, Hotlink-Schutz) wurde ebenfalls so benannt. Der
            # requestHandler unterscheidet die Faelle inzwischen ueber getProtection();
            # die Eigencodes sind wie -1 keine gueltigen HTTP-Codes und dienen nur der
            # Anzeige. Fuer die Logik unten bleibt der echte status_code stehen, damit
            # die globale Suche wie gehabt abgeschaltet wird.
            sProtection = oRequest.getProtection()
            if sProtection == 'ddos':
                sStatusForMenu = STATUS_DDOS
            elif sProtection == 'cf':
                sStatusForMenu = STATUS_CLOUDFLARE
            else:
                sStatusForMenu = str(status_code)
            cConfig().setSetting('plugin_' + provider + '_status', sStatusForMenu)
            logger.debug('Status Code ' + sStatusForMenu + '  ' + provider + ': - ' + base_link)

            if status_code == -1:
                # Lese-Timeout. Frueher flog der als Exception aus request() heraus und
                # wurde unten von `except TimeoutError` gefangen; seit der Handler ihn
                # selbst abfaengt, kommt er als Status -1 hier an. Behandlung unveraendert:
                # global_search und .domain bleiben stehen, denn "langsam" ist nicht "tot".
                logger.debug('Timeout ' + provider + ': - ' + base_link)
                return

            if status_code >= 403:  # Sperre, Serverfehler oder Seite weg — Domain bleibt stehen
                # Frueher war die Grenze `403 <= status_code <= 503`; alles darueber fiel
                # in den else-Zweig ganz unten und LOESCHTE die Domain. Cloudflare
                # antwortet mit 520-526, wenn der Ursprungsserver nicht erreichbar ist —
                # gemessen am 01.09.2026: ein 520 warf die eingetragene Domain weg,
                # obwohl es dieselbe Lage wie ein 500er ist.
                cConfig().setSetting('global_search_' + provider, 'false')
                logger.debug('Internal Server Error for ' + provider + ' (DDOS Guard, HTTP Error, Cloudflare or BlazingFast active)')

            elif 300 <= status_code <= 400:  # Domain erreichbar mit Umleitung
                url = oRequest.getRealUrl()
                redirected_domain = urlparse(url).hostname
                if _isWrongDomain(redirected_domain):
                    cConfig().setSetting('plugin_' + provider + '.domain', '')
                    cConfig().setSetting('global_search_' + provider, 'false')
                    logger.debug('Redirect to wrong domain: ' + redirected_domain + ' for ' + provider)
                else:
                    cConfig().setSetting('plugin_' + provider + '.domain', redirected_domain)
                    cConfig().setSetting('global_search_' + provider, 'true')
                    logger.debug('globalSearch for ' + provider + ' is activated.')

            elif status_code == 200:  # Domain erreichbar
                cConfig().setSetting('plugin_' + provider + '.domain', urlparse(base_link).hostname)
                cConfig().setSetting('global_search_' + provider, 'true')
                logger.debug('globalSearch for ' + provider + ' is activated.')
            # Wenn keiner der Status oben greift
            else:
                logger.debug('Error ' + provider + ' not available.')
                cConfig().setSetting('global_search_' + provider, 'false')
                cConfig().setSetting('plugin_' + provider + '.domain', '')
                logger.debug('globalSearch for ' + provider + ' is deactivated.')
        except TimeoutError:
            # Sicherheitsnetz: den Lese-Timeout faengt seit dem 25.08. der requestHandler
            # selbst ab (Status -1, siehe oben). Kommt er doch einmal von woanders hier
            # an, bleibt die Behandlung dieselbe — global_search und .domain unangetastet,
            # denn "langsam" ist nicht "tot".
            # -1 ist kein gueltiger HTTP-Status und wird im Menue als Timeout ausgewiesen.
            cConfig().setSetting('plugin_' + provider + '_status', '-1')
            logger.debug('Timeout ' + provider + ': - ' + base_link)
        except Exception as e:
            # Rest-Netz fuer Unvorhergesehenes. Netzfehler ohne HTTP-Antwort landen seit
            # dem 01.09.2026 NICHT mehr hier (siehe oben), deshalb wird die Domain hier
            # auch nicht mehr geloescht — ein unbekannter Fehler ist kein Beleg dafuer,
            # dass die eingetragene Adresse falsch ist. Die globale Suche geht aus, weil
            # wir ueber die Erreichbarkeit nichts wissen.
            logger.error('checkdomain failed for %s: %s' % (provider, e))
            cConfig().setSetting('global_search_' + provider, 'false')
            # Status auf 0 setzen statt den alten Wert stehen zu lassen: sonst zeigt eine
            # Seite, die frueher erreichbar war und jetzt gar nicht mehr antwortet, im
            # Hauptmenue weiterhin ihren letzten Code (z.B. 200 = "Online").
            # 0 ist kein gueltiger HTTP-Status; STATUS_LABELS zeigt ihn als "Unbekannter Fehler".
            cConfig().setSetting('plugin_' + provider + '_status', STATUS_UNKNOWN)
            logger.debug('Error ' + provider + ' not available.')
            pass
