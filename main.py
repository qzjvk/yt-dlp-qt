#!/usr/bin/env python3
"""Development entry point (run from the source tree).

The installed launcher (see meson.build) calls ``ytdlp_gui.__main__``
directly; this wrapper just makes ``python3 main.py`` work in development.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ytdlp_gui.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())