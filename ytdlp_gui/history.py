"""Persistent download history."""

import json
import os
import tempfile
import time


def history_path():
    """Return the per-user history file path (XDG state aware)."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "ytdlp-frontend", "history.json")


class History:
    """Small JSON-backed list of finished downloads, newest first."""

    LIMIT = 1000

    def __init__(self, path=None):
        self.path = path or history_path()
        self.entries = self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return []
        if isinstance(data, dict):
            data = data.get("entries", [])
        if not isinstance(data, list):
            return []
        entries = [entry for entry in data if isinstance(entry, dict)]
        return entries[: self.LIMIT]

    def add(self, url, name, status, destination="", size="", message=""):
        """Record a finished download and persist immediately."""
        entry = {
            "time": time.time(),
            "url": url,
            "name": name,
            "status": status,
            "destination": destination,
            "size": size,
            "message": message,
        }
        self.entries.insert(0, entry)
        del self.entries[self.LIMIT:]
        self.save()
        return entry

    def remove_entries(self, entries):
        """Remove entries by identity (works with filtered dialogs)."""
        ids = {id(entry) for entry in entries}
        if not ids:
            return
        self.entries = [entry for entry in self.entries if id(entry) not in ids]
        self.save()

    def clear(self):
        self.entries = []
        self.save()

    def save(self):
        directory = os.path.dirname(self.path) or "."
        tmp_path = None
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                prefix=".history-", suffix=".json", dir=directory
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {"entries": self.entries},
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
            os.replace(tmp_path, self.path)
            tmp_path = None
        except OSError:
            pass
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
