"""Persistent application settings backed by a small INI file."""

import configparser
import os
import tempfile


def config_path():
    """Return the per-user settings file path (XDG aware)."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "ytdlp-frontend", "settings.ini")


class Settings:
    """Thin, typed wrapper around a [settings] INI section."""

    SECTION = "settings"

    def __init__(self):
        self.path = config_path()
        self._cp = configparser.ConfigParser(interpolation=None)
        try:
            self._cp.read(self.path, encoding="utf-8")
        except (OSError, configparser.Error):
            # A malformed settings file must never stop the app from starting.
            self._cp = configparser.ConfigParser(interpolation=None)
        if not self._cp.has_section(self.SECTION):
            self._cp.add_section(self.SECTION)

    def get(self, key, default=None):
        return self._cp.get(self.SECTION, key, fallback=default)

    def set(self, key, value):
        self._cp.set(self.SECTION, key, str(value))

    def getint(self, key, default=0):
        try:
            return int(self._cp.get(self.SECTION, key))
        except (configparser.Error, TypeError, ValueError):
            return default

    def getbool(self, key, default=False):
        value = self._cp.get(self.SECTION, key, fallback=None)
        if value is None:
            return default
        return value.strip().lower() in ("1", "true", "yes", "on")

    def getfloat(self, key, default=0.0):
        try:
            return float(self._cp.get(self.SECTION, key))
        except (configparser.Error, TypeError, ValueError):
            return default

    def save(self):
        """Write the settings atomically so a crash cannot truncate them."""
        directory = os.path.dirname(self.path)
        tmp_path = None
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                prefix=".settings-", suffix=".ini", dir=directory
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                self._cp.write(handle)
            os.replace(tmp_path, self.path)
            tmp_path = None
        except OSError:
            # Settings are a convenience; never fail shutdown over them.
            pass
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
