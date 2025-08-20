# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import re
import shlex
from contextlib import suppress

from gitfourchette.forms.ui_statusform import Ui_StatusForm
from gitfourchette.gitdriver import GitDriver
from gitfourchette.localization import _
from gitfourchette.qt import *
from gitfourchette.toolbox import stockIcon, tweakWidgetFont

logger = logging.getLogger(__name__)


class StatusForm(QWidget):
    def __init__(self, parent):
        super().__init__(parent)

        self.trackedProcess = None
        self.sentSigterm = False
        self.abortButton = None
        self.abortButtonDefaultText = ""
        self.abortButtonDefaultIcon = None

        self.ui = Ui_StatusForm()
        self.ui.setupUi(self)

        # Fix slightly different background color in blurb page in Fusion and macOS styles
        self.ui.blurbScrollArea.viewport().setAutoFillBackground(False)
        self.ui.blurbScrollAreaWidgetContents.setAutoFillBackground(False)

        tweakWidgetFont(self.ui.titleLabel, bold=True)
        tweakWidgetFont(self.ui.commandLabel, relativeSize=88)
        tweakWidgetFont(self.ui.statusLabel, tabularNumbers=True)

    def connectAbortButton(self, abortButton: QPushButton):
        self.abortButton = abortButton
        self.abortButtonDefaultText = abortButton.text()
        self.abortButtonDefaultIcon = abortButton.icon()

    def setBlurb(self, text: str):
        self.ui.stackedWidget.setCurrentIndex(0)
        self.ui.blurbLabel.setText(text)

    def initProgress(self, text: str):
        self.ui.stackedWidget.setCurrentIndex(1)
        self.setProgressMessage(text)
        self.ui.progressBar.setMinimum(0)
        self.setProgressValue(0, 0)

    def setProgressValue(self, value: int, maximum: int):
        self.ui.progressBar.setValue(value)
        self.ui.progressBar.setMaximum(maximum)

    def setProgressMessage(self, message: str):
        self.ui.statusLabel.setText(message)

    def connectProcess(self, process: QProcess):
        # Forget any existing process
        self.disconnectProcess()

        self.trackedProcess = process
        self.sentSigterm = False

        commandLine = shlex.join([process.program()] + process.arguments())
        self.ui.commandLabel.setText(commandLine)

        gitVerbMatch = re.search(r"git(?=\s).*?\s+(\w\S*)", commandLine)
        if gitVerbMatch:
            title = "git " + gitVerbMatch.group(1) + "…"
        else:
            title = process.program()

        self.ui.titleLabel.setText(title)
        self.initProgress(_("Please wait…"))
        self.setProgressValue(0, 0)

        assert self.abortButton is not None, "abort button not connected"
        self.abortButton.setText(_("Abort"))
        self.abortButton.setIcon(stockIcon("SP_DialogCloseButton"))
        self.abortButton.clearFocus()

        process.errorOccurred.connect(self.onProcessFinished)
        process.finished.connect(self.onProcessFinished)

        if isinstance(process, GitDriver):
            process.progressMessage.connect(self.setProgressMessage)
            process.progressFraction.connect(self.setProgressValue)

    def disconnectProcess(self):
        process = self.trackedProcess
        if not process:
            return

        self.trackedProcess = None

        process.errorOccurred.disconnect(self.onProcessFinished)
        process.finished.disconnect(self.onProcessFinished)

        if isinstance(process, GitDriver):
            with suppress(TypeError, RuntimeError):
                process.progressMessage.disconnect(self.setProgressMessage)
            with suppress(TypeError, RuntimeError):
                process.progressFraction.disconnect(self.setProgressValue)

        assert self.abortButton is not None, "abort button not connected"
        self.abortButton.setText(self.abortButtonDefaultText)
        self.abortButton.setIcon(self.abortButtonDefaultIcon)

    def requestAbort(self):
        self.setProgressMessage(_("Aborting…"))
        self.setProgressValue(0, 0)

        if self.abortButton is not None and not self.sentSigterm:
            self.abortButton.setText("SIGKILL")
            self.abortButton.setIcon(stockIcon("sigkill"))

        if self.trackedProcess:
            if not self.sentSigterm:
                self.trackedProcess.terminate()
                self.sentSigterm = True
                self.ui.titleLabel.setText(_("SIGTERM sent. Waiting for process to terminate…"))
            else:
                self.trackedProcess.kill()

    def onProcessFinished(self):
        self.disconnectProcess()
