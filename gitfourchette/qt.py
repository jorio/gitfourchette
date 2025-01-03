# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

# GitFourchette's preferred Qt binding is PyQt6, but you can use another
# binding via the QT_API environment variable. Values recognized by QT_API:
#       pyqt6
#       pyside6
#       pyqt5
# NOTE: PyQt5 support is deprecated and will be removed soon.
# PySide2 is not supported at all.
#
# If you're running unit tests, use the PYTEST_QT_API environment variable instead.
# If you're packaging the app, you may prefer to force a binding via appconsts.py.

import json as _json
import logging as _logging
import os as _os
import sys as _sys
from contextlib import suppress as _suppress

from gitfourchette.appconsts import *

_logger = _logging.getLogger(__name__)

_qtBindingOrder = ["pyqt6", "pyside6", "pyqt5"]

QT5 = False
QT6 = False
PYSIDE6 = False
PYQT5 = False
PYQT6 = False
MACOS = False
WINDOWS = False

if APP_FREEZE_QT:  # in frozen apps (PyInstaller, AppImage, Flatpak), target a fixed API
    _qtBindingOrder = [APP_FREEZE_QT]
    _qtBindingBootPref = _qtBindingOrder[0]
else:
    _qtBindingBootPref = _os.environ.get("QT_API", "").lower()

# If QT_API isn't set, see if the app's prefs file specifies a preferred Qt binding
if not _qtBindingBootPref:
    if _sys.platform == "darwin":
        _prefsPath = _os.path.expanduser("~/Library/Preferences")
    else:
        _prefsPath = _os.environ.get("XDG_CONFIG_HOME", _os.path.expanduser("~/.config"))
    _prefsPath = _os.path.join(_prefsPath, APP_SYSTEM_NAME, "prefs.json")
    with _suppress(OSError, ValueError):
        with open(_prefsPath, encoding="utf-8") as _f:
            _jsonPrefs = _json.load(_f)
        _qtBindingBootPref = _jsonPrefs.get("forceQtApi", "").lower()

if _qtBindingBootPref:
    if _qtBindingBootPref not in _qtBindingOrder:
        # Don't touch default binding order if user passed in an unsupported binding name.
        # Pass _qtBindingBootPref on to application code so it can complain.
        _logger.warning(f"Unrecognized Qt binding name: '{_qtBindingBootPref}'")
    else:
        # Move preferred binding to front of list
        _qtBindingOrder.remove(_qtBindingBootPref)
        _qtBindingOrder.insert(0, _qtBindingBootPref)

_logger.debug(f"Qt binding order is: {_qtBindingOrder}")

QT_BINDING = ""
QT_BINDING_VERSION = ""

for _tentative in _qtBindingOrder:
    assert _tentative.islower()

    try:
        if _tentative == "pyside6":
            from PySide6.QtCore import *
            from PySide6.QtWidgets import *
            from PySide6.QtGui import *
            from PySide6 import __version__ as QT_BINDING_VERSION
            QT_BINDING = "PySide6"
            QT6 = PYSIDE6 = True

        elif _tentative == "pyqt6":
            from PyQt6.QtCore import *
            from PyQt6.QtWidgets import *
            from PyQt6.QtGui import *
            QT_BINDING_VERSION = PYQT_VERSION_STR
            QT_BINDING = "PyQt6"
            QT6 = PYQT6 = True

        elif _tentative == "pyqt5":
            from PyQt5.QtCore import *
            from PyQt5.QtWidgets import *
            from PyQt5.QtGui import *
            QT_BINDING_VERSION = PYQT_VERSION_STR
            QT_BINDING = "PyQt5"
            QT5 = PYQT5 = True

        else:
            _logger.warning(f"Unsupported Qt binding {_tentative}")
            continue

        break

    except ImportError:
        continue

if not QT_BINDING:
    _sys.stderr.write("No Qt binding found. Please install either PyQt6, PySide6, or PyQt5.\n")
    _sys.exit(1)

# -----------------------------------------------------------------------------
# Set up platform constants

