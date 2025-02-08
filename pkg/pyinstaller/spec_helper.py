# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import subprocess
from pathlib import Path

ROOT = Path().resolve()

if not (ROOT/'gitfourchette/qt.py').is_file():
    raise ValueError("Please cd to the root of the GitFourchette repo")

EXCLUDES = [
    'psutil',
    'cached_property',  # optionally imported by pygit2 (this pulls in asyncio)
    'qtpy',
    'PySide6',
    'PySide2',
    'PyQt5',
    'PyQt5.QtTest',
    'PyQt5.QtMultimedia',
    'PyQt6',
    'PyQt6.QtPdf',
    'PyQt6.QtTest',
    'PyQt6.QtMultimedia',
    'PySide6.QtMultimedia',
    'PySide6.QtNetwork',
    'PySide6.QtOpenGL',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtQuick3D',
    'PySide6.QtQuickControls2',
    'PySide6.QtQuickWidgets',
    'PySide6.QtTest',
]


def getExcludeList(api):
    excludes = EXCLUDES[:]
    api = api.lower()
    if api == 'pyside6':
        excludes.remove('PySide6')
    elif api == 'pyqt6':
        excludes.remove('PyQt6')
    elif api == 'pyqt5':
        excludes.remove('PyQt5')
    else:
        raise NotImplementedError(f"Unsupported Qt binding for Pyinstaller bundle: {api}")
    return excludes


def writeBuildConstants(api):
    subprocess.run(['python3', ROOT/'update_resources.py', '--freeze', api])
