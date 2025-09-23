# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *
from gitfourchette.toolbox import *


class QStatusBar2(QStatusBar):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("QStatusBar2")

        self.memoryIndicator = MemoryIndicator(self)

        self.setSizeGripEnabled(False)
        self.addPermanentWidget(self.memoryIndicator)
        # macOS: must reset stylesheet after addPermanentWidget for no-border thickness thing to take effect
        self.memoryIndicator.setStyleSheet(self.memoryIndicator.styleSheet())

        self.busyMessageDelayer = QTimer(self)
        self.busyMessageDelayer.setSingleShot(True)
        self.busyMessageDelayer.setInterval(20)
        self.busyMessageDelayer.timeout.connect(self.commitBusyMessage)

        self.busyWidget = QWidget(self)
        self.busySpinner = QBusySpinner(self.busyWidget, centerOnParent=False)
        self.busySpinner.stop()
        self.busyLabel = QLabel(self.busyWidget)
        # Emojis such as the lightbulb may increase the label's height
        self.busyWidget.setMaximumHeight(self.fontMetrics().height())

        layout = QHBoxLayout(self.busyWidget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.busySpinner)
        layout.addWidget(self.busyLabel, 1)

        self.busyWidget.setVisible(False)

    def showMessage(self, text: str, msecs=0):
        if self.busyMessageDelayer.isActive():
            # Commit the busy message now and kill the delayer.
            # It'll be immediately overridden by the temporary message.
            # We don't want it to happen the other way around.
            self.commitBusyMessage()

        super().showMessage(text, msecs)

    @property
    def isBusyMessageVisible(self):
        # Temporary messages take precedence over busySpinner/busyWidget, so
        # those widgets might be invisible even though a message is set.
        # So, busySpinner.isSpinning is a better way to check that a message
        # is currently set than .isVisible.
        return self.busySpinner.isSpinning()

    def showBusyMessage(self, text: str):
        self.busyLabel.setText(text)
        if not self.isBusyMessageVisible and not self.busyMessageDelayer.isActive():
            self.busyMessageDelayer.start()

    def commitBusyMessage(self):
        self.busyMessageDelayer.stop()

        if self.busySpinner.isSpinning():
            # Spinner is already spinning: busy widget already visible.
            return

        # Replace permanent status message with our busyWidget
        # which includes the spinner and the busy message.
        self.busySpinner.start()
        self.busyWidget.setVisible(True)
        self.insertPermanentWidget(0, self.busyWidget, 1)

    def clearMessage(self):
        self.busyMessageDelayer.stop()

        if self.isBusyMessageVisible:
            self.busySpinner.stop()
            self.removeWidget(self.busyWidget)
            self.busyWidget.setVisible(False)

        super().clearMessage()

    def enableMemoryIndicator(self, show: bool = False):
        self.memoryIndicator.setVisible(show)
