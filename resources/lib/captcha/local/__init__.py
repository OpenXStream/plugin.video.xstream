# -*- coding: utf-8 -*-
# Python 3
#
# Lokale Captcha-Loeser: alles, was der Client SELBST rechnet — ohne Dienst,
# ohne Schluessel und ohne Kosten. Gegenstueck zu captcha_solver.py (2captcha).
# Dieses Paket ist zugleich die Fassade: altcha.py (Altcha, Proof-of-Work) und
# hostadmin.py (HostAdmin.online-WAF, Proof-of-Work) rechnen, hier werden ihre
# Namen gebuendelt — Abnehmer importieren aus resources.lib.captcha.local.
#
# REIHENFOLGE IST PFLICHT: local_ready() steht VOR den Re-Export-Importen, weil
# altcha.py und hostadmin.py es aus diesem Paket importieren, waehrend das Paket
# sie gerade laedt. So ist der Import in jeder Reihenfolge zirkelfrei (auch beim
# Direktimport eines Teilmoduls).
from resources.lib.config import cConfig
from resources.lib.logger import logger


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


# --- Fassade (nach local_ready, siehe Kopf) ---------------------------------
from resources.lib.captcha.local.altcha import (  # noqa: E402
    ALTCHA_DEFAULT_MAX_NUMBER, ALTCHA_TIME_LIMIT, ALTCHA_V1_DIGESTS, ALTCHA_V2_DIGESTS,
    solve_altcha, _solve_altcha_v1, _solve_altcha_v2,
)
from resources.lib.captcha.local.hostadmin import (  # noqa: E402
    HOSTADMIN_MARKERS, HOSTADMIN_VERIFY_PATH, HOSTADMIN_TIME_LIMIT, HOSTADMIN_MIX_FALLBACK,
    HOSTADMIN_ROUND_BITS_FALLBACK, HOSTADMIN_BOT_KEYS, HOSTADMIN_FINGERPRINT, HOSTADMIN_FP_FIRST,
    HOSTADMIN_BOT_FIRST, HOSTADMIN_DATA_MARKERS, HOSTADMIN_DATA, HOSTADMIN_BACKGROUND, HOSTADMIN_PAGE_MARKERS,
    is_hostadmin_background, is_hostadmin_gate, _hostadmin_first, _hostadmin_field_order, _hostadmin_canonical,
    _hostadmin_mix, _hostadmin_spot_values, solve_hostadmin,
)

__all__ = [
    'local_ready',
    'ALTCHA_DEFAULT_MAX_NUMBER', 'ALTCHA_TIME_LIMIT', 'ALTCHA_V1_DIGESTS', 'ALTCHA_V2_DIGESTS',
    'solve_altcha', '_solve_altcha_v1', '_solve_altcha_v2',
    'HOSTADMIN_MARKERS', 'HOSTADMIN_VERIFY_PATH', 'HOSTADMIN_TIME_LIMIT', 'HOSTADMIN_MIX_FALLBACK',
    'HOSTADMIN_ROUND_BITS_FALLBACK', 'HOSTADMIN_BOT_KEYS', 'HOSTADMIN_FINGERPRINT', 'HOSTADMIN_FP_FIRST',
    'HOSTADMIN_BOT_FIRST', 'HOSTADMIN_DATA_MARKERS', 'HOSTADMIN_DATA', 'HOSTADMIN_BACKGROUND', 'HOSTADMIN_PAGE_MARKERS',
    'is_hostadmin_background', 'is_hostadmin_gate', '_hostadmin_first', '_hostadmin_field_order', '_hostadmin_canonical',
    '_hostadmin_mix', '_hostadmin_spot_values', 'solve_hostadmin',
]
