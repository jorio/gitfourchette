# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *
from gitfourchette.toolbox import *


class BlameBusySpinner(QWidget):
    def __init__(self, parent: QWidget):
        super().__init__(parent)

        radius = 50
        self.resize(radius*2, radius*2)
        self.setEnabled(False)

        spinner = QBusySpinner(self, centerOnParent=False)  # we manage positioning ourselves
        spinner.setInnerRadius(radius//3)
        spinner.setLineLength(radius//3)
        spinner.setHaloThickness(radius//3)
        spinner.setLineWidth(radius//8)
        self.spinner = spinner

        self.delayStart = QTimer(self)
        self.delayStart.timeout.connect(self.spinner.start)
        self.delayStart.setSingleShot(True)

        layout = QVBoxLayout()
        layout.addWidget(spinner)
        self.setLayout(layout)

        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.reposition()

    def reposition(self):
        self.move((self.parentWidget().width() - self.width()) // 2, 64)

    def start(self):
        if not self.delayStart.isActive():
            self.delayStart.start(200)

    def stop(self):
        self.delayStart.stop()
        self.spinner.stop()
