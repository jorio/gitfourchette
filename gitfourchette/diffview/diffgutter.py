# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import TYPE_CHECKING

from gitfourchette import settings
from gitfourchette.qt import *
from gitfourchette.toolbox import *

if TYPE_CHECKING:
    from gitfourchette.diffview.diffview import DiffView


class DiffGutter(QWidget):
    """
    Line number gutter for DiffView
    (inspired by https://doc.qt.io/qt-5/qtwidgets-widgets-codeeditor-example.html)
    """

    diffView: DiffView
    paddingString: str

    def __init__(self, parent):
        super().__init__(parent)
        self.diffView = parent
        self.paddingString = ""

        cursorDpr = 1 if FREEDESKTOP else 4  # On Linux, Qt doesn't seem to support cursors at non-1 DPR
        cursorPix = QPixmap(f"assets:icons/right_ptr@{cursorDpr}x")
        cursorPix.setDevicePixelRatio(cursorDpr)
        flippedCursor = QCursor(cursorPix, hotX=19, hotY=5)
        self.setCursor(flippedCursor)

        # Enable customContextMenuRequested signal
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def setMaxLineNumber(self, lineNumber: int):
        if lineNumber == 0:
            maxDigits = 0
        else:
            maxDigits = len(str(lineNumber))
        self.paddingString = "0" * (2 * maxDigits + 2)

    def calcWidth(self) -> int:
        return self.fontMetrics().horizontalAdvance(self.paddingString)

    def onParentUpdateRequest(self, rect: QRect, dy: int):
        if dy != 0:
            self.scroll(0, dy)
        else:
            self.update(0, rect.y(), self.width(), rect.height())

    def sizeHint(self) -> QSize:
        return QSize(self.calcWidth(), 0)

    def wheelEvent(self, event: QWheelEvent):
        # Forward mouse wheel to parent widget
        self.parentWidget().wheelEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        # Double click to select clump of lines
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            self.diffView.selectClumpOfLinesAt(clickPoint=pos)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.diffView.selectWholeLinesTo(pos)
            else:
                self.diffView.selectWholeLineAt(pos)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            self.diffView.selectWholeLinesTo(pos)

    def mouseReleaseEvent(self, event: QMouseEvent):
        super().mouseReleaseEvent(event)
        if settings.prefs.middleClickToStage and event.button() == Qt.MouseButton.MiddleButton:
            self.diffView.doPrimaryApplyLinesAction()

    def paintEvent(self, event: QPaintEvent):
        diffView = self.diffView
        painter = QPainter(self)
        painter.setFont(self.font())

        # Set up colors
        palette = self.palette()
        themeBG = palette.color(QPalette.ColorRole.Base)  # standard theme background color
        themeFG = palette.color(QPalette.ColorRole.Text)  # standard theme foreground color
        if isDarkTheme(palette):
            gutterColor = themeBG.darker(105)  # light theme
        else:
            gutterColor = themeBG.lighter(140)  # dark theme
        lineColor = QColor(themeFG.red(), themeFG.green(), themeFG.blue(), 80)
        textColor = QColor(themeFG.red(), themeFG.green(), themeFG.blue(), 80)

        # Gather some metrics
        paintRect = event.rect()
        gutterRect = self.rect()
        rightEdge = gutterRect.width() - 1
        fontHeight = self.fontMetrics().height()

        # Clip painting to QScrollArea viewport rect (don't draw beneath horizontal scroll bar)
        vpRect = diffView.viewport().rect()
        vpRect.setWidth(paintRect.width())  # vpRect is adjusted by gutter width, so undo this
        paintRect = paintRect.intersected(vpRect)
        painter.setClipRect(paintRect)

        # Draw background
        painter.fillRect(paintRect, gutterColor)

        # Draw vertical separator line
        painter.fillRect(rightEdge, paintRect.y(), 1, paintRect.height(), lineColor)

        block: QTextBlock = diffView.firstVisibleBlock()
        blockNumber = block.blockNumber()
        top = round(diffView.blockBoundingGeometry(block).translated(diffView.contentOffset()).top())
        bottom = top + round(diffView.blockBoundingRect(block).height())

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

        while block.isValid() and top <= paintRect.bottom():
            if blockNumber >= len(diffView.lineData):
                break

            if block.isVisible() and bottom >= paintRect.top():
                ld = diffView.lineData[blockNumber]
                if ld.diffLine:
                    # Draw line numbers
                    old = str(ld.diffLine.old_lineno) if ld.diffLine.old_lineno > 0 else noOldPlaceholder
                    new = str(ld.diffLine.new_lineno) if ld.diffLine.new_lineno > 0 else noNewPlaceholder

                    colW = (rightEdge - 3) // 2
                    painter.drawText(0, top, colW, fontHeight, Qt.AlignmentFlag.AlignRight, old)
                    painter.drawText(colW, top, colW, fontHeight, Qt.AlignmentFlag.AlignRight, new)
                else:
                    # Draw hunk separator horizontal line
                    y = round((top + bottom) / 2)
                    painter.setPen(linePen)
                    painter.drawLine(QLine(0, y, rightEdge, y))
                    painter.setPen(textPen)  # restore text pen

            block = block.next()
            top = bottom
            bottom = top + round(diffView.blockBoundingRect(block).height())
            blockNumber += 1

        painter.end()
