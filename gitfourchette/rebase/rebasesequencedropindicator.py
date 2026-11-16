# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *


class RebaseSequenceDropIndicator(QWidget):
    """
    Nicer-looking drop indicator than PE_IndicatorItemView for RebaseSequenceView.
    """

    def syncPositionOnDrag(self, event: QDragMoveEvent, itemView: QAbstractItemView):
        pos = event.position().toPoint()
        index = itemView.indexAt(pos)

        if not event.isAccepted() or not index.isValid():
            self.hide()
            return

        rect = itemView.visualRect(index)

        if pos.y() >= rect.center().y():
            # Mouse below row center: pin to bottom edge
            y = rect.bottom()
        elif index.row() == 0:
            # Mouse above center of topmost row: pin to top edge
            y = rect.top()
        else:
            # Mouse above row center: pin to bottom edge of sibling above
            # (instead of top edge of this row, to prevent jitter)
            index = index.siblingAtRow(index.row() - 1)
            rect = itemView.visualRect(index)
            y = rect.bottom()

        y += 2
        height = self.height()
        self.setGeometry(0, y - height//2, itemView.viewport().width(), height)
        self.show()

    def paintEvent(self, event: QPaintEvent):
        rect = QRect(0, 0, self.width(), self.height())
        palette = self.palette()

        barH = 2
        triH = self.height() // 2
        triW = 24
        triCurvature = .66
        outline = 4

        left     = rect.left()
        leftTip  = left + triW
        leftCtl  = left+int(triW*(1-triCurvature))

        right    = rect.right()
        rightTip = right-triW
        rightCtl = right-int(triW*(1-triCurvature))

        y = rect.center().y()
        yTriTop = y - triH//2
        yBarTop = y - barH//2
        yTriBot = y + triH//2
        yBarBot = y + barH//2

        color = palette.color(QPalette.ColorRole.Text)
        outlineColor = palette.color(QPalette.ColorRole.Base)
        outlineColor.setAlphaF(.75)

        path = QPainterPath()
        path.moveTo(left    , yTriTop)
        path.quadTo(leftCtl , yBarTop, leftTip, yBarTop)
        path.lineTo(rightTip, yBarTop)
        path.quadTo(rightCtl, yBarTop, right, yTriTop)
        path.lineTo(right   , yTriBot)
        path.quadTo(rightCtl, yBarBot, rightTip, yBarBot)
        path.lineTo(leftTip , yBarBot)
        path.quadTo(leftCtl , yBarBot, left, yTriBot)
        path.closeSubpath()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(outlineColor, outline, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)
        painter.end()
