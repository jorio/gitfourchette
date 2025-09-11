# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.statusform import StatusForm
from gitfourchette.qt import *


class ProcessDialog(QDialog):
    PopUpDelay = 200

    becameVisible = Signal()

    trackedProcess: QProcess | None
    sentSigterm: bool

    def __init__(self, parent: QWidget):
        super().__init__(parent)

        self.trackedProcess = None
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
        # (In unit tests, show it immediately for code coverage.)
        self.delayPopUp = QTimer(self)
        self.delayPopUp.timeout.connect(self.popUp)
        self.delayPopUp.setSingleShot(True)
        self.delayPopUp.setInterval(ProcessDialog.PopUpDelay if not APP_TESTMODE else 0)

        self.setMinimumWidth(self.fontMetrics().horizontalAdvance("W" * 40))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)  # hide close button
        self.setWindowModality(Qt.WindowModality.WindowModal)

        self.resize(self.width(), 1)

        # Remove keyboard focus from the abort button to prevent accidental triggering.
        # The user can still press the Escape key to abort.
        self.abortButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.statusForm.connectAbortButton(self.abortButton)

    def connectProcess(self, process: QProcess, title: str):
        # Forget existing process
        self.disconnectProcess()

        self.setWindowTitle(title)
        self.trackedProcess = process

        process.errorOccurred.connect(self.onProcessFinished)
        process.finished.connect(self.onProcessFinished)

        if self.isVisible():
            # Dialog already shown, update UI now
            self.popUp()
        else:
            # Delay popup to avoid ugly flashing + unnecessary layout work
            # if the process finishes fast enough
            self.delayPopUp.start()

    def popUp(self):
        if self.trackedProcess is None:
            return

        self.statusForm.connectProcess(self.trackedProcess)
        self.show()
        self.becameVisible.emit()

    def disconnectProcess(self):
        self.delayPopUp.stop()
        self.setVisible(False)

        if self.trackedProcess is None:
            return

        process = self.trackedProcess
        self.trackedProcess = None

        process.errorOccurred.disconnect(self.onProcessFinished)
        process.finished.disconnect(self.onProcessFinished)

    def close(self) -> bool:
        self.disconnectProcess()
        return super().close()

    def reject(self):  # bound to abort button and ESC key
        self.statusForm.requestAbort()

    def onProcessFinished(self):
        self.disconnectProcess()
