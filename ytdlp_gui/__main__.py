"""Application entry point.

The app deliberately does not force a style or a stylesheet: Qt picks the
platform style and the palette from the system (on Linux the gtk3 platform
theme plugin follows the active GTK theme), so the app looks native in
whatever theme the desktop is using.
"""

import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPalette
from PyQt6.QtWidgets import QApplication

from . import __version__
from .main_window import MainWindow

APP_ID = "ytdlp-frontend"


def app_icon():
    """Return the application icon, preferring the system icon theme."""
    icon = QIcon.fromTheme(APP_ID)
    if not icon.isNull():
        return icon
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        # source tree (development)
        os.path.join(here, "..", "assets", "icon.png"),
    ]
    # installed data dir (meson install): XDG_DATA_HOME default first, then
    # each XDG_DATA_DIRS entry.
    data_dirs = [os.path.expanduser("~/.local/share")]
    data_dirs += os.environ.get(
        "XDG_DATA_DIRS", "/usr/local/share:/usr/share"
    ).split(":")
    for data_dir in data_dirs:
        if data_dir:
            candidates.append(os.path.join(data_dir, APP_ID, "icon.png"))
    for path in candidates:
        path = os.path.normpath(path)
        if os.path.exists(path):
            return QIcon(path)
    return QIcon()


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("yt-dlp Frontend")
    app.setOrganizationName("YtDlpFrontend")
    app.setApplicationVersion(__version__)
    # Lets the desktop environment match this app to its .desktop entry
    # (also sets WM_CLASS for taskbar grouping).
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())
    _force_black_text(app)

    win = MainWindow()
    win.show()
    return app.exec()


def _force_black_text(app):
    """Force all text to black so it stays readable in every state.

    The system theme's text color is too light to read in some states —
    disabled widgets and inactive windows in particular — so pin the text
    roles to black for every color group.
    """
    pal = app.palette()
    black = QColor("black")
    for group in (
        QPalette.ColorGroup.Normal,
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    ):
        pal.setColor(group, QPalette.ColorRole.Text, black)
        pal.setColor(group, QPalette.ColorRole.WindowText, black)
        pal.setColor(group, QPalette.ColorRole.ButtonText, black)
    app.setPalette(pal)


if __name__ == "__main__":
    sys.exit(main())