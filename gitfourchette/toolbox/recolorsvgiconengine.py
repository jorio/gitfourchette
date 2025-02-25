# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from pathlib import Path

from gitfourchette.qt import *
from gitfourchette.toolbox.qtutils import mixColors


class RecolorSvgIconEngine(QIconEngine):
    def __init__(self, iconPath: str, colorTable: str = ""):
        super().__init__()

        self.colorTable = colorTable

        lightPath = Path(iconPath)
        self.lightSvg = lightPath.read_text("utf-8").strip()

        try:
            darkPath = lightPath.with_stem(lightPath.stem + "@dark")
            self.darkSvg = darkPath.read_text("utf-8").strip()
        except FileNotFoundError:
            self.darkSvg = self.lightSvg

        self.initVariants()

        from gitfourchette.application import GFApplication
        GFApplication.instance().restyle.connect(self.initVariants)

    def initVariants(self):
        palette = QApplication.palette()
        bgColor = palette.color(QPalette.ColorRole.Window)
        fgColor = palette.color(QPalette.ColorRole.WindowText)
        hlColor = palette.color(QPalette.ColorRole.HighlightedText)
        mainColor = mixColors(bgColor, fgColor, .58)
        isDark = bgColor.lightness() < fgColor.lightness()

        self.referenceSvg = self.darkSvg if isDark else self.lightSvg
        self.basePixmapKey = hash(self.referenceSvg) ^ hash(self.colorTable)
        self.renderers = {
            QIcon.Mode.Normal: self._recolor(mainColor),
            QIcon.Mode.Disabled: self._recolor(mainColor, opacity=.33),
            QIcon.Mode.Selected: self._recolor(hlColor),
            QIcon.Mode.SelectedInactive: self._recolor(fgColor)
        }

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State):
        try:
            renderer = self.renderers[mode]
        except KeyError:
            renderer = self.renderers[QIcon.Mode.Normal]
        rectf = QRectF(rect)
        renderer.render(painter, rectf)

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State):
        if not QT5:
            key = f"{self.basePixmapKey},{size.width()},{size.height()},{mode.value},{state.value}"
        else:  # pragma: no cover
            key = f"{self.basePixmapKey},{size.width()},{size.height()},{mode},{state}"
        pixmap = QPixmapCache.find(key)
        if pixmap is not None:
            return pixmap

        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        rect = QRect(QPoint(0, 0), size)
        self.paint(painter, rect, mode, state)

        QPixmapCache.insert(key, pixmap)
        return pixmap

    def _recolor(self, replaceGray: QColor, opacity: float = 1.0) -> QSvgRenderer:
        """ Create a QSvgRenderer for a recolored variant of referenceSvg. """

        # self.colorTable takes precedence over replaceGray
        colorTable = self.colorTable.split()
        colorTable.append(f"gray={replaceGray.name()}")

        data = self.referenceSvg

        for pair in colorTable:
            oldColor, newColor = pair.split("=")
            data = data.replace(oldColor, newColor)

        if opacity != 1.0:
            dataLines = data.splitlines()
            dataLines[0] += f"<g opacity='{opacity}'>"
            dataLines[-1] = "</g>" + dataLines[-1]
            data = "\n".join(dataLines)

        blob = data.encode("utf-8")
        renderer = QSvgRenderer(blob)
        renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        return renderer
