# -*- coding: utf-8 -*-
# Python 3
#
# Lokale Captcha-Loeser: alles, was der Client SELBST rechnet — ohne Dienst,
# ohne Schluessel und ohne Kosten. Gegenstueck zu captcha_solver.py (2captcha).
#
# Erster Fall ist Altcha (Proof-of-Work): die Seite liefert eine Challenge,
# der Client sucht die Zahl, deren SHA-256 zusammen mit dem Salt die Challenge
# trifft, und schickt das Ergebnis als Formularfeld zurueck. Kostet nur
# Rechenzeit — deshalb haengt dieser Weg am Schalter `captcha.enabled`, NICHT
# am 2Captcha-Schluessel: wer keinen Dienst bezahlt, soll eine Pruefung, die
# ihn nichts kostet, trotzdem bestehen koennen.
#
# Die Funktionen kennen weder Seite noch Domain. Woher die Challenge-Adresse
# kommt, entscheidet der Aufrufer (bei serienstream steht sie im Markup der
# Episodenseite als data-altcha-challenge-url).
#
# Zweiter Fall ist die Pruefseite des Fremd-WAF HostAdmin.online (ebenfalls
# Proof-of-Work): solve_hostadmin() rechnet nur und liefert den Rumpf fuer die
# Einreichung. Abruf, Einreichen, Cookies und der feste User-Agent gehoeren
# dem Aufrufer — der WAF bindet seine Freigabe an beides.

import base64
import hashlib
import json
import re
import struct
import time

from resources.lib.config import cConfig
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger

# Vorgabe fuer maxnumber, wenn die Seite keinen Wert nennt — die Vorgabe des
# Altcha-Widgets selbst. Nennt die Seite einen Wert (serienstream 09/2026:
# 100000), gilt der; einen Deckel gibt es bewusst nicht: die einzige Bremse ist
# die Zeitgrenze, und die passt sich dem Geraet an — ein schneller Rechner
# schafft in derselben Zeit mehr als ein Fire Stick, ein fester Deckel haette
# ihn nur ausgebremst (Jack 10.09.2026: „Deckel raus, nur Zeitgrenze reicht").
ALTCHA_DEFAULT_MAX_NUMBER = 1000000
# Zeitgrenze fuer die Suche: laenger als das soll kein Klick warten. Zur
# Einordnung: 100.000 SHA-256 dauern hier rund 0,1 s, auf einem schwachen
# Android-Geraet grob eine Sekunde.
ALTCHA_TIME_LIMIT = 30

# --- HostAdmin.online (Fremd-WAF mit Proof-of-Work-Pruefseite) -------------
# Die Pruefseite kommt mit Status 200 und ist nur am Markup zu erkennen. Der WAF
# baut sie mehrfach um und benennt dabei um, was der Loeser braucht — deshalb
# wird, wo es geht, an der FORM erkannt statt am Namen: das WASM an seiner
# base64-Signatur, Feldreihenfolgen aus der Seite, die Pruefseite ueber mehrere
# Marker. Rechenkern (sha256 + Mischwert) und Einreichung sind unveraendert,
# nur das Auslesen ist robust.
# Pruefseiten-Marker, EINER genuegt: die Verify-Adresse steht seit 09/2026 nur
# noch im verschleierten Skript, Engine-Funktion und Sprach-Objekt im Klartext.
HOSTADMIN_MARKERS = ('hostadminonline-waf-verify', 'runWafEngine', '__WAF_I18N__')
# Dorthin gehoert die Loesung (POST, JSON), relativ zur geschuetzten Seite.
HOSTADMIN_VERIFY_PATH = '/hostadminonline-waf-verify'
HOSTADMIN_TIME_LIMIT = 30
# Rueckfall fuer den Mischwert, falls er sich nicht aus dem Modul lesen laesst
# (Stand 09/2026; wird er gebraucht, steht es im Log).
HOSTADMIN_MIX_FALLBACK = 0x0FF0A55A
# Nullbits je Kettenrunde, Rueckfall: der Wert stand frueher offen (ROUND_BITS),
# seit 09/2026 nur noch im verschleierten Worker; 16 ist seit 09/2026 belegt.
# Greift NUR bei erkannter Kette (Runden vorhanden), mit Logzeile.
HOSTADMIN_ROUND_BITS_FALLBACK = 16
# Schema fp/botSignals: die acht Bot-Signale in Payload-Reihenfolge, "0" =
# unauffaellig. Rueckfall — normal werden Reihenfolge und Zahl aus dem
# Sammler-Block der Seite gelesen, ein neues Signal wandert so automatisch mit.
HOSTADMIN_BOT_KEYS = ('webdriver', 'chrome_missing', 'selenium', 'phantom', 'headless_agent',
                      'tostring_tampered', 'iframe_webdriver', 'software_gpu')
