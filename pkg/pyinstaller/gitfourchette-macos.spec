# -*- mode: python ; coding: utf-8 -*-

from pkg.pyinstaller import spec_helper
from gitfourchette.appconsts import APP_VERSION

QT_API = "pyqt6"
spec_helper.writeBuildConstants(QT_API)

MAC_EXCLUDES = [
    'PyQt6.QtDBus',
]

a = Analysis(
    [spec_helper.ROOT / 'gitfourchette/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[(spec_helper.ROOT / 'gitfourchette/assets', 'assets')],
    hiddenimports=['_cffi_backend'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=spec_helper.getExcludeList(QT_API) + MAC_EXCLUDES,
    noarchive=False,  # True: keep pyc files
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GitFourchette',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64', #'universal2',
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='GitFourchette',
)

app = BUNDLE(
    coll,
    name='GitFourchette.app',
    icon='gitfourchette.icns',
    bundle_identifier='org.gitfourchette.gitfourchette',
    version=APP_VERSION,
    info_plist={
        "NSReadableCopyright": "© 2025 Iliyas Jorio",
        "LSApplicationCategoryType": "public.app-category.developer-tools",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "folder",
                "CFBundleTypeRole": "Editor",
                "LSItemContentTypes": ["public.folder", "public.item"],
            }
        ]
    }
)
