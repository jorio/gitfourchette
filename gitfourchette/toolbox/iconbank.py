# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from pathlib import Path

from gitfourchette.qt import *
from gitfourchette.toolbox.recolorsvgiconengine import RecolorSvgIconEngine

STOCK_ICON_URL_SCHEME = "gitfourchette-stockicon"  # lowercase!

_stockIconCache: dict[int, QIcon] = {}
_stockIconPixmapCache: dict[int, QPixmap] = {}

# Override some icon IDs depending on desktop environment
_overrideIconIds: dict[str, str] = {}

_autoDarkVariants = {
    "achtung",
    "git-lfs",
    "git-lfs-add",
    "git-lfs-remove",
    "status_a",
    "status_c",  # just in case we ever add this one
    "status_d",
    "status_m",
    "status_r",
    "status_t",
    "status_x",
    # status_u intentionally omitted. Its white outline should stand out against a white background.
}


def _iconOverrideTable() -> dict[str, str]:
    overrides = {
        "status_?": "status_a",  # Use Added icon for Untracked
    }

    assert QApplication.instance(), "need app instance for QIcon.themeName()"
    iconTheme = QIcon.themeName().casefold()

    # Use native warning icon in all contexts on Mac & Windows
    if MACOS or WINDOWS:  # pragma: no cover
        overrides["achtung"] = "SP_MessageBoxWarning"

    # Override Ubuntu default theme's scary red icon for warnings
    if FREEDESKTOP and iconTheme.startswith("yaru"):  # pragma: no cover
        overrides["SP_MessageBoxWarning"] = "warning-small-symbolic"

    return overrides


def stockIcon(
        iconId: str,
        colorTable: str = "",
        flags: RecolorSvgIconEngine.Flags = RecolorSvgIconEngine.Flags.NoFlags
) -> QIcon:
    # Special cases
    if not _overrideIconIds:
        _overrideIconIds.update(_iconOverrideTable())
        assert _overrideIconIds, "expecting overrides to contain at least one entry"
    iconId = _overrideIconIds.get(iconId, iconId)

    if RecolorSvgIconEngine.IconColors.preferDarkVariants and iconId in _autoDarkVariants:
        # Merge dark variant remapping into caller's color table (caller's entries take precedence)
        colorTable = f"white=#000 black=#fff {colorTable}".rstrip()

    # Compute cache key
    key = hash((iconId, colorTable, flags))

    # Attempt to get cached icon
    try:
        return _stockIconCache[key]
    except KeyError:
        pass

    # Find path to icon file (if any)
    iconPath = ""
    for ext in ".svg", ".png":
        file = QFile(f"assets:icons/{iconId}{ext}")
        if file.exists():
            iconPath = file.fileName()
            break

    # Create QIcon
    if iconPath.endswith(".svg"):
        # Dynamic SVG icon
        engine = RecolorSvgIconEngine(iconPath, colorTable, flags)
        icon = QIcon(engine)
    elif iconPath:
        # Bitmap file
        icon = QIcon(iconPath)
    elif iconId.startswith("SP_"):
        # Qt standard pixmaps (with "SP_" prefix)
        entry = getattr(QStyle.StandardPixmap, iconId)
        icon = QApplication.style().standardIcon(entry)
    else:
        # Fall back to theme icon
        icon = QIcon.fromTheme(iconId)

    # Cache icon
    _stockIconCache[key] = icon
    return icon


def stockIconResourceProvider(url: QUrl) -> QPixmap | None:
    if url.scheme() != STOCK_ICON_URL_SCHEME:
        return None

    # Figure out dpr
    app = QApplication.instance()
    try:
        # Use mainWindow's dpr
        dpr = app.mainWindow.devicePixelRatio()  # type: ignore[attr-defined]
    except AttributeError:
        # Too early, no window yet; fall back to highest dpr on the system.
        # Note: on Wayland, this may be higher than the actual dpr if fractional
        # scaling is enabled (e.g. this may return 2.0 if your system is set up
        # for 1.25 frac scaling)
        dpr = app.devicePixelRatio()  # type: ignore[attr-defined]  # incomplete stubs

    iconId = url.path()
    size = int(url.fragment())
    key = hash((iconId, dpr, size))

    try:
        pixmap = _stockIconPixmapCache[key]
    except KeyError:
        icon = stockIcon(iconId)
        if QT5:  # Qt 5 compat: no devicePixelRatio argument in ctor
            pixmap = icon.pixmap(QSize(size, size))
        else:
            pixmap = icon.pixmap(QSize(size, size), dpr)
        _stockIconPixmapCache[key] = pixmap

        # print(f"{len(_stockIconPixmapCache)} pixmaps cached, "
        #       f"{sum(p.toImage().sizeInBytes() for p in _stockIconPixmapCache.values())//1024} KB total")

    return pixmap


def stockIconImgTag(iconId: str, size: int = 16) -> str:
    """
    Qt's HTML subset renders <img> tags at devicePixelRatio=1, and it can't load
    Qt's standard icons (SP_...). So, we'll pre-render the icon at the desired
    size and dpr.

    On PyQt6, pixmaps remain in memory. Before the first use, call
    QTextDocument.setDefaultResourceProvider(stockIconResourceProvider).

    On PySide6 and PyQt5, pixmaps are written to the temporary directory.
    """

    src = f"{STOCK_ICON_URL_SCHEME}:{iconId}#{size}"

    # Neither PyQt5 nor PySide6 support QTextDocument.setDefaultResourceProvider(),
    # so we can't pass our internal URL. Use a PNG file in the temp dir.
    if not QT_RESOURCE_PROVIDER_OK:  # pragma: no cover
        internalSrc = src
        src = f"{qTempDir()}/icon-{hash(internalSrc) & 0xFFFFFFFF:x}.png"
        if not Path(src).exists():
            stockIconResourceProvider(QUrl(internalSrc)).save(src)

    return f"<img src='{src}' width={size} height={size} style='vertical-align: bottom;'>"


def clearStockIconCache():
    _stockIconCache.clear()
    _stockIconPixmapCache.clear()
