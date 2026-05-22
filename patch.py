import time
import re
from parser_2gis.parser.main import MainParser

_orig = MainParser._get_available_pages

def _patched(self):
    for attempt in range(15):
        pages = _orig(self)
        if pages:
            return pages
        time.sleep(2)
    return {}

MainParser._get_available_pages = _patched
