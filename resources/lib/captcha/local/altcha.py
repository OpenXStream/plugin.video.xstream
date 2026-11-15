# -*- coding: utf-8 -*-
# Python 3
#
# Altcha-Loeser (Proof-of-Work): die Seite liefert eine Challenge, der Client
# rechnet die Loesung und schickt sie als Formularfeld zurueck. Teil des Pakets
# resources.lib.captcha.local (Fassade in __init__.py), verschoben aus dem
# frueheren Sammelmodul — Rechenkern unveraendert.
# QUELLE der Rechenwege und Antwortformen: die offizielle Bibliothek
# https://github.com/altcha-org/altcha-lib (v1: solveChallenge in v1/index,
# v2: v2/algorithms/sha und pbkdf2) — altcha-lib 2.6.0 und Widget altcha 3.3.0,
# gelesen 14.10.2026; beide Formen am 13.10.2026 mit createChallenge und
# verifySolution der Bibliothek gegengerechnet.
import base64
import hashlib
import json
import re
import struct
import time

from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger
from resources.lib.captcha.local import local_ready

# Vorgabe fuer maxnumber, wenn die Seite keinen Wert nennt — die Vorgabe der
# Altcha-Bibliothek selbst (DEFAULT_MAX_NUMBER = 1e6 in v1/index, 2.6.0,
# gelesen 14.10.2026). Nennt die Seite einen Wert (serienstream 09/2026:
# 100000), gilt der; einen Deckel gibt es bewusst nicht: die einzige Bremse ist
# die Zeitgrenze, und die passt sich dem Geraet an — ein schneller Rechner
# schafft in derselben Zeit mehr als ein Fire Stick, ein fester Deckel haette
# ihn nur ausgebremst (so entschieden am 10.09.2026: „Deckel raus, nur Zeitgrenze reicht").
ALTCHA_DEFAULT_MAX_NUMBER = 1000000
# Zeitgrenze fuer die Suche: laenger als das soll kein Klick warten. Zur
# Einordnung: 100.000 SHA-256 dauern hier rund 0,1 s, auf einem schwachen
# Android-Geraet grob eine Sekunde; ein PBKDF2-Versuch mit cost 10000 kostet
# rund 4 ms, bei keyPrefix "00" sind im Mittel 256 Versuche noetig.
ALTCHA_TIME_LIMIT = 30
# Rechenarten der v1-Form (Hash ueber salt + Zahl), Digest aus dem Namen. Die
# Altcha-Bibliothek nennt SHA-1, SHA-256 und SHA-512 (Typ Algorithm in v1/types)
# und rechnet auch SHA-384 (hash() reicht den Namen an crypto.subtle durch), das
# Widget nimmt SHA-256, SHA-384 und SHA-512 (Enum in altcha 3.3.0) — zusammen
# diese vier, mehr kennt die alte Form nicht (gelesen 14.10.2026); serienstream
# nutzt SHA-256.
ALTCHA_V1_DIGESTS = {'SHA-1': 'sha1', 'SHA-256': 'sha256', 'SHA-384': 'sha384', 'SHA-512': 'sha512'}
# Rechenarten der v2-Form, die hier gerechnet werden, mit dem Digest aus dem
# Namen: PBKDF2 (Schluesselableitung ueber hashlib.pbkdf2_hmac) und iteriertes
# SHA (Digest ueber salt + Passwort, `cost`-mal, am Ende auf keyLength gekuerzt)
# — derselbe Weg, nur der Hash wechselt. Nicht gerechnet: SCRYPT (speicher- und
# zeitintensiv, ohne echten Server nicht belegbar), ARGON2ID (nicht in Kodis
# Python) und die Zusatzpruefungen (aufgezeichnete Eingaben, Bild-/Audio-Code,
# keine Rechenaufgabe) — sie landen mit Logzeile im Rueckweg ''.
ALTCHA_V2_DIGESTS = {'SHA-256': 'sha256', 'SHA-384': 'sha384', 'SHA-512': 'sha512',
                     'PBKDF2/SHA-256': 'sha256', 'PBKDF2/SHA-384': 'sha384', 'PBKDF2/SHA-512': 'sha512'}


