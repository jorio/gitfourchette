# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *
from gitfourchette.toolbox import *


class BlameBusySpinner(QBusySpinner):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setFixedSize(96, 96)

        self.delayStart = QTimer(self)
        self.delayStart.timeout.connect(self.show)
        self.delayStart.setInterval(200)
        self.delayStart.setSingleShot(True)

        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.reposition()
        self.hide()

    def reposition(self):
        self.move((self.parentWidget().width() - self.width()) // 2, 64)

    def start(self):
        if not self.delayStart.isActive():
            self.delayStart.start()

    def stop(self):
        self.delayStart.stop()
        self.hide()
