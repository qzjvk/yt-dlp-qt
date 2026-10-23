"""Main window for the yt-dlp GUI frontend (GTK 3)."""

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")

from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from .downloader import DownloadWorker, PreviewWorker, ytdlp_version  # noqa: E402
from .settings import Settings  # noqa: E402

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
ACTIVE_STATES = (
    "starting",
    "fetching info",
    "downloading",
    "merging",
    "extracting audio",
    "post-processing",
)

# ListStore columns.
COL_INDEX = 0
COL_NAME = 1
COL_STATUS = 2
COL_COLOR = 3
COL_PCT = 4
COL_PCT_TEXT = 5
COL_SPEED = 6
COL_ETA = 7
COL_SIZE = 8
COL_TASK = 9


@dataclass(eq=False)
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


def _install_css():
    provider = Gtk.CssProvider()
    provider.load_from_data(
        b".ytdlp-dim { opacity: 0.55; }\n"
        b".compact-button { padding-left: 4px; padding-right: 4px; }\n"
    )
    screen = Gdk.Screen.get_default()
    if screen is not None:
        Gtk.StyleContext.add_provider_for_screen(
            screen,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )


def _frame(title):
    frame = Gtk.Frame()
    label = Gtk.Label()
    label.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
    label.set_margin_start(2)
    frame.set_label_widget(label)
    return frame


