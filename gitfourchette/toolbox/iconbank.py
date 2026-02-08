# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *
from gitfourchette.toolbox.recolorsvgiconengine import RecolorSvgIconEngine


_stockIconCache: dict[int, QIcon] = {}
_stockIconHtmlCache: dict[int, str] = {}

# Override some icon IDs depending on desktop environment
_overrideIconIds = {}
_overrideIconIdsReady = False

_autoDarkVariants = {
    "achtung",
    "status_a",
    "status_c",  # just in case we ever add this one
    "status_d",
    "status_m",
    "status_r",
    "status_t",
    "status_x",
    # status_u intentionally omitted. Its white outline should stand out against a white background.
}


def _iconOverrideTable():
    overrides = {}

    assert QApplication.instance(), "need app instance for QIcon.themeName()"
    iconTheme = QIcon.themeName().casefold()

    # Use native warning icon in all contexts on Mac & Windows
    if MACOS or WINDOWS:  # pragma: no cover
        overrides["achtung"] = "SP_MessageBoxWarning"

    # Override Ubuntu default theme's scary red icon for warnings
    if FREEDESKTOP and iconTheme.startswith("yaru"):  # pragma: no cover
        overrides["SP_MessageBoxWarning"] = "warning-small-symbolic"

    return overrides


def stockIcon(iconId: str, colorTable="") -> QIcon:
    # Special cases
    global _overrideIconIdsReady
    if not _overrideIconIdsReady:
        _overrideIconIds.clear()
        _overrideIconIds.update(_iconOverrideTable())
    iconId = _overrideIconIds.get(iconId, iconId)

    if RecolorSvgIconEngine.IconColors.preferDarkVariants and iconId in _autoDarkVariants:
        assert not colorTable
        colorTable = "white=#000 black=#fff"

    # Compute cache key
    key = hash(iconId) ^ hash(colorTable)

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
        engine = RecolorSvgIconEngine(iconPath, colorTable)
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

    assert iconPath.endswith(".svg") or not colorTable, f"can't remap colors in non-SVG icon! {iconId}"

    # Cache icon
    _stockIconCache[key] = icon
    return icon


def stockIconImgTag(iconId: str, dpr: float = 0) -> str:
    # Qt's HTML subset renders <img> tags at devicePixelRatio=1. To avoid ugly
    # stretching beyond 1x, we'll pre-render the image at the desired dpr. This
    # makes most sense for SVG images which make up the bulk of our icon bank.
    if dpr == 0:
        # devicePixelRatio not specified, figure it out.
        app = QApplication.instance()
        try:
            # Use mainWindow's dpr
            dpr = app.mainWindow.devicePixelRatio()
        except AttributeError:
            # Too early, no window yet; fall back to highest dpr on the system.
            # Note: on Wayland, this may be higher than the actual dpr if
            # fractional scaling is enabled (e.g. this may return 2.0 if your
            # system is set up for 1.25 frac scaling)
            dpr = app.devicePixelRatio()

    key = hash(iconId) ^ hash(dpr)

    try:
        return _stockIconHtmlCache[key]
    except KeyError:
        pass

    size = QSize(16, 16)

    if dpr == 1 or QT5:
        # Pre-rendering not necessary for dpr=1
        # (Qt 5: can't pass devicePixelRatio to QIcon.pixmap())
        src = f"assets:icons/{iconId}"
    else:
        # Pre-render at the given dpr into a temporary PNG file.
        icon = stockIcon(iconId)
        pixmap = icon.pixmap(size, dpr)
        fileName = f"i{int(dpr*100)}-{key & 0xFFFFFFFF:x}.png"
        src = f"{qTempDir()}/{fileName}"
        pixmap.save(src)

    tag = f"<img src='{src}' width={size.width()} height={size.height()} style='vertical-align: bottom;'/>"

    _stockIconHtmlCache[key] = tag
    return tag


def clearStockIconCache():
    _stockIconCache.clear()
    _stockIconHtmlCache.clear()
