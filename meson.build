project(
  'ytdlp-frontend',
  version: '2.1.0',
  license: 'MIT',
  meson_version: '>= 1.1.0',
)

py = import('python').find_installation('python3', pure: true, required: false)
if not py.found()
  py = import('python').find_installation(pure: true)
endif

# --- Python package (GTK 3 / PyGObject) -------------------------------------
py.install_sources(
  'ytdlp_gui/__init__.py',
  'ytdlp_gui/__main__.py',
  'ytdlp_gui/main_window.py',
  'ytdlp_gui/downloader.py',
  'ytdlp_gui/history.py',
  'ytdlp_gui/settings.py',
  subdir: 'ytdlp_gui',
)

# --- Launcher script (bindir/ytdlp-frontend) --------------------------------
launcher = configure_file(
  input: 'launcher.py.in',
  output: 'ytdlp-frontend',
  configuration: {'PYTHON': py.full_path()},
)
install_data(launcher, install_dir: get_option('bindir'), install_mode: 'rwxr-xr-x')

# --- Desktop entry -----------------------------------------------------------
# The Exec path is computed from the configured prefix, so configure with the
# final install prefix (e.g. `meson setup builddir --prefix=$HOME/.local`).
desktop_file = configure_file(
  input: 'ytdlp-frontend.desktop.in',
  output: 'ytdlp-frontend.desktop',
  configuration: {
    'exec_path': get_option('prefix') / get_option('bindir') / 'ytdlp-frontend',
  },
)
install_data(desktop_file, install_dir: get_option('datadir') / 'applications')

# --- Icons (hicolor theme) ----------------------------------------------------
foreach size : ['16', '22', '24', '32', '48', '64', '128', '256']
  install_data(
    'assets/icons/' + size + '.png',
    install_dir: get_option('datadir') / 'icons' / 'hicolor' / (size + 'x' + size) / 'apps',
    rename: 'ytdlp-frontend.png',
  )
endforeach

# hicolor index.theme: required for icon-theme lookups to recognise the
# per-user hicolor directory (some themes, e.g. Deepsea, do not declare
# hicolor in their inheritance chain). Skip system prefixes, where the
# hicolor-icon-theme package already provides one.
if get_option('prefix') != '/usr'
  install_data(
    'assets/hicolor-index.theme',
    install_dir: get_option('datadir') / 'icons' / 'hicolor',
    rename: 'index.theme',
  )
endif

# Fallback icon for the window icon when the icon theme is not available
install_data('assets/icon.png', install_dir: get_option('datadir') / 'ytdlp-frontend')