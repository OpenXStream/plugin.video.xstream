# -*- coding: utf-8 -*-
# Python 3
"""
Vavoo authentication layer — everything auth-related lives in THIS file.

To switch backend, only this file needs to be touched:
  - flip ACTIVE to another profile name, or
  - add a new profile block under PROFILES and point ACTIVE at it.

A profile defines BOTH halves of the backend:
  - the auth ping (where the signature comes from), and
  - the catalog/resolve config (base, endpoint paths, signature header, UA,
    catalogId, clientVersion) that vavoo.py reads.

Current setup (ported from Oracle 3.6):
  - AUTH    -> vypn.net (tokenless; no borrowed token to revoke)
  - CATALOG -> vavoo.to (kept; it accepts the vypn signature)

The signature is requested WITHOUT any token: vypn issues it from the device
fingerprint + electron platform + package net.vypn.app. The device identity
(uniqueId + hostname) is generated once and persisted, so each install keeps a
stable fingerprint across pings — see the DEVICE IDENTITY section.

All HTTP goes through xStream's cRequestHandler (no 'requests' dependency).
"""

import os
import json
import time
import uuid
import base64
import random
import string

import xbmcgui
import xbmcvfs

from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.config import cConfig
from resources.lib.logger import logger


# Home window (10000) — properties persist for the Kodi session.
home = xbmcgui.Window(10000)


# =============================================================================
# PROFILES  — the only thing to edit when switching backend
# =============================================================================

ACTIVE = "vypn"

PROFILES = {
    "vypn": {
        # --- auth ping (tokenless) ---
        "ping_endpoints": [
            "https://www.vypn.net/api/app/ping",
        ],
        "ping_ua": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"),
        "ping_body": {
            "reason": "app-focus",
            "locale": "de",
            "theme": "dark",
            "metadata": {
                # uniqueId + os.host are filled per-request from the persistent
                # device identity (see _get_device_identity); "" are placeholders.
                "device": {"type": "desktop", "uniqueId": ""},
                "os": {"name": "win32", "version": "Windows 11 Pro",
                       "abis": ["x64"], "host": ""},
                "app": {"platform": "electron"},   # server validates this -> app.ok=true
                "version": {"package": "net.vypn.app", "binary": "3.1.0", "js": "3.1.0"},
            },
            "appFocusTime": 0,
            "playerActive": False,
            "playDuration": 0,
            "devMode": False,
            "hasAddon": True,
            "castConnected": False,
            "package": "net.vypn.app",
            "version": "3.1.0",
            "process": "app",
            "firstAppStart": 0,
            "lastAppStart": 0,
            "ipLocation": None,
            "adblockEnabled": True,
            "proxy": {"supported": ["ss"], "engine": "Mu", "enabled": False, "autoServer": True},
            "iap": {"supported": False},
        },

        # --- persistent identity targets (which paths get the stable id/host) ---
        # vypn is electron/windows/desktop -> both uniqueId and host are coherent.
        # A profile only receives fields listed here; omit a target to leave that
        # field as-is (e.g. an android profile keeps its android host).
        "identity_targets": {
            "uniqueId": ["metadata", "device", "uniqueId"],
            "host":     ["metadata", "os", "host"],
        },

        # --- catalog / resolve (kept on vavoo.to; accepts the vypn signature) ---
        "catalog_base": "https://vavoo.to",
        "catalog_endpoint": "mediahubmx-catalog.json",
        "resolve_endpoint": "mediahubmx-resolve.json",
        "sig_header": "mediahubmx-signature",
        "catalog_ua": "MediaHubMX/2",
        "catalog_id": "vto-iptv",
        "client_version": "3.1.4",
    },
}

_P = PROFILES[ACTIVE]