# Schema fp/botSignals: Fingerprint des Pruefskripts (Aufloesung, Zeitzone,
# Schriftarten, Grafiktreiber). Der WAF rechnet ihn nur ein und gleicht ihn nicht
# mit dem User-Agent ab (gemessen 09/2026 mit frei gewaehlten Werten) — ein
# fester, plausibler Satz genuegt; Reihenfolge aus der Seite, unbekannte Felder "0".
HOSTADMIN_FINGERPRINT = {'res': '1920x1080', 'tz': 'Europe/Berlin', 'fontsCount': '38',
                         'webgl_renderer': 'ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)'}
# Erste Felder der beiden Sammler-Bloecke — der Anker fuer _hostadmin_field_order.
HOSTADMIN_FP_FIRST = 'res'
HOSTADMIN_BOT_FIRST = 'webdriver'
# Schema „Datenhash" (seit 24.09.2026): das Skript sammelt einen grossen
# Umgebungsdatensatz (Bildschirm, Audio, Schriften, WebGL, Navigator, Laufzeit),
# serialisiert ihn kanonisch (Schluessel sortiert, ohne Leerzeichen), hasht ihn
# (SHA-256) und traegt im Runden-Payload nur diesen Hash (`data_sha`) — keine
# Fingerprint- und Bot-Felder mehr. Eingereicht wird der Datensatz unter `data`
# plus `compute_profile` (Rundenzeiten). Der WAF prueft `data` BYTEGLEICH gegen
# den Hash (24.09.2026 gemessen: Leerzeichen oder andere Schluesselreihenfolge
# -> 403): der Satz steht hier deshalb sortiert, und der Aufrufer serialisiert
# kompakt (json.dumps, separators=(',', ':')) — dann liefern json.dumps und
# _hostadmin_canonical dieselben Bytes. Die Werte gleicht der WAF nicht mit dem
# UA ab (24.09.2026 mit Firefox- und Safari-UA angenommen); ein fester Satz
# eines Windows-Chrome genuegt. Erkennung: einer der Marker im Klartext (sie
# stehen nur zufaellig dort, das Skript wird je Abruf neu verschleiert) ODER
# kein lesbarer Sammler-Block — Rueckfall ist das neue Schema, nicht das alte.
HOSTADMIN_DATA_MARKERS = ('data_sha', 'dataSha', 'compute_profile')
HOSTADMIN_DATA = {
    'audio': {
        'base_latency': 0.01, 'max_channels': 2, 'output_latency': 0.02, 'sample_rate': 48000,
        'sample_sum': 124.04347527516074,
    },
    'battery': {'charging': True, 'level': 1},
    'canvas': {
        'data_len': 8134, 'pixel_sum': 2860415986,
        'subpixel': {'act_box_ascent': 12, 'act_box_descent': 4, 'width': 141.1875},
    },
    'css_media': {
        'dark_mode': False, 'hover_hover': True, 'hover_none': False, 'pointer_coarse': False,
        'pointer_fine': True, 'reduced_motion': False,
    },
    'fonts': {'count': 22, 'mask': 4231372795},
    'intl': {'calendar': 'gregory', 'locale': 'de-DE', 'timezone': 'Europe/Berlin', 'tz_offset': -120},
    'memory': {'device_memory_gb': 8, 'js_heap_limit': 4294705152, 'total_js_heap': 17358244, 'used_js_heap': 14231176},
    'nav': {
        'cookie_enabled': True, 'do_not_track': '', 'hw_concurrency': 8, 'language': 'de-DE',
        'languages': ['de-DE', 'de', 'en-US', 'en'], 'max_touch_points': 0, 'pdf_viewer_enabled': True,
        'platform': 'Win32', 'vendor': 'Google Inc.', 'webdriver': False,
    },
    'net': {'downlink': 10, 'effective_type': '4g', 'rtt': 50, 'save_data': False},
    'permissions': {'camera': 'prompt', 'geolocation': 'prompt', 'microphone': 'prompt', 'notifications': 'prompt'},
    'plugins': [
        {'description': 'Portable Document Format', 'filename': 'internal-pdf-viewer', 'name': 'PDF Viewer'},
        {'description': 'Portable Document Format', 'filename': 'internal-pdf-viewer', 'name': 'Chrome PDF Viewer'},
        {'description': 'Portable Document Format', 'filename': 'internal-pdf-viewer', 'name': 'Chromium PDF Viewer'},
        {'description': 'Portable Document Format', 'filename': 'internal-pdf-viewer', 'name': 'Microsoft Edge PDF Viewer'},
        {'description': 'Portable Document Format', 'filename': 'internal-pdf-viewer', 'name': 'WebKit built-in PDF'},
    ],
    'runtime': {
        'cdc_doc': False, 'cdc_win': False, 'chrome_keys_len': 4, 'document_hidden': False,
        'eval_tostring': 'function eval() { [native code] }',
        'fn_tostring': 'function toString() { [native code] }', 'has_chrome': True,
        'has_chrome_runtime': True, 'iframe_webdriver': 'false', 'nav_keys_count': 0,
        'nav_webdriver_desc': True,
        'stack_trace_sample': "TypeError: Cannot read properties of null (reading '0')\n    at https://kinoger.to/:1:104211\n    at async _0x21aa4e (https://kinoger.to/:1:104333)",
        'window_keys_count': 213,
    },
    'screen': {
        'avail_h': 1040, 'avail_w': 1920, 'color_depth': 24, 'dpr': 1, 'h': 1080, 'inner_h': 911,
        'inner_w': 1920, 'orientation_angle': 0, 'orientation_type': 'landscape-primary', 'pixel_depth': 24,
        'w': 1920,
    },
    'speech_voices_count': 0,
    'user_entropy': {'clicks': 0, 'keys': 0, 'mouse_moves': 14, 'scrolls': 0, 'touches': 0},
    'webgl': {
        'alpha_bits': 8, 'blue_bits': 8, 'depth_bits': 24,
        'extensions': [
            'ANGLE_instanced_arrays', 'EXT_blend_minmax', 'EXT_clip_control', 'EXT_color_buffer_half_float',
            'EXT_depth_clamp', 'EXT_disjoint_timer_query', 'EXT_float_blend', 'EXT_frag_depth',
            'EXT_polygon_offset_clamp', 'EXT_sRGB', 'EXT_shader_texture_lod', 'EXT_texture_compression_bptc',
            'EXT_texture_compression_rgtc', 'EXT_texture_filter_anisotropic',
            'EXT_texture_mirror_clamp_to_edge', 'KHR_parallel_shader_compile', 'OES_element_index_uint',
            'OES_fbo_render_mipmap', 'OES_standard_derivatives', 'OES_texture_float',
            'OES_texture_float_linear', 'OES_texture_half_float', 'OES_texture_half_float_linear',
            'OES_vertex_array_object', 'WEBGL_blend_func_extended', 'WEBGL_color_buffer_float',
            'WEBGL_compressed_texture_s3tc', 'WEBGL_compressed_texture_s3tc_srgb',
            'WEBGL_debug_renderer_info', 'WEBGL_debug_shaders', 'WEBGL_depth_texture', 'WEBGL_draw_buffers',
            'WEBGL_lose_context', 'WEBGL_multi_draw', 'WEBGL_polygon_mode',
        ],
        'green_bits': 8, 'max_texture_size': 16384, 'max_viewport_dims': [32767, 32767], 'red_bits': 8,
        'renderer': 'WebKit WebGL',
        'shader_precisions': {
            'FRAGMENT_SHADER': {
                'HIGH_FLOAT': {'precision': 23, 'range_max': 127, 'range_min': 127},
                'HIGH_INT': {'precision': 0, 'range_max': 30, 'range_min': 31},
                'LOW_FLOAT': {'precision': 23, 'range_max': 127, 'range_min': 127},
                'LOW_INT': {'precision': 0, 'range_max': 30, 'range_min': 31},
                'MEDIUM_FLOAT': {'precision': 23, 'range_max': 127, 'range_min': 127},
                'MEDIUM_INT': {'precision': 0, 'range_max': 30, 'range_min': 31},
            },
            'VERTEX_SHADER': {
                'HIGH_FLOAT': {'precision': 23, 'range_max': 127, 'range_min': 127},
                'HIGH_INT': {'precision': 0, 'range_max': 30, 'range_min': 31},
                'LOW_FLOAT': {'precision': 23, 'range_max': 127, 'range_min': 127},
                'LOW_INT': {'precision': 0, 'range_max': 30, 'range_min': 31},
                'MEDIUM_FLOAT': {'precision': 23, 'range_max': 127, 'range_min': 127},
                'MEDIUM_INT': {'precision': 0, 'range_max': 30, 'range_min': 31},
            },
        },
        'shading_language_version': 'WebGL GLSL ES 1.0 (OpenGL ES GLSL ES 1.0 Chromium)', 'stencil_bits': 0,
        'unmasked_renderer': 'ANGLE (Intel, Intel(R) UHD Graphics 620 (0x00003EA0) Direct3D11 vs_5_0 ps_5_0, D3D11)',
        'unmasked_vendor': 'Google Inc. (Intel)', 'vendor': 'WebKit',
        'version': 'WebGL 1.0 (OpenGL ES 2.0 Chromium)',
    },
    'webrtc_support': True,
}


