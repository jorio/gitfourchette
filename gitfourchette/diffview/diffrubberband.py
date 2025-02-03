# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import colors
from gitfourchette.qt import *
from gitfourchette.toolbox import isDarkTheme


class DiffRubberBand(QWidget):
    def paintEvent(self, event: QPaintEvent):
        # Don't inherit QRubberBand (pen thickness ignored on Linux!)
        RX = 12  # rounded rect x radius
        RY = 4  # rounded rect y radius
        T = 4  # thickness
        HT = T//2  # half thickness
        CT = T//2  # clipped thickness
        OT = 1  # outline extra thickness

        palette: QPalette = self.palette()
        painter = QPainter(self)
        rect: QRect = self.rect().marginsRemoved(QMargins(HT, HT, HT, HT))

        outlineColor: QColor = palette.color(QPalette.ColorRole.Base)
        outlineColor.setAlphaF(.75 if outlineColor.lightnessF() < .5 else .5)  # light mode: subtler alpha

        if self.parent().hasFocus():
            try:
                penColor = palette.accent().color()
            except AttributeError:
                # QPalette.accent() was introduced in Qt 6.7
                penColor = colors.teal if isDarkTheme() else colors.blue
        else:
            penColor = palette.color(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight)

        pen = QPen(penColor, T)
        outlinePen = QPen(outlineColor, T+2*OT)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setClipRect(rect.marginsAdded(QMargins(HT, CT-HT, HT, CT-HT)))

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), RX, RY, Qt.SizeMode.AbsoluteSize)

        painter.setClipRect(rect.marginsAdded(QMargins(HT, CT-HT+OT, HT, CT-HT+OT)))
        painter.setPen(outlinePen)
        painter.drawPath(path)

        painter.setClipRect(rect.marginsAdded(QMargins(HT, CT-HT, HT, CT-HT)))
        painter.setPen(pen)
        painter.drawPath(path)
