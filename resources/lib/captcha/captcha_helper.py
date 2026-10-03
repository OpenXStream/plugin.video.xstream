# -*- coding: utf-8 -*-
# Python 3
#
#05.07.2025 Heptamer
#
# Captcha Helper — der Klebstoff: Bereitschaft (captcha_ready), solve_* fuer
# den Dienst und die Sitekey-Extraktoren. Die Gate-Muster fuer Hoster stehen
# in captcha_schemas.py, die lokalen Loeser (Altcha, HostAdmin) in local_solver.py, die
# Dienst-Anbindung in captcha_solver.py. Site-eigene Gates bleiben im Site-File.

from resources.lib.logger import logger
from resources.lib.config import cConfig
from resources.lib.captcha.captcha_solver import CaptchaSolver

def captcha_ready():
    """
    Prueft, ob ueberhaupt geloest werden darf.

    Zwei Bedingungen, beide vom Nutzer gesteuert: der Schalter im Captcha-Reiter
    und ein hinterlegter Schluessel. Faellt eine weg, wird gar keine Seite geladen
    und kein Dialog gezeigt — der Aufrufer bricht still ab und zeigt seine
    gewohnte Meldung. Der Grund steht im Log, damit beide Faelle unterscheidbar
    bleiben.

    Returns:
        bool: True, wenn der Schalter an ist und ein Schluessel hinterlegt ist
    """
    if cConfig().getSetting('captcha.enabled', 'true') != 'true':
        logger.info('Captcha: Dienst ist in den Einstellungen abgeschaltet')
        return False
    if not cConfig().getSetting('2captcha.pass'):
        logger.info('Captcha: kein 2Captcha-Schluessel hinterlegt')
        return False
    return True


def solve_recaptcha(site_key, page_url, provider=None):
    """
    Hilfsfunktion zum Lösen von reCAPTCHAs

    Args:
        site_key (str): Der Google reCAPTCHA Site-Key
        page_url (str): Die URL der Seite mit dem Captcha
        provider (str): Optional, überschreibt den konfigurierten Provider


    Returns:
        str: Der Captcha-Lösungstoken
    """
    if not captcha_ready():
        return None

    # captcha.provider ist seit dem 9kw-Ausbau kein Setting mehr; der Vorgabewert
    # greift, die Dienst-Weiche steht in captcha_solver.py
    if provider is None:
        provider = cConfig().getSetting('captcha.provider', '2captcha')

    if provider != '2captcha':
        logger.error(f"Unbekannter Captcha-Provider '{provider}'")
        return None

    api_key = cConfig().getSetting('2captcha.pass')

    timeout = int(cConfig().getSetting('captcha.timeout', '120'))

    solver = CaptchaSolver(api_key=api_key, provider=provider, timeout=timeout)
    try:
        return solver.solve_recaptcha_v2(site_key, page_url)
    except Exception as e:
        logger.error(f"Fehler beim Lösen des reCAPTCHAs: {str(e)}")
        return None


def solve_turnstile(site_key, page_url, provider=None):
    """
    Hilfsfunktion zum Lösen von Cloudflare Turnstile

    Args:
        site_key (str): Der Turnstile Site-Key
        page_url (str): Die URL der Seite mit dem Captcha
        provider (str): Optional, überschreibt den konfigurierten Provider

    Returns:
        str: Der Captcha-Lösungstoken
    """
    if not captcha_ready():
        return None

    # Aktuell gibt es nur einen Dienst; captcha.provider ist seit dem 9kw-Ausbau
    # kein Setting mehr, der Vorgabewert greift
    if provider is None:
        provider = cConfig().getSetting('captcha.provider', '2captcha')

    if provider != '2captcha':
        logger.error(f"Captcha-Provider '{provider}' unterstützt kein Turnstile")
        return None

    api_key = cConfig().getSetting('2captcha.pass')

    timeout = int(cConfig().getSetting('captcha.timeout', '120'))

    solver = CaptchaSolver(api_key=api_key, provider=provider, timeout=timeout)
    try:
        return solver.solve_turnstile(site_key, page_url)
    except Exception as e:
        logger.error(f"Fehler beim Lösen des Turnstile: {str(e)}")
        return None


def extract_turnstile_sitekey(html_content):
    """
    Extrahiert den Turnstile Site-Key aus dem HTML-Inhalt.

    Args:
        html_content (str): Der HTML-Inhalt der Webseite

    Returns:
        str: Der extrahierte Site-Key oder None
    """
    from resources.lib.tools import cParser

    # Im Kompatibilitätsmodus trägt das Widget die reCAPTCHA-Klasse, deshalb
    # entscheidet der Turnstile-Marker der Seite und nicht die Klasse
    isMatch, site_key = cParser.parseSingleResult(html_content, r'data-sitekey=["\']([^"\']+)')
    return site_key if isMatch else None


def extract_recaptcha_sitekey(html_content):
    """
    Extrahiert den reCAPTCHA Site-Key aus dem HTML-Inhalt.

    Args:
        html_content (str): Der HTML-Inhalt der Webseite

    Returns:
        str: Der extrahierte Site-Key oder None
    """
    from resources.lib.tools import cParser

    patterns = [
        r"series\.init\s*\(\s*\d+\s*,\s*\d+\s*,\s*'([^']+)'\s*\)\s*;",  # BurningSeries-Muster
        r'data-sitekey="([^"]+)"',  # Standard reCAPTCHA-Muster
        r"grecaptcha.execute\s*\(\s*'([^']+)'"  # Unsichtbares reCAPTCHA
    ]

    for pattern in patterns:
        isMatch, site_key = cParser.parseSingleResult(html_content, pattern)
        if isMatch:
            return site_key

    return None