def local_ready():
    """True, wenn lokal geloest werden darf — nur der Schalter zaehlt.

    Bewusst nicht captcha_ready() aus dem Helper: der prueft auch den
    Schluessel, und ohne Schluessel waere eine kostenlose Pruefung sonst
    still abgeschaltet. Fehlt das Setting (Bestandsnutzer direkt nach dem
    Update), gilt der Vorgabewert an — wie beim Dienst.
    """
    if cConfig().getSetting('captcha.enabled', 'true') != 'true':
        logger.info('Captcha: Dienst ist in den Einstellungen abgeschaltet, kein lokales Loesen')
        return False
    return True


def solve_altcha(sChallengeUrl, sReferer=''):
    """Altcha-Challenge holen, rechnen, Antwort als base64-JSON liefern.

    Ablauf wie im Altcha-Widget: GET auf die Challenge-Adresse liefert JSON mit
    algorithm, challenge, salt, signature und maxnumber. Gesucht wird die Zahl n,
    fuer die SHA-256(salt + n) gleich challenge ist. Die Antwort ist das
    base64-kodierte JSON mit algorithm, challenge, number, salt, signature und
    took — genau die Form, die das Widget in sein verstecktes Feld schreibt.
    Die Signatur wird unveraendert zurueckgegeben, sie prueft der Server.

    Args:
        sChallengeUrl (str): Adresse, die die Challenge liefert
        sReferer (str): Seite, auf der das Widget steht (Referer-Header)

    Returns:
        str: die Antwort fuers Formularfeld oder '' — der Aufrufer entscheidet,
             ob er ohne das Feld weitermacht
    """
    if not local_ready():
        return ''

    # caching=False: jede Challenge gilt genau einmal (Salt mit Ablauf).
    # ignoreErrors=True: ein Fehler hier bekommt kein eigenes Fenster — der
    # Aufrufer fuehrt den Ablauf ohne das Feld fort und meldet selbst, wenn
    # die Seite die Antwort nicht annimmt.
    oRequest = cRequestHandler(sChallengeUrl, caching=False, ignoreErrors=True)
    oRequest.addHeaderEntry('Accept', 'application/json')
    if sReferer:
        oRequest.addHeaderEntry('Referer', sReferer)
    jChallenge = oRequest.requestJson()
    if not isinstance(jChallenge, dict):
        logger.error('Altcha: keine Challenge von %s' % sChallengeUrl)
        return ''

    sAlgorithm = str(jChallenge.get('algorithm', '')).upper()
    sChallenge = str(jChallenge.get('challenge', '')).lower()
    sSalt = str(jChallenge.get('salt', ''))
    sSignature = str(jChallenge.get('signature', ''))
    # Nur SHA-256: andere Algorithmen waeren ein neuer Fall und werden nicht
    # geraten (das Widget kann auch SHA-1/SHA-512, die Seite nutzt SHA-256).
    if sAlgorithm != 'SHA-256' or not (sChallenge and sSalt and sSignature):
        logger.error('Altcha: unbekannte Challenge-Form (%s)' % sAlgorithm)
        return ''
    try:
        iMaxNumber = int(jChallenge.get('maxnumber') or ALTCHA_DEFAULT_MAX_NUMBER)
    except (TypeError, ValueError):
        iMaxNumber = ALTCHA_DEFAULT_MAX_NUMBER

    tStart = time.time()
    sSaltBytes = sSalt.encode('utf-8')
    for iNumber in range(iMaxNumber + 1):
        if hashlib.sha256(sSaltBytes + str(iNumber).encode('utf-8')).hexdigest() == sChallenge:
            iTook = int((time.time() - tStart) * 1000)
            aPayload = {'algorithm': jChallenge.get('algorithm'), 'challenge': jChallenge.get('challenge'),
                        'number': iNumber, 'salt': sSalt, 'signature': sSignature, 'took': iTook}
            logger.info('Altcha geloest: Zahl %d nach %d ms' % (iNumber, iTook))
            # Kompakt wie JSON.stringify im Browser (ohne Leerzeichen)
            return base64.b64encode(json.dumps(aPayload, separators=(',', ':')).encode('utf-8')).decode('ascii')
        if iNumber % 10000 == 0 and time.time() - tStart > ALTCHA_TIME_LIMIT:
            logger.error('Altcha: Zeitgrenze von %d s erreicht bei Zahl %d' % (ALTCHA_TIME_LIMIT, iNumber))
            return ''
    logger.error('Altcha: keine Loesung bis %d' % iMaxNumber)
    return ''