def _set_combo_text(combo, text):
    model = combo.get_model()
    if model is None:
        return
    for index, row in enumerate(model):
        if row[0] == text:
            combo.set_active(index)
            return


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application=None):
        super().__init__(application=application, title="yt-dlp Frontend")
        self.settings = Settings()
        self.tasks: list[Task] = []
        self.active: set[Task] = set()
        self.preview_worker: PreviewWorker | None = None
        self._quitting = False
        self._log_mark = None

        self.set_default_size(1080, 720)
        self.set_size_request(900, 560)

        _install_css()
        self._setup_ui()
        self._load_settings()
        self._update_statusbar()

        self.connect("delete-event", self._on_delete_event)

    # ------------------------------------------------------------------ UI

    def _setup_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(12)
        root.set_margin_bottom(8)
        root.set_margin_start(12)
        root.set_margin_end(12)

        root.pack_start(self._build_url_group(), False, False, 0)

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        options_scroll = Gtk.ScrolledWindow()
        options_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        options_scroll.set_size_request(300, -1)
        options_scroll.set_shadow_type(Gtk.ShadowType.NONE)
        options_scroll.add(self._build_options_panel())
        body.pack_start(options_scroll, False, True, 0)
        body.pack_start(self._build_queue_panel(), True, True, 0)
        root.pack_start(body, True, True, 0)

        self.statusbar = Gtk.Statusbar()
        self.status_label = Gtk.Label(label="")
        self.status_label.set_xalign(0)
        self.status_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.counts_label = Gtk.Label(label="")
        self.ytdlp_label = Gtk.Label(label=f"yt-dlp {ytdlp_version()}")
        self.ytdlp_label.get_style_context().add_class("ytdlp-dim")
        area = self.statusbar.get_message_area()
        area.pack_start(self.status_label, True, True, 6)
        area.pack_end(self.ytdlp_label, False, False, 6)
        area.pack_end(self.counts_label, False, False, 6)
        root.pack_end(self.statusbar, False, False, 0)

        self.add(root)
        self.set_default(self.add_btn)

    def _build_url_group(self):
        frame = _frame("Video URL(s) — one per line")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(8)

        self.url_edit = Gtk.TextView()
        self.url_edit.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.url_edit.set_left_margin(6)
        self.url_edit.set_right_margin(6)
        self.url_edit.set_top_margin(4)
        self.url_edit.set_bottom_margin(4)
        self.url_edit.set_tooltip_text(
            "Works with any site yt-dlp supports (YouTube, X, Instagram, …).\n"
            "X and Instagram often need a cookies file — set it under Advanced."
        )
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(-1, 58)
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.add(self.url_edit)

        placeholder = Gtk.Label(label="Paste video URLs — YouTube, X, Instagram, …  (Ctrl+Return to add)")
        placeholder.set_halign(Gtk.Align.START)
        placeholder.set_valign(Gtk.Align.START)
        placeholder.set_margin_start(8)
        placeholder.set_margin_top(5)
        placeholder.set_can_focus(False)
        placeholder.get_style_context().add_class("ytdlp-dim")

        self.url_overlay = Gtk.Overlay()
        self.url_overlay.add(scroll)
        self.url_overlay.add_overlay(placeholder)
        self._url_placeholder = placeholder

        buffer = self.url_edit.get_buffer()
        buffer.connect("changed", self._update_url_placeholder)
        self.url_edit.connect("key-press-event", self._on_url_key_press)
        box.pack_start(self.url_overlay, False, False, 0)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.preview_btn = Gtk.Button(label="Preview")
        self.preview_btn.set_tooltip_text(
            "Fetch title, uploader, duration and more without downloading"
        )
        self.add_btn = Gtk.Button(label="Add to Queue")
        self.add_btn.set_tooltip_text("Add the URLs above to the download queue (Ctrl+Return)")
        self.add_btn.set_can_default(True)
        self.add_btn.get_style_context().add_class("suggested-action")
        self.playlist_cb = Gtk.CheckButton(label="Include playlists")
        row.pack_start(self.preview_btn, False, False, 0)
        row.pack_start(self.add_btn, False, False, 0)
        row.pack_start(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL), True, True, 0)
        row.pack_end(self.playlist_cb, False, False, 0)
        box.pack_start(row, False, False, 0)

        self.preview_btn.connect("clicked", self._preview)
        self.add_btn.connect("clicked", self.add_to_queue)
        frame.add(box)
        return frame

    def _build_options_panel(self):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        panel.set_size_request(300, -1)

        # --- Format
        fmt_group = _frame("Format")
        fmt_grid = Gtk.Grid(column_spacing=8, row_spacing=6)
        fmt_grid.set_border_width(8)
        self.format_combo = Gtk.ComboBoxText()
        for item in ("Best available", "Specific resolution", "Audio only"):
            self.format_combo.append_text(item)
        self.format_combo.set_active(0)
        self.format_combo.set_hexpand(True)

        self.quality_combo = Gtk.ComboBoxText()
        for resolution in RESOLUTIONS:
            self.quality_combo.append_text(f"{resolution}p")
        self.quality_combo.set_active(RESOLUTIONS.index("1080"))
        self.quality_combo.set_hexpand(True)

        self.audio_combo = Gtk.ComboBoxText()
        for audio_format in AUDIO_FORMATS:
            self.audio_combo.append_text(audio_format)
        self.audio_combo.set_active(0)
        self.audio_combo.set_hexpand(True)

        self.audio_quality_combo = Gtk.ComboBoxText()
        for index in range(11):
            if index == 0:
                label = "Best (0)"
            elif index == 10:
                label = "Worst (10)"
            else:
                label = str(index)
            self.audio_quality_combo.append_text(label)
        self.audio_quality_combo.set_active(0)
        self.audio_quality_combo.set_hexpand(True)

        format_rows = (
            ("Mode:", self.format_combo),
            ("Resolution:", self.quality_combo),
            ("Audio format:", self.audio_combo),
            ("Audio quality:", self.audio_quality_combo),
        )
        for row, (text, widget) in enumerate(format_rows):
            label = Gtk.Label(label=text, xalign=0)
            fmt_grid.attach(label, 0, row, 1, 1)
            fmt_grid.attach(widget, 1, row, 1, 1)
        self.format_combo.connect("changed", self._on_format_changed)
        fmt_group.add(fmt_grid)
        panel.pack_start(fmt_group, False, False, 0)

        # --- Output
        out_group = _frame("Output")
        out_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        out_box.set_border_width(8)
        dir_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.dir_edit = Gtk.Entry()
        self.dir_edit.set_hexpand(True)
        self.dir_edit.set_width_chars(8)
        self.dir_edit.set_placeholder_text(os.path.expanduser("~/Downloads"))
        self.dir_btn = Gtk.Button(label="Browse…")
        self.dir_btn.set_size_request(80, -1)
        dir_row.pack_start(self.dir_edit, True, True, 0)
        dir_row.pack_start(self.dir_btn, False, False, 0)
        out_box.pack_start(dir_row, False, False, 0)
        out_box.pack_start(Gtk.Label(label="Filename template:", xalign=0), False, False, 0)
        self.template_edit = Gtk.Entry()
        self.template_edit.set_width_chars(8)
        self.template_edit.set_placeholder_text("%(title)s [%(id)s].%(ext)s")
        self.template_edit.set_tooltip_text(
            "yt-dlp output template, e.g. %(title)s [%(id)s].%(ext)s"
        )
        out_box.pack_start(self.template_edit, False, False, 0)
        self.dir_btn.connect("clicked", self._browse_dir)
        out_group.add(out_box)
        panel.pack_start(out_group, False, False, 0)

        # --- Advanced
        adv_group = _frame("Advanced")
        adv_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        adv_box.set_border_width(8)
        self.adv_toggle = Gtk.ToggleButton(label="Show advanced options")
        self.adv_body = Gtk.Grid(column_spacing=8, row_spacing=6)
        self.adv_body.set_border_width(2)

        self.cookies_edit = Gtk.Entry()
        self.cookies_edit.set_width_chars(8)
        self.cookies_edit.set_placeholder_text("cookies.txt")
        self.cookies_edit.set_hexpand(True)
        self.cookies_btn = Gtk.Button(label="…")
        self.cookies_btn.set_size_request(32, -1)
        self.proxy_edit = Gtk.Entry()
        self.proxy_edit.set_width_chars(8)
        self.proxy_edit.set_placeholder_text("http://user:pass@host:port")
        self.rate_edit = Gtk.Entry()
        self.rate_edit.set_width_chars(8)
        self.rate_edit.set_placeholder_text("e.g. 1M")
        self.retries_spin = Gtk.SpinButton.new_with_range(0, 20, 1)
        self.retries_spin.set_value(3)
        self.frag_spin = Gtk.SpinButton.new_with_range(0, 32, 1)
        self.frag_spin.set_value(4)
        self.frag_spin.set_tooltip_text("Concurrent fragment downloads (DASH/HLS)")
        self.extra_edit = Gtk.Entry()
        self.extra_edit.set_width_chars(8)
        self.extra_edit.set_placeholder_text("--write-thumbnail --embed-thumbnail …")
        self.extra_edit.set_tooltip_text("Extra yt-dlp arguments, appended verbatim")

        cookies_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        cookies_row.pack_start(self.cookies_edit, True, True, 0)
        cookies_row.pack_start(self.cookies_btn, False, False, 0)

        adv_rows = (
            ("Cookies file:", cookies_row),
            ("Proxy:", self.proxy_edit),
            ("Rate limit:", self.rate_edit),
            ("Retries:", self.retries_spin),
            ("Fragments:", self.frag_spin),
            ("Extra args:", self.extra_edit),
        )
        for row, (text, widget) in enumerate(adv_rows):
            label = Gtk.Label(label=text, xalign=0)
            self.adv_body.attach(label, 0, row, 1, 1)
            self.adv_body.attach(widget, 1, row, 1, 1)

        self.adv_revealer = Gtk.Revealer()
        self.adv_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.adv_revealer.set_transition_duration(150)
        self.adv_revealer.add(self.adv_body)

        adv_box.pack_start(self.adv_toggle, False, False, 0)
        adv_box.pack_start(self.adv_revealer, False, False, 0)
        adv_group.add(adv_box)
        panel.pack_start(adv_group, False, False, 0)

        self.adv_toggle.connect("toggled", self._on_advanced_toggled)
        self.cookies_btn.connect("clicked", self._browse_cookies)

        panel.pack_start(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL), True, True, 0)
        return panel

    def _build_queue_panel(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.pause_btn = Gtk.Button(label="Pause")
        self.pause_btn.set_tooltip_text("Stop the selected downloads; partial files are kept")
        self.resume_btn = Gtk.Button(label="Resume")
        self.cancel_btn = Gtk.Button(label="Cancel")
        self.open_btn = Gtk.Button(label="Open Folder")
        self.remove_btn = Gtk.Button(label="Remove")
        self.clear_btn = Gtk.Button(label="Clear Completed")
        for button in (
            self.pause_btn,
            self.resume_btn,
            self.cancel_btn,
            self.open_btn,
            self.remove_btn,
            self.clear_btn,
        ):
            button.get_style_context().add_class("compact-button")
            bar.pack_start(button, False, False, 0)
        bar.pack_start(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL), True, True, 0)
        self.max_concurrent_spin = Gtk.SpinButton.new_with_range(1, 8, 1)
        self.max_concurrent_spin.set_value(1)
        self.max_concurrent_spin.set_tooltip_text("Maximum simultaneous downloads")
        bar.pack_end(self.max_concurrent_spin, False, False, 0)
        bar.pack_end(Gtk.Label(label="Concurrent:"), False, False, 0)
        box.pack_start(bar, False, False, 0)

        self.store = Gtk.ListStore(str, str, str, str, float, str, str, str, str, object)
        self.table = Gtk.TreeView(model=self.store)
        self.table.set_headers_visible(True)
        self.table.set_grid_lines(Gtk.TreeViewGridLines.HORIZONTAL)
        selection = self.table.get_selection()
        selection.set_mode(Gtk.SelectionMode.MULTIPLE)

        self._append_column("#", COL_INDEX, fixed=40)
        self._append_column(
            "Name",
            COL_NAME,
            expand=True,
            ellipsize=Pango.EllipsizeMode.END,
            min_width=100,
        )
        self._append_column("Status", COL_STATUS, fixed=120, color_column=COL_COLOR)
        self._append_progress_column()
        self._append_column("Speed", COL_SPEED, fixed=100)
        self._append_column("ETA", COL_ETA, fixed=90)
        self._append_column("Size", COL_SIZE, fixed=110)
        self.table.connect("row-activated", self._on_row_activated)

        table_scroll = Gtk.ScrolledWindow()
        table_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        table_scroll.set_shadow_type(Gtk.ShadowType.IN)
        table_scroll.add(self.table)
        box.pack_start(table_scroll, True, True, 0)

        log_group = _frame("Log")
        log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        log_box.set_border_width(8)
        log_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.log_edit = Gtk.TextView()
        self.log_edit.set_editable(False)
        self.log_edit.set_cursor_visible(False)
        self.log_edit.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.log_edit.set_left_margin(4)
        self.log_edit.set_right_margin(4)
        self.log_edit.override_font(Pango.FontDescription("Monospace"))
        self.log_buffer = self.log_edit.get_buffer()
        self._log_mark = self.log_buffer.create_mark(
            None, self.log_buffer.get_end_iter(), False
        )
        log_scroll = Gtk.ScrolledWindow()
        log_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_scroll.set_size_request(-1, 140)
        log_scroll.set_shadow_type(Gtk.ShadowType.IN)
        log_scroll.add(self.log_edit)
        clear_log_btn = Gtk.Button(label="Clear")
        clear_log_btn.set_size_request(70, -1)
        clear_log_btn.set_valign(Gtk.Align.START)
        log_row.pack_start(log_scroll, True, True, 0)
        log_row.pack_start(clear_log_btn, False, False, 0)
        log_box.pack_start(log_row, True, True, 0)
        log_group.add(log_box)
        box.pack_start(log_group, False, False, 0)

        self.pause_btn.connect("clicked", self._pause_selected)
        self.resume_btn.connect("clicked", self._resume_selected)
        self.cancel_btn.connect("clicked", self._cancel_selected)
        self.open_btn.connect("clicked", self._open_folder)
        self.remove_btn.connect("clicked", self._remove_selected)
        self.clear_btn.connect("clicked", self._clear_completed)
        clear_log_btn.connect("clicked", self._clear_log)
        self.max_concurrent_spin.connect("value-changed", lambda _spin: self._start_next())
        return box

    def _append_column(self, title, column, fixed=None, expand=False,
                       ellipsize=None, min_width=None, color_column=None):
        renderer = Gtk.CellRendererText()
        if ellipsize is not None:
            renderer.set_property("ellipsize", ellipsize)
        view_column = Gtk.TreeViewColumn(title, renderer)
        view_column.add_attribute(renderer, "text", column)
        if color_column is not None:
            view_column.add_attribute(renderer, "foreground", color_column)
        if fixed is not None:
            view_column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            view_column.set_fixed_width(fixed)
        if min_width is not None:
            view_column.set_min_width(min_width)
        view_column.set_expand(expand)
        self.table.append_column(view_column)

    def _append_progress_column(self):
        renderer = Gtk.CellRendererProgress()
        view_column = Gtk.TreeViewColumn("Progress", renderer)
        view_column.add_attribute(renderer, "value", COL_PCT)
        view_column.add_attribute(renderer, "text", COL_PCT_TEXT)
        view_column.set_expand(True)
        self.table.append_column(view_column)

    def _update_url_placeholder(self, buffer):
        self._url_placeholder.set_visible(buffer.get_char_count() == 0)

    def _on_url_key_press(self, _widget, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        if ctrl and event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.add_to_queue()
            return True
        return False

    def _on_advanced_toggled(self, button):
        active = button.get_active()
        self.adv_revealer.set_reveal_child(active)
        button.set_label(
            "Hide advanced options" if active else "Show advanced options"
        )

    # ------------------------------------------------------------- settings

    def _load_settings(self):
        settings = self.settings
        self.dir_edit.set_text(
            settings.get("output_dir", os.path.expanduser("~/Downloads"))
        )
        self.template_edit.set_text(
            settings.get("template", "%(title)s [%(id)s].%(ext)s")
        )
        format_mode = settings.getint("format_mode", 0)
        self.format_combo.set_active(format_mode if 0 <= format_mode <= 2 else 0)
        _set_combo_text(self.quality_combo, settings.get("quality", "1080p"))
        _set_combo_text(self.audio_combo, settings.get("audio_format", "mp3"))
        audio_quality = settings.getint("audio_quality", 0)
        self.audio_quality_combo.set_active(
            audio_quality if 0 <= audio_quality <= 10 else 0
        )
        self.playlist_cb.set_active(settings.getbool("playlist", False))
        self.cookies_edit.set_text(settings.get("cookies", ""))
        self.proxy_edit.set_text(settings.get("proxy", ""))
        self.rate_edit.set_text(settings.get("rate_limit", ""))
        self.retries_spin.set_value(settings.getint("retries", 3))
        self.frag_spin.set_value(settings.getint("fragments", 4))
        self.extra_edit.set_text(settings.get("extra_args", ""))
        self.max_concurrent_spin.set_value(settings.getint("max_concurrent", 1))
        self.adv_toggle.set_active(settings.getbool("advanced", False))
        self._on_format_changed(self.format_combo)

        width = settings.getint("window_width", 1080)
        height = settings.getint("window_height", 720)
        self.set_default_size(max(width, 900), max(height, 560))
        if settings.getbool("window_maximized", False):
            self.maximize()

    def _save_settings(self):
        settings = self.settings
        settings.set("output_dir", self.dir_edit.get_text().strip())
        settings.set("template", self.template_edit.get_text().strip())
        settings.set("format_mode", self.format_combo.get_active())
        settings.set("quality", self._combo_text(self.quality_combo))
        settings.set("audio_format", self._combo_text(self.audio_combo))
        settings.set("audio_quality", self.audio_quality_combo.get_active())
        settings.set("playlist", self.playlist_cb.get_active())
        settings.set("cookies", self.cookies_edit.get_text().strip())
        settings.set("proxy", self.proxy_edit.get_text().strip())
        settings.set("rate_limit", self.rate_edit.get_text().strip())
        settings.set("retries", self.retries_spin.get_value_as_int())
        settings.set("fragments", self.frag_spin.get_value_as_int())
        settings.set("extra_args", self.extra_edit.get_text().strip())
        settings.set("max_concurrent", self.max_concurrent_spin.get_value_as_int())
        settings.set("advanced", self.adv_toggle.get_active())
        width, height = self.get_size()
        settings.set("window_width", width)
        settings.set("window_height", height)
        settings.set("window_maximized", self.is_maximized())
        settings.save()

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _combo_text(combo):
        return combo.get_active_text() or ""

    def _on_format_changed(self, _combo):
        mode = self.format_combo.get_active()
        self.quality_combo.set_sensitive(mode == 1)
        self.audio_combo.set_sensitive(mode == 2)
        self.audio_quality_combo.set_sensitive(mode == 2)

    def _browse_dir(self):
        dialog = Gtk.FileChooserDialog(
            title="Choose output folder",
            transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            "Select",
            Gtk.ResponseType.ACCEPT,
        )
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        current = os.path.expanduser(self.dir_edit.get_text().strip())
        if current and os.path.isdir(current):
            dialog.set_current_folder(current)
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            self.dir_edit.set_text(dialog.get_filename() or "")
        dialog.destroy()

    def _browse_cookies(self):
        dialog = Gtk.FileChooserDialog(
            title="Choose cookies file",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN,
            Gtk.ResponseType.ACCEPT,
        )
        dialog.set_default_response(Gtk.ResponseType.ACCEPT)
        cookies_filter = Gtk.FileFilter()
        cookies_filter.set_name("Cookies (*.txt)")
        cookies_filter.add_pattern("*.txt")
        dialog.add_filter(cookies_filter)
        current = self.cookies_edit.get_text().strip()
        if current:
            folder = os.path.dirname(os.path.expanduser(current))
            if os.path.isdir(folder):
                dialog.set_current_folder(folder)
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            self.cookies_edit.set_text(dialog.get_filename() or "")
        dialog.destroy()

    def _audio_quality(self):
        audio_format = self._combo_text(self.audio_combo)
        quality = self.audio_quality_combo.get_active()
        if quality < 0:
            quality = 0
        if audio_format in ("wav", "flac"):
            return None
        if audio_format in ("m4a", "aac"):
            return {
                0: "192K",
                2: "160K",
                4: "128K",
                6: "96K",
                8: "64K",
                10: "48K",
            }.get(quality, "128K")
        return str(quality)

    def _build_args(self):
        args = ["--newline", "--no-colors"]
        if not self.playlist_cb.get_active():
            args.append("--no-playlist")
        mode = self.format_combo.get_active()
        if mode == 0:
            args += ["-f", "bv*+ba/b"]
        elif mode == 1:
            height = self._combo_text(self.quality_combo).rstrip("p")
            args += ["-f", f"bv*[height<=?{height}]+ba/b[height<=?{height}]"]
        else:
            args += [
                "-f",
                "ba/b",
                "--extract-audio",
                "--audio-format",
                self._combo_text(self.audio_combo),
            ]
            quality = self._audio_quality()
            if quality:
                args += ["--audio-quality", quality]
        outdir = self.dir_edit.get_text().strip() or os.path.expanduser("~")
        try:
            os.makedirs(outdir, exist_ok=True)
        except OSError as exc:
            self._warn("Output folder", f"Cannot create output folder:\n{exc}")
        template = (
            self.template_edit.get_text().strip()
            or "%(title)s [%(id)s].%(ext)s"
        )
        args += ["-o", os.path.join(outdir, template)]
        cookies = self.cookies_edit.get_text().strip()
        if cookies:
            args += ["--cookies", cookies]
        proxy = self.proxy_edit.get_text().strip()
        if proxy:
            args += ["--proxy", proxy]
        rate = self.rate_edit.get_text().strip()
        if rate:
            args += ["--limit-rate", rate]
        retries = self.retries_spin.get_value_as_int()
        if retries:
            args += ["--retries", str(retries)]
        fragments = self.frag_spin.get_value_as_int()
        if fragments:
            args += ["--concurrent-fragments", str(fragments)]
        extra = self.extra_edit.get_text().strip()
        if extra:
            args += shlex.split(extra)
        return args

    def _warn(self, title, text, secondary=None):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CLOSE,
            text=text,
        )
        dialog.set_title(title)
        if secondary:
            dialog.format_secondary_text(secondary)
        dialog.run()
        dialog.destroy()

    def _selected_tasks(self):
        model, paths = self.table.get_selection().get_selected_rows()
        tasks = []
        for path in paths:
            try:
                tasks.append(model[path][COL_TASK])
            except (KeyError, TypeError, IndexError):
                continue
        return tasks

    def _append_log(self, text):
        end = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end, text + "\n")
        line_count = self.log_buffer.get_line_count()
        if line_count > 5000:
            start = self.log_buffer.get_start_iter()
            cut = self.log_buffer.get_iter_at_line(line_count - 5000)
            self.log_buffer.delete(start, cut)
        self.log_buffer.move_mark(self._log_mark, self.log_buffer.get_end_iter())
        self.log_edit.scroll_to_mark(self._log_mark, 0.0, True, 0.0, 1.0)

    def _clear_log(self, _button=None):
        self.log_buffer.set_text("")

    def _update_statusbar(self):
        active = sum(1 for task in self.tasks if task.status in ACTIVE_STATES)
        completed = sum(1 for task in self.tasks if task.status == "completed")
        failed = sum(1 for task in self.tasks if task.status == "failed")
        self.counts_label.set_text(
            f"Active: {active}    Completed: {completed}    Failed: {failed}"
        )

    def _url_text(self):
        buffer = self.url_edit.get_buffer()
        return buffer.get_text(
            buffer.get_start_iter(), buffer.get_end_iter(), True
        )

    # --------------------------------------------------------------- queue

    def add_to_queue(self, _button=None):
        urls = [line.strip() for line in self._url_text().splitlines() if line.strip()]
        if not urls:
            self.status_label.set_text("Paste at least one URL first.")
            return
        for url in urls:
            task = Task(url=url, name=url, row=len(self.tasks))
            self.tasks.append(task)
            self.store.append(
                [
                    str(task.row + 1),
                    task.name,
                    task.status,
                    STATUS_COLORS.get(task.status, "#ffffff"),
                    0.0,
                    "",
                    "",
                    "",
                    "",
                    task,
                ]
            )
        self.url_edit.get_buffer().set_text("")
        self.status_label.set_text(f"Added {len(urls)} item(s) to the queue.")
        self._update_statusbar()
        self._start_next()

    def _update_row(self, task):
        if task.row < 0 or task.row >= self.store.iter_n_children(None):
            return
        row = self.store[task.row]
        row[COL_INDEX] = str(self.tasks.index(task) + 1)
        row[COL_NAME] = task.name
        row[COL_STATUS] = task.status
        row[COL_COLOR] = STATUS_COLORS.get(task.status, "#ffffff")
        row[COL_PCT] = max(0.0, min(100.0, task.pct))
        row[COL_PCT_TEXT] = f"{task.pct:.0f}%" if task.pct else ""
        row[COL_SPEED] = task.speed
        row[COL_ETA] = task.eta
        row[COL_SIZE] = task.size

    def _reindex(self):
        for index, task in enumerate(self.tasks):
            task.row = index
            if index < self.store.iter_n_children(None):
                self.store[index][COL_INDEX] = str(index + 1)

    def _remove_task(self, task):
        if 0 <= task.row < self.store.iter_n_children(None):
            path = Gtk.TreePath.new_from_indices([task.row])
            tree_iter = self.store.get_iter(path)
            self.store.remove(tree_iter)
        if task in self.tasks:
            self.tasks.remove(task)

    def _start_next(self):
        if self._quitting:
            return
        maximum = self.max_concurrent_spin.get_value_as_int()
        while len(self.active) < maximum:
            next_task = next(
                (task for task in self.tasks if task.status == "pending"), None
            )
            if next_task is None:
                break
            self._start_task(next_task)

    def _start_task(self, task):
        worker = DownloadWorker(task.url, self._build_args())
        worker.connect("log", lambda _worker, line, t=task: self._on_log(t, line))
        worker.connect(
            "progress",
            lambda _worker, pct, speed, eta, size, t=task: self._on_progress(
                t, pct, speed, eta, size
            ),
        )
        worker.connect(
            "state-changed", lambda _worker, state, t=task: self._on_state(t, state)
        )
        worker.connect(
            "destination",
            lambda _worker, path, t=task: self._on_destination(t, path),
        )
        worker.connect(
            "finished",
            lambda _worker, result, message, t=task: self._on_finished(
                t, result, message
            ),
        )
        task.worker = worker
        self.active.add(task)
        task.status = "starting"
        self._update_row(task)
        self._update_statusbar()
        worker.start()

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
        self.active.discard(task)
        worker = task.worker
        task.worker = None
        if worker is not None:
            # The thread has already emitted its final signal; make sure it is
            # fully gone before dropping our last reference.
            worker.wait(5.0)
        if result == "success":
            task.status = "completed"
            task.pct = 100.0
            task.speed = ""
            task.eta = ""
            if task.destination and not os.path.exists(task.destination):
                # Audio conversion changed the extension; find the final file.
                base, _ = os.path.splitext(task.destination)
                for extension in (
                    ".mp3",
                    ".m4a",
                    ".opus",
                    ".ogg",
                    ".wav",
                    ".flac",
                    ".aac",
                ):
                    candidate = base + extension
                    if os.path.exists(candidate):
                        task.destination = candidate
                        break
        elif result == "paused":
            task.status = "paused"
        elif result == "cancelled":
            task.status = "cancelled"
        else:
            task.status = "failed"
        self._update_row(task)
        self._update_statusbar()
        self.status_label.set_text(f"{task.name[:60]}: {message}")
        self._start_next()

    # ------------------------------------------------------------- actions

    def _pause_selected(self, _button=None):
        for task in self._selected_tasks():
            if task.status in ACTIVE_STATES and task.worker is not None:
                task.worker.request_pause()

    def _resume_selected(self, _button=None):
        resumed = 0
        for task in self._selected_tasks():
            if task.status == "paused":
                task.status = "pending"
                self._update_row(task)
                resumed += 1
        if resumed:
            self._start_next()

    def _cancel_selected(self, _button=None):
        for task in self._selected_tasks():
            if task.worker is not None:
                task.worker.request_cancel()
            elif task.status == "pending":
                task.status = "cancelled"
                self._update_row(task)
        self._update_statusbar()

    def _open_folder_for(self, task):
        if task.destination and os.path.exists(task.destination):
            open_path(os.path.dirname(task.destination))
        else:
            outdir = self.dir_edit.get_text().strip() or os.path.expanduser("~")
            open_path(outdir)

    def _open_folder(self, _button=None):
        tasks = self._selected_tasks()
        if tasks:
            self._open_folder_for(tasks[0])

    def _remove_selected(self, _button=None):
        to_remove = [task for task in self._selected_tasks() if task.worker is None]
        for task in sorted(to_remove, key=lambda item: item.row, reverse=True):
            self._remove_task(task)
        if to_remove:
            self._reindex()
            self._update_statusbar()

    def _clear_completed(self, _button=None):
        to_remove = [
            task
            for task in self.tasks
            if task.status in ("completed", "cancelled", "failed")
            and task.worker is None
        ]
        for task in sorted(to_remove, key=lambda item: item.row, reverse=True):
            self._remove_task(task)
        if to_remove:
            self._reindex()
            self._update_statusbar()

    def _on_row_activated(self, _tree, path, _column):
        try:
            task = self.store[path][COL_TASK]
        except (KeyError, TypeError, IndexError):
            return
        if task.status == "completed":
            self._open_folder_for(task)
        elif task.status == "paused":
            task.status = "pending"
            self._update_row(task)
            self._start_next()

    # ------------------------------------------------------------- preview

    def _preview(self, _button=None):
        lines = [
            line.strip()
            for line in self._url_text().splitlines()
            if line.strip()
        ]
        if not lines:
            self.status_label.set_text("Paste a URL to preview.")
            return
        self.preview_btn.set_sensitive(False)
        self.preview_worker = PreviewWorker(
            lines[0],
            cookies=self.cookies_edit.get_text().strip(),
            proxy=self.proxy_edit.get_text().strip(),
        )
        self.preview_worker.connect("finished", self._on_preview_done)
        self.preview_worker.start()

    def _on_preview_done(self, _worker, ok, text):
        self.preview_btn.set_sensitive(True)
        self.preview_worker = None
        if not ok:
            self._warn("Preview failed", text)
            return
        fields = text.split("|")
        while len(fields) < 7:
            fields.append("")
        title, uploader, duration, views, likes, thumbnail, video_id = fields[:7]

        dialog = Gtk.Dialog(
            title="Video info", transient_for=self, modal=True
        )
        dialog.set_default_size(480, -1)
        dialog.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)
        dialog.set_default_response(Gtk.ResponseType.CLOSE)
        content = dialog.get_content_area()
        content.set_border_width(12)
        content.set_spacing(10)

        title_label = Gtk.Label()
        title_label.set_markup(
            "<big><b>%s</b></big>"
            % GLib.markup_escape_text(title or "(untitled)")
        )
        title_label.set_xalign(0)
        title_label.set_line_wrap(True)
        title_label.set_selectable(True)
        content.pack_start(title_label, False, False, 0)

        details = Gtk.Grid(column_spacing=10, row_spacing=4)
        row = 0
        for key, value in (
            ("Uploader", uploader),
            ("Duration", duration),
            ("Views", views),
            ("Likes", likes),
            ("ID", video_id),
        ):
            if value and value.lower() != "none":
                key_label = Gtk.Label(label=f"{key}:", xalign=0)
                key_label.set_size_request(80, -1)
                key_label.get_style_context().add_class("ytdlp-dim")
                value_label = Gtk.Label(label=value, xalign=0)
                value_label.set_selectable(True)
                value_label.set_line_wrap(True)
                details.attach(key_label, 0, row, 1, 1)
                details.attach(value_label, 1, row, 1, 1)
                row += 1
        content.pack_start(details, False, False, 0)

        if thumbnail:
            link = Gtk.Label()
            link.set_markup(
                '<a href="%s">View thumbnail</a>'
                % GLib.markup_escape_text(thumbnail)
            )
            link.set_xalign(0)
            link.connect("activate-link", self._on_link_activated)
            content.pack_start(link, False, False, 0)

        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def _on_link_activated(self, _label, uri):
        try:
            Gtk.show_uri_on_window(self, uri, Gtk.get_current_event_time())
        except AttributeError:
            Gtk.show_uri(None, uri, Gtk.get_current_event_time())
        return True

    # -------------------------------------------------------------- closing

    def _on_delete_event(self, _window, _event):
        if self.active and not self._quitting:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                text="Downloads running",
            )
            dialog.format_secondary_text(
                f"{len(self.active)} download(s) still running.\n"
                "Quit anyway? Partial files are kept."
            )
            dialog.set_default_response(Gtk.ResponseType.NO)
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.YES:
                return True
        self._quitting = True
        for task in list(self.active):
            if task.worker is not None:
                task.worker.request_cancel()
        deadline = time.monotonic() + 3.0
        for task in list(self.active):
            if task.worker is not None:
                task.worker.wait(max(0.0, deadline - time.monotonic()))
        self._save_settings()
        return False