# Convenience exports read by vavoo.py (so the request code stays hardcode-free).
CATALOG_BASE     = _P["catalog_base"]
CATALOG_ENDPOINT = _P["catalog_endpoint"]
RESOLVE_ENDPOINT = _P["resolve_endpoint"]
SIG_HEADER       = _P["sig_header"]
CATALOG_UA       = _P["catalog_ua"]
CATALOG_ID       = _P["catalog_id"]
CLIENT_VERSION   = _P["client_version"]


# =============================================================================
# CACHE / RETRY CONSTANTS
# =============================================================================

AUTH_RETRIES = 3        # ping attempts per endpoint round
AUTH_TTL = 600          # fallback cache TTL if a signature carries no validUntil (10 min)
AUTH_BUFFER = 180       # refresh this many seconds before a signature's validUntil (3 min)

# Namensraum wie der Rest des Addons (xstream.<Bereich>.<Schluessel>): Fenster
# 10000 teilen sich alle Addons, der Prefix haelt unsere Werte auseinander.
_PROP_SIG = "xstream.vavoo.auth_sig"
_PROP_EXP = "xstream.vavoo.auth_exp"   # absolute epoch (s) at which the cached signature expires


# =============================================================================
# SIGNATURE CACHE  (window properties, survive across plugin invocations)
# =============================================================================

def _extract_valid_until(signature):
    """Return the signature's validUntil as epoch seconds, or None.

    The signature is base64(JSON) with a "data" field that is itself JSON
    containing validUntil (epoch ms). Signatures without it return None and
    the caller falls back to AUTH_TTL.
    """
    try:
        env = json.loads(base64.b64decode(signature + "=="))
        inner = json.loads(env.get("data", "{}"))
        valid_until = inner.get("validUntil")
        if isinstance(valid_until, (int, float)) and valid_until > 0:
            return int(valid_until / 1000)   # ms -> s
    except Exception:
        pass
    return None


def _get_cached():
    """Return the cached signature while still valid, else clear and return None."""
    sig = home.getProperty(_PROP_SIG) or None
    exp = home.getProperty(_PROP_EXP) or None
    if not sig or not exp:
        return None
    try:
        exp = int(exp)
    except (ValueError, TypeError):
        _clear_cached()
        return None
    now = int(time.time())
    if now >= exp:
        logger.debug("[vavoo.auth] expired (now=%s >= exp=%s), clearing" % (now, exp))
        _clear_cached()
        return None
    logger.debug("[vavoo.auth] cached signature valid (%ss left)" % (exp - now))
    return sig


def _set_cached(signature):
    """Store the signature with expiry derived from its validUntil (minus buffer)."""
    now = int(time.time())
    valid_until = _extract_valid_until(signature)
    if valid_until and (valid_until - AUTH_BUFFER) > now:
        expiry = valid_until - AUTH_BUFFER
        logger.debug("[vavoo.auth] expiry from validUntil: %ss ahead" % (expiry - now))
    else:
        expiry = now + AUTH_TTL
        logger.debug("[vavoo.auth] no usable validUntil, fallback expiry: %ss" % AUTH_TTL)
    home.setProperty(_PROP_SIG, signature)
    home.setProperty(_PROP_EXP, str(expiry))


def _clear_cached():
    """Clear cached auth state."""
    home.clearProperty(_PROP_SIG)
    home.clearProperty(_PROP_EXP)


# =============================================================================
# DEVICE IDENTITY  (stable per install)
# =============================================================================
#
# A real desktop client keeps the SAME device fingerprint across every ping;
# regenerating it each call is the tell of a script. We generate one identity
# on first run and persist it, so each install has its own stable uniqueId +
# hostname (different across devices, constant over time).
#
#   uniqueId : full uuid4 with dashes (matches Windows MachineGuid format)
#   host     : DESKTOP-XXXXXXX (Windows default computer-name format)
#
# Stored as JSON under <profile>/vavoo/; survives restarts and addon updates.

_DEVICE_FILE = "device.json"
_LEGACY_DEVICE_FILE = "vavoo_device.json"   # lag bis 29.07 direkt im Profil-Root
_device_identity = None   # in-memory cache for the current process


