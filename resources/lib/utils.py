# -*- coding: utf-8 -*-
# Python 3

import os
import zipfile
import xbmcgui, xbmcvfs
from xbmcvfs import translatePath
from resources.lib.config import cConfig
from resources.lib.logger import logger

# Nur noch der Einstieg fuer translatePath (service.py holt es von hier). Die
# Zip-Helfer und der help()-Platzhalter sind seit 14.10.2026 raus: ohne Aufrufer im
# Paket, der updateManager entpackt selbst.
