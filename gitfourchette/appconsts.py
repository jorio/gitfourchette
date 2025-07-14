# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import sys as _sys
import os as _os


def _envBool(key: str) -> bool:
    return _os.environ.get(key, "") not in ["", "0"]


APP_VERSION = "1.4.0"
APP_SYSTEM_NAME = "gitfourchette"
APP_DISPLAY_NAME = "GitFourchette"
APP_URL_SCHEME = APP_SYSTEM_NAME
APP_IDENTIFIER = "org.gitfourchette.gitfourchette"

# -----------------------------------------------------------------------------
# BEGIN_FREEZE_CONSTS
# These constants can be overwritten by `update_resources.py --freeze`
# Do not commit changes in this file unless you know what you are doing!
APP_FREEZE_COMMIT = ""
APP_FREEZE_DATE = ""
APP_FREEZE_QT = ""
# END_FREEZE_CONSTS
# -----------------------------------------------------------------------------

APP_TESTMODE = _envBool("APP_TESTMODE") or "pytest" in _sys.modules
"""
Unit testing mode (don't touch real user prefs, etc.).
Can be forced with environment variable APP_TESTMODE.
"""

APP_DEBUG = APP_TESTMODE or _envBool("APP_DEBUG")
"""
Enable expensive assertions and debugging features.
Can be forced with environment variable APP_DEBUG.
Implied by APP_TESTMODE.
"""

APP_NOTHREADS = APP_TESTMODE or _envBool("APP_NOTHREADS")
"""
Disable multithreading (run all tasks on UI thread).
Can be forced with environment variable APP_NOTHREADS.
Implied by APP_TESTMODE.
"""

APP_VERBOSEDEL = _envBool("APP_VERBOSEDEL")
"""
Verbose QObject Python destructors (__del__).
"""

if APP_TESTMODE:
    APP_SYSTEM_NAME += "_testmode"
    APP_DISPLAY_NAME += "TestMode"
