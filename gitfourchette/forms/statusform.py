# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import re
import shlex
from contextlib import suppress

from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.forms.ui_statusform import Ui_StatusForm
from gitfourchette.gitdriver import GitDriver
from gitfourchette.localization import _
from gitfourchette.qt import *
from gitfourchette.toolbox import stockIcon, tweakWidgetFont, QProcessConnection

logger = logging.getLogger(__name__)

# Capture the verb in a git command, e.g. "cherry-pick" in:
#       git cherry-pick
#       git cherry-pick args
#       /usr/bin/git cherry-pick
#       git --option cherry-pick
#       git -c config.item cherry-pick
#       'c:\program files\git.EXE' cherry-pick
_gitVerbPattern = re.compile(r"git(?:\.exe|\.EXE)?['\"]?(?=\s).*?\s([a-z][a-z\-]*)(?=$|\s)")


class StatusForm(QWidget):
    def __init__(self, parent):
        super().__init__(parent)

        self.processConnection = QProcessConnection(self)
        self.processConnection.processLost.connect(self.onProcessLost)

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
        self.processConnection.track(process)
        self.sentSigterm = False

        commandLine = shlex.join([process.program()] + process.arguments())
        self.ui.commandLabel.setText(commandLine)

        gitVerbMatch = _gitVerbPattern.search(commandLine)
        if gitVerbMatch:
            title = f"git {gitVerbMatch.group(1)}…"
        else:
            title = f"{process.program()}…"

        self.ui.titleLabel.setText(title)
        self.initProgress(_("Please wait…"))
        self.setProgressValue(0, 0)

        assert self.abortButton is not None, "abort button not connected"
        self.abortButton.setText(_("Abort"))
        self.abortButton.setIcon(stockIcon("SP_DialogCloseButton"))
        self.abortButton.clearFocus()

        if isinstance(process, GitDriver):
            process.progressMessage.connect(self.setProgressMessage)
            process.progressFraction.connect(self.setProgressValue)

    def onProcessLost(self):
        process = self.processConnection.process
        assert process is not None
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

        process = self.processConnection.process
        if not process:
            return
        elif not self.sentSigterm:
            ToolCommands.terminatePlus(process)
            self.sentSigterm = True
            self.ui.titleLabel.setText(_("SIGTERM sent. Waiting for process to terminate…"))
        else:
            process.kill()
