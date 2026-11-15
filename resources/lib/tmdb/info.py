# -*- coding: utf-8 -*-
# Python 3

import ast
import xbmc
import time
import xbmcgui

from resources.lib.config import cConfig
from resources.lib.tmdb.api import cTMDB, IMAGE_URL, POSTER_SIZE
from resources.lib.logger import logger
from datetime import date, datetime
from urllib.parse import urlencode

# Info-Fenster bleiben bis zum Skriptende erhalten (siehe Ende von WindowsBoxes).
_dialogs = []


def _regionDate(sDate):
    """TMDB-Datum (JJJJ-MM-TT) in der Datumsform der Kodi-Region — Kodi liefert sie als strftime-Format,
    z.B. %d.%m.%Y (Premiere, Geburts- und Sterbedatum). Ein Format, das dieses Python nicht kennt, oder
    ein Datum in anderer Form kommt unveraendert zurueck."""
    if not sDate:
        return ''
    try:
        oDate = datetime(*(time.strptime(sDate, '%Y-%m-%d')[0:6]))
        return oDate.strftime(xbmc.getRegion('dateshort') or '%Y-%m-%d')
    except ValueError:
        return sDate


def _zahl(oWert, iStellen=0):
    """Zahl in der Schreibweise der Oberflaechensprache (seit dem 03.11.2026): Deutsch mit Punkt als Tausender- und
    Komma als Dezimalzeichen (160.000.000 · 8,4), jede andere Sprache mit Komma und Punkt (160,000,000 · 8.4). Kodi
    nennt keine Zahlenform der Region (getRegion kennt Datum, Uhrzeit, Temperatur, Tempo), deshalb die Sprache.
    Was keine Zahl ist, kommt unveraendert zurueck."""
    try:
        sText = '{:,.{p}f}'.format(float(oWert), p=iStellen)
    except (TypeError, ValueError):
        return oWert
    if xbmc.getLanguage(xbmc.ISO_639_1) == 'de':
        sText = sText.replace(',', '\x00').replace('.', ',').replace('\x00', '.')
    return sText


def _geld(oWert):
    """Dollar-Betrag von TMDB (Budget, Einnahmen): „160.000.000 $" auf Deutsch, „$160,000,000" sonst; ohne Wert leer
    (info.xml blendet die Zeile dann aus)."""
    if not oWert:
        return ''
    sText = _zahl(oWert)
    return sText + ' $' if xbmc.getLanguage(xbmc.ISO_639_1) == 'de' else '$' + sText


