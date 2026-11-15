# -*- coding: utf-8 -*-
# Python 3

import os
import json
import requests
import zipfile

from requests.auth import HTTPBasicAuth
from resources.lib.config import cConfig
from resources.lib.handler.requestHandler import cRequestHandler  # RandomUA() SSOT
from resources.lib.tools import infoDialog
from resources.lib.logger import logger
from xbmc import executebuiltin
from xbmcvfs import translatePath


def resolverUpdate():
    # Release Branch https://github.com/Gujal00/ResolveURL
    username = 'Gujal00'
    resolve_dir = 'ResolveURL'
    resolve_id = 'script.module.resolveurl'
    branch = 'master'
    token = ''

    try:
        return UpdateResolve(username, resolve_dir, resolve_id, branch, token)
    except Exception as e:
        logger.error('Exception Raised: %s' % str(e))
        return False


def UpdateResolve(username, resolve_dir, resolve_id, branch, token):
    REMOTE_PLUGIN_COMMITS = "https://api.github.com/repos/%s/%s/commits/%s" % (username, resolve_dir, branch)
    REMOTE_PLUGIN_DOWNLOADS = "https://api.github.com/repos/%s/%s/zipball/%s" % (username, resolve_dir, branch)
    INSTALL_PATH = translatePath(os.path.join('special://home/addons/', '%s') % resolve_id)

    auth = HTTPBasicAuth(username, token)
    sessionUA = cRequestHandler.RandomUA()  # EIN einheitlicher UA fuer alle Requests dieses Laufs 
    logger.info('%s: - Search for updates.' % resolve_id)
    try:
        ADDON_DIR = translatePath(os.path.join('special://userdata/addon_data/', '%s') % resolve_id)
        LOCAL_PLUGIN_VERSION = os.path.join(ADDON_DIR, "update_sha")
        LOCAL_FILE_NAME_PLUGIN = os.path.join(ADDON_DIR, 'update-' + resolve_id + '.zip')
        if not os.path.exists(ADDON_DIR): os.mkdir(ADDON_DIR)

        commitXML = _getXmlString(REMOTE_PLUGIN_COMMITS, auth, sessionUA)
        if commitXML:
            # Direkter Install: ZIP wird in doUpdate() direkt nach INSTALL_PATH entpackt.
            # Kein Packages-Umweg + kein make_archive/unpack_archive Roundtrip mehr.
            isTrue = commitUpdate(commitXML, LOCAL_PLUGIN_VERSION, REMOTE_PLUGIN_DOWNLOADS, INSTALL_PATH, resolve_id, LOCAL_FILE_NAME_PLUGIN, auth, sessionUA)

            if isTrue is True:
                logger.info('%s: - update completed.' % resolve_id)
                return True
            elif isTrue is None:
                logger.info('%s: - no update available.' % resolve_id)
                return None

        logger.error('%s: - Error updating!' % resolve_id)
        return False
    except:
        logger.error('%s: - Error updating!' % resolve_id)
        return False

def commitUpdate(onlineFile, offlineFile, downloadLink, LocalDir, plugin_id, localFileName, auth, sessionUA):
    try:
        jsData = json.loads(onlineFile)
        if not os.path.exists(offlineFile) or open(offlineFile).read() != jsData['sha']:
            logger.info('%s: - Start updating!' % plugin_id)
            isTrue = doUpdate(LocalDir, downloadLink, plugin_id, localFileName, auth, sessionUA)
            if isTrue is True:
                try:
                    open(offlineFile, 'w').write(jsData['sha'])
                    return True
                except:
                    return False
            else:
                return False
        else:
            return None
    except Exception:
        os.remove(offlineFile)
        logger.info('RateLimit reached')
        return False


def doUpdate(LocalDir, REMOTE_PATH, Title, localFileName, auth, sessionUA):
    try:
        response = requests.get(REMOTE_PATH, auth=auth, headers={'User-Agent': sessionUA}, timeout=8)
        if response.status_code == 200:
            open(localFileName, "wb").write(response.content)
        else:
            return False
        updateFile = zipfile.ZipFile(localFileName)
        _written = 0
        _skipped = 0
        for index, n in enumerate(updateFile.namelist()):
            if n[-1] != "/":
                # Zipball enthaelt mehrere Addons nebeneinander unter dem GitHub-Wrapper.
                # Nur Dateien im Title-Ordner (script.module.resolveurl) uebernehmen und
                # ab DORT schneiden -> Dateien landen direkt in LocalDir (keine Verschachtelung).
                parts = n.split("/")
                if Title not in parts:
                    _skipped += 1
                    continue  # Fremd-Addon (.xxx, smr_link_tester) oder Repo-Root -> ignorieren
                dest = os.path.join(LocalDir, "/".join(parts[parts.index(Title) + 1:]))
                if not os.path.abspath(dest).startswith(os.path.abspath(LocalDir)):
                    _skipped += 1
                    continue  # skip entries that escape target directory
                destdir = os.path.dirname(dest)
                if not os.path.isdir(destdir):
                    os.makedirs(destdir)
                data = updateFile.read(n)
                if os.path.exists(dest):
                    os.remove(dest)
                f = open(dest, 'wb')
                f.write(data)
                f.close()
                _written += 1
        updateFile.close()
        logger.info('doUpdate: %s Dateien geschrieben, %s uebersprungen' % (_written, _skipped))
        os.remove(localFileName)
        executebuiltin("UpdateLocalAddons()")
        return True
    except Exception as e:
        logger.info('doUpdate not possible: %s' % str(e))
        return False


def _getXmlString(xml_url, auth, sessionUA):
    try:
        xmlString = requests.get(xml_url, auth=auth, headers={'User-Agent': sessionUA}, timeout=4).content
        if "sha" in json.loads(xmlString):
            return xmlString
        else:
            logger.info('Update-URL incorrect or bad credentials')
    except Exception as e:
        logger.error(str(e))


def manualResolverUpdate():
    try:
        cConfig().setSetting('resolver.branch', 'release')
        # SHA löschen → erzwingt frischen Download
        sha_path = os.path.join(translatePath('special://userdata/addon_data/script.module.resolveurl'), 'update_sha')
        if os.path.exists(sha_path): os.remove(sha_path)
        status = resolverUpdate()
        if status == True:  infoDialog(cConfig().getLocalizedString(30116), sound=False, icon='INFO', time=6000)
        if status == False: infoDialog(cConfig().getLocalizedString(30117), sound=True, icon='ERROR')
        if status == None:  infoDialog(cConfig().getLocalizedString(30118), sound=False, icon='INFO', time=6000)
    except Exception as e:
        logger.error(str(e))
