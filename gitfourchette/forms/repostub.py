# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import os.path

from gitfourchette import settings
from gitfourchette.forms.ui_repostub import Ui_RepoStub
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.qt import *
from gitfourchette.toolbox import *

_logger = logging.getLogger(__name__)


class RepoStub(QWidget):
    """
    Placeholder for RepoWidget shown when RepoModel isn't ready.
    """

    # Signals for cross-thread control from PrimeRepo task
    progressRange = Signal(int, int)
    progressValue = Signal(int)
    progressMessage = Signal(str)
    progressAbortable = Signal(bool)

    def __init__(self, parent=None, workdir="", locator=NavLocator.Empty, maxCommits=-1):
        super().__init__(parent)

        from gitfourchette.tasks import RepoTaskRunner

        self.workdir = os.path.normpath(workdir)
        self.locator = locator
        self.maxCommits = maxCommits
        self.didAbort = False
        self.didClose = False

        self.ui = Ui_RepoStub()
        self.ui.setupUi(self)
        self.setObjectName(f"{self.__class__.__name__}({self.getTitle()})")  # override setupUi's name
        self.setWindowTitle(self.getTitle())

        # Connect buttons
        self.ui.promptLoadButton.clicked.connect(self.loadNow)
        self.ui.progressAbortButton.clicked.connect(self.onAbortButtonClicked)

        self.progressRange.connect(self.ui.progressBar.setRange)
        self.progressValue.connect(self.ui.progressBar.setValue)
        self.progressMessage.connect(self.ui.progressLabel.setText)
        self.progressAbortable.connect(self.onChangeProgressInterruptable)
        self.ui.progressPage.setCursor(Qt.CursorShape.BusyCursor)

        tweakWidgetFont(self.ui.promptNameLabel, bold=True)
        self.ui.promptNameLabel.setText(tquo(self.getTitle()))
        self.ui.promptIcon.setPixmap(stockIcon("image-missing").pixmap(96))
        self.ui.progressAbortButton.setIcon(stockIcon("SP_BrowserStop"))

        # Initialize labels, etc.
        self.resetUi()

        # We need a task runner to run the initialization task (PrimeRepo).
        self.taskRunner = RepoTaskRunner(parent=self)
        self.taskRunner.setObjectName(f"RepoTaskRunner(STUB: {self.getTitle()})")

    def close(self):
        self.didAbort = True
        self.didClose = True
        if self.taskRunner.isBusy():
            _logger.info("Interrupting ongoing PrimeRepo task because RepoStub was force closed!")
            self.taskRunner.killCurrentTask()
            self.taskRunner.joinZombieTask()
        super().close()

    def resetUi(self):
        self.didAbort = False
        self.ui.retranslateUi(self)
        self.ui.promptIcon.setText("")
        self.ui.promptIcon.setVisible(False)
        self.ui.progressLabel.setText(_("Opening {0}…", tquo(self.getTitle())))
        self.ui.stackedWidget.setCurrentWidget(self.ui.progressPage)
        self.ui.progressBar.setRange(0, 0)
        self.ui.progressBar.setValue(0)
        self.ui.progressAbortButton.setEnabled(True)

    def disableAutoLoad(self, message=""):
        self.ui.stackedWidget.setCurrentWidget(self.ui.promptPage)

        if message:
            self.ui.promptReadyLabel.setText(message)
            self.ui.promptIcon.setVisible(True)
            self.ui.promptLoadButton.setText(_("Try to reload"))

    def willAutoLoad(self):
        return self.ui.stackedWidget.currentWidget() is self.ui.progressPage

    def onAbortButtonClicked(self):
        self.didAbort = True
        self.ui.progressLabel.setText(_("Loading interrupted. Just a moment…"))
        self.ui.progressAbortButton.setEnabled(False)

    def onChangeProgressInterruptable(self, abortable: True):
        self.ui.progressAbortButton.setEnabled(abortable and self.didAbort)

    def overridePendingLocator(self, locator: NavLocator):
        self.locator = locator

    def getTitle(self):
        return settings.history.getRepoTabName(self.workdir)

    def superproject(self):
        return settings.history.getRepoSuperproject(self.workdir)

    def isPriming(self):
        from gitfourchette.tasks.loadtasks import PrimeRepo
        task = self.taskRunner.currentTask
        priming = isinstance(task, PrimeRepo)
        assert not task or priming
        return priming

    def loadNow(self):
        assert not self.isPriming(), "attempting to load RepoStub twice"
        from gitfourchette.tasks.loadtasks import PrimeRepo
        primeTask = PrimeRepo(self.taskRunner)
        self.resetUi()
        self.taskRunner.put(primeTask, repoStub=self)
