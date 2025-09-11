# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *
from gitfourchette.toolbox.recolorsvgiconengine import RecolorSvgIconEngine


_stockIconCache: dict[int, QIcon] = {}

# Override some icon IDs depending on desktop environment
_overrideIconIds = {}
_overrideIconIdsReady = False


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


def stockIconImgTag(iconId: str) -> str:
    return f"<img src='assets:icons/{iconId}' style='vertical-align: bottom;'/>"
