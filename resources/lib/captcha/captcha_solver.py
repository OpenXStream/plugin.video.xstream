# -*- coding: utf-8 -*-
# Python 3
#
#05.07.2025 Heptamer
#
# Captcha Bibliothek


import json
import time
import xbmc
import xbmcgui
from resources.lib.handler.requestHandler import cRequestHandler
from resources.lib.logger import logger
from resources.lib.config import cConfig


# Fehlercodes von in.php, mit denen 2Captcha den Schluessel oder das Konto ablehnt, je mit dem
# Grund fuer die Einblendung (captcha_helper meldet ihn ueber tools.keyRejected, dieselben Strings
# wie beim TMDB-Schluessel). Codes und Bedeutung aus dem offiziellen Client
# 2captcha/2captcha-javascript (src/structs/2captchaError.ts, Master d3587e3 vom 20.10.2026,
# gelesen 01.11.2026); die beiden Schluessel-Codes am 01.11.2026 gegen in.php gemessen.
KEY_ERRORS = {
    'ERROR_WRONG_USER_KEY': 30917,      # Schluessel hat nicht die Form: 32 Zeichen (gemessen: 10 und 33 Zeichen)
    'ERROR_KEY_DOES_NOT_EXIST': 30917,  # Schluessel gibt es nicht (gemessen: ausgedachter Schluessel mit 32 Zeichen)
    'ERROR_ZERO_BALANCE': 30918,        # kein Guthaben auf dem Konto
    'IP_BANNED': 30919,                 # IP gesperrt nach vielen Anfragen mit falschem Schluessel (laut Client 5 Minuten)
    'ERROR_IP_NOT_ALLOWED': 30920,      # IP fehlt in der IP-Liste, die im 2Captcha-Konto gepflegt wird
}


class CaptchaKeyError(Exception):
    """in.php lehnt Schluessel oder Konto ab; die Nachricht ist der Fehlercode aus KEY_ERRORS."""


def _raiseIfRejected(json_response):
    """Antwort von in.php pruefen, bevor die Auftrags-ID benutzt wird.

    Bei status 0 steht im Feld 'request' der Fehlercode (ERROR_KEY_DOES_NOT_EXIST,
    ERROR_ZERO_BALANCE ...) — bis zum 10.09.2026 lief der als Auftrags-ID in den Abfrage-Loop
    und res.php wurde einmal umsonst gefragt. Lehnt der Dienst Schluessel oder Konto ab, kommt
    CaptchaKeyError: der Helfer nennt dann den Grund statt „Captcha nicht geloest".
    """
    if json_response.get('status') != 1:
        sCode = json_response.get('request')
        if sCode in KEY_ERRORS:
            raise CaptchaKeyError(sCode)
        raise Exception(f"Captcha-Dienst lehnt die Anfrage ab: {sCode}")


