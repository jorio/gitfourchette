# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from pathlib import Path

from gitfourchette.qt import *
from gitfourchette.toolbox.qtutils import mixColors

_Gray = "gray"
"""
Name of the placeholder color in the icons' SVG markup.
This color will be replaced with IconColors.mainColor.
"""


class RecolorSvgIconEngine(QIconEngine):
    """
    QIcon renderer that adjusts the colors in an SVG icon. The colors are chosen
    based on the global color palette, active/disabled/selected icon modes, and
    an optional color remapping table.
    """

    class IconColors:
        background = QColor(0xFFFFFF)
        foreground = QColor(0x000000)
        highlight = QColor(0x00FFFF)
        mainColor = QColor(0xFF00FF)
        preferDarkVariants = False

        @classmethod
        def refresh(cls):
            palette = QApplication.palette()
            cls.background = palette.color(QPalette.ColorRole.Window)
            cls.foreground = palette.color(QPalette.ColorRole.WindowText)
            cls.highlight = palette.color(QPalette.ColorRole.HighlightedText)
            cls.mainColor = mixColors(cls.background, cls.foreground, .58)
            cls.preferDarkVariants = cls.background.lightness() < cls.foreground.lightness()

    def __init__(self, iconPath: str, colorTable: str = ""):
        super().__init__()

        # Read in SVG data
        assert iconPath.endswith(".svg")
        iconPath = Path(iconPath)
        svg = iconPath.read_text("utf-8").strip()

        # Replace colors in hardcoded color table
        hardcodedColors = {}
        for entry in colorTable.split():
            original, replacement = entry.split("=", 1)
            hardcodedColors[original] = replacement
            svg = svg.replace(original, "{" + original + "}")
        svg = svg.format_map(hardcodedColors)

        # Inject format token for gray (unless colorTable overrides it)
        if _Gray not in hardcodedColors:
            svg = svg.replace(_Gray, "{" + _Gray + "}")

        # Inject format token for surrounding tag (used for opacity)
        beg = svg.index(">") + 1
        end = svg.rindex("</svg>")
        svg = svg[:beg] + "{prefix}" + svg[beg:end] + "{suffix}" + svg[end:]

        self.svg = svg
        self.informalIconName = iconPath.name  # for debugging
        self.basePixmapKey = hash(svg)
        self.renderers = {}
        self.referenceSize = QSize(0, 0)

        self.initVariants()

        from gitfourchette.application import GFApplication
        GFApplication.instance().restyle.connect(self.initVariants)

    def initVariants(self):
        IC = RecolorSvgIconEngine.IconColors
        self.renderers = {
            QIcon.Mode.Normal: self._recolor(IC.mainColor),
            QIcon.Mode.Disabled: self._recolor(IC.mainColor, opacity=.33),
            QIcon.Mode.Selected: self._recolor(IC.highlight),
            QIcon.Mode.SelectedInactive: self._recolor(IC.foreground),
        }
        self.referenceSize = self.renderers[QIcon.Mode.Normal].defaultSize()

    def iconName(self):
        return self.informalIconName

    def actualSize(self, size: QSize, mode: QIcon.Mode, state: QIcon.State):
        # Crispness hack: Tweak width/height so that centered X/Y coordinates
        # snap to integers. This fixes blurriness at 1x scaling when rendering,
        # for example, a 16x16 SVG into a 16x19 rectangle.
        rw, rh = self.referenceSize.width(), self.referenceSize.height()
        sw, sh = size.width(), size.height()
        if sw > rw and (sw ^ rw) & 1 != 0:
            sw -= 1
        if sh > rh and (sh ^ rh) & 1 != 0:
            sh -= 1
        return QSize(sw, sh)

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
        painter.end()

        QPixmapCache.insert(key, pixmap)
        return pixmap

    def _recolor(self, replaceGray: QColor, opacity: float = 1.0) -> QSvgRenderer:
        """
        Create a QSvgRenderer for a recolored variant of the base SVG icon.
        """

        tokens = {
            _Gray: replaceGray.name(),
            "prefix": "",
            "suffix": ""
        }

        if opacity != 1.0:
            tokens["prefix"] = f"<g opacity='{opacity}'>"
            tokens["suffix"] = "</g>"

        data = self.svg.format_map(tokens)
        blob = data.encode("utf-8")

        renderer = QSvgRenderer(blob)
        renderer.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        return renderer
