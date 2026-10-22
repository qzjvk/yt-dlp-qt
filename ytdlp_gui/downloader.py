"""yt-dlp subprocess workers.

Each download runs yt-dlp in its own QThread with ``--newline`` so progress
lines can be parsed one at a time. Pausing terminates the process (yt-dlp
keeps its ``.part`` file) and resuming simply restarts it, which continues
from the partial file.
"""

import re
import shutil
import subprocess
import sys

from PyQt6.QtCore import QThread, pyqtSignal

PROGRESS_RE = re.compile(
    r"\[download\]\s+(?P<pct>\d+(?:\.\d+)?)%\s+of\s+(?P<size>[\d.]+\s*[KMGTPE]?i?B?)\s+at\s+"
    r"(?P<speed>[\d.]+\s*[KMGTPE]?i?B?/s|Unknown B/s)\s+ETA\s+(?P<eta>[\d:]+|Unknown)"
)
DEST_RE = re.compile(r"\[download\]\s+Destination:\s*(?P<path>.+)$")


def find_ytdlp():
    """Return the command prefix for yt-dlp, or None if not found."""
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    try:
        import yt_dlp  # noqa: F401

        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        return None


def ytdlp_version():
    cmd = find_ytdlp()
    if not cmd:
        return "not found"
    try:
        out = subprocess.run(cmd + ["--version"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


class DownloadWorker(QThread):
    """Runs one yt-dlp download and reports progress via signals."""

    sig_log = pyqtSignal(str)
    sig_progress = pyqtSignal(float, str, str, str)  # pct, speed, eta, total size
    sig_state = pyqtSignal(str)
    sig_destination = pyqtSignal(str)
    sig_finished = pyqtSignal(str, str)  # result, message

    def __init__(self, url, args, parent=None):
        super().__init__(parent)
        self.url = url
        self.args = args
        self._proc = None
        self._stop = False
        self._pause = False
        self._last_state = ""

    def request_pause(self):
        self._pause = True
        self._kill()

    def request_cancel(self):
        self._stop = True
        self._kill()

    def _kill(self):
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except OSError:
                pass

    def _emit_state(self, state):
        if state != self._last_state:
            self._last_state = state
            self.sig_state.emit(state)

    def _parse(self, line):
        m = PROGRESS_RE.search(line)
        if m:
            self.sig_progress.emit(float(m["pct"]), m["speed"], m["eta"], m["size"])
            self._emit_state("downloading")
            return
        m = DEST_RE.search(line)
        if m:
            self.sig_destination.emit(m["path"].strip())
            return
        if line.startswith("[download]"):
            self._emit_state("downloading")
        elif line.startswith("[Merger]"):
            self._emit_state("merging")
        elif line.startswith("[ExtractAudio]"):
            self._emit_state("extracting audio")
        elif line.startswith("[ffmpeg]"):
            self._emit_state("post-processing")
        elif line.startswith("[info]"):
            self._emit_state("fetching info")

    def run(self):
        cmd_prefix = find_ytdlp()
        if not cmd_prefix:
            self.sig_finished.emit("failed", "yt-dlp executable not found")
            return
        cmd = cmd_prefix + self.args + [self.url]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as e:
            self.sig_finished.emit("failed", f"Failed to start yt-dlp: {e}")
            return
        try:
            for line in self._proc.stdout:
                line = line.rstrip("\n")
                self.sig_log.emit(line)
                self._parse(line)
                if self._stop or self._pause:
                    break
        finally:
            if self._proc.poll() is None:
                self._kill()
            try:
                rc = self._proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                rc = -1
        if self._pause:
            self.sig_finished.emit("paused", "Paused — partial file kept")
        elif self._stop:
            self.sig_finished.emit("cancelled", "Cancelled")
        elif rc == 0:
            self.sig_finished.emit("success", "Completed")
        else:
            self.sig_finished.emit("failed", f"yt-dlp exited with code {rc}")


class PreviewWorker(QThread):
    """Fetches metadata for a URL without downloading."""

    sig_finished = pyqtSignal(bool, str)

    def __init__(self, url, cookies="", proxy=""):
        super().__init__()
        self.url = url
        self.cookies = cookies
        self.proxy = proxy

    def run(self):
        cmd_prefix = find_ytdlp()
        if not cmd_prefix:
            self.sig_finished.emit(False, "yt-dlp executable not found")
            return
        fmt = (
            "%(title)s|%(uploader)s|%(duration_string)s|%(view_count)s|"
            "%(like_count)s|%(thumbnail)s|%(id)s"
        )
        cmd = cmd_prefix + ["--no-playlist", "--no-warnings", "--print", fmt, self.url]
        if self.cookies:
            cmd += ["--cookies", self.cookies]
        if self.proxy:
            cmd += ["--proxy", self.proxy]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        except Exception as e:
            self.sig_finished.emit(False, str(e))
            return
        if out.returncode != 0:
            lines = [l for l in out.stderr.strip().splitlines() if l.strip()]
            self.sig_finished.emit(False, lines[-1] if lines else "Failed to fetch info")
        else:
            lines = [l for l in out.stdout.strip().splitlines() if l.strip()]
            self.sig_finished.emit(True, lines[0] if lines else "")