# -*- coding: utf-8 -*-
# Python 3
#
# Gate-Muster (Schemas) fuer Anti-Bot-Huerden, die VOR einer Hoster-Seite
# stehen. Gilt fuer alles, was mehrere Hoster oder Seiten betrifft — ein Gate,
# das nur zu einer Seite gehoert, bleibt in deren Site-File (serienstream
# `_passRedirectGate`, burningseries reCAPTCHA).
#
# Rollen im Captcha-Ordner: captcha_solver.py ist die bezahlte Dienst-Anbindung
# (2captcha), local_solver.py rechnet selbst (Altcha, HostAdmin), captcha_helper.py ist
# der Klebstoff (Bereitschaft, solve_*, Sitekey-Extraktoren) — und hier stehen
# die Muster. Je Schema ein Erkenner `matches(html)` und ein Raeumer
# `clear(...)`; `clear_gate(url)` darunter ist der Dispatcher, den
# gui/hoster.py aufruft.
#
# Erkennung IMMER ueber das Markup, nie ueber eine Domainliste: im ganzen
# Captcha-Kern steht kein Hostername, der Weg haengt allein am Verhalten der
# Seite. Wer ein neues Schema baut, schreibt einen Erkenner und einen Raeumer
# und haengt die Klasse an SCHEMAS — der Dispatcher laedt die Seite EINMAL und
# reicht dasselbe HTML an alle Erkenner (der Abruf ist der teure Schritt, und
# er laeuft bewusst ueber ResolveURLs Net, damit das Freigabe-Cookie in dem
# Jar landet, den der Resolver danach benutzt).

import re
from urllib.parse import urlparse

from resources.lib.logger import logger
from resources.lib.config import cConfig
from resources.lib.tools import infoDialog
from resources.lib.captcha.captcha_helper import captcha_ready, solve_turnstile, extract_turnstile_sitekey

# Kennzeichen einer Seite mit Cloudflare Turnstile; im Kompatibilitätsmodus
# heisst das Widget-Element 'g-recaptcha', Google ist dabei nicht beteiligt
TURNSTILE_MARKER = 'challenges.cloudflare.com/turnstile'


