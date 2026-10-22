"""Persistent application settings backed by QSettings."""

from PyQt6.QtCore import QSettings


class Settings:
    ORG = "YtDlpFrontend"
    APP = "yt-dlp-frontend"

    def __init__(self):
        self.s = QSettings(self.ORG, self.APP)

    def get(self, key, default=None):
        return self.s.value(key, default)

    def set(self, key, value):
        self.s.setValue(key, value)

    def getint(self, key, default=0):
        try:
            return int(self.s.value(key, default))
        except (TypeError, ValueError):
            return default

    def getbool(self, key, default=False):
        v = self.s.value(key, default)
        if isinstance(v, str):
            return v.lower() in ("1", "true", "yes")
        return bool(v)