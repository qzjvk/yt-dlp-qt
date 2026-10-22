"""Main window for the yt-dlp GUI frontend."""

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QKeySequence, QPalette, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .downloader import DownloadWorker, PreviewWorker, ytdlp_version
from .settings import Settings

RESOLUTIONS = ["2160", "1440", "1080", "720", "576", "480", "360", "240", "144"]
AUDIO_FORMATS = ["mp3", "m4a", "opus", "aac", "vorbis", "wav", "flac"]

# Semantic status colors, chosen mid-dark so they stay readable on both
# light and dark system themes.
STATUS_COLORS = {
    "pending": "#616161",
    "starting": "#1565c0",
    "fetching info": "#1565c0",
    "downloading": "#c62828",
    "merging": "#6a1b9a",
    "extracting audio": "#6a1b9a",
    "post-processing": "#6a1b9a",
    "paused": "#ef6c00",
    "completed": "#2e7d32",
    "failed": "#b71c1c",
    "cancelled": "#616161",
}
ACTIVE_STATES = ("starting", "fetching info", "downloading", "merging",
                 "extracting audio", "post-processing")


@dataclass
class Task:
    url: str
    name: str = ""
    status: str = "pending"
    pct: float = 0.0
    speed: str = ""
    eta: str = ""
    size: str = ""
    destination: str = ""
    worker: DownloadWorker | None = None
    row: int = -1


class ProgressDelegate(QStyledItemDelegate):
    """Draws a rounded progress bar inside a table cell."""

    def paint(self, painter, option, index):
        value = index.data(Qt.ItemDataRole.UserRole)
        try:
            value = max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            value = 0.0
        painter.save()
        rect = option.rect.adjusted(6, 9, -6, -9)
        pal = option.palette
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pal.color(QPalette.ColorRole.Mid))
        painter.drawRoundedRect(QRectF(rect), 7, 7)
        if value > 0:
            fill = QRectF(rect.left(), rect.top(), rect.width() * value / 100.0, rect.height())
            painter.setBrush(pal.color(QPalette.ColorRole.Highlight))
            painter.drawRoundedRect(fill, 7, 7)
        painter.restore()