QT_BINDING_BOOTPREF = _qtBindingBootPref
KERNEL = QSysInfo.kernelType().lower()
MACOS = KERNEL == "darwin"
WINDOWS = KERNEL == "winnt"
FREEDESKTOP = not MACOS and not WINDOWS
FLATPAK = FREEDESKTOP and _os.path.exists("/.flatpak-info")

# -----------------------------------------------------------------------------
# Try to import optional modules

# Test mode stuff
HAS_QTEST = False
with _suppress(ImportError):
    if PYQT6:
        from PyQt6.QtTest import QAbstractItemModelTester, QTest, QSignalSpy
    elif PYQT5:
        from PyQt5.QtTest import QAbstractItemModelTester, QTest, QSignalSpy
    elif PYSIDE6:
        from PySide6.QtTest import QAbstractItemModelTester, QTest, QSignalSpy
    HAS_QTEST = True

# Try to import QtDBus on Linux
HAS_QTDBUS = False
if FREEDESKTOP:
    with _suppress(ImportError):
        if PYSIDE6:
            from PySide6.QtDBus import *
        elif PYQT6:
            from PyQt6.QtDBus import *
        elif PYQT5:
            from PyQt5.QtDBus import *
        else:
            raise ImportError("QtDBus")
        HAS_QTDBUS = True

# -----------------------------------------------------------------------------
# Exclude some known bad PySide6 versions

if PYSIDE6:
    _badPyside6Versions = [
        "6.4.0",  # PYSIDE-2104
        "6.4.0.1",  # PYSIDE-2104
        "6.5.1",  # PYSIDE-2346
    ]
    if any(v == QT_BINDING_VERSION for v in _badPyside6Versions):
        QApplication()
        QMessageBox.critical(None, "", f"PySide6 version {QT_BINDING_VERSION} isn't supported.\nPlease upgrade to the latest version of PySide6.")
        _sys.exit(1)

# -----------------------------------------------------------------------------
# Patch some holes and incompatibilities in Qt bindings

# Keep Qt from faking bold face with some variable fonts (see issue #10).
# This looks nicer out of the box in Ubuntu 24.10 and Fedora 41 (KDE spin).
# This is supposedly fixed in Qt 6.7 (https://bugreports.qt.io/browse/QTBUG-112136)
# but I've seen it occur with Qt 6.8 still.
_os.environ["QT_NO_SYNTHESIZED_BOLD"] = "1"

# Match PyQt signal/slot names with PySide6
if PYQT5 or PYQT6:
    Signal = pyqtSignal
    SignalInstance = pyqtBoundSignal
    Slot = pyqtSlot

if PYSIDE6:
    def _QCommandLineParser_addOptions(self, options):
        for o in options:
            self.addOption(o)

    QCommandLineParser.addOptions = _QCommandLineParser_addOptions

if QT5:
    # Disable "What's this?" in Qt 5 dialog box title bars (Qt 6 sets this off by default.)
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_DisableWindowContextHelpButton)

    # QMouseEvent.pos() is deprecated in Qt 6, so we don't use it.
    # Fill in QMouseEvent.position() for Qt 5.
    def _QMouseEvent_position(self):
        return QPointF(self.pos())

    QMouseEvent.position = _QMouseEvent_position

    # Some of these QFontDatabase functions became static in Qt 6, but they weren't in Qt 5.
    _QFontDatabase_families = QFontDatabase.families
    _QFontDatabase_isFixedPitch = QFontDatabase.isFixedPitch
    _QFontDatabase_isPrivateFamily = QFontDatabase.isPrivateFamily
    QFontDatabase.families = lambda *a, **k: _QFontDatabase_families(QFontDatabase(), *a, **k)
    QFontDatabase.isFixedPitch = lambda *a, **k: _QFontDatabase_isFixedPitch(QFontDatabase(), *a, **k)
    QFontDatabase.isPrivateFamily = lambda *a, **k: _QFontDatabase_isPrivateFamily(QFontDatabase(), *a, **k)


# -----------------------------------------------------------------------------
# Utility functions

def qAppName():
    """ User-facing application name. Shorthand for QApplication.applicationDisplayName(). """
    return QApplication.applicationDisplayName()


def qTempDir():
    """ Path to temporary directory for this session. """
    return QApplication.instance().tempDir.path()
