# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.statusform import StatusForm
from gitfourchette.qt import *
from gitfourchette.toolbox import QProcessConnection, QSignalBlockerContext


class ProcessDialog(QDialog):
    PopUpDelay = 300 if not WINDOWS else 600

    becameVisible = Signal()

    processConnection: QProcessConnection
    sentSigterm: bool

    def __init__(self, parent: QWidget):
        super().__init__(parent)

        self.processConnection = QProcessConnection(self)
        self.processConnection.processLost.connect(self.onProcessLost)

        self.sentSigterm = False

        # Set up UI
        layout = QVBoxLayout(self)
        self.statusForm = StatusForm(self)
        self.buttonBox = QDialogButtonBox(self)
        self.buttonBox.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.abortButton = self.buttonBox.addButton(QDialogButtonBox.StandardButton.Abort)
        layout.addWidget(self.statusForm)
        layout.addWidget(self.buttonBox)

        # Delay popup to avoid flashing when the process finishes fast enough.
        self.delayPopUp = QTimer(self)
        self.delayPopUp.timeout.connect(self.popUp)
        self.delayPopUp.setSingleShot(True)
        self.delayPopUp.setInterval(ProcessDialog.PopUpDelay)

        self.setMinimumWidth(self.fontMetrics().horizontalAdvance("W" * 40))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)  # hide close button
        self.setWindowModality(Qt.WindowModality.WindowModal)

        self.resize(self.width(), 1)

        # Remove keyboard focus from the abort button to prevent accidental triggering.
        # The user can still press the Escape key to abort.
        self.abortButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.statusForm.connectAbortButton(self.abortButton)

    def connectProcess(self, process: QProcess, title: str):
        # Forget existing process, if any, and keep track of this one.
        # Block signal 'processConnection.processLost' to avoid closing and
        # reopening the dialog when chaining processes quickly.
        with QSignalBlockerContext(self.processConnection):
            self.processConnection.track(process)

        self.setWindowTitle(title)

        if self.isVisible():
            # Dialog already shown, update UI now
            self.connectProcessInStatusForm()
        elif not self.delayPopUp.isActive():
            # Delay popup to avoid ugly flashing + unnecessary layout work
            # if the process finishes fast enough
            self.delayPopUp.start()

    def popUp(self):
        if not self.processConnection:
            return

        self.connectProcessInStatusForm()
        self.show()
        self.becameVisible.emit()

    def connectProcessInStatusForm(self):
        self.statusForm.connectProcess(self.processConnection.process)

    def onProcessLost(self):
        self.delayPopUp.stop()
        self.setVisible(False)

        # HACK: In offscreen unit tests, re-activate the previous window so we can assume
        # keyboard focus is still valid. Qt does this for us in non-offscreen mode.
        if APP_TESTMODE and OFFSCREEN:
            self.parentWidget().activateWindow()

    def close(self) -> bool:
        self.processConnection.stopTracking()
        return super().close()

    def reject(self):  # bound to abort button and ESC key
        self.statusForm.requestAbort()