def is_hostadmin_gate(sHtml):
    """True, wenn sHtml die Pruefseite des HostAdmin-WAF ist (nur am Markup erkannt).

    Mehrere Marker, weil der WAF sie umbenennt: EINER genuegt. So bleibt die
    Erkennung stehen, wenn ein einzelnes Merkmal (etwa die Verify-Adresse)
    aus dem sichtbaren HTML in das verschleierte Skript wandert.
    """
    return bool(sHtml) and any(sMarker in sHtml for sMarker in HOSTADMIN_MARKERS)


def _hostadmin_first(sHtml, aPatterns):
    """Ersten Treffer ueber eine geordnete Muster-Liste liefern, sonst None.

    Die Muster sind nach Vorrang sortiert: erst der frueher benutzte Feldname,
    dann die neuere Form, zuletzt ein reiner Form-Anker. Das erste Muster, das
    greift, gewinnt; seine erste nicht-leere Gruppe (oder der ganze Treffer)
    ist der Wert.
    """
    for sPattern in aPatterns:
        oMatch = re.search(sPattern, sHtml)
        if oMatch:
            aGroups = [g for g in oMatch.groups() if g is not None]
            return aGroups[0] if aGroups else oMatch.group(0)
    return None


def _hostadmin_field_order(sHtml, sFirstKey, aFallback):
    """Reihenfolge der Schluessel eines Sammler-Blocks aus dem Pruefskript lesen.

    Das Skript baut Fingerprint und Bot-Signale als Objekt-Literal
    `{ 'res': …, 'tz': …, … }` bzw. `{ 'webdriver': …, … }`. Der Block wird ab
    seinem ersten Schluessel bis zur schliessenden Klammer genommen (die Werte
    enthalten keine geschweifte Klammer) und die Schluessel in ihrer Reihenfolge
    zurueckgegeben. So wandert ein zusaetzliches oder umgestelltes Feld
    automatisch mit — der gehashte Payload muss GENAU diese Reihenfolge haben,
    und weil derselbe Block auch den Browser der Gegenseite speist, ist er die
    verlaessliche Quelle dafuer. Laesst sich der Block nicht lesen (Reihenfolge
    obfuskiert, erstes Feld umbenannt), gilt der bekannte Rueckfall.

    Args:
        sHtml (str): die Pruefseite
        sFirstKey (str): erwartetes erstes Feld des Blocks (Anker)
        aFallback (tuple): bekannte Reihenfolge, falls der Block nicht lesbar ist

    Returns:
        tuple: (Reihenfolge, bFallback) — bFallback True, wenn der Rueckfall gilt
    """
    oBlock = re.search(r"'" + re.escape(sFirstKey) + r"'\s*:.*?\}", sHtml, re.S)
    if oBlock:
        aKeys = re.findall(r"'([a-zA-Z_]+)'\s*:", oBlock.group(0))
        if aKeys:
            return tuple(aKeys), False
    return tuple(aFallback), True


