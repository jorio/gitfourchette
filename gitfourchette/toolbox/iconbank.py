# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
If SVG icons don't show up, you may need to install the 'qt6-svg' package.
"""

from gitfourchette.qt import *
from gitfourchette.toolbox.qtutils import isDarkTheme, writeTempFile, mixColors

_stockIconCache: dict[int, QIcon] = {}
_tempSvgFiles: list[QTemporaryFile] = []


def assetCandidates(name: str):
    prefix = "assets:icons/"
    dark = isDarkTheme()
    for ext in ".svg", ".png":
        if dark:  # attempt to get dark mode variant first
            yield QFile(f"{prefix}{name}@dark{ext}")
        yield QFile(f"{prefix}{name}{ext}")


def getBestIconFile(name: str) -> str:
    try:
        f = next(f for f in assetCandidates(name) if f.exists())
        return f.fileName()
    except StopIteration as exc:
        raise KeyError(f"no built-in icon asset '{name}'") from exc


def lookUpNamedIcon(name: str) -> QIcon:
    try:
        # First, attempt to get a matching icon from the assets
        path = getBestIconFile(name)
        return QIcon(path)
    except KeyError:
        pass

    # Fall back to Qt standard icons (with "SP_" prefix)
    if name.startswith("SP_"):
        entry = getattr(QStyle.StandardPixmap, name)
        return QApplication.style().standardIcon(entry)

    # Fall back to theme icon
    return QIcon.fromTheme(name)


def remapSvgColors(path: str, forcedRemapTable: str) -> QIcon:
    with open(path, encoding="utf-8") as f:
        originalSvg = f.read().strip()

    def remapFile(replaceGray: QColor | None, opacity=1.0) -> str:
        remapTable = forcedRemapTable.split()
        if replaceGray is not None:
            remapTable.append(f"gray={replaceGray.name()}")

        data = originalSvg
        for pair in remapTable:
            oldColor, newColor = pair.split("=")
            data = data.replace(oldColor, newColor)
        if opacity != 1.0:
            dataLines = data.splitlines()
            dataLines[0] += f"<g opacity='{opacity}'>"
            dataLines[-1] = "</g>" + dataLines[-1]
            data = "\n".join(dataLines)
        if data == originalSvg:  # No changes, return original icon
            return path

        # Keep temp file object around so that QIcon can read off it as needed
        tempFile = writeTempFile("icon-XXXXXX.svg", data)
        _tempSvgFiles.append(tempFile)
        return tempFile.fileName()

    palette = QApplication.palette()
    bgColor = palette.color(QPalette.ColorRole.Window)
    fgColor = palette.color(QPalette.ColorRole.WindowText)
    hlColor = palette.color(QPalette.ColorRole.HighlightedText)
    mainColor = None if forcedRemapTable else mixColors(bgColor, fgColor, .62)

    icon = QIcon()
    icon.addFile(remapFile(mainColor),      mode=QIcon.Mode.Normal)
    icon.addFile(remapFile(mainColor, .33), mode=QIcon.Mode.Disabled)
    icon.addFile(remapFile(hlColor),        mode=QIcon.Mode.Selected)
    icon.addFile(remapFile(fgColor),        mode=QIcon.Mode.SelectedInactive)
    return icon


def stockIcon(iconId: str, colorRemapTable="") -> QIcon:
    # Special cases
    if (MACOS or WINDOWS) and iconId == "achtung":
        iconId = "SP_MessageBoxWarning"

    # Compute key
    key = hash(iconId) ^ hash(colorRemapTable)

    # Attempt to get cached icon
    try:
        return _stockIconCache[key]
    except KeyError:
        pass

    # Determine if it's an SVG
    try:
        iconPath = getBestIconFile(iconId)
        isSvg = iconPath.endswith(".svg")
    except KeyError:
        isSvg = False

    # Create QIcon
    if isSvg:
        icon = remapSvgColors(iconPath, colorRemapTable)
    else:
        assert not colorRemapTable, f"can't remap colors in non-SVG icon! {iconId}"
        icon = lookUpNamedIcon(iconId)

    # Cache icon
    _stockIconCache[key] = icon
    return icon


def clearStockIconCache():
    _stockIconCache.clear()
    _tempSvgFiles.clear()
