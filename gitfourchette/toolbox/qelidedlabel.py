# Adapted from https://stackoverflow.com/a/68092991
# New: per-line elision in multiline strings

from gitfourchette.qt import *


class QElidedLabel(QLabel):
    _elideMode = Qt.TextElideMode.ElideRight

    def elideMode(self):
        return self._elideMode

    def setElideMode(self, mode):
        if self._elideMode != mode and mode != Qt.TextElideMode.ElideNone:
            self._elideMode = mode
            self.updateGeometry()

    def minimumSizeHint(self):
        return self.sizeHint()

    def sizeHint(self):
        hint = self.fontMetrics().boundingRect(self.text()).size()
        cm = self.contentsMargins()
        margin = self.margin() * 2
        return QSize(
            min(100, hint.width()) + cm.left() + cm.right() + margin,
            min(self.fontMetrics().height(), hint.height()) + cm.top() + cm.bottom() + margin
        )

    def paintEvent(self, event):
        qp = QPainter(self)
        opt = QStyleOptionFrame()
        self.initStyleOption(opt)
        self.style().drawControl(QStyle.ControlElement.CE_ShapedFrame, opt, qp, self)

        elideMode = self.elideMode()
        metrics = self.fontMetrics()
        margin = self.margin()
        m = int(metrics.horizontalAdvance('x') / 2 - margin)  # int() for PyQt5 compat
        r = self.contentsRect().adjusted(margin + m,  margin, -(margin + m), -margin)
        width = r.width()

        elidedText = "\n".join(
            metrics.elidedText(line, elideMode, width)
            for line in self.text().splitlines())

        qp.drawText(r, self.alignment(), elidedText)
        qp.end()
