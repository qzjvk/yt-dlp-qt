# yt-dlp Frontend (Qt)

A native desktop GUI for [yt-dlp](https://github.com/yt-dlp/yt-dlp), built with
Python and **PyQt6 (Qt Widgets)** — a real native widget toolkit, no web view.

## Features

- **Multi-URL queue** — paste one URL per line, add them all at once
  (`Ctrl+Return` in the URL box works too)
- **Metadata preview** — fetch title, uploader, duration, views and likes
  before downloading
- **Format selection**
  - Best available (video + audio)
  - Specific resolution (2160p → 144p)
  - Audio only: mp3, m4a, opus, aac, vorbis, wav, flac — with quality control
- **Output options** — output folder picker, editable filename template
  (default `%(title)s [%(id)s].%(ext)s`)
- **Advanced options** — cookies file, proxy, rate limit, retries,
  concurrent fragments, and raw extra yt-dlp arguments
- **Download queue table** — per-row status, progress bar, speed, ETA and
  size; pause / resume / cancel per selection; clear completed; open folder
- **Pause & resume** — pausing terminates yt-dlp (the `.part` file is kept);
  resuming restarts it and continues from the partial file
- **Live log console** — full yt-dlp output, per-task prefixed
- **Concurrent downloads** — configurable (1–8)
- **Persistent settings** — all options and window geometry are remembered
  between sessions (QSettings)
- **Platform-native theme** — no forced style or stylesheet; the app follows
  the system theme (on Linux the Qt gtk3 platform theme plugin picks up the
  active GTK theme, including light/dark)

## Requirements

- Python 3.10+
- PyQt6 (`apt install python3-pyqt6` or `pip install PyQt6`)
- `yt-dlp` on `PATH` (the GUI drives it as a subprocess)
- `ffmpeg` on `PATH` (needed for merging video+audio and audio conversion)

## Run (development)

```bash
python3 main.py
```

## Build & install (Meson)

The project builds with [Meson](https://mesonbuild.com) and installs the
Python package, a `ytdlp-frontend` launcher, a `.desktop` entry and the icon
set (hicolor theme, all standard sizes).

```bash
# user install (no root needed)
meson setup builddir --prefix=$HOME/.local
ninja -C builddir
meson install -C builddir

# system install
sudo meson setup builddir --prefix=/usr
sudo ninja -C builddir
sudo meson install -C builddir
```

Configure with the final prefix: the `.desktop` file's `Exec=` line is
generated from it. After a user install, the app appears in the application
menu as **yt-dlp Frontend** and launches from `~/.local/bin/ytdlp-frontend`.

Installed locations (user prefix `~/.local`):

| File | Location |
| --- | --- |
| Python package | `~/.local/lib/python3/dist-packages/ytdlp_gui/` |
| Launcher | `~/.local/bin/ytdlp-frontend` |
| Desktop entry | `~/.local/share/applications/ytdlp-frontend.desktop` |
| Icons | `~/.local/share/icons/hicolor/<size>/apps/ytdlp-frontend.png` |

## Project layout

```
main.py               development entry point
meson.build           Meson build (package, launcher, desktop file, icons)
launcher.py.in        template for the installed launcher script
ytdlp-frontend.desktop.in   template for the .desktop entry
make_icon.py          one-shot icon generator (needs Pillow)
assets/icon.png       application icon (256x256)
assets/icons/         icon set for the hicolor theme (16…256)
assets/hicolor-index.theme  index.theme for per-user hicolor installs
ytdlp_gui/
    __init__.py
    __main__.py       application entry point (main())
    main_window.py    main window, queue management, UI
    downloader.py     DownloadWorker / PreviewWorker (QThread + subprocess)
    settings.py       QSettings wrapper
```

## How it works

Each queued URL runs `yt-dlp` in its own `QThread` with `--newline
--no-colors`, so progress lines (`[download] 45.2% of 10.23MiB at 2.34MiB/s
ETA 00:05`) can be parsed line by line and pushed to the UI via Qt signals.
State transitions (fetching info → downloading → merging / extracting audio /
post-processing) are detected from yt-dlp's output prefixes.

Pausing sends SIGTERM to the yt-dlp process; because yt-dlp keeps its partial
`.part` file and continues by default, resuming simply restarts the same
command and picks up where it left off.