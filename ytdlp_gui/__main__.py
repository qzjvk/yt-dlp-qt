"""Application entry point for the GTK 3 frontend."""

import os
import sys

from . import __version__

APP_ID = "ytdlp-frontend"
APPLICATION_ID = "io.github.ytdlp_frontend"


def _icon_file():
    """Return a fallback icon path, preferring the installed data dir."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(here, "..", "assets", "icon.png")]
    data_dirs = [os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")]
    data_dirs += os.environ.get(
        "XDG_DATA_DIRS", "/usr/local/share:/usr/share"
    ).split(":")
    for data_dir in data_dirs:
        if data_dir:
            candidates.append(os.path.join(data_dir, APP_ID, "icon.png"))
    for path in candidates:
        path = os.path.normpath(path)
        if os.path.exists(path):
            return path
    return None


def _load_gtk():
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: F401
    except (ImportError, ValueError) as exc:
        sys.stderr.write(
            "GTK 3 is required. Install PyGObject and the GTK 3 bindings, e.g.\n"
            "  Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-3.0\n"
            f"({exc})\n"
        )
        return None
    return Gdk, Gio, GLib, Gtk


def _set_default_icon(Gtk, GLib):
    theme = Gtk.IconTheme.get_default()
    if theme is not None and theme.has_icon(APP_ID):
        Gtk.Window.set_default_icon_name(APP_ID)
        return
    icon_path = _icon_file()
    if icon_path is not None:
        try:
            Gtk.Window.set_default_icon_from_file(icon_path)
            return
        except GLib.Error:
            pass
    Gtk.Window.set_default_icon_name(APP_ID)


def _on_activate(application):
    # Imported lazily so a missing GTK installation produces the friendly
    # error above instead of a traceback at import time.
    from gi.repository import GLib, Gtk

    from .main_window import MainWindow

    windows = application.get_windows()
    if windows:
        windows[0].present()
        return
    _set_default_icon(Gtk, GLib)
    window = MainWindow(application=application)
    window.show_all()


def main(argv=None):
    loaded = _load_gtk()
    if loaded is None:
        return 1
    Gdk, Gio, GLib, Gtk = loaded

    GLib.set_prgname(APP_ID)
    GLib.set_application_name("yt-dlp Frontend")
    # Sets WM_CLASS, so the desktop can match the window to its .desktop file.
    Gdk.set_program_class(APP_ID)

    application = Gtk.Application(
        application_id=APPLICATION_ID,
        flags=Gio.ApplicationFlags.FLAGS_NONE,
    )
    application.set_version(__version__)
    application.connect("activate", _on_activate)
    return application.run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    sys.exit(main())