class CaptchaSolver:
    """
    Eine wiederverwendbare Klasse zum Lösen verschiedener Captcha-Typen.
    Unterstützt aktuell 2Captcha für reCAPTCHA v2 und Cloudflare Turnstile.
    """

    def __init__(self, api_key=None, provider=None, timeout=120):
        """
        Initialisiert den Captcha-Solver.

        Args:
            api_key (str): API-Schlüssel für den Captcha-Dienst
            provider (str): Captcha-Dienst ('2captcha')
            timeout (int): Maximale Wartezeit in Sekunden
        """
        self.api_key = api_key
        self.provider = provider
        self.timeout = timeout

    def solve_recaptcha_v2(self, site_key, page_url):
        """
        Löst ein reCAPTCHA v2.

        Args:
            site_key (str): Der Google reCAPTCHA Site-Key
            page_url (str): Die URL der Seite mit dem Captcha

        Returns:
            str: Der Captcha-Lösungstoken
        """
        if self.provider == '2captcha':
            return self._solve_with_2captcha(site_key, page_url)
        # Hier können später weitere Provider hinzugefügt werden
        raise ValueError(f"Captcha-Provider '{self.provider}' wird nicht unterstützt")

    def solve_turnstile(self, site_key, page_url):
        """
        Löst ein Cloudflare Turnstile (Standalone-Widget auf einer Seite).

        Args:
            site_key (str): Der Turnstile Site-Key (data-sitekey)
            page_url (str): Die URL der Seite mit dem Captcha

        Returns:
            str: Der Captcha-Lösungstoken
        """
        if self.provider == '2captcha':
            return self._solve_turnstile_with_2captcha(site_key, page_url)
        # Ein zweiter Dienst muesste hier einen eigenen Zweig bekommen
        raise ValueError(f"Captcha-Provider '{self.provider}' unterstützt kein Turnstile")

    def _solve_turnstile_with_2captcha(self, site_key, page_url):
        """2Captcha-Implementation für Cloudflare Turnstile"""
        if not self.api_key:
            xbmcgui.Dialog().ok(cConfig().getLocalizedString(30241), cConfig().getLocalizedString(30291))
            return None

        params = {
            'key': self.api_key,
            'method': 'turnstile',
            'sitekey': site_key,
            'pageurl': page_url,
            'json': 1,
        }

        # ignoreErrors wie bei den Abfragen in _get_2captcha_result: scheitert der Dienst selbst (5xx, Reset,
        # Timeout), meldet captcha_helper._solved „Captcha nicht geloest" (30826). Bis zum 02.11.2026 kam
        # ausserhalb des Hosterlink-Schritts (Gate eines Hosters, clear_gate) zusaetzlich das Fehlerfenster des
        # requestHandlers — zwei Meldungen fuer einen Fehlschlag (lokal nachgestellt).
        captcha_request = cRequestHandler('https://2captcha.com/in.php', caching=False, method='POST',
                                          data=json.dumps(params), ignoreErrors=True)
        captcha_request.addHeaderEntry('Content-Type', 'application/json')
        response_text = captcha_request.request()

        try:
            json_response = json.loads(response_text)
        except json.JSONDecodeError:
            raise Exception(f"Ungültige Antwort vom Captcha-Dienst: {response_text}")

        if 'request' not in json_response:
            raise Exception(f"Ungültige Antwort vom Captcha-Dienst: {json_response}")
        _raiseIfRejected(json_response)

        captcha_id = json_response['request']
        logger.info(f'Turnstile-Anfrage gesendet mit ID: {captcha_id}')

        return self._get_2captcha_result(captcha_id)

    def _solve_with_2captcha(self, site_key, page_url):
        """2Captcha-Implementation für reCAPTCHA v2"""
        if not self.api_key:
            xbmcgui.Dialog().ok(cConfig().getLocalizedString(30241), cConfig().getLocalizedString(30291))
            return None

        params = {
            'key': self.api_key,
            'method': 'userrecaptcha',
            'googlekey': site_key,
            'pageurl': page_url,
            'json': 1,
        }

        # ignoreErrors: ein Fehlschlag des Dienstes meldet _solved, siehe _solve_turnstile_with_2captcha
        captcha_request = cRequestHandler('https://2captcha.com/in.php', caching=False, method='POST',
                                          data=json.dumps(params), ignoreErrors=True)
        captcha_request.addHeaderEntry('Content-Type', 'application/json')
        response_text = captcha_request.request()

        try:
            json_response = json.loads(response_text)
        except json.JSONDecodeError:
            raise Exception(f"Ungültige Antwort vom Captcha-Dienst: {response_text}")

        if 'request' not in json_response:
            raise Exception(f"Ungültige Antwort vom Captcha-Dienst: {json_response}")
        _raiseIfRejected(json_response)

        captcha_id = json_response['request']
        logger.info(f'Captcha-Anfrage gesendet mit ID: {captcha_id}')

        return self._get_2captcha_result(captcha_id)

    def _get_2captcha_result(self, captcha_id):
        """Wartet auf und holt das Ergebnis von 2Captcha.

        Der Auftrag ist bezahlt, sobald in.php die ID geliefert hat. Deshalb wirft nur noch
        eine ANTWORT DES DIENSTES (JSON mit Fehlercode, z.B. ERROR_CAPTCHA_UNSOLVABLE) die
        Schleife ab; alles, was der Transport zurueckgibt (leer, HTML, die Sentinel des
        requestHandlers bei 5xx, Reset oder Timeout eines einzelnen Abrufs), gilt als
        voruebergehend und es wird bis captcha.timeout weiter gefragt. Bis zum 01.10.2026
        beendete die erste solche Antwort den Kauf, obwohl der Dienst die Loesung kurz darauf
        hatte (BurningSeries, ID nachtraeglich status 1); ein 5xx oder Reset oeffnete dabei
        ueber den requestHandler ein Fenster mitten im Kauf. Gemessen gegen den echten Dienst:
        Token oft beim ersten Poll, echte Loesungen in 12–14 s bei 2-s-Takt.
        """
        start_time = time.time()
        last_answer = ''

        while True:
            # Bewusst POST statt GET: der requestHandler schreibt jede Adresse ins
            # Kodi-Log, und in einer Abfrage per GET stuende der API-Schluessel im
            # Klartext darin. Logs landen im Support haeufig in fremden Haenden.
            # ignoreErrors: ein gescheiterter Poll bleibt eine Logzeile, kein Fenster und
            # keine Einblendung — gemeldet wird am Ende vom Aufrufer (Captcha nicht geloest).
            request = cRequestHandler('https://2captcha.com/res.php', caching=False, method='POST',
                                      data={'key': self.api_key, 'action': 'get', 'id': captcha_id, 'json': 1},
                                      ignoreErrors=True)
            response_text = request.request()
            last_answer = (response_text or '')[:120]

            json_res = None
            try:
                json_res = json.loads(response_text)
            except (json.JSONDecodeError, TypeError):
                logger.error(f"2Captcha-Antwort kein JSON, frage weiter: {last_answer}")

            if json_res is not None:
                if json_res.get('status') == 1:
                    return json_res.get('request')
                elif json_res.get('request') != 'CAPCHA_NOT_READY':
                    error_msg = f"Fehler beim Lösen des Captchas: {json.dumps(json_res, indent=2)} \nID: {captcha_id}"
                    logger.error(error_msg)
                    raise Exception(error_msg)

            if time.time() - start_time >= self.timeout:
                error_msg = f"Timeout beim Warten auf Captcha-Lösung (ID: {captcha_id}, letzte Antwort: {last_answer})"
                logger.error(error_msg)
                raise Exception(error_msg)

            # Kurze Pause zwischen den Anfragen (2 s: der Dienst liefert Token oft beim ersten
            # Poll, ein laengerer Erstabstand wuerde genau diesen Fall verzoegern)
            time.sleep(2)