def open_path(path):
    """Open a file or folder with the system handler."""
    try:
        if sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", path])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            os.startfile(path)  # type: ignore[attr-defined]
    except Exception:
        pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.tasks: list[Task] = []
        self.active: dict[int, Task] = {}  # row -> running task
        self.preview_worker: PreviewWorker | None = None
        self._quitting = False

        self.setWindowTitle("yt-dlp Frontend")
        self.resize(1080, 720)
        self._setup_ui()
        self._load_settings()
        self._update_statusbar()

    # ------------------------------------------------------------------ UI

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(10)

        root.addWidget(self._build_url_group())

        body = QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self._build_options_panel())
        body.addLayout(self._build_queue_panel(), 1)
        root.addLayout(body, 1)

        # Status bar
        self.status_label = QLabel("")
        self.counts_label = QLabel("")
        self.ytdlp_label = QLabel(f"yt-dlp {ytdlp_version()}")
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.counts_label)
        self.statusBar().addPermanentWidget(self.ytdlp_label)

    def _build_url_group(self):
        group = QGroupBox("Video URL(s) — one per line")
        lay = QVBoxLayout(group)

        self.url_edit = QPlainTextEdit()
        self.url_edit.setPlaceholderText(
            "Paste video URLs — YouTube, X, Instagram, …  (Ctrl+Return to add)"
        )
        self.url_edit.setToolTip(
            "Works with any site yt-dlp supports (YouTube, X, Instagram, …).\n"
            "X and Instagram often need a cookies file — set it under Advanced."
        )
        self.url_edit.setFixedHeight(58)
        lay.addWidget(self.url_edit)

        row = QHBoxLayout()
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.setToolTip("Fetch title, uploader, duration and more without downloading")
        self.add_btn = QPushButton("Add to Queue")
        self.add_btn.setObjectName("primary")
        self.add_btn.setDefault(True)
        self.playlist_cb = QCheckBox("Include playlists")
        row.addWidget(self.preview_btn)
        row.addWidget(self.add_btn)
        row.addStretch(1)
        row.addWidget(self.playlist_cb)
        lay.addLayout(row)

        self.preview_btn.clicked.connect(self._preview)
        self.add_btn.clicked.connect(self.add_to_queue)
        sc = QShortcut(QKeySequence("Ctrl+Return"), self.url_edit)
        sc.activated.connect(self.add_to_queue)
        return group

    def _build_options_panel(self):
        panel = QWidget()
        panel.setFixedWidth(300)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # --- Format
        fmt_group = QGroupBox("Format")
        fmt_lay = QGridLayout(fmt_group)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["Best available", "Specific resolution", "Audio only"])
        self.quality_combo = QComboBox()
        self.quality_combo.addItems([f"{r}p" for r in RESOLUTIONS])
        self.quality_combo.setCurrentText("1080p")
        self.audio_combo = QComboBox()
        self.audio_combo.addItems(AUDIO_FORMATS)
        self.audio_quality_combo = QComboBox()
        for i in range(11):
            label = "Best (0)" if i == 0 else ("Worst (10)" if i == 10 else str(i))
            self.audio_quality_combo.addItem(label, i)
        self.audio_quality_combo.setCurrentIndex(0)
        fmt_lay.addWidget(QLabel("Mode:"), 0, 0)
        fmt_lay.addWidget(self.format_combo, 0, 1)
        fmt_lay.addWidget(QLabel("Resolution:"), 1, 0)
        fmt_lay.addWidget(self.quality_combo, 1, 1)
        fmt_lay.addWidget(QLabel("Audio format:"), 2, 0)
        fmt_lay.addWidget(self.audio_combo, 2, 1)
        fmt_lay.addWidget(QLabel("Audio quality:"), 3, 0)
        fmt_lay.addWidget(self.audio_quality_combo, 3, 1)
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        lay.addWidget(fmt_group)

        # --- Output
        out_group = QGroupBox("Output")
        out_lay = QVBoxLayout(out_group)
        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText(os.path.expanduser("~/Downloads"))
        self.dir_btn = QPushButton("Browse…")
        self.dir_btn.setFixedWidth(80)
        dir_row.addWidget(self.dir_edit)
        dir_row.addWidget(self.dir_btn)
        out_lay.addLayout(dir_row)
        out_lay.addWidget(QLabel("Filename template:"))
        self.template_edit = QLineEdit()
        self.template_edit.setPlaceholderText("%(title)s [%(id)s].%(ext)s")
        self.template_edit.setToolTip(
            "yt-dlp output template, e.g. %(title)s [%(id)s].%(ext)s"
        )
        out_lay.addWidget(self.template_edit)
        self.dir_btn.clicked.connect(self._browse_dir)
        lay.addWidget(out_group)

        # --- Advanced
        adv_group = QGroupBox("Advanced")
        adv_lay = QVBoxLayout(adv_group)
        self.adv_toggle = QPushButton("Show advanced options")
        self.adv_toggle.setCheckable(True)
        self.adv_body = QWidget()
        adv_body_lay = QGridLayout(self.adv_body)

        self.cookies_edit = QLineEdit()
        self.cookies_edit.setPlaceholderText("cookies.txt")
        self.cookies_btn = QPushButton("…")
        self.cookies_btn.setFixedWidth(32)
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("http://user:pass@host:port")
        self.rate_edit = QLineEdit()
        self.rate_edit.setPlaceholderText("e.g. 1M")
        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 20)
        self.retries_spin.setValue(3)
        self.frag_spin = QSpinBox()
        self.frag_spin.setRange(0, 32)
        self.frag_spin.setValue(4)
        self.frag_spin.setToolTip("Concurrent fragment downloads (DASH/HLS)")
        self.extra_edit = QLineEdit()
        self.extra_edit.setPlaceholderText("--write-thumbnail --embed-thumbnail …")
        self.extra_edit.setToolTip("Extra yt-dlp arguments, appended verbatim")

        adv_body_lay.addWidget(QLabel("Cookies file:"), 0, 0)
        cookies_row = QHBoxLayout()
        cookies_row.addWidget(self.cookies_edit)
        cookies_row.addWidget(self.cookies_btn)
        adv_body_lay.addLayout(cookies_row, 0, 1)
        adv_body_lay.addWidget(QLabel("Proxy:"), 1, 0)
        adv_body_lay.addWidget(self.proxy_edit, 1, 1)
        adv_body_lay.addWidget(QLabel("Rate limit:"), 2, 0)
        adv_body_lay.addWidget(self.rate_edit, 2, 1)
        adv_body_lay.addWidget(QLabel("Retries:"), 3, 0)
        adv_body_lay.addWidget(self.retries_spin, 3, 1)
        adv_body_lay.addWidget(QLabel("Fragments:"), 4, 0)
        adv_body_lay.addWidget(self.frag_spin, 4, 1)
        adv_body_lay.addWidget(QLabel("Extra args:"), 5, 0)
        adv_body_lay.addWidget(self.extra_edit, 5, 1)

        adv_lay.addWidget(self.adv_toggle)
        adv_lay.addWidget(self.adv_body)
        self.adv_body.setVisible(False)
        self.adv_toggle.toggled.connect(self.adv_body.setVisible)
        self.cookies_btn.clicked.connect(self._browse_cookies)
        lay.addWidget(adv_group)

        lay.addStretch(1)
        return panel

    def _build_queue_panel(self):
        lay = QVBoxLayout()
        lay.setSpacing(8)

        # Toolbar
        bar = QHBoxLayout()
        self.pause_btn = QPushButton("Pause")
        self.resume_btn = QPushButton("Resume")
        self.cancel_btn = QPushButton("Cancel")
        self.open_btn = QPushButton("Open Folder")
        self.remove_btn = QPushButton("Remove")
        self.clear_btn = QPushButton("Clear Completed")
        bar.addWidget(self.pause_btn)
        bar.addWidget(self.resume_btn)
        bar.addWidget(self.cancel_btn)
        bar.addWidget(self.open_btn)
        bar.addWidget(self.remove_btn)
        bar.addStretch(1)
        bar.addWidget(QLabel("Concurrent:"))
        self.max_concurrent_spin = QSpinBox()
        self.max_concurrent_spin.setRange(1, 8)
        self.max_concurrent_spin.setValue(1)
        bar.addWidget(self.max_concurrent_spin)
        lay.addLayout(bar)

        # Table
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["#", "Name", "Status", "Progress", "Speed", "ETA", "Size"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(4, 100)
        self.table.setColumnWidth(5, 90)
        self.table.setColumnWidth(6, 110)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setItemDelegateForColumn(3, ProgressDelegate(self.table))
        self.table.itemDoubleClicked.connect(self._on_double_click)
        lay.addWidget(self.table, 1)

        # Log
        log_group = QGroupBox("Log")
        log_lay = QVBoxLayout(log_group)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(5000)
        self.log_edit.setFixedHeight(140)
        font = QFont("Monospace")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.log_edit.setFont(font)
        log_row = QHBoxLayout()
        log_row.addWidget(self.log_edit, 1)
        clear_log_btn = QPushButton("Clear")
        clear_log_btn.setFixedWidth(70)
        log_row.addWidget(clear_log_btn)
        log_lay.addLayout(log_row)
        clear_log_btn.clicked.connect(self.log_edit.clear)
        lay.addWidget(log_group)

        self.pause_btn.clicked.connect(self._pause_selected)
        self.resume_btn.clicked.connect(self._resume_selected)
        self.cancel_btn.clicked.connect(self._cancel_selected)
        self.open_btn.clicked.connect(self._open_folder)
        self.remove_btn.clicked.connect(self._remove_selected)
        self.clear_btn.clicked.connect(self._clear_completed)
        return lay

    # ------------------------------------------------------------- settings

    def _load_settings(self):
        s = self.settings
        self.dir_edit.setText(s.get("output_dir", os.path.expanduser("~/Downloads")))
        self.template_edit.setText(s.get("template", "%(title)s [%(id)s].%(ext)s"))
        self.format_combo.setCurrentIndex(s.getint("format_mode", 0))
        self.quality_combo.setCurrentText(s.get("quality", "1080p"))
        self.audio_combo.setCurrentText(s.get("audio_format", "mp3"))
        self.audio_quality_combo.setCurrentIndex(s.getint("audio_quality", 0))
        self.playlist_cb.setChecked(s.getbool("playlist", False))
        self.cookies_edit.setText(s.get("cookies", ""))
        self.proxy_edit.setText(s.get("proxy", ""))
        self.rate_edit.setText(s.get("rate_limit", ""))
        self.retries_spin.setValue(s.getint("retries", 3))
        self.frag_spin.setValue(s.getint("fragments", 4))
        self.extra_edit.setText(s.get("extra_args", ""))
        self.max_concurrent_spin.setValue(s.getint("max_concurrent", 1))
        geo = s.get("geometry")
        if geo is not None:
            self.restoreGeometry(geo)

    def _save_settings(self):
        s = self.settings
        s.set("output_dir", self.dir_edit.text().strip())
        s.set("template", self.template_edit.text().strip())
        s.set("format_mode", self.format_combo.currentIndex())
        s.set("quality", self.quality_combo.currentText())
        s.set("audio_format", self.audio_combo.currentText())
        s.set("audio_quality", self.audio_quality_combo.currentIndex())
        s.set("playlist", self.playlist_cb.isChecked())
        s.set("cookies", self.cookies_edit.text().strip())
        s.set("proxy", self.proxy_edit.text().strip())
        s.set("rate_limit", self.rate_edit.text().strip())
        s.set("retries", self.retries_spin.value())
        s.set("fragments", self.frag_spin.value())
        s.set("extra_args", self.extra_edit.text().strip())
        s.set("max_concurrent", self.max_concurrent_spin.value())
        s.set("geometry", self.saveGeometry())

    # -------------------------------------------------------------- helpers

    def _on_format_changed(self, index):
        self.quality_combo.setEnabled(index == 1)
        self.audio_combo.setEnabled(index == 2)
        self.audio_quality_combo.setEnabled(index == 2)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output folder", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def _browse_cookies(self):
        f, _ = QFileDialog.getOpenFileName(self, "Choose cookies file", "", "Cookies (*.txt)")
        if f:
            self.cookies_edit.setText(f)

    def _audio_quality(self):
        fmt = self.audio_combo.currentText()
        q = self.audio_quality_combo.currentData()
        if fmt in ("wav", "flac"):
            return None
        if fmt in ("m4a", "aac"):
            return {0: "192K", 2: "160K", 4: "128K", 6: "96K", 8: "64K", 10: "48K"}.get(q, "128K")
        return str(q)

    def _build_args(self):
        args = ["--newline", "--no-colors"]
        if not self.playlist_cb.isChecked():
            args.append("--no-playlist")
        mode = self.format_combo.currentIndex()
        if mode == 0:
            args += ["-f", "bv*+ba/b"]
        elif mode == 1:
            h = self.quality_combo.currentText().rstrip("p")
            args += ["-f", f"bv*[height<=?{h}]+ba/b[height<=?{h}]"]
        else:
            args += ["-f", "ba/b", "--extract-audio", "--audio-format", self.audio_combo.currentText()]
            q = self._audio_quality()
            if q:
                args += ["--audio-quality", q]
        outdir = self.dir_edit.text().strip() or os.path.expanduser("~")
        try:
            os.makedirs(outdir, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "Output folder", f"Cannot create output folder:\n{e}")
        template = self.template_edit.text().strip() or "%(title)s [%(id)s].%(ext)s"
        args += ["-o", os.path.join(outdir, template)]
        cookies = self.cookies_edit.text().strip()
        if cookies:
            args += ["--cookies", cookies]
        proxy = self.proxy_edit.text().strip()
        if proxy:
            args += ["--proxy", proxy]
        rate = self.rate_edit.text().strip()
        if rate:
            args += ["--limit-rate", rate]
        retries = self.retries_spin.value()
        if retries:
            args += ["--retries", str(retries)]
        frag = self.frag_spin.value()
        if frag:
            args += ["--concurrent-fragments", str(frag)]
        extra = self.extra_edit.text().strip()
        if extra:
            args += shlex.split(extra)
        return args

    def _selected_tasks(self):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        return [t for t in self.tasks if t.row in rows]

    def _append_log(self, text):
        self.log_edit.appendPlainText(text)

    def _update_statusbar(self):
        active = sum(1 for t in self.tasks if t.status in ACTIVE_STATES)
        completed = sum(1 for t in self.tasks if t.status == "completed")
        failed = sum(1 for t in self.tasks if t.status == "failed")
        self.counts_label.setText(f"Active: {active}    Completed: {completed}    Failed: {failed}")

    # --------------------------------------------------------------- queue

    def add_to_queue(self):
        urls = [l.strip() for l in self.url_edit.toPlainText().splitlines() if l.strip()]
        if not urls:
            self.status_label.setText("Paste at least one URL first.")
            return
        base_row = self.table.rowCount()
        for i, url in enumerate(urls):
            row = base_row + i
            self.table.insertRow(row)
            task = Task(url=url, name=url, row=row)
            self.tasks.append(task)
            self._fill_row(task)
        self.url_edit.clear()
        self.status_label.setText(f"Added {len(urls)} item(s) to the queue.")
        self._start_next()

    def _fill_row(self, task):
        row = task.row
        for col in range(7):
            item = QTableWidgetItem()
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, col, item)
        self._update_row(task)

    def _update_row(self, task):
        row = task.row
        if row < 0 or row >= self.table.rowCount():
            return
        self.table.item(row, 0).setText(str(self.tasks.index(task) + 1))
        self.table.item(row, 1).setText(task.name)
        status_item = self.table.item(row, 2)
        status_item.setText(task.status)
        status_item.setForeground(QColor(STATUS_COLORS.get(task.status, "#ffffff")))
        prog_item = self.table.item(row, 3)
        prog_item.setData(Qt.ItemDataRole.UserRole, task.pct)
        prog_item.setText(f"{task.pct:.0f}%" if task.pct else "")
        self.table.item(row, 4).setText(task.speed)
        self.table.item(row, 5).setText(task.eta)
        self.table.item(row, 6).setText(task.size)

    def _reindex(self):
        for i, t in enumerate(self.tasks):
            t.row = i
            if i < self.table.rowCount():
                self.table.item(i, 0).setText(str(i + 1))

    def _start_next(self):
        maxc = self.max_concurrent_spin.value()
        while len(self.active) < maxc:
            nxt = next((t for t in self.tasks if t.status == "pending"), None)
            if nxt is None:
                break
            self._start_task(nxt)

    def _start_task(self, task):
        args = self._build_args()
        task.worker = DownloadWorker(task.url, args)
        task.worker.sig_log.connect(lambda line, t=task: self._on_log(t, line))
        task.worker.sig_progress.connect(
            lambda pct, speed, eta, size, t=task: self._on_progress(t, pct, speed, eta, size)
        )
        task.worker.sig_state.connect(lambda state, t=task: self._on_state(t, state))
        task.worker.sig_destination.connect(lambda path, t=task: self._on_destination(t, path))
        task.worker.sig_finished.connect(lambda result, msg, t=task: self._on_finished(t, result, msg))
        task.worker.start()
        self.active[task.row] = task
        task.status = "starting"
        self._update_row(task)
        self._update_statusbar()

    # ----------------------------------------------------------- task events

    def _on_log(self, task, line):
        self._append_log(f"[{task.name[:48]}] {line}")

    def _on_progress(self, task, pct, speed, eta, size):
        task.pct = pct
        task.speed = speed
        task.eta = eta
        task.size = size
        self._update_row(task)

    def _on_state(self, task, state):
        task.status = state
        self._update_row(task)
        self._update_statusbar()

    def _on_destination(self, task, path):
        task.destination = path
        if task.name == task.url:
            task.name = os.path.splitext(os.path.basename(path))[0]
            self._update_row(task)

    def _on_finished(self, task, result, message):
        self.active.pop(task.row, None)
        worker = task.worker
        task.worker = None
        if worker is not None:
            # Let the thread fully finish before dropping the last reference,
            # otherwise Qt destroys a still-running QThread.
            worker.wait(5000)
        if result == "success":
            task.status = "completed"
            task.pct = 100.0
            task.speed = ""
            task.eta = ""
            if task.destination and not os.path.exists(task.destination):
                # Audio conversion changed the extension; find the final file.
                base, _ = os.path.splitext(task.destination)
                for ext in (".mp3", ".m4a", ".opus", ".ogg", ".wav", ".flac", ".aac"):
                    cand = base + ext
                    if os.path.exists(cand):
                        task.destination = cand
                        break
        elif result == "paused":
            task.status = "paused"
        elif result == "cancelled":
            task.status = "cancelled"
        else:
            task.status = "failed"
        self._update_row(task)
        self._update_statusbar()
        self.status_label.setText(f"{task.name[:60]}: {message}")
        self._start_next()

    # ------------------------------------------------------------- actions

    def _pause_selected(self):
        for task in self._selected_tasks():
            if task.status in ACTIVE_STATES and task.worker is not None:
                task.worker.request_pause()

    def _resume_selected(self):
        resumed = 0
        for task in self._selected_tasks():
            if task.status == "paused":
                task.status = "pending"
                self._update_row(task)
                resumed += 1
        if resumed:
            self._start_next()

    def _cancel_selected(self):
        for task in self._selected_tasks():
            if task.worker is not None:
                task.worker.request_cancel()
            elif task.status == "pending":
                task.status = "cancelled"
                self._update_row(task)
        self._update_statusbar()

    def _open_folder(self):
        tasks = self._selected_tasks()
        if not tasks:
            return
        task = tasks[0]
        if task.destination and os.path.exists(task.destination):
            open_path(os.path.dirname(task.destination))
        else:
            outdir = self.dir_edit.text().strip() or os.path.expanduser("~")
            open_path(outdir)

    def _remove_selected(self):
        to_remove = [t for t in self._selected_tasks() if t.worker is None]
        for task in sorted(to_remove, key=lambda t: t.row, reverse=True):
            self.tasks.remove(task)
            self.table.removeRow(task.row)
        if to_remove:
            self._reindex()
            self._update_statusbar()

    def _clear_completed(self):
        to_remove = [
            t for t in self.tasks
            if t.status in ("completed", "cancelled", "failed") and t.worker is None
        ]
        for task in sorted(to_remove, key=lambda t: t.row, reverse=True):
            self.tasks.remove(task)
            self.table.removeRow(task.row)
        if to_remove:
            self._reindex()
            self._update_statusbar()

    def _on_double_click(self, item):
        task = next((t for t in self.tasks if t.row == item.row()), None)
        if task is None:
            return
        if task.status == "completed":
            self._open_folder()
        elif task.status == "paused":
            self._resume_selected()

    # ------------------------------------------------------------- preview

    def _preview(self):
        lines = [l.strip() for l in self.url_edit.toPlainText().splitlines() if l.strip()]
        if not lines:
            self.status_label.setText("Paste a URL to preview.")
            return
        url = lines[0]
        self.preview_btn.setEnabled(False)
        self.preview_worker = PreviewWorker(
            url,
            cookies=self.cookies_edit.text().strip(),
            proxy=self.proxy_edit.text().strip(),
        )
        self.preview_worker.sig_finished.connect(self._on_preview_done)
        self.preview_worker.start()

    def _on_preview_done(self, ok, text):
        self.preview_btn.setEnabled(True)
        if not ok:
            QMessageBox.warning(self, "Preview failed", text)
            return
        fields = text.split("|")
        while len(fields) < 7:
            fields.append("")
        title, uploader, duration, views, likes, thumb, vid = fields
        dlg = QDialog(self)
        dlg.setWindowTitle("Video info")
        dlg.setMinimumWidth(440)
        lay = QVBoxLayout(dlg)
        t = QLabel(title or "(untitled)")
        f = QFont()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 2)
        t.setFont(f)
        t.setWordWrap(True)
        lay.addWidget(t)
        for k, v in (
            ("Uploader", uploader),
            ("Duration", duration),
            ("Views", views),
            ("Likes", likes),
            ("ID", vid),
        ):
            if v and v.lower() != "none":
                h = QHBoxLayout()
                lbl = QLabel(f"{k}:")
                lbl.setMinimumWidth(80)
                lbl.setForeground(
                    dlg.palette().color(QPalette.ColorRole.PlaceholderText)
                )
                h.addWidget(lbl)
                h.addWidget(QLabel(v))
                h.addStretch(1)
                lay.addLayout(h)
        if thumb:
            link = QLabel(f'<a href="{thumb}">View thumbnail</a>')
            link.setOpenExternalLinks(True)
            lay.addWidget(link)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)
        dlg.exec()

    # -------------------------------------------------------------- closing

    def closeEvent(self, event):
        # A modal dialog needs a running event loop. The only quit path in
        # this app is the user closing the window, so the loop is running
        # here — unless a programmatic quit set _quitting first.
        if self.active and not self._quitting:
            ret = QMessageBox.question(
                self,
                "Downloads running",
                f"{len(self.active)} download(s) still running.\nQuit anyway? Partial files are kept.",
            )
            if ret != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._quitting = True
        for task in list(self.active.values()):
            if task.worker is not None:
                task.worker.request_cancel()
                task.worker.wait(3000)
        self._save_settings()
        event.accept()