def solve_altcha(sChallengeUrl, sReferer=''):
    """Altcha-Challenge holen, rechnen, Antwort als base64-JSON liefern.

    Ablauf wie im Altcha-Widget: GET auf die Challenge-Adresse liefert die
    Challenge als JSON, die Form entscheidet den Rechenweg. v1 (flach):
    gesucht wird die Zahl n, fuer die Hash(salt + n) gleich challenge ist,
    die Antwort ist das base64-kodierte JSON mit algorithm, challenge, number,
    salt, signature und took. v2 (`parameters`): gesucht wird der Zaehler,
    dessen abgeleiteter Schluessel (PBKDF2 oder iteriertes SHA) mit keyPrefix
    beginnt, die Antwort ist das base64-kodierte JSON aus challenge und
    solution — jeweils genau die Form, die das Widget in sein verstecktes Feld
    schreibt. Die Signatur wird unveraendert zurueckgegeben, sie prueft der
    Server.

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

    # Die v2-Form traegt die Aufgabe unter `parameters`, v1 flach — daran wird
    # die Form erkannt, nicht an der Seite.
    if isinstance(jChallenge.get('parameters'), dict):
        return _solve_altcha_v2(jChallenge)
    return _solve_altcha_v1(jChallenge)


def _solve_altcha_v1(jChallenge):
    """v1: die Zahl n mit Hash(salt + n) == challenge, Antwort als base64-JSON oder ''."""
    sAlgorithm = str(jChallenge.get('algorithm', '')).upper()
    sChallenge = str(jChallenge.get('challenge', '')).lower()
    sSalt = str(jChallenge.get('salt', ''))
    sSignature = str(jChallenge.get('signature', ''))
    # Der Hash kommt aus dem Namen der Rechenart; der Konstruktor wird einmal
    # geholt, damit die Schleife so schnell bleibt wie mit hashlib.sha256 direkt.
    fnHash = getattr(hashlib, ALTCHA_V1_DIGESTS.get(sAlgorithm, ''), None)
    if fnHash is None or not (sChallenge and sSalt and sSignature):
        logger.error('Altcha: unbekannte Challenge-Form (%s)' % sAlgorithm)
        return ''
    try:
        iMaxNumber = int(jChallenge.get('maxnumber') or ALTCHA_DEFAULT_MAX_NUMBER)
    except (TypeError, ValueError):
        iMaxNumber = ALTCHA_DEFAULT_MAX_NUMBER

    tStart = time.time()
    sSaltBytes = sSalt.encode('utf-8')
    for iNumber in range(iMaxNumber + 1):
        if fnHash(sSaltBytes + str(iNumber).encode('utf-8')).hexdigest() == sChallenge:
            iTook = int((time.time() - tStart) * 1000)
            aPayload = {'algorithm': jChallenge.get('algorithm'), 'challenge': jChallenge.get('challenge'),
                        'number': iNumber, 'salt': sSalt, 'signature': sSignature, 'took': iTook}
            logger.info('Altcha v1 geloest (%s): Zahl %d nach %d ms' % (sAlgorithm, iNumber, iTook))
            # Kompakt wie JSON.stringify im Browser (ohne Leerzeichen)
            return base64.b64encode(json.dumps(aPayload, separators=(',', ':')).encode('utf-8')).decode('ascii')
        if iNumber % 10000 == 0 and time.time() - tStart > ALTCHA_TIME_LIMIT:
            logger.error('Altcha: Zeitgrenze von %d s erreicht bei Zahl %d' % (ALTCHA_TIME_LIMIT, iNumber))
            return ''
    logger.error('Altcha: keine Loesung bis %d' % iMaxNumber)
    return ''


def _solve_altcha_v2(jChallenge):
    """v2: der Zaehler, dessen abgeleiteter Schluessel mit keyPrefix beginnt, Antwort als base64-JSON oder ''.

    Rechnung wie in der Altcha-Bibliothek: Passwort = nonce + Zaehler (4 Byte,
    big-endian); Schluessel = PBKDF2(Passwort, salt, cost, keyLength) bzw. bei
    iteriertem SHA der Digest ueber salt + Passwort, `cost`-mal ueber den vollen
    Digest, am Ende auf keyLength gekuerzt — Digest jeweils aus dem Namen der
    Rechenart; passt, wenn der Schluessel (hex) mit keyPrefix beginnt. Die
    Antwort traegt die Challenge unveraendert (parameters und signature) plus
    solution (counter, derivedKey, time).
    """
    dParams = jChallenge['parameters']
    sAlgorithm = str(dParams.get('algorithm', ''))
    # Zusatzpruefungen des Widgets — aufgezeichnete Eingaben (his = Human
    # Interaction Signature, das Widget 3.3.0 schickt sie an his.url) und der
    # Bild-/Audio-Code (codeChallenge) — sind keine Rechenaufgabe; ohne sie
    # wuerde der Server die Loesung ablehnen, also gleich mit Logzeile raus.
    for sExtra in ('his', 'codeChallenge'):
        if sExtra in jChallenge or sExtra in dParams:
            logger.error('Altcha v2: Zusatzpruefung %s nicht unterstuetzt' % sExtra)
            return ''
    sDigest = ALTCHA_V2_DIGESTS.get(sAlgorithm)
    if not sDigest:
        logger.error('Altcha v2: unbekannte Rechenart (%s)' % sAlgorithm)
        return ''
    try:
        bNonce = bytes.fromhex(str(dParams.get('nonce', '')))
        bSalt = bytes.fromhex(str(dParams.get('salt', '')))
        iCost = int(dParams.get('cost'))
        iKeyLength = int(dParams.get('keyLength') or 32)
        sKeyPrefix = str(dParams.get('keyPrefix', '')).lower()
    except (TypeError, ValueError):
        logger.error('Altcha v2: Challenge unvollstaendig (%s)' % ', '.join(sorted(dParams)))
        return ''
    # Ein Praefix, das laenger als der Schluessel oder kein Hex ist, trifft nie —
    # das waere sonst eine volle Zeitgrenze fuer nichts.
    if not (bNonce and bSalt and iCost > 0 and iKeyLength > 0 and sKeyPrefix
            and len(sKeyPrefix) <= iKeyLength * 2 and re.match(r'^[0-9a-f]+$', sKeyPrefix)):
        logger.error('Altcha v2: Challenge unvollstaendig (%s)' % ', '.join(sorted(dParams)))
        return ''
    bPbkdf2 = sAlgorithm.startswith('PBKDF2/')
    fnPbkdf2 = getattr(hashlib, 'pbkdf2_hmac', None)
    if bPbkdf2 and fnPbkdf2 is None:
        # Python ohne OpenSSL-Anbindung — kein Absturz nach dem bezahlten Turnstile
        logger.error('Altcha v2: pbkdf2 in dieser Python-Umgebung nicht verfuegbar')
        return ''

    def deriveKey(bPassword):
        if bPbkdf2:
            return fnPbkdf2(sDigest, bPassword, bSalt, iCost, iKeyLength)
        bData = bSalt + bPassword
        for _ in range(iCost):
            bData = hashlib.new(sDigest, bData).digest()
        return bData[:iKeyLength]

    tStart = time.time()
    iCounter = 0
    while True:
        sKey = deriveKey(bNonce + struct.pack('>I', iCounter)).hex()
        if sKey.startswith(sKeyPrefix):
            break
        iCounter += 1
        # Ein Versuch kostet Millisekunden, deshalb oefter auf die Uhr als bei v1
        if iCounter % 16 == 0 and time.time() - tStart > ALTCHA_TIME_LIMIT:
            logger.error('Altcha v2: Zeitgrenze von %d s erreicht bei Zaehler %d' % (ALTCHA_TIME_LIMIT, iCounter))
            return ''
    iTook = int((time.time() - tStart) * 1000)
    aPayload = {'challenge': {'parameters': dParams, 'signature': jChallenge.get('signature')},
                'solution': {'counter': iCounter, 'derivedKey': sKey, 'time': iTook}}
    logger.info('Altcha v2 geloest (%s): Zaehler %d nach %d ms' % (sAlgorithm, iCounter, iTook))
    # Kompakt wie JSON.stringify im Browser (ohne Leerzeichen)
    return base64.b64encode(json.dumps(aPayload, separators=(',', ':')).encode('utf-8')).decode('ascii')