class TurnstileFormGate:
    """Schema 1: Formular mit Cloudflare Turnstile, Freigabe per Cookie.

    So sieht es bei Dropload/dr0pstream aus (seit 09/2026): ohne gueltiges Token
    liefert die Seite nur ein Formular mit dem Widget, ResolveURL findet dort
    keinen Stream — ein Turnstile ist in reinem Python nicht loesbar. Das Token
    wird beim Captcha-Dienst gekauft und das Formular abgeschickt; das
    Freigabe-Cookie liegt danach im Jar von ResolveURLs Net, und der
    unveraenderte Resolver bekommt beim naechsten Versuch die Playerseite.
    Die Aufloesung selbst bleibt ResolveURLs Aufgabe, wir raeumen nur die
    Anti-Bot-Huerde.

    Grenzen (bewusst nicht gebaut, ohne echten Fall): ein Formular, dessen
    `action` auf eine fremde Adresse zeigt (wir posten an die Seite selbst
    zurueck, Dropload fuehrt action=""); eine Freigabe, die nicht am Cookie
    haengt; eine echte Cloudflare-Zwischenseite. Braucht ein Fall davon
    mehr als andere Feldwerte, ist das ein eigenes Schema hier — kein `if`
    nach Hoster oder Seite in diesem.
    """
    name = 'turnstile-form'
    needs_key = True    # das Token kostet, ohne Schluessel wird die Seite nicht geladen

    @staticmethod
    def matches(htmlContent):
        return TURNSTILE_MARKER in htmlContent

    @staticmethod
    def clear(net, htmlContent, pageUrl, headers):
        sitekey = extract_turnstile_sitekey(htmlContent)
        if not sitekey:
            logger.error('Turnstile: kein Sitekey in der Hoster-Seite gefunden')
            return False

        infoDialog(cConfig().getLocalizedString(30825), icon='INFO', time=10000)
        token = solve_turnstile(sitekey, pageUrl)
        if not token:
            infoDialog(cConfig().getLocalizedString(30826), icon='ERROR', time=10000)
            return False

        data = dict(re.findall(r'<input[^>]+type=["\']hidden["\'][^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']', htmlContent))
        # Turnstile im reCAPTCHA-Kompatibilitätsmodus füllt beide Feldnamen
        data.update({'cf-turnstile-response': token, 'g-recaptcha-response': token})
        rootUrl = urlparse(pageUrl)
        headers = dict(headers)
        headers.update({'Referer': pageUrl, 'Origin': f'{rootUrl.scheme}://{rootUrl.netloc}'})
        htmlContent = net.http_POST(pageUrl, form_data=data, headers=headers).content
        # Erfolgskontrolle gehoert zum Schema: steht der Marker danach noch da,
        # hat die Seite das Token nicht angenommen
        if TURNSTILE_MARKER in htmlContent:
            logger.error('Turnstile: Token wurde von der Hoster-Seite nicht akzeptiert')
            infoDialog(cConfig().getLocalizedString(30826), icon='ERROR', time=10000)
            return False
        logger.info('Turnstile: Hoster-Seite freigeschaltet')
        return True


# Reihenfolge = Prueffolge; das erste passende Schema raeumt
SCHEMAS = (TurnstileFormGate,)


def clear_gate(sUrl):
    """
    Räumt ein Gate, das VOR einer Hoster-Playerseite steht — falls eines der
    bekannten Schemas darauf passt.

    ENTSCHEIDEND ist der Weg über ResolveURLs eigenes Net: dessen Cookie-Jar
    ist ein Klassenattribut und wird von jeder weiteren Anfrage im selben
    Kodi-Aufruf mitbenutzt. Das Freigabe-Cookie der gelösten Runde liegt danach
    also im Jar, und der unveränderte Resolver von ResolveURL bekommt beim
    nächsten Versuch die Playerseite statt des Formulars.

    Args:
        sUrl (str): Die Hoster-Adresse, an der ResolveURL gescheitert ist

    Returns:
        bool: True, wenn ein Gate stand und geräumt wurde
    """
    # Kostenschutz: solange jedes Schema den bezahlten Dienst braucht, wird
    # ohne Schalter oder Schluessel die Seite gar nicht erst geladen (kein
    # Netzzugriff, keine Meldung). Ein Schema ohne Schluesselbedarf (lokal
    # gerechnet) hebt das auf, dann prueft der Dispatcher je Schema.
    if all(schema.needs_key for schema in SCHEMAS) and not captcha_ready():
        return False

    try:
        from resolveurl import common as resolverCommon
    except Exception as e:
        logger.error(f"Gate: ResolveURL nicht verfügbar: {str(e)}")
        return False

    try:
        # user_agent im Konstruktor: derselbe User-Agent gilt danach auch fuer
        # die Anfragen des Resolvers. Aeltere ResolveURL-Staende bauten ihren
        # Opener (der den Cookie-Speicher an urllib haengt) erst ueber
        # set_user_agent / set_cookies / set_proxy — ohne den Schritt landete das
        # Freigabe-Cookie nicht im Jar und der Resolver bekam wieder das Formular
        # (gemessen 08.09.2026: mal ging es, mal nicht). Der aktuelle Master
        # (09/2026) baut den Opener im Konstruktor immer.
        # ssl_verify=False wie in ResolveURLs eigenen Resolvern fuer Hoster mit
        # unvollstaendiger Zertifikatskette (vids.st, cimanow, playhd): mit der
        # Pruefung brach der Gate-Check dort mit CERTIFICATE_VERIFY_FAILED ab,
        # bevor er die Seite sah (Jacks Log 30.09.2026, vids.st), waehrend
        # Gujals VidsSt-Resolver dieselbe Seite ohne Pruefung bekam. Unser
        # requestHandler prueft ohnehin nicht; Geheimnisse gehen hier nicht mit.
        net = resolverCommon.Net(user_agent=resolverCommon.RAND_UA, ssl_verify=False)
        headers = {'User-Agent': resolverCommon.RAND_UA}
        response = net.http_GET(sUrl, headers=headers)
        htmlContent = response.content
        pageUrl = response.get_url()  # Zweitdomains leiten auf die Hauptdomain um
        for schema in SCHEMAS:
            if not schema.matches(htmlContent):
                continue
            if schema.needs_key and not captcha_ready():
                return False
            logger.info('Gate: Schema %s erkannt auf %s' % (schema.name, urlparse(pageUrl).hostname))
            return schema.clear(net, htmlContent, pageUrl, headers)
        return False
    except Exception as e:
        logger.error(f"Fehler beim Räumen des Gates: {str(e)}")
        return False
