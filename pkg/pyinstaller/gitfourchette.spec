# -*- mode: python ; coding: utf-8 -*-

import datetime
import platform
import re
import subprocess
from pathlib import Path

from gitfourchette.appconsts import *

QT_API = 'pyqt6'

MACOS = platform.system() == 'Darwin'
WINDOWS = platform.system() == 'Windows'
YEAR = datetime.datetime.now().year

TARGET_ARCH = 'arm64' if MACOS else None
ICON = f'{APP_SYSTEM_NAME}.ico' if WINDOWS else None

ROOT = Path().resolve()

if not (ROOT/'gitfourchette/qt.py').is_file():
    raise ValueError('Please cd to the root of the GitFourchette repo')

# Write build constants
subprocess.run(['python3', ROOT/'update_resources.py', '--freeze', QT_API])

EXCLUDES = [
    'psutil',
    'cached_property',  # optionally imported by pygit2 (this pulls in asyncio)
    'qtpy',
    'PIL',
    'PySide6',
    'PySide2',
    'PyQt5',
    'PyQt6',
    'PyQt6.QtPdf',
    'PyQt6.QtTest',
    'PyQt6.QtMultimedia',
    'PyQt6.QtNetwork',  # not effective?
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

if MACOS or WINDOWS:
    EXCLUDES += ['PyQt6.QtDBus']

if QT_API == 'pyside6':
    EXCLUDES.remove('PySide6')
elif QT_API == 'pyqt6':
    EXCLUDES.remove('PyQt6')
else:
    raise NotImplementedError(f'Unsupported Qt binding for PyInstaller bundle: {QT_API}')

initialDatas = [(ROOT / 'gitfourchette/assets', 'assets')]

# Contents/Resources/empty.lproj:
# If macOS sees this file, AND the system's preferred language matches the language of
# "Edit" and "Help" menu titles, we'll automagically get stuff like a search field
# in the Help menu, or dictation stuff in the Edit menu.
# If this file is absent, the magic menu entries are only added if the menu names
# are in English.
if MACOS:
    initialDatas.append(('empty.lproj', '.'))

a = Analysis(
    [ROOT / 'gitfourchette/__main__.py'],
    pathex=[],
    binaries=[],
    datas=initialDatas,
    hiddenimports=['_cffi_backend'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=True,  # True: keep pyc files (reduces false positives on Virustotal)
)

def filterPath(p: Path):
    # Remove stock Qt localizations for unsupported languages to save a few megs
    if p.suffix == '.qm':
        return re.match(r'^qt.*_(en|es|fr|it|zh_CN)$', p.stem)

    if p.suffix in ['.po', '.pot']:
        return False

    # Remove mac-specific assets on other platforms
    if not MACOS and p.as_posix().startswith('assets/mac/'):
        return False
    
    # Remove framework bloat
    bloatLibs = ['QtPdf', 'QtNetwork', 'libqpdf', 'opengl32sw']
    if MACOS:
        # Don't force-remove QtDBus on macos; app doesn't start without it
        if any(f'/{lib}.framework' in str(p)
                or p.name == f'{lib}.dylib'
                or p.name == lib
                for lib in bloatLibs):
            return False
    elif WINDOWS:
        if p.suffix == '.dll' and p.stem in bloatLibs:
            return False
    
    return True

a.datas = [item for item in a.datas if filterPath(Path(item[0]))]
a.binaries = [item for item in a.binaries if filterPath(Path(item[0]))]

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_DISPLAY_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=TARGET_ARCH,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=APP_DISPLAY_NAME,
)

if MACOS:
    app = BUNDLE(
        coll,
        name=f'{APP_DISPLAY_NAME}.app',
        icon=f'{APP_SYSTEM_NAME}.icns',
        bundle_identifier=APP_IDENTIFIER,
        version=APP_VERSION,
        info_plist={
            'NSReadableCopyright': f'\u00a9 {YEAR} Iliyas Jorio',
            'LSApplicationCategoryType': 'public.app-category.developer-tools',
            'CFBundleDocumentTypes': [
                {
                    'CFBundleTypeName': 'folder',
                    'CFBundleTypeRole': 'Editor',
                    'LSItemContentTypes': ['public.folder', 'public.item'],
                }
            ]
        }
    )
    print(dir(app))