def _profile_dir():
    """Absolute path to the addon profile dir."""
    return xbmcvfs.translatePath(cConfig().getAddonInfo("profile"))


def _vavoo_dir():
    """Absolute path to <profile>/vavoo (created if missing).

    Alles was Vavoo ablegt liegt in diesem einen Ordner — Device-Identity und
    der Katalog-Cache aus vavoo.py.
    """
    path = os.path.join(_profile_dir(), "vavoo")
    if not os.path.isdir(path):
        try:
            os.makedirs(path)
        except OSError:
            pass
    return path


def _migrate_legacy_device_file(new_path):
    """Ein altes vavoo_device.json aus dem Profil-Root nach vavoo/device.json holen.

    Die Identity MUSS ueber Updates hinweg stabil bleiben — ohne diesen Umzug
    wuerde jede bestehende Installation beim Update eine neue uniqueId erzeugen
    und sich bei Vavoo als frisches Geraet melden. Laeuft einmalig und still.
    """
    if os.path.exists(new_path):
        return
    old_path = os.path.join(_profile_dir(), _LEGACY_DEVICE_FILE)
    if not os.path.exists(old_path):
        return
    try:
        os.replace(old_path, new_path)
        logger.info("[vavoo.auth] moved device identity to vavoo/%s" % _DEVICE_FILE)
    except OSError as e:
        logger.error("[vavoo.auth] could not move device identity: %s" % e)


def _generate_host():
    """A fresh Windows-style computer name: DESKTOP- + 7 upper alphanumerics."""
    chars = string.ascii_uppercase + string.digits
    return "DESKTOP-" + "".join(random.choice(chars) for _ in range(7))


def _get_device_identity():
    """Return the persistent {uniqueId, host}, generating+storing it on first run."""
    global _device_identity
    if _device_identity:
        return _device_identity

    file_path = os.path.join(_vavoo_dir(), _DEVICE_FILE)
    _migrate_legacy_device_file(file_path)

    # Try to load an existing identity.
    try:
        with open(file_path, "r") as fh:
            data = json.load(fh)
        if data.get("uniqueId") and data.get("host"):
            _device_identity = {"uniqueId": data["uniqueId"], "host": data["host"]}
            logger.debug("[vavoo.auth] loaded persistent device identity")
            return _device_identity
    except (IOError, ValueError):
        pass   # missing or corrupt -> regenerate below

    # Generate a fresh, stable identity and persist it.
    _device_identity = {"uniqueId": str(uuid.uuid4()), "host": _generate_host()}
    try:
        with open(file_path, "w") as fh:
            json.dump(_device_identity, fh)
        logger.info("[vavoo.auth] generated new persistent device identity")
    except IOError as e:
        logger.error("[vavoo.auth] could not persist device identity: %s" % e)
    return _device_identity


# =============================================================================
# PING  (tokenless signature request)
# =============================================================================

def _build_ping_body():
    """Fresh copy of the active profile's ping body with per-request values.

    The persistent device identity (uniqueId + host) is written only into the
    paths declared by the active profile's "identity_targets". A profile
    receives only the fields that are coherent for its platform: an electron/
    windows profile takes both uniqueId and host, an android profile takes the
    uniqueId but keeps its android host, and a token-paired profile (whose
    identity is hardcoded and bound to its token) declares no targets and is
    left untouched. firstAppStart/lastAppStart are set to request time.
    """
    body = json.loads(json.dumps(_P["ping_body"]))   # deep copy
    now_ms = int(time.time() * 1000)
    identity = _get_device_identity()

    for id_key, path in _P.get("identity_targets", {}).items():
        value = identity.get(id_key)
        if value is None or not path:
            continue
        node = body
        try:
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
        except (KeyError, TypeError):
            logger.error("[vavoo.auth] identity_targets path %s not found for '%s'" % (
                path, id_key))

    body["firstAppStart"] = now_ms - 86400000   # simulate install ~24h ago
    body["lastAppStart"] = now_ms
    return body


