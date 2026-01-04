# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *
from gitfourchette.toolbox.iconbank import stockIcon


class QBusySpinner(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.currentFrame = 0
        self.numFrames = 8
        self.timer = QTimer(self)
        self.timer.setInterval(125)
        self.timer.timeout.connect(self.nextFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        if not self.timer.isActive():
            self.timer.start()
            self.nextFrame()

    def hideEvent(self, event: QHideEvent):
        self.timer.stop()
        super().hideEvent(event)

    def nextFrame(self):
        self.currentFrame = (self.currentFrame + 1) % self.numFrames
        self.updatePixmap()

    def updatePixmap(self):
        size = min(self.width(), self.height())
        icon = stockIcon(f"busyspinner{1 + self.currentFrame}")
        pixmap = icon.pixmap(QSize(size, size))
        self.setPixmap(pixmap)