def _hostadmin_canonical(oValue):
    """Kanonische JSON-Form wie im Pruefskript: Schluessel sortiert, keine Leerzeichen.

    Nur die Schluessel werden sortiert, Listen behalten ihre Reihenfolge; Zahlen,
    Wahrheitswerte und Texte wie JSON.stringify. Darueber rechnet das Skript den
    `data_sha` — und der WAF haelt den eingereichten Datensatz Byte fuer Byte
    dagegen.
    """
    if isinstance(oValue, dict):
        return '{' + ','.join(json.dumps(sKey) + ':' + _hostadmin_canonical(oValue[sKey]) for sKey in sorted(oValue)) + '}'
    if isinstance(oValue, list):
        return '[' + ','.join(_hostadmin_canonical(oItem) for oItem in oValue) + ']'
    return json.dumps(oValue, separators=(',', ':'))


def _hostadmin_mix(aWasm):
    """Mischwert der Aufgabe aus dem mitgelieferten WASM-Modul lesen.

    Das Modul haengt vor dem Hashen vier feste Bytes an den Payload. Sie stehen
    im Code als `i32.const <wert>` (0x41, SLEB128) direkt vor einem `i32.store`
    (0x36). Gesucht ist der eine Kandidat groesser 2^24, der nicht 0xffffffff
    ist; alles andere sind Adressen und Zaehler.
    """
    for iPos in range(len(aWasm) - 6):
        if aWasm[iPos] != 0x41:
            continue
        iValue = 0
        iShift = 0
        iNext = iPos + 1
        while iNext < len(aWasm):
            iByte = aWasm[iNext]
            iNext += 1
            iValue |= (iByte & 0x7F) << iShift
            iShift += 7
            if not iByte & 0x80 or iShift > 35:
                break
        iValue &= 0xFFFFFFFF
        if iNext < len(aWasm) and aWasm[iNext] == 0x36 and (1 << 24) < iValue < 0xFFFFFFFF:
            return iValue
    return 0


