"""yt-dlp subprocess workers for the GTK application.

Each download runs in a plain Python thread, with ``--newline`` so progress
lines can be parsed one at a time.  Results are marshalled to the GTK main
loop with ``GLib.idle_add`` before GObject signals are emitted, which keeps
all UI updates on the main thread.

Pausing terminates the yt-dlp process group (yt-dlp keeps its ``.part`` file)
and resuming simply restarts it, which continues from the partial file.
"""

import os
import re
import shutil
import signal
import subprocess
import sys
import threading

from gi.repository import GLib, GObject

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
        out = subprocess.run(
            cmd + ["--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


class _ProcessWorker(GObject.GObject):
    """Base class: a GObject with a daemon thread and idle-loop signalling."""

    def __init__(self):
        super().__init__()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def wait(self, timeout=None):
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def is_alive(self):
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        raise NotImplementedError

    def _emit(self, signal_name, *args):
        """Emit a signal from the GTK main loop (thread-safe)."""
        GLib.idle_add(self.emit, signal_name, *args)


class DownloadWorker(_ProcessWorker):
    """Runs one yt-dlp download and reports progress via signals."""

    __gsignals__ = {
        "log": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "progress": (GObject.SignalFlags.RUN_FIRST, None, (float, str, str, str)),
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "destination": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "finished": (GObject.SignalFlags.RUN_FIRST, None, (str, str)),
    }

    def __init__(self, url, args):
        super().__init__()
        self.url = url
        self.args = args
        self._proc = None
        self._stop = False
        self._pause = False
        self._last_state = ""

    def request_pause(self):
        self._pause = True
        self._terminate()

    def request_cancel(self):
        self._stop = True
        self._terminate()

    def _signal_process_group(self, sig):
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            if os.name == "posix":
                # yt-dlp may have spawned ffmpeg; take the whole group down.
                os.killpg(os.getpgid(proc.pid), sig)
            elif sig == signal.SIGTERM:
                proc.terminate()
            else:
                proc.kill()
        except (OSError, ProcessLookupError):
            pass

    def _terminate(self):
        self._signal_process_group(signal.SIGTERM)

    def _kill(self):
        self._signal_process_group(signal.SIGKILL)

    def _emit_state(self, state):
        if state != self._last_state:
            self._last_state = state
            self._emit("state-changed", state)

    def _parse(self, line):
        match = PROGRESS_RE.search(line)
        if match:
            self._emit(
                "progress",
                float(match["pct"]),
                match["speed"],
                match["eta"],
                match["size"],
            )
            self._emit_state("downloading")
            return
        match = DEST_RE.search(line)
        if match:
            self._emit("destination", match["path"].strip())
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

    def _run(self):
        cmd_prefix = find_ytdlp()
        if not cmd_prefix:
            self._emit("finished", "failed", "yt-dlp executable not found")
            return
        cmd = cmd_prefix + self.args + [self.url]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                start_new_session=(os.name == "posix"),
            )
        except OSError as exc:
            self._emit("finished", "failed", f"Failed to start yt-dlp: {exc}")
            return

        rc = -1
        try:
            if self._stop or self._pause:
                self._terminate()
            for line in self._proc.stdout:
                line = line.rstrip("\n")
                self._emit("log", line)
                self._parse(line)
                if self._stop or self._pause:
                    break
        finally:
            if self._proc.poll() is None:
                self._terminate()
            try:
                rc = self._proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._kill()
                rc = self._proc.wait()

        if self._pause:
            self._emit("finished", "paused", "Paused — partial file kept")
        elif self._stop:
            self._emit("finished", "cancelled", "Cancelled")
        elif rc == 0:
            self._emit("finished", "success", "Completed")
        else:
            self._emit("finished", "failed", f"yt-dlp exited with code {rc}")


class PreviewWorker(_ProcessWorker):
    """Fetches metadata for a URL without downloading."""

    __gsignals__ = {
        "finished": (GObject.SignalFlags.RUN_FIRST, None, (bool, str)),
    }

    def __init__(self, url, cookies="", proxy=""):
        super().__init__()
        self.url = url
        self.cookies = cookies
        self.proxy = proxy

    def _run(self):
        cmd_prefix = find_ytdlp()
        if not cmd_prefix:
            self._emit("finished", False, "yt-dlp executable not found")
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
            out = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
            )
        except Exception as exc:
            self._emit("finished", False, str(exc))
            return
        if out.returncode != 0:
            lines = [l for l in out.stderr.strip().splitlines() if l.strip()]
            self._emit(
                "finished",
                False,
                lines[-1] if lines else "Failed to fetch info",
            )
        else:
            lines = [l for l in out.stdout.strip().splitlines() if l.strip()]
            self._emit("finished", True, lines[0] if lines else "")


class PlaylistWorker(_ProcessWorker):
    """Fetches the flat item list of a playlist as JSON."""

    __gsignals__ = {
        "finished": (GObject.SignalFlags.RUN_FIRST, None, (bool, str, str)),
    }

    def __init__(self, url, cookies="", proxy=""):
        super().__init__()
        self.url = url
        self.cookies = cookies
        self.proxy = proxy

    def _run(self):
        cmd_prefix = find_ytdlp()
        if not cmd_prefix:
            self._emit("finished", False, "yt-dlp executable not found", "")
            return
        cmd = cmd_prefix + [
            "--flat-playlist",
            "--dump-single-json",
            "--no-warnings",
            self.url,
        ]
        if self.cookies:
            cmd += ["--cookies", self.cookies]
        if self.proxy:
            cmd += ["--proxy", self.proxy]
        try:
            out = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except Exception as exc:
            self._emit("finished", False, str(exc), "")
            return
        if out.returncode != 0:
            lines = [l for l in out.stderr.strip().splitlines() if l.strip()]
            self._emit(
                "finished",
                False,
                lines[-1] if lines else "Failed to fetch playlist",
                "",
            )
        else:
            self._emit("finished", True, "", out.stdout)