def WindowsBoxes(sTitle, sFileName, metaType, year='', tmdb_id=''):
    meta = {}  # scheitert get_meta, bleibt es leer -> Hinweis unten statt UnboundLocalError (bis 01.11.2026)
    try:
        # Mit ID (Kontextmenue eines Eintrags, der sie kennt) holt get_meta direkt die Details, sonst
        # Namenssuche plus Details. Bis zum 25.10.2026 stand hier ListItem.Property(TmdbId) — die
        # setzt niemand (Kodi speichert Property-Namen kleingeschrieben, unsere heisst tmdb_id),
        # das Fenster suchte deshalb immer per Name.
        meta = cTMDB().get_meta(metaType, sFileName, tmdb_id=tmdb_id, year=year, advanced='true')
        try:
            meta['plot'] = str(meta['plot'].encode('latin-1'), 'utf-8')
        except Exception:
            pass
    except Exception:
        logger.error("TMDB - error")
        pass

    if 'tmdb_id' not in meta:
        xbmc.executebuiltin("Notification(TMDB, %s, 1000, '')" % cConfig().getLocalizedString(30253))
        return
    # Leere Werte bleiben leer: info.xml blendet Zeilen ohne Wert aus und haengt in der Kopfzeile
    # nur an, was da ist (vorher "-" bzw. "0h0" bei einer Serie ohne Laufzeit).
    meta['releaseDate'] = _regionDate(meta.get('premiered'))   # vorher fest Tag/Monat/Jahr mit Schraegstrich
    meta['durationH'] = ''
    meta['durationM'] = ''
    if 'duration' in meta and meta['duration']:
        duration = meta['duration']
        durationH = duration // 60
        meta['durationH'] = durationH
        meta['durationM'] = '{:02d}'.format(int(duration - 60 * durationH))

    class XMLDialog(xbmcgui.WindowXMLDialog):
        def __init__(self, *args, **kwargs):
            xbmcgui.WindowXMLDialog.__init__(self)
            pass

        def onInit(self):
            # Fest Hellblau: die Einstellung "Farbe" ist seit dem 25.10.2026 ausgebaut (so entschieden), sie
            # wirkte nur hier — info.xml faerbt damit Fokusrahmen und Kaesten (Window.Property(color)).
            # Kodi kennt den Namen aus system/colors.xml; ohne Wert bliebe der Rahmen durchsichtig.
            self.setProperty('color', 'lightblue')
            self.poster = IMAGE_URL + POSTER_SIZE
            self.none_poster = 'https://eu.ui-avatars.com/api/?background=000&size=512&name=%s&color=FFF&font-size=0.33'
            self.setFocusId(9000)
            if 'credits' in meta and meta['credits']:
                cast = []
                crew = []
                try:
                    data = ast.literal_eval(str(meta['credits'].encode('latin-1'), 'utf-8'))
                except Exception:
                    data = ast.literal_eval(str(meta['credits']))

                listitems = []
                if 'cast' in data and data['cast']:
                    for i in data['cast']:
                        slabel = i['name']
                        slabel2 = i['character']
                        if i['profile_path']:
                            sicon = self.poster + str(i['profile_path'])
                        else:
                            sicon = self.none_poster % slabel
                        sid = i['id']
                        listitem_ = xbmcgui.ListItem(label=slabel, label2=slabel2)
                        listitem_.setProperty('id', str(sid))
                        listitem_.setArt({'icon': sicon})
                        listitems.append(listitem_)
                        cast.append(slabel)
                    self.getControl(50).addItems(listitems)

                listitems2 = []
                if 'crew' in data and data['crew']:
                    for i in data['crew']:
                        slabel = i['name']
                        slabel2 = i['job']
                        if i['profile_path']:
                            sicon = self.poster + str(i['profile_path'])
                        else:
                            sicon = self.none_poster % slabel
                        sid = i['id']
                        listitem_ = xbmcgui.ListItem(label=slabel, label2=slabel2)
                        listitem_.setProperty('id', str(sid))
                        listitem_.setArt({'icon': sicon})
                        listitems2.append(listitem_)
                        crew.append(slabel)
                    self.getControl(5200).addItems(listitems2)

            meta['title'] = sTitle
            # Wertung (eine Nachkommastelle), Stimmen, Budget und Einnahmen in der Zahlenform der Oberflaechensprache —
            # bis zum 03.11.2026 standen sie roh da (8.373, 40628, „160,000,000 $" auch auf Deutsch)
            meta['rating'] = _zahl(meta['rating'], 1) if meta.get('rating') else '-'
            meta['votes'] = _zahl(meta['votes']) if meta.get('votes') else '-'
            meta['budget'] = _geld(meta.get('budget'))
            meta['revenue'] = _geld(meta.get('revenue'))

            for prop in meta:
                try:
                    if isinstance(meta[prop], str):
                        self.setProperty(prop, meta[prop])
                    else:
                        self.setProperty(prop, str(meta[prop]))
                except Exception:
                    if isinstance(meta[prop], str):
                        self.setProperty(prop, meta[prop])
                    else:
                        self.setProperty(prop, str(meta[prop]))
            # Keine Trailer-Pruefung beim Oeffnen: bis zum 01.11.2026 lief hier hasTrailer im Hintergrund
            # (KinoCheck, TMDB, IMDb) und setzte isTrailer, das info.xml nie las — der Trailer-Knopf haengt
            # nur an !Player.HasMedia, ob es einen Trailer gibt, zeigt erst der Klick (wie im Kontextmenue)

        def credit(self, meta='', control=''):
            listitems = []
            if not meta:
                meta = {}
            for i in meta:
                if 'title' in i and i['title']:
                    sTitle = i['title']
                elif 'name' in i and i['name']:
                    sTitle = i['name']
                if i['poster_path']:
                    sThumbnail = self.poster + str(i['poster_path'])
                else:
                    sThumbnail = self.none_poster % sTitle
                listitem_ = xbmcgui.ListItem(label=sTitle)
                listitem_.setArt({'icon': sThumbnail})
                listitems.append(listitem_)
            self.getControl(control).addItems(listitems)

        def onClick(self, controlId):
            if controlId == 11:
                _tmdb_id = str(self.getProperty('tmdb_id'))
                _poster = self.getProperty('cover_url') or ''
                self.close()
                try:
                    from resources.lib.trailer import playTrailer
                    from resources.lib.config import cConfig
                    playTrailer(
                        tmdb_id=_tmdb_id,
                        mediatype=metaType,
                        title=sTitle,
                        year=year,
                        poster=_poster,
                    )
                except Exception:
                    import traceback
                    logger.error('trailer onClick error: %s' % traceback.format_exc())
                    xbmc.executebuiltin("Notification(%s, %s, 3000, '')" % (cConfig().getLocalizedString(30027), cConfig().getLocalizedString(30900)))
                return
            elif controlId == 30:
                self.close()
                return
            elif controlId == 50 or controlId == 5200:
                item = self.getControl(controlId).getSelectedItem()
                sid = item.getProperty('id')
                sUrl = 'person/' + str(sid)
                try:
                    # page=1 statt '': getUrl haengt den Wert immer an, und TMDB weist einen leeren page-Parameter
                    # mit 400 ab ("Pages start at 1") — die Person oeffnete deshalb meist nicht (30.10.2026,
                    # 2 von 3 Personen 400, mit page=1 alle 200).
                    meta = cTMDB().getUrl(sUrl, 1, "append_to_response=movie_credits,tv_credits")
                    # Filme und Serien der Person zusammen, jeder Titel einmal, die mit den meisten
                    # TMDB-Stimmen zuerst. Bis zum 30.10.2026 kamen nur die Filme an, die Serien wurden
                    # mitgeholt und nie gezeigt (Bryan Cranston ohne Breaking Bad). Gemessen an ihm:
                    # tv_credits fuehrt eine Serie je Rolle (Family Guy sechsmal), und nach TMDB-Popularitaet
                    # staenden Gastrollen (Family Guy, Simpsons, Baywatch) vor Breaking Bad — nach Stimmen
                    # kommen Breaking Bad, Der Soldat James Ryan, Drive.
                    meta_credits = []
                    seen = set()
                    for typ in ('movie_credits', 'tv_credits'):
                        for c in (meta.get(typ) or {}).get('cast') or []:
                            if (typ, c.get('id')) not in seen:
                                seen.add((typ, c.get('id')))
                                meta_credits.append(c)
                    meta_credits.sort(key=lambda c: c.get('vote_count') or 0, reverse=True)
                    self.credit(meta_credits, 5215)
                    personName = meta['name']
                    if not meta['deathday']:
                        today = date.today()
                        try:
                            birthday = datetime(*(time.strptime(meta['birthday'], '%Y-%m-%d')[0:6]))
                            age = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day))
                            age = cConfig().getLocalizedString(30901) % age
                        except Exception:
                            age = ''
                    else:
                        age = _regionDate(meta['deathday'])
                    self.setProperty('Person_name', personName)
                    self.setProperty('Person_birthday', _regionDate(meta['birthday']))
                    self.setProperty('Person_place_of_birth', meta['place_of_birth'])
                    self.setProperty('Person_deathday', str(age))
                    self.setProperty('Person_biography', meta['biography'])
                    self.setFocusId(9000)
                except Exception:
                    return
                self.setProperty('xstream_menu', 'Person')
            elif controlId == 9:
                sid = self.getProperty('tmdb_id')
                if metaType == 'movie':
                    sUrl_simil = 'movie/%s/similar' % str(sid)
                    sUrl_recom = 'movie/%s/recommendations' % str(sid)
                else:
                    sUrl_simil = 'tv/%s/similar' % str(sid)
                    sUrl_recom = 'tv/%s/recommendations' % str(sid)
                try:
                    meta = cTMDB().getUrl(sUrl_simil)
                    meta = meta['results']
                    self.credit(meta, 5205)
                except Exception:
                    pass
                try:
                    meta = cTMDB().getUrl(sUrl_recom)
                    meta = meta['results']
                    self.credit(meta, 5210)
                except Exception:
                    return
            elif controlId == 5215 or controlId == 5205 or controlId == 5210:
                item = self.getControl(controlId).getSelectedItem()
                self.close()
                # Weitere Quellen (searchAlter) wie Kontextmenue und TMDB-Browser — eine Suche mit
                # Ergebnis-Cache, Titelfilter und Hinweis bei null Treffern. Bis zum 30.10.2026 lief hier
                # eine eigene Sammelsuche (searchTMDB) ohne Cache: Kodi ruft das Verzeichnis nach einem
                # Stream und beim Zurueck erneut auf, und jedes Mal suchten alle Seiten noch einmal.
                xbmc.executebuiltin("Container.Update(%s?function=searchAlter&%s)" % ('plugin://plugin.video.xstream/', urlencode({'searchTitle': item.getLabel()})))
                return

        def onFocus(self, controlId):
            self.controlId = controlId

        def onAction(self, action):
            if action.getId() in (104, 105, 1, 2):
                return
            if action.getId() in (9, 10, 11, 30, 92, 216, 247, 257, 275, 61467, 61448):
                self.close()

# kasi
    path = 'special://home/addons/%s' % cConfig().getAddonInfo('id')   
    wd = XMLDialog('info.xml', path, 'default', '720p')
    wd.doModal()
    # Fenster bis zum Skriptende halten statt es hier freizugeben: Kodis neue
    # SWIG-Anbindung gibt sonst die Fensterklasse samt Modul nicht mehr frei —
    # Grund und Beleg bei cPlayer._players in resources/lib/player.py, fuer
    # Fenster-Unterklassen gilt dasselbe.
    _dialogs.append(wd)