def _hostadmin_spot_values(sSeed):
    """`spotValuesHex` des Pruefskripts nachrechnen.

    Im Browser: fuenf rote Rechtecke auf einer 100x100-Flaeche, Lage und Groesse
    aus einem Zufallsgenerator (LCG) ueber die ersten acht Hex-Zeichen des Seeds;
    danach je Pixel ein Bit (gefuellt oder nicht), acht Bits je Byte mit dem
    niedrigsten Bit zuerst, als Hex. Hier ohne Zeichenflaeche, nur die Bits.
    """
    iState = int(sSeed[:8], 16) or 123456789
    aGrid = [[0] * 100 for _ in range(100)]
    aValues = []
    for _ in range(20):
        iState = (iState * 1664525 + 1013904223) & 0xFFFFFFFF
        aValues.append(iState >> 16)
    for i in range(5):
        iX, iY = aValues[i * 4] % 100, aValues[i * 4 + 1] % 100
        iW, iH = aValues[i * 4 + 2] % 50 + 10, aValues[i * 4 + 3] % 50 + 10
        for iRow in range(iY, min(100, iY + iH)):
            for iCol in range(iX, min(100, iX + iW)):
                aGrid[iRow][iCol] = 1
    aHex = []
    iCurrent = 0
    for i in range(10000):
        if aGrid[i // 100][i % 100]:
            iCurrent |= 1 << (i % 8)
        if i % 8 == 7:
            aHex.append('%02x' % iCurrent)
            iCurrent = 0
    return ''.join(aHex)


def solve_hostadmin(sHtml):
    """Aufgabe der HostAdmin-Pruefseite rechnen -> Rumpf fuer die Einreichung.

    Die Pruefseite traegt im Skript Seed, Anfrage-ID, Aufgabe und das WASM-Modul
    (base64). Gerechnet wird immer gleich: die kleinste Nonce, fuer die SHA-256
    ueber Payload + Mischwert + Nonce (4 Byte, little-endian) mit der geforderten
    Zahl Nullbits beginnt — ohne WASM mit hashlib, gegen das Modul geprueft
    (gleiche Nonces). Weil der WAF Felder umbenennt, werden die Werte ueber
    mehrere Muster gelesen (alter Name, neue Form, Form-Anker). DREI Schemata,
    sie unterscheiden sich nur im Payload:

      1. Kette, Datenhash (seit 24.09.2026, Standard und Rueckfall):
         `totalRounds`/`rounds` Runden zu ROUND_BITS Nullbits, Payload
         {"data_sha", "round", "seed"} — der Hash des Datensatzes HOSTADMIN_DATA,
         der selbst unter `data` mit eingereicht wird (bytegleich!). Erkennung
         siehe HOSTADMIN_DATA_MARKERS.
      2. Kette, fp/botSignals (21./22.09.2026): gleiche Runden, Payload
         {"round", "seed", "fp", "botSignals"} mit der Feldreihenfolge aus dem
         Sammler-Block der Seite — nur, wenn dieser Block lesbar ist.
      3. Einzelrunde (bis 20.09.2026): eine Runde mit `difficulty * 4` Nullbits,
         Payload ohne Rundennummer, eingereicht als Feld `nonce`. Rueckfall, falls
         die Gegenseite zurueckschaltet (ob die Kette Umbau oder Modus ist, sieht
         man von aussen nicht); greift nur, wenn von der Kette nichts da ist.

    Kette: an den Seed der naechsten Runde haengt das Skript "_<Nonce>",
    eingereicht wird die Liste `nonces`; steht ROUND_BITS nicht im HTML (seit
    09/2026 nur im verschleierten Worker), gilt HOSTADMIN_ROUND_BITS_FALLBACK mit
    Logzeile. Das gerechnete Schema steht im Log. Rueckgabe ist genau das Objekt,
    das das Skript per POST als JSON an HOSTADMIN_VERIFY_PATH schickt.

    Args:
        sHtml (str): die Pruefseite

    Returns:
        dict: Rumpf fuer die Einreichung, oder None (abgeschaltet, Seite nicht
              lesbar, Zeitgrenze) — der Aufrufer macht dann ohne Freigabe weiter
    """
    if not local_ready():
        return None
    # Jeder Wert zweistufig: erst der frueher benutzte Name, dann die neue Form.
    # Der WAF hat 09/2026 alle Namen umbenannt (serverSeed->seed, initialReqId
    # ->reqId, WASM_BINARY_B64->wasm, totalRounds->rounds) und die Werte in den
    # Aufruf `runWafEngine({ ... })` verschoben. Deshalb je ein zusaetzlicher
    # Anker an der FORM: die reqId an ihrer Blockstruktur, das WASM an seiner
    # base64-Signatur "AGFzbQ" (jedes WASM-Modul beginnt damit), die als
    # letztes auch ohne bekannten Feldnamen greift.
    sSeed = _hostadmin_first(sHtml, (r'serverSeed\s*=\s*"([0-9a-fA-F]{16,})"',
                                     r'\bseed\s*:\s*"([0-9a-fA-F]{16,})"'))
    sReqId = _hostadmin_first(sHtml, (r'initialReqId\s*=\s*"([^"]*)"',
                                      r'\breqId\s*:\s*"([0-9a-fA-F]{4,}-[0-9a-fA-F]{4,}-[0-9a-fA-F]{4,})"'))
    sWasm = _hostadmin_first(sHtml, (r'WASM_BINARY_B64\s*=\s*"([A-Za-z0-9+/=]+)"',
                                     r'\bwasm\s*:\s*"(AGFzbQ[A-Za-z0-9+/=]+)"',
                                     r'"(AGFzbQ[A-Za-z0-9+/=]{200,})"'))
    # Runden: `totalRounds`/`rounds`, je als `Math.max(2, N)` oder als nackte Zahl.
    sRounds = _hostadmin_first(sHtml, (r'totalRounds\s*=\s*Math\.max\(\s*\d+\s*,\s*(\d+)\s*\)',
                                       r'totalRounds\s*=\s*(\d+)',
                                       r'\brounds\s*:\s*Math\.max\(\s*\d+\s*,\s*(\d+)\s*\)',
                                       r'\brounds\s*:\s*(\d+)\b'))
    sBits = _hostadmin_first(sHtml, (r'ROUND_BITS\s*=\s*(\d+)',))
    sDifficulty = _hostadmin_first(sHtml, (r'difficulty\s*=\s*(\d+)',))
    bChain = sRounds is not None
    # Altes Schema (Einzelrunde) nur, wenn von der Kette GAR NICHTS da ist.
    bSingle = sDifficulty is not None and sRounds is None
    aMissing = [sName for sName, sHit in (('serverSeed/seed', sSeed), ('initialReqId/reqId', sReqId)) if not sHit]
    if not bChain and not bSingle:
        if not sRounds:
            aMissing.append('totalRounds/rounds')
        if sDifficulty is None:
            aMissing.append('difficulty')
    if aMissing:
        # Die Namen stehen im Log, damit ein Umbau der Pruefseite sofort zeigt, WAS sich geaendert hat.
        logger.error('HostAdmin: Pruefseite nicht lesbar, es fehlt: %s' % ', '.join(aMissing))
        return None
    if bChain:
        sScheme = 'Kette'
        iRounds = int(sRounds)
        if sBits is not None:
            iBits = int(sBits)
        else:
            # Die Kette steht (Runden erkannt), nur ROUND_BITS ist nicht mehr im
            # HTML — der bekannte Wert und eine Logzeile. Bewusst kein "nicht
            # lesbar": sonst faellt kinoger aus, sobald die Seite den Wert in
            # den Worker schiebt (so am 22.09.2026 geschehen, 16 war korrekt).
            # Der Rueckfall greift NUR hier, nie wenn gar keine Runden erkannt
            # wurden. Stimmt der Wert einmal nicht, meldet der WAF 403 und es
            # steht neben dieser Zeile im Log — teurer als ein 200 wird es nie,
            # die Pruefung ist gratis.
            iBits = HOSTADMIN_ROUND_BITS_FALLBACK
            logger.info('HostAdmin: ROUND_BITS nicht auf der Seite, nehme %d' % HOSTADMIN_ROUND_BITS_FALLBACK)
    else:
        sScheme = 'Einzelrunde'
        iRounds = 1
        iBits = int(sDifficulty) * 4
    if iRounds < 1 or not 0 < iBits <= 256:
        logger.error('HostAdmin: unbrauchbare Aufgabe (%s: %d Runden, %d Bit)' % (sScheme, iRounds, iBits))
        return None

    iMix = 0
    if sWasm:
        try:
            iMix = _hostadmin_mix(base64.b64decode(sWasm))
        except Exception as e:
            logger.error('HostAdmin: WASM-Modul nicht lesbar: %s' % e)
    if not iMix:
        iMix = HOSTADMIN_MIX_FALLBACK
        logger.info('HostAdmin: Mischwert nicht im Modul gefunden, nehme den bekannten Wert')

    # Reihenfolge der Fingerprint- und Bot-Felder aus der Seite lesen (Rueckfall:
    # die bekannte Reihenfolge). Ein zusaetzliches Bot-Signal wandert so
    # automatisch mit; unbekannte Felder bekommen den Wert "0". Der gehashte
    # Payload MUSS dieselbe Feldreihenfolge tragen wie der Browser der Gegenseite.
    aFpKeys, bFpFallback = _hostadmin_field_order(sHtml, HOSTADMIN_FP_FIRST, tuple(HOSTADMIN_FINGERPRINT))
    # Schema Datenhash: an einem Marker erkannt ODER daran, dass der lesbare
    # Sammler-Block des Fingerprint-Schemas fehlt (seit 24.09.2026 ist das der
    # Normalfall — die Marker stehen nur zufaellig im Klartext). Nur in der Kette.
    bDataHash = bChain and (bFpFallback or any(sMarker in sHtml for sMarker in HOSTADMIN_DATA_MARKERS))
    if bDataHash:
        sScheme = 'Kette, Datenhash'
        sDataSha = hashlib.sha256(_hostadmin_canonical(HOSTADMIN_DATA).encode('utf-8')).hexdigest()
        sPayloadTail = '"}'
    else:
        if bFpFallback:
            logger.info('HostAdmin: Fingerprint-Reihenfolge nicht lesbar, nehme die bekannte')
        aBotKeys, bBotFallback = _hostadmin_field_order(sHtml, HOSTADMIN_BOT_FIRST, HOSTADMIN_BOT_KEYS)
        if bBotFallback:
            logger.info('HostAdmin: Bot-Signal-Reihenfolge nicht lesbar, nehme die bekannte')
        aFp = dict((sKey, HOSTADMIN_FINGERPRINT.get(sKey, '0')) for sKey in aFpKeys)
        aBot = dict((sKey, '0') for sKey in aBotKeys)
        # Zeichengenau wie im Pruefskript zusammengesetzt (kein json.dumps: die
        # Gegenseite hasht denselben Text, jedes Leerzeichen zaehlt). In der Kette
        # wechseln Rundennummer und Seed je Runde, der Rest bleibt.
        sFpBody = ','.join('"%s":"%s"' % (sKey, aFp[sKey]) for sKey in aFpKeys)
        sBotBody = ','.join('"%s":"%s"' % (sKey, aBot[sKey]) for sKey in aBotKeys)
        sPayloadTail = '","fp":{' + sFpBody + '},"botSignals":{' + sBotBody + '}}'

    tStart = time.time()
    iFullBytes, iRestBits = divmod(iBits, 8)
    sRoundSeed = sSeed
    aNonces = []
    aRoundMs = []
    for iRound in range(1, iRounds + 1):
        tRound = time.time()
        # Zeitgrenze fuer die GANZE Aufgabe, nicht je Runde: geprueft vor jeder
        # Runde und in langen Runden zwischendurch.
        if time.time() - tStart > HOSTADMIN_TIME_LIMIT:
            logger.error('HostAdmin: Zeitgrenze von %d s erreicht vor Runde %d von %d (%s, %d Bit)'
                         % (HOSTADMIN_TIME_LIMIT, iRound, iRounds, sScheme, iBits))
            return None
        if bDataHash:
            # Reihenfolge wie im Worker-Skript: data_sha, round, seed.
            sPayload = '{"data_sha":"' + sDataSha + '","round":' + str(iRound) + ',"seed":"' + sRoundSeed + sPayloadTail
        else:
            sPayload = ('{"round":' + str(iRound) + ',' if bChain else '{') + '"seed":"' + sRoundSeed + sPayloadTail
        oBase = hashlib.sha256(sPayload.encode('utf-8') + struct.pack('<I', iMix))
        iNonce = 0
        iFound = -1
        while iNonce <= 0xFFFFFFFF:
            oHash = oBase.copy()
            oHash.update(struct.pack('<I', iNonce))
            sDigest = oHash.digest()
            if not any(sDigest[:iFullBytes]) and (not iRestBits or sDigest[iFullBytes] >> (8 - iRestBits) == 0):
                iFound = iNonce
                break
            iNonce += 1
            if iNonce % 50000 == 0 and time.time() - tStart > HOSTADMIN_TIME_LIMIT:
                logger.error('HostAdmin: Zeitgrenze von %d s erreicht in Runde %d von %d bei Zahl %d (%s, %d Bit)'
                             % (HOSTADMIN_TIME_LIMIT, iRound, iRounds, iNonce, sScheme, iBits))
                return None
        if iFound < 0:
            logger.error('HostAdmin: keine Loesung gefunden in Runde %d von %d (%s)' % (iRound, iRounds, sScheme))
            return None
        aNonces.append(iFound)
        aRoundMs.append(round((time.time() - tRound) * 1000, 2))
        sRoundSeed = sRoundSeed + '_' + str(iFound)
    iTook = int((time.time() - tStart) * 1000)
    logger.info('HostAdmin geloest (%s): %d Runde%s zu %d Bit nach %d ms' % (sScheme, iRounds, '' if iRounds == 1 else 'n', iBits, iTook))
    aBody = {'fast': False, 'initialReqId': sReqId, 'ticket': sSeed}
    if bChain:
        aBody['nonces'] = aNonces
    else:
        aBody['nonce'] = aNonces[0]
    if not bDataHash:
        aBody['fp'] = aFp
        aBody['botSignals'] = aBot
    aBody['spotValuesHex'] = _hostadmin_spot_values(sSeed)
    # timeMs ist im Browser die Zeit vom Seitenstart bis zur Einreichung, also
    # Rechenzeit plus das Einsammeln des Fingerprints.
    aBody['timeMs'] = iTook + 350
    if bDataHash:
        # Rechenprofil wie im Skript: total_hashes ist dort die SUMME der Nonces.
        iTotal = sum(aNonces)
        fPowMs = sum(aRoundMs)
        aBody['compute_profile'] = {'total_hashes': iTotal, 'pow_time_ms': int(round(fPowMs)),
                                    'hashrate_hps': int(round(iTotal / fPowMs * 1000)) if fPowMs > 0 else 0,
                                    'round_times_ms': aRoundMs}
        # Muss als LETZTES und bytegleich zur gehashten Form raus — der Aufrufer
        # serialisiert kompakt, die Schluessel sind schon sortiert.
        aBody['data'] = HOSTADMIN_DATA
    return aBody