def _log_signature_details(signature):
    """Decode and log signature data for debugging."""
    try:
        inner = json.loads(json.loads(base64.b64decode(signature + "==")).get("data", "{}"))
        logger.info("[vavoo.auth] status=%s, verified=%s, validUntil=%s" % (
            inner.get('status'), inner.get('verified'), inner.get('validUntil')))
    except Exception:
        pass


def _fetch():
    """Request a fresh signature from the active profile's ping endpoint(s).

    Tries each endpoint in order, AUTH_RETRIES rounds, silent (no UI dialogs).
    Returns (signature, None) on success, or (None, reason) where reason is
    "server_down" (all attempts unreachable) or "auth_failed".

    HTTP via cRequestHandler (POST JSON; ignoreErrors so no built-in dialogs).
    """
    got_response = False   # server replied with parseable JSON at least once

    for attempt in range(1, AUTH_RETRIES + 1):
        for endpoint in _P["ping_endpoints"]:
            body = _build_ping_body()
            try:
                logger.debug("[vavoo.auth] POST %s (attempt %s/%s)" % (endpoint, attempt, AUTH_RETRIES))
                oRequest = cRequestHandler(endpoint, caching=False, ignoreErrors=True,
                                           method='POST', data=json.dumps(body))
                oRequest.addHeaderEntry('User-Agent', _P["ping_ua"])
                oRequest.addHeaderEntry('Accept', '*/*')
                oRequest.addHeaderEntry('Content-Type', 'application/json; charset=utf-8')
                content = oRequest.request()

                try:
                    result = json.loads(content)
                except Exception:
                    # cRequestHandler returns a sentinel string on transport error
                    logger.info("[vavoo.auth] non-JSON response from %s (status=%s)" % (
                        endpoint, oRequest.getStatus()))
                    continue

                got_response = True
                signature = result.get("addonSig") or result.get("sig")
                if signature:
                    logger.info("[vavoo.auth] signature obtained successfully")
                    _log_signature_details(signature)
                    return signature, None

                logger.info("[vavoo.auth] no signature in response from %s (attempt %s/%s)" % (
                    endpoint, attempt, AUTH_RETRIES))

            except Exception as e:
                logger.error("[vavoo.auth] request to %s failed (attempt %s/%s): %s" % (
                    endpoint, attempt, AUTH_RETRIES, e))

    reason = "auth_failed" if got_response else "server_down"
    logger.error("[vavoo.auth] failed after all retries (%s)" % reason)
    return None, reason


# =============================================================================
# PUBLIC API  (what vavoo.py calls)
# =============================================================================

def get_signature():
    """Return a valid signature (cached or freshly fetched), or None.

    Silently retries on failure; only shows an error dialog if all attempts fail.
    """
    cached = _get_cached()
    if cached:
        logger.debug("[vavoo.auth] using cached auth")
        return cached

    logger.debug("[vavoo.auth] no valid cached auth, requesting fresh signature...")
    try:
        signature, fail_reason = _fetch()
        if signature:
            _set_cached(signature)
            logger.info("[vavoo.auth] auth obtained successfully")
            return signature

        if fail_reason == "server_down":
            logger.error("[vavoo.auth] server unreachable!")
            xbmcgui.Dialog().ok(cConfig().getLocalizedString(30845),
                                cConfig().getLocalizedString(30846))
        else:
            logger.error("[vavoo.auth] authentication rejected!")
            xbmcgui.Dialog().ok(cConfig().getLocalizedString(30847),
                                cConfig().getLocalizedString(30848))
        return None

    except Exception as e:
        logger.error("[vavoo.auth] unexpected error during auth: %s" % e)
        return None


def refresh():
    """Clear cached auth and request a fresh signature.

    Used by vavoo.py when a request fails and a fresh signature might help.
    """
    logger.info("[vavoo.auth] refreshing auth...")
    _clear_cached()
    return get_signature()
