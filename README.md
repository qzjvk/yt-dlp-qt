# yt-dlp Frontend (GTK 3)

A native desktop GUI for [yt-dlp](https://github.com/yt-dlp/yt-dlp), built with
Python and **GTK 3 via PyGObject** — real native widgets, no web view and no
Qt dependency.

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
- **Persistent settings** — all options, the advanced panel state and window
  size are remembered between sessions
- **Platform-native theme** — no forced style or stylesheet; the app follows
  the active GTK theme, including light/dark

## Requirements

- Python 3.10+
- PyGObject and GTK 3 (3.22 or newer)
- `yt-dlp` on `PATH` (the GUI drives it as a subprocess)
- `ffmpeg` on `PATH` (needed for merging video+audio and audio conversion)

Install the Python/GTK bindings with your distribution:

```bash
# Debian / Ubuntu
sudo apt install python3-gi gir1.2-gtk-3.0

# Fedora
sudo dnf install python3-gobject gtk3

# Arch
sudo pacman -S python-gobject gtk3
```

`pip install PyGObject` also works, but it needs the GTK development headers
and a C compiler.

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
| Python package | `~/.local/lib/python3/dist-packages/ytdlp_gui/` (or `python3.x/site-packages`) |
| Launcher | `~/.local/bin/ytdlp-frontend` |
| Desktop entry | `~/.local/share/applications/ytdlp-frontend.desktop` |
| Icons | `~/.local/share/icons/hicolor/<size>/apps/ytdlp-frontend.png` |

Settings are stored in `~/.config/ytdlp-frontend/settings.ini`
(or `$XDG_CONFIG_HOME/ytdlp-frontend/settings.ini`).

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
    __main__.py       Gtk.Application entry point (main())
    main_window.py    main window, queue management, UI
    downloader.py     DownloadWorker / PreviewWorker (threads + subprocess)
    settings.py       INI settings wrapper
```

## How it works

Each queued URL runs `yt-dlp` in its own Python thread with `--newline
--no-colors`, so progress lines (`[download] 45.2% of 10.23MiB at 2.34MiB/s
ETA 00:05`) can be parsed line by line. Worker callbacks are marshalled to the
GTK main loop with `GLib.idle_add`, so every widget update happens on the UI
thread. State transitions (fetching info → downloading → merging / extracting
audio / post-processing) are detected from yt-dlp's output prefixes.

Pausing sends `SIGTERM` to the yt-dlp process group; because yt-dlp keeps its
partial `.part` file and continues by default, resuming simply restarts the
same command and picks up where it left off.
