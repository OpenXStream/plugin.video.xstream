# -*- coding: utf-8 -*-
# Python 3

import ast
import time
import xbmcgui

# Eigener Namensraum im Hauptfenster (Window 10000). Alle Addons teilen sich
# dieses Fenster, deshalb duerfen wir beim Leeren NUR unsere eigenen Werte
# anfassen: ein pauschales clearProperties() loeschte auch fremde Properties
# (z.B. den Monitor des YouTube-Plugins, wodurch dessen Wiedergabe abbrach) und
# unsere eigenen (die lastSearchText-/sessionUA-Merker der Site-Files). Deshalb
# tragen alle Cache-Werte den Prefix und ihre Schluessel eine Index-Liste, und
# clear() raeumt nur diese ab. Der Prefix wird intern angehaengt — fuer die
# Aufrufer bleiben die Schluessel unveraendert (md5-Hash bzw. <addon>_main).
_PREFIX = 'xstream.cache.'
_INDEX = 'xstream.cache.__keys__'


class cCache(object):
    _win = None

    def __init__(self):
        # see https://kodi.wiki/view/Window_IDs
        self._win = xbmcgui.Window(10000)

    def __del__(self):
        del self._win

    def _keys(self):
        raw = self._win.getProperty(_INDEX)
        return set(raw.split('\n')) if raw else set()

    def _save_keys(self, keys):
        self._win.setProperty(_INDEX, '\n'.join(keys))

    def get(self, key, cache_time):
        prop = _PREFIX + key
        cachedata = self._win.getProperty(prop)
        if not cachedata:
            return None
        try:
            stamp, data = ast.literal_eval(cachedata)
        except (ValueError, SyntaxError, TypeError):
            # Beschaedigter Eintrag: wegraeumen statt bei jedem Aufruf zu knallen.
            self._win.clearProperty(prop)
            return None
        if cache_time < 0 or time.time() - stamp < cache_time:
            return data
        self._win.clearProperty(prop)
        return None

    def set(self, key, data):
        self._win.setProperty(_PREFIX + key, repr((time.time(), data)))
        keys = self._keys()
        if key not in keys:
            keys.add(key)
            self._save_keys(keys)

    def clear(self):
        for key in self._keys():
            self._win.clearProperty(_PREFIX + key)
        self._win.clearProperty(_INDEX)
