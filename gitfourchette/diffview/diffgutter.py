# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

from gitfourchette import settings
from gitfourchette.codeview.codegutter import CodeGutter
from gitfourchette.qt import *


class DiffGutter(CodeGutter):
    def __init__(self, parent):
        super().__init__(parent)
        self.maxLine = 0
        self.paddingString = "0 0"

    def refreshMetrics(self):
        lineNumber = self.maxLine
        if lineNumber == 0:
            maxDigits = 0
        else:
            maxDigits = len(str(lineNumber))
        self.paddingString = "0" * (2 * maxDigits + 2)

    def calcWidth(self) -> int:
        return self.fontMetrics().horizontalAdvance(self.paddingString)

    def paintEvent(self, event: QPaintEvent):
        diffView = self.codeView
        painter = QPainter(self)

        # Set up colors
        palette = self.palette()
        themeFG = palette.color(QPalette.ColorRole.Text)  # standard theme foreground color
        lineColor = QColor(themeFG.red(), themeFG.green(), themeFG.blue(), 80)
        textColor = QColor(themeFG.red(), themeFG.green(), themeFG.blue(), 80)

        # Gather some metrics
        rightEdge = self.rect().width() - 1
        fontHeight = self.fontMetrics().height()

        # Draw line numbers and hunk separator lines
        if settings.prefs.colorblind:
            noOldPlaceholder = "+"
            noNewPlaceholder = "-"
        else:
            noOldPlaceholder = "·"
            noNewPlaceholder = "·"

        linePen = QPen(lineColor, 1, Qt.PenStyle.DashLine)
        textPen = QPen(textColor)
        painter.setPen(textPen)

        for block, top, bottom in self.paintBlocks(event, painter, lineColor):
            blockNumber = block.blockNumber()

            if blockNumber >= len(diffView.lineData):
                break

            ld = diffView.lineData[blockNumber]
            if ld.origin:
                # Draw line numbers
                old = str(ld.oldLineNo) if ld.oldLineNo > 0 else noOldPlaceholder
                new = str(ld.newLineNo) if ld.newLineNo > 0 else noNewPlaceholder

                colW = (rightEdge - 3) // 2
                painter.drawText(0, top, colW, fontHeight, Qt.AlignmentFlag.AlignRight, old)
                painter.drawText(colW, top, colW, fontHeight, Qt.AlignmentFlag.AlignRight, new)
            else:
                # Draw hunk separator horizontal line
                y = round((top + bottom) / 2)
                painter.setPen(linePen)
                painter.drawLine(QLine(0, y, rightEdge, y))
                painter.setPen(textPen)  # restore text pen

        painter.end()
