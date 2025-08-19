# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import shlex
from contextlib import suppress

from gitfourchette.forms.ui_processdialog import Ui_ProcessDialog
from gitfourchette.gitdriver import GitDriver
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class ProcessDialog(QDialog):
    PopUpDelay = 200

    becameVisible = Signal()

    trackedProcess: QProcess | None

    def __init__(self, parent: QWidget):
        super().__init__(parent)

        self.trackedProcess = None

        self.ui = Ui_ProcessDialog()
        self.ui.setupUi(self)

        # Delay popup to avoid flashing when the process finishes fast enough.
        # (In unit tests, show it immediately for code coverage.)
        self.delayPopUp = QTimer(self)
        self.delayPopUp.timeout.connect(self.popUp)
        self.delayPopUp.setSingleShot(True)
        self.delayPopUp.setInterval(ProcessDialog.PopUpDelay if not APP_TESTMODE else 0)

        statusFont = self.ui.statusLabel.font()
        setFontFeature(statusFont, "tnum")
        self.ui.statusLabel.setFont(statusFont)
        tweakWidgetFont(self.ui.titleLabel, bold=True)
        tweakWidgetFont(self.ui.commandLabel, 88)

        self.setMinimumWidth(self.fontMetrics().horizontalAdvance("W" * 40))
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint | Qt.WindowType.WindowTitleHint)  # hide close button
        self.setWindowModality(Qt.WindowModality.WindowModal)

        self.resize(self.width(), 1)

        # Remove keyboard focus from the abort button to prevent accidental triggering.
        # The user can still press the Escape key to abort.
        self.abortButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def install(self, process: QProcess, title: str):
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
        process = self.trackedProcess
        if not process:
            return

        commandLine = shlex.join([process.program()] + process.arguments())
        self.ui.commandLabel.setText(commandLine)

        self.ui.titleLabel.setText(self.windowTitle())
        self.setMessage(_("Please wait…"))
        self.setProgress(0, 0)

        self.abortButton.setEnabled(True)

        if isinstance(process, GitDriver):
            process.progressMessage.connect(self.setMessage)
            process.progressFraction.connect(self.setProgress)

        self.show()
        self.becameVisible.emit()
        self.abortButton.clearFocus()

    def disconnectProcess(self):
        self.delayPopUp.stop()

        process = self.trackedProcess
        if not process:
            return

        self.trackedProcess = None

        process.errorOccurred.disconnect(self.onProcessFinished)
        process.finished.disconnect(self.onProcessFinished)

        if isinstance(process, GitDriver):
            with suppress(TypeError, RuntimeError):
                process.progressMessage.disconnect(self.setMessage)
            with suppress(TypeError, RuntimeError):
                process.progressFraction.disconnect(self.setProgress)

    def close(self) -> bool:
        self.disconnectProcess()
        return super().close()

    @property
    def abortButton(self) -> QPushButton:
        return self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Abort)

    def setProgress(self, value: int, maximum: int):
        self.ui.progressBar.setMaximum(maximum)
        self.ui.progressBar.setValue(value)

    def setMessage(self, text: str):
        self.ui.statusLabel.setText(text)

    def reject(self):  # bound to abort button
        self.abortButton.setEnabled(False)
        self.ui.statusLabel.setText(_("Aborting…"))
        self.setProgress(0, 0)

        if self.trackedProcess:
            self.trackedProcess.terminate()

    def onProcessFinished(self):
        self.disconnectProcess()
        self.setVisible(False)
