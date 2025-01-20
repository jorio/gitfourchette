# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import TYPE_CHECKING

from gitfourchette.qt import *
from gitfourchette.toolbox import *

if TYPE_CHECKING:
    from gitfourchette.codeview.codeview import CodeView


class CodeGutter(QWidget):
    """
    Generic gutter for CodeView
    """
    # Inspired by https://doc.qt.io/qt-6.2/qtwidgets-widgets-codeeditor-example.html

    lineClicked = Signal(QPoint)
    lineShiftClicked = Signal(QPoint)
    lineDoubleClicked = Signal(QPoint)
    selectionMiddleClicked = Signal()

    codeView: CodeView

    def __init__(self, parent):
        super().__init__(parent)
        self.codeView = parent

        cursorDpr = 1 if FREEDESKTOP else 4  # On Linux, Qt doesn't seem to support cursors at non-1 DPR
        cursorPix = QPixmap(f"assets:icons/right_ptr@{cursorDpr}x")
        cursorPix.setDevicePixelRatio(cursorDpr)
        flippedCursor = QCursor(cursorPix, hotX=19, hotY=5)
        self.setCursor(flippedCursor)

        # Enable customContextMenuRequested signal
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def refreshMetrics(self):
        raise NotImplementedError("override this")

    def calcWidth(self) -> int:
        raise NotImplementedError("override this")

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
            # self.codeView.selectClumpOfLinesAt(clickPoint=pos)
            self.lineDoubleClicked.emit(pos)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                # self.codeView.selectWholeLinesTo(pos)
                self.lineShiftClicked.emit(pos)
            else:
                # self.codeView.selectWholeLineAt(pos)
                self.lineClicked.emit(pos)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            self.selectionMiddleClicked.emit()

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            # self.codeView.selectWholeLinesTo(pos)
            self.lineShiftClicked.emit(pos)

    def paintBlocks(self, event: QPaintEvent, painter: QPainter, lineColor: QColor):
        # Set up colors
        palette = self.palette()
        themeBG = palette.color(QPalette.ColorRole.Base)  # standard theme background color
        if isDarkTheme(palette):
            gutterColor = themeBG.darker(105)
        else:
            gutterColor = themeBG.lighter(140)

        # Gather some metrics
        paintRect = event.rect()
        gutterRect = self.rect()
        rightEdge = gutterRect.width() - 1

        # Clip painting to QScrollArea viewport rect (don't draw beneath horizontal scroll bar)
        vpRect = self.codeView.viewport().rect()
        vpRect.setWidth(paintRect.width())  # vpRect is adjusted by gutter width, so undo this
        paintRect = paintRect.intersected(vpRect)
        painter.setClipRect(paintRect)

        # Draw background
        painter.fillRect(paintRect, gutterColor)

        # Draw vertical separator line
        painter.fillRect(rightEdge, paintRect.y(), 1, paintRect.height(), lineColor)

        block: QTextBlock = self.codeView.firstVisibleBlock()
        top = round(self.codeView.blockBoundingGeometry(block).translated(self.codeView.contentOffset()).top())
        bottom = top + round(self.codeView.blockBoundingRect(block).height())

        while block.isValid() and top <= paintRect.bottom():
            if block.isVisible() and bottom >= paintRect.top():
                yield block, top, bottom

            block = block.next()
            top = bottom
            bottom = top + round(self.codeView.blockBoundingRect(block).height())
