# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import enum
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

    class Flags(enum.Flag):
        NoFlags = 0
        HighlightActiveMode = enum.auto()

    class IconColors:
        background = QColor(0xFFFFFF)
        foreground = QColor(0x000000)
        highlight = QColor(0x00FFFF)
        mainColor = QColor(0xFF00FF if APP_DEBUG else 0x808080)
        preferDarkVariants = False
        systemFont = "sans-serif"
        initialized = False

        @classmethod
        def refresh(cls):
            palette = QApplication.palette()
            cls.background = palette.color(QPalette.ColorRole.Window)
            cls.foreground = palette.color(QPalette.ColorRole.WindowText)
            cls.highlight = palette.color(QPalette.ColorRole.HighlightedText)
            cls.mainColor = mixColors(cls.background, cls.foreground, .58)
            cls.preferDarkVariants = cls.background.lightness() < cls.foreground.lightness()
            cls.systemFont = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
            cls.initialized = True

    @staticmethod
    def unpackColorTable(colorTable: str) -> dict[str, str]:
        """
        Convert a color remapping string (e.g. "white=#000 black=#fff") to a
        dict. In case of duplicate keys, the last key wins out.
        """
        hardcodedColors = {}
        for entry in colorTable.split():
            original, replacement = entry.split("=", 1)
            hardcodedColors[original] = replacement
        return hardcodedColors

    def __init__(self, iconPathStr: str, colorTable: str = "", flags: Flags = Flags.NoFlags):
        super().__init__()

        # Initialize color scheme
        if not RecolorSvgIconEngine.IconColors.initialized:
            RecolorSvgIconEngine.IconColors.refresh()

        # Read in SVG data
        iconPath = Path(iconPathStr)
        assert iconPath.name.endswith(".svg")
        svg = iconPath.read_text("utf-8").strip()

        # Inject system font
        svg = svg.replace("sans-serif", RecolorSvgIconEngine.IconColors.systemFont)

        # Inject hardcoded colors
        hardcodedColors = RecolorSvgIconEngine.unpackColorTable(colorTable)
        for original in hardcodedColors:
            svg = svg.replace(original, "{" + original + "}")
        svg = svg.format_map(hardcodedColors)

        # Inject format token for gray (unless colorTable overrides it)
        # and leave it there for _recolor to pick up later
        if _Gray not in hardcodedColors:
            svg = svg.replace(_Gray, "{" + _Gray + "}")

        # Inject format token for surrounding tag (used for opacity)
        # and leave it there for _recolor to pick up later
        beg = svg.index(">") + 1
        end = svg.rindex("</svg>")
        svg = svg[:beg] + "{prefix}" + svg[beg:end] + "{suffix}" + svg[end:]

        self.svg = svg
        self.informalIconName = iconPath.name  # for debugging
        self.basePixmapKey = hash((svg, flags))
        self.renderers: dict[QIcon.Mode, QSvgRenderer] = {}
        self.referenceSize = QSize(0, 0)
        self.flags = flags

        self.initVariants()

        from gitfourchette.application import GFApplication
        GFApplication.instance().restyle.connect(self.initVariants)

    def initVariants(self):
        IC = RecolorSvgIconEngine.IconColors
        F = RecolorSvgIconEngine.Flags

        normal = self._recolor(IC.mainColor)
        disabled = self._recolor(IC.mainColor, opacity=.33)
        selected = self._recolor(IC.highlight)
        active = selected if (self.flags & F.HighlightActiveMode) else normal

        self.renderers = {
            QIcon.Mode.Normal: normal,
            QIcon.Mode.Disabled: disabled,
            QIcon.Mode.Selected: selected,
            QIcon.Mode.Active: active,
        }

        self.referenceSize = normal.defaultSize()

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
