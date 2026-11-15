# -*- coding: utf-8 -*-
# Python 3
#
#05.07.2025 Heptamer
#
# Captcha Helper — der Klebstoff: Schluessel und Bereitschaft (captcha_key, captcha_ready),
# solve_* fuer den Dienst samt Meldung beim Scheitern und die Sitekey-Extraktoren. Die
# Gate-Muster fuer Hoster stehen in captcha_schemas.py, die lokalen Loeser (Altcha, HostAdmin)
# im Paket local/, die Dienst-Anbindung in captcha_solver.py. Site-eigene Gates bleiben im
# Site-File.

from resources.lib.logger import logger
from resources.lib.config import cConfig
from resources.lib.tools import infoDialog, keyRejected
from resources.lib.handler.requestHandler import _markErrorShown
from resources.lib.captcha.captcha_solver import CaptchaSolver, CaptchaKeyError, KEY_ERRORS

# Hat 2Captcha den Schluessel in DIESEM Aufruf schon abgelehnt (captcha_solver.KEY_ERRORS)? Dann fragt
# kein weiterer Hoster desselben Klicks den Dienst — wie beim eigenen TMDB-Schluessel, der fuer den Rest
# des Aufrufs ausfaellt (tmdb/api.py _ownKeyRejected; so entschieden am 01.11.2026). Im Auto-Modus fragte sonst jeder
# BurningSeries-Hoster neu an, mit eigenem „Captcha wird geloest", und viele Anfragen mit falschem
# Schluessel fuehren zu IP_BANNED. Jeder Aufruf ist ein frischer Interpreter: der naechste Klick fragt
# wieder, eine Pause ueber Klicks hinweg gibt es nicht (so entschieden: „Pause brauchen wir nicht").
_bKeyRejected = False


def captcha_key():
    """Der hinterlegte 2Captcha-Schluessel ohne Leerzeichen am Rand, wie der eigene TMDB-Schluessel
    (tmdb/api.py). 2Captcha schneidet sie selbst ab (gemessen 01.11.2026: 32 Zeichen plus
    Leerzeichen ergibt ERROR_KEY_DOES_NOT_EXIST, 33 Zeichen ohne ERROR_WRONG_USER_KEY); hier
    zaehlt ein Schluessel aus lauter Leerzeichen damit als keiner — BurningSeries schaltet sich
    ab, und es geht keine Anfrage raus."""
    return (cConfig().getSetting('2captcha.pass') or '').strip()


def captcha_ready():
    """
    Prueft, ob ueberhaupt geloest werden darf.

    Zwei Bedingungen, beide vom Nutzer gesteuert: der Schalter im Captcha-Reiter
    und ein hinterlegter Schluessel. Faellt eine weg, wird gar keine Seite geladen
    und kein Dialog gezeigt — der Aufrufer bricht still ab und zeigt seine
    gewohnte Meldung. Der Grund steht im Log, damit beide Faelle unterscheidbar
    bleiben. Dazu kommt: hat 2Captcha den Schluessel in diesem Aufruf schon
    abgelehnt (_bKeyRejected), ist fuer den Rest des Klicks Schluss — die
    Meldung mit dem Grund kam schon.

    Returns:
        bool: True, wenn der Schalter an ist, ein Schluessel hinterlegt ist und 2Captcha
        ihn in diesem Aufruf nicht abgelehnt hat
    """
    if cConfig().getSetting('captcha.enabled', 'true') != 'true':
        logger.info('Captcha: Dienst ist in den Einstellungen abgeschaltet')
        return False
    if not captcha_key():
        logger.info('Captcha: kein 2Captcha-Schluessel hinterlegt')
        return False
    if _bKeyRejected:
        logger.info('Captcha: 2Captcha hat den Schluessel in diesem Aufruf schon abgelehnt')
        return False
    return True


def _solved(fSolve, sName):
    """Loesung holen und ein Scheitern einmal melden, fuer alle Aufrufer gleich.

    Lehnt 2Captcha Schluessel oder Konto ab (captcha_solver.KEY_ERRORS), nennt die Einblendung
    den Grund — dieselbe wie beim TMDB-Schluessel (tools.keyRejected) — und fuer den Rest des
    Aufrufs fragt niemand mehr an (_bKeyRejected, captcha_ready). Jedes andere Scheitern
    meldet „Captcha nicht geloest" (30826); bis zum 01.11.2026 zeigte das jeder Aufrufer
    selbst, und beide Meldungen hintereinander waeren zwei Einblendungen fuer einen Fehlschlag.
    Danach gilt der Fehler als gemeldet (Merker des requestHandlers): die allgemeine
    Hoster-Meldung 30134/30135 desselben Klicks entfaellt (cGui.showError) — bis zum
    01.11.2026 kam sie nach 30826 noch dazu.
    """
    global _bKeyRejected
    try:
        sToken = fSolve()
    except CaptchaKeyError as e:
        logger.error(f"2Captcha lehnt Schluessel oder Konto ab: {e}")
        _bKeyRejected = True
        keyRejected('2Captcha', KEY_ERRORS[str(e)])
        _markErrorShown()
        return None
    except Exception as e:
        logger.error(f"Fehler beim Lösen des {sName}: {str(e)}")
        sToken = None
    if not sToken:
        infoDialog(cConfig().getLocalizedString(30826), icon='ERROR', time=10000)
        _markErrorShown()
    return sToken


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

    api_key = captcha_key()

    timeout = int(cConfig().getSetting('captcha.timeout', '120'))

    solver = CaptchaSolver(api_key=api_key, provider=provider, timeout=timeout)
    return _solved(lambda: solver.solve_recaptcha_v2(site_key, page_url), 'reCAPTCHAs')


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

    api_key = captcha_key()

    timeout = int(cConfig().getSetting('captcha.timeout', '120'))

    solver = CaptchaSolver(api_key=api_key, provider=provider, timeout=timeout)
    return _solved(lambda: solver.solve_turnstile(site_key, page_url), 'Turnstile')


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