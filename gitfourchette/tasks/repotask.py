# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import enum
import logging
import re
import shlex
import warnings
from collections.abc import Generator
from typing import Any, TYPE_CHECKING, Literal, TypeVar

from gitfourchette.forms.askpassdialog import AskpassDialog
from gitfourchette.gitdriver import GitDriver
from gitfourchette.manualgc import gcHint
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import ConflictError, GitError, MultiFileError, Repo, RepositoryState
from gitfourchette.qt import *
from gitfourchette.repomodel import RepoModel
from gitfourchette.toolbox import *

if TYPE_CHECKING:
    from gitfourchette.repowidget import RepoWidget

_lineEndingReplacementPattern = re.compile("(LF|CRLF) would be replaced by (LF|CRLF) in '.+'")

logger = logging.getLogger(__name__)


def showConflictErrorMessage(parent: QWidget, exc: ConflictError, opName="Operation"):
    numConflicts = len(exc.conflicts)

    title = _n("Conflicting file", "{n} conflicting files", numConflicts)
    nFilesText = _np("operation conflicts with…", "a file", "{n} files", numConflicts)
    nFilesText = f"<b>{nFilesText}</b>"

    if exc.description == "workdir":
        message = _("Operation {op} conflicts with {files} in the working directory:")
    elif exc.description == "HEAD":
        message = _("Operation {op} conflicts with {files} in the commit at HEAD:")
    else:
        message = _("Operation {op} has caused a conflict with {files} ({exc}):")
    message = message.format(op=bquo(opName), files=nFilesText, exc=exc.description)

    qmb = showWarning(parent, title, message)
    addULToMessageBox(qmb, exc.conflicts)

    if exc.description == "workdir":
        dt = qmb.detailedText()
        dt += _("Before you try again, you should either commit, stash, or discard your changes.")
        qmb.setDetailedText(dt)


def showMultiFileErrorMessage(parent: QWidget, exc: MultiFileError, opName="Operation"):
    details = []

    if exc.message:
        message = exc.message
    else:
        message = _n("Operation {op} ran into an issue with {n} file.",
                     "Operation {op} ran into issues with {n} files.",
                     n=len(exc.file_exceptions), op=hquo(opName))
        if exc.file_successes > 0:
            message += " " + _n("({n} other file was successful.)",
                                "({n} other files were successful.)", n=exc.file_successes)

    for path, error in exc.file_exceptions.items():
        if not error:
            details.append(escape(path))
            continue

        m = ""

        # Reword some libgit2 messages
        if type(error) is GitError:
            lineEndings = _lineEndingReplacementPattern.match(str(error))
            if lineEndings:
                m = _("This file contains {a} line endings. "
                      "They will not be replaced by {b} because {opt} is enabled.",
                      a=lineEndings.group(1), b=lineEndings.group(2), opt=hquo("core.safecrlf"))

        if not m:
            m = escape(str(error))

        details.append(f"<b>{escape(path)}</b>: {m}")

    qmb = asyncMessageBox(parent, 'warning', opName, message)
    addULToMessageBox(qmb, details)
    qmb.show()


class TaskPrereqs(enum.IntFlag):
    Nothing = 0
    NoUnborn = enum.auto()
    NoDetached = enum.auto()
    NoConflicts = enum.auto()
    NoCherrypick = enum.auto()
    NoStagedChanges = enum.auto()


class TaskEffects(enum.IntFlag):
    """
    Flags indicating which parts of the UI to refresh
    after a task runs to completion.
    """

    Nothing = 0
    "The task doesn't modify the repository."

    Workdir = enum.auto()
    "The task affects indexed and/or unstaged changes."

    Refs = enum.auto()
    "The task affects branches (local or remote), stashes, or tags."

    Remotes = enum.auto()
    "The task affects remotes registered with this repository."

    Head = enum.auto()
    "The task moves HEAD to a different commit."

    Upstreams = enum.auto()
    "The task affects the upstream of a local branch."

    DefaultRefresh = Workdir | Refs | Remotes | Upstreams
    "Default flags for RefreshRepo"
    # Index is included so the banner can warn about conflicts
    # regardless of what part of the repo is being viewed.


class FlowControlToken:
    """
    Object that can be yielded from `RepoTask.flow()` to control the flow of the coroutine.
    """

    class Kind(enum.IntEnum):
        ContinueOnUiThread = enum.auto()
        ContinueOnWorkThread = enum.auto()
        WaitUserReady = enum.auto()
        WaitProcessReady = enum.auto()
        InterruptedByException = enum.auto()

    flowControl: Kind
    exception: Exception | None

    def __init__(self, flowControl: Kind = Kind.ContinueOnUiThread, exception=None):
        self.flowControl = flowControl
        self.exception = exception

    def __str__(self):
        return F"FlowControlToken({self.flowControl.name})"


class FlowWorkerThread(QThread):
    tokenReady = Signal(FlowControlToken)

    flow: RepoTask.FlowGeneratorType | None

    @calledFromQThread  # enable code coverage in task threads
    def run(self):
        assert self.flow is not None, "flow not set"
        token = RepoTaskRunner._getNextToken(self.flow)
        self.flow = None
        self.tokenReady.emit(token)


class AbortTask(Exception):
    """ To bail from a coroutine early, we must raise an exception to ensure that
    any active context managers exit deterministically."""
    def __init__(
            self,
            text: str = "",
            icon: MessageBoxIconName = "warning",
            asStatusMessage: bool = False,
            details: str = ""
    ):
        super().__init__(text)
        self.icon = icon
        self.asStatusMessage = asStatusMessage
        self.details = details


class RepoGoneError(FileNotFoundError):
    pass


class RepoTask(QObject):
    """
    Task that manipulates a repository.
    """

    FlowGeneratorType = Generator[FlowControlToken, None, Any]

    uiReady = Signal()

    repo: Repo

    repoModel: RepoModel

    jumpTo: NavLocator
    """ Jump to this location when this task completes. """

    effects: TaskEffects
    """ Which parts of the UI should be refreshed when this task completes. """

    _currentProcess: QProcess | None
    """ External process that this task is currently waiting on (via flowStartProcess).
    This is only valid in the root task in the stack (non-root tasks are allowed
    to set the root task's current process). """

    _postStatus: str
    """ Display this message in the status bar after completion (user code should use the getter/setter). """

    _postStatusLocked: bool
    """ Subtasks can override postStatus as long as this flag is unset.
    This flag is set when user code sets postStatus manually (via the setter). """

    _currentFlow: FlowGeneratorType | None
    _currentIteration: int

    _taskStack: list[RepoTask]
    """Stack of active tasks in the chain of flowSubtask calls, including the root task at index 0.
    The reference to the list object is shared by all tasks in the same flowSubtask chain."""

    @classmethod
    def name(cls) -> str:
        from gitfourchette.tasks.taskbook import TaskBook
        return TaskBook.names.get(cls, cls.__name__)

    @classmethod
    def invoke(cls, invoker: QObject, *args, **kwargs):
        call = TaskInvocation(invoker, cls, *args, **kwargs)
        TaskInvocation.invokeSignal.emit(call)

    def __init__(self, parent: QObject):
        super().__init__(parent)
        self.repo = None
        self.repoModel = None
        self._currentFlow = None
        self._currentIteration = 0
        self.setObjectName(self.__class__.__name__)
        self.jumpTo = NavLocator()
        self.effects = TaskEffects.Nothing
        self._currentProcess = None
        self._postStatus = ""
        self._postStatusLocked = False
        self._taskStack = [self]
        self._runningOnUiThread = True  # for debugging

    @property
    def rootTask(self) -> RepoTask:
        assert self._taskStack
        return self._taskStack[0]

    @property
    def isRootTask(self) -> bool:
        return self.rootTask is self

    @property
    def currentProcess(self) -> QProcess | None:
        return self.rootTask._currentProcess

    def parentWidget(self) -> QWidget:
        return findParentWidget(self)

    @property
    def rw(self) -> RepoWidget:  # hack for now - assume parent is a RepoWidget
        parentWidget = self.parentWidget()
        if APP_DEBUG:
            from gitfourchette.repowidget import RepoWidget
            assert isinstance(parentWidget, RepoWidget)
        return parentWidget

    def setRepoModel(self, repoModel: RepoModel):
        self.repoModel = repoModel
        self.repo = repoModel.repo

    def __str__(self):
        return self.objectName()

    def canKill(self, task: RepoTask) -> bool:
        """
        Meant to be overridden by your task.
        Return true if this task is allowed to take precedence over the given running task.
        The default implementation will not attempt to kill any other tasks.
        """
        return False

    def broadcastProcesses(self) -> bool:
        """
        Meant to be overridden by your task.
        Returns whether this task should emit the `processStarted` signal when
        `flowStartProcess` starts a process. This enables automatic progress
        reporting via ProcessDialog.
        """
        return True

    def _isRunningOnAppThread(self):
        return onAppThread() and self._runningOnUiThread

    @classmethod
    def makeInternalLink(cls, **kwargs):
        return makeInternalLink("exec", urlPath=cls.__name__, urlFragment="", **kwargs)

    @property
    def postStatus(self):
        """ Display this message in the status bar after completion. """
        return self._postStatus

    @postStatus.setter
    def postStatus(self, value):
        self._postStatus = value
        self._postStatusLocked = True

    def flow(self, *args, **kwargs) -> FlowGeneratorType:
        """
        Generator that performs the task. You can think of this as a coroutine.

        You can control the flow of the coroutine by yielding a `FlowControlToken` object.
        This lets you wait for you user input via dialog boxes, abort the task, or move long
        computations to a separate thread.

        It is recommended to `yield from` one of the `flowXXX` methods instead of instantiating
        a FlowControlToken directly. For example::

            meaning = QInputDialog.getInt(self.parentWidget(), "Hello",
                                          "What's the meaning of life?")
            yield from self.flowEnterWorkerThread()
            expensiveComputationCorrect = meaning == 42
            yield from self.flowEnterUiThread()
            if not expensiveComputationCorrect:
                raise AbortTask("Sorry, computer says no.")

        The coroutine always starts on the UI thread.
        """
        # Dummy yield to make it a generator. You should override this function anyway!
        yield from self.flowEnterUiThread()

    def cleanup(self):
        """
        Clean up any resources used by the task on completion or failure.
        Meant to be overridden by your task.
        Called from UI thread.
        """
        assert onAppThread()

    def onError(self, exc: Exception):
        """
        Report an error to the user if flow() was interrupted by an exception.
        Can be overridden by your task, but you should call super().onError() if you can't handle the exception.
        Called from the UI thread, after cleanup().
        """
        if isinstance(exc, AbortTask):
            pass
        elif isinstance(exc, ConflictError):
            showConflictErrorMessage(self.parentWidget(), exc, self.name())
        elif isinstance(exc, MultiFileError):
            showMultiFileErrorMessage(self.parentWidget(), exc, self.name())
        else:
            message = _("Operation failed: {0}.", escape(self.name()))
            excMessageBox(exc, title=self.name(), message=message, parent=self.parentWidget())

    def prereqs(self) -> TaskPrereqs:
        """
        Can be overridden by your task.
        """
        return TaskPrereqs.Nothing

    def onGitProgressMessage(self, message: str):
        """
        Can be overridden by your task.
        """
        pass

    def onGitProgressFraction(self, num: int, denom: int):
        """
        Can be overridden by your task.
        """
        pass

    def flowEnterWorkerThread(self):
        """
        Move the task to a non-UI thread.
        (Note that the flow always starts on the UI thread.)

        This function is intended to be called by flow() with "yield from".
        """
        assert self._currentFlow is not None
        self._runningOnUiThread = False
        yield FlowControlToken(FlowControlToken.Kind.ContinueOnWorkThread)

    def flowEnterUiThread(self):
        """
        Move the task to the UI thread.
        (Note that the flow always starts on the UI thread.)

        This function is intended to be called by flow() with "yield from".
        """
        assert self._currentFlow is not None
        self._runningOnUiThread = True
        yield FlowControlToken(FlowControlToken.Kind.ContinueOnUiThread)

    def flowSubtask(self, subtaskClass: type[RepoTaskSubtype], *args, **kwargs
                    ) -> Generator[FlowControlToken, None, RepoTaskSubtype]:
        """
        Run a subtask's flow() method as if it were part of this task.
        Note that if the subtask raises an exception, the root task's flow will be stopped as well.
        You must be on the UI thread before starting a subtask.

        This function is intended to be called by flow() with "yield from".
        """

        assert self._currentFlow is not None
        assert self._isRunningOnAppThread(), "Subtask must be started start on UI thread"

        # To ensure correct deletion of the subtask when we get deleted, we are the subtask's parent
        subtask = subtaskClass(self)
        subtask.setRepoModel(self.repoModel)
        subtask.setObjectName(f"{self.objectName()}:{subtask.objectName()}")
        # logger.debug(f"Subtask {subtask}")

        # Push subtask onto stack
        subtask._taskStack = self._taskStack  # share reference to task stack
        self._taskStack.append(subtask)

        # Get flow generator from subtask
        subtask._currentFlow = subtask.flow(*args, **kwargs)
        assert isinstance(subtask._currentFlow, Generator), "flow() must contain at least one yield statement"

        # Forward coroutine continuation signal
        subtask.uiReady.connect(self.uiReady)

        # Actually perform the subtask
        yield from subtask._currentFlow

        # Make sure we're back on the UI thread before re-entering the root task
        if not self._isRunningOnAppThread():
            yield FlowControlToken(FlowControlToken.Kind.ContinueOnUiThread)

        # Pop subtask off stack
        rc = self._popSubtask()
        assert rc is subtask

        return subtask

    def _popSubtask(self) -> RepoTask:
        assert self._taskStack, "task stack is already empty!"
        assert onAppThread()

        # Pop last subtask off stack
        subtask = self._taskStack.pop()

        # Percolate effect bits to caller task
        self.effects |= subtask.effects

        # Percolate postStatus to caller task if it's not manually overridden
        if not self._postStatusLocked and subtask.postStatus:
            self._postStatus = subtask.postStatus

        # Percolate jumpTo to caller task
        if not self.jumpTo:
            self.jumpTo = subtask.jumpTo
        elif subtask.jumpTo and subtask.jumpTo != self.jumpTo:
            warnings.warn(f"Subtask {subtask}: Ignoring subtask jumpTo")

        # Clean up subtask (on UI thread)
        subtask.cleanup()

        return subtask

    def flowRequestForegroundUi(self):
        """
        Pause the coroutine until the RepoWidget is the foreground tab.

        This function is intended to be called by flow() with "yield from".
        """
        assert self._currentFlow is not None
        assert self._isRunningOnAppThread()

        parentWidget = self.parentWidget()
        if parentWidget.isVisible():
            return

        token = FlowControlToken(FlowControlToken.Kind.WaitUserReady)
        parentWidget.becameVisible.connect(self.uiReady)
        yield token
        parentWidget.becameVisible.disconnect(self.uiReady)

    def flowStartProcess(self, process: QProcess, autoFail=True) -> Generator[FlowControlToken, None, None]:
        assert self._isRunningOnAppThread(), "start processes from UI thread"
        assert self.currentProcess is None, "a process is already running in this task"

        pe, se = process.processEnvironment(), QProcessEnvironment.systemEnvironment()
        envStrs = [f"{key}={pe.value(key)}" for key in pe.keys() if pe.value(key) != se.value(key)]

        commandLine = shlex.join(envStrs + [process.program()] + process.arguments())
        simpleCommandLine = shlex.join([process.program()] + process.arguments())
        logger.info(f"Starting process (from {process.workingDirectory()}): {commandLine}")

        self.rootTask._currentProcess = process

        def onProcessError():
            nonlocal processError
            processError = True
        processError = False

        # Intercept errorOccurred before the process starts so that we can
        # report that the command was not found. Disconnect errorOccurred as
        # soon as the program has started so that sending SIGTERM manually
        # won't cause a "ProcessCrashed" message box.
        process.errorOccurred.connect(onProcessError)
        process.started.connect(lambda: process.errorOccurred.disconnect(onProcessError))

        # Continue the coroutine when the process is ready.
        process.finished.connect(self.uiReady)

        # Start the process.
        process.start()

        # The process is supposed to be Starting or Running by now.
        if process.state() != QProcess.ProcessState.NotRunning:
            # Pause the coroutine until the process is ready.
            process.errorOccurred.connect(self.uiReady)
            waitToken = FlowControlToken(FlowControlToken.Kind.WaitProcessReady)
            yield waitToken
        else:
            # If it's NotRunning immediately after start(), that means the process
            # couldn't be started for some reason (e.g. working directory missing).
            # The errorOccurred signal should have called onProcessError.
            pass

        self.rootTask._currentProcess = None

        if processError:
            message = _("Process failed to start ({0}).", process.error())
            message += f"<p style='font-size: small'><code>{escape(commandLine)}</code><br>"
            raise AbortTask(message)

        if autoFail and process.exitCode() != 0:
            if isinstance(process, GitDriver):
                stderr = process.stderrScrollback()
                message = _("Git command exited with code {0}.", process.exitCode())
            else:
                stderr = process.readAllStandardError().data().decode(errors="replace")
                message = _("Process {0} exited with code {1}.", escape(process.program()), process.exitCode())
            message += f"<p style='font-size: small'>{escape(simpleCommandLine)}</p>"
            if stderr.strip():
                message += f"<p style='white-space: pre-wrap'>{escape(stderr)}</p>"
            raise AbortTask(message, details=commandLine)

    def flowCallGit(
            self,
            *args: str,
            remote="",
            customKey="",
            workdir="",
            env: dict[str, str] | None = None,
            autoFail=True,
    ) -> Generator[FlowControlToken, None, GitDriver]:
        from gitfourchette import settings
        from gitfourchette.application import GFApplication
        from gitfourchette.exttools.toolcommands import ToolCommands
        from gitfourchette.repoprefs import RepoPrefs
        from gitfourchette.porcelain import GitConfigHelper

        repo = self.repo

        if not workdir:
            workdir = repo.workdir if repo is not None else ""

        env = env or {}
        sshOptions = []
        gitProgram = shlex.split(settings.prefs.gitPath, posix=True)

        env["LC_ALL"] = "C.UTF-8"  # force Git output in English

        # SSH_ASKPASS
        if settings.prefs.ownAskpass:
            env |= AskpassDialog.environmentForChildProcess()

        # Use internal ssh-agent
        if settings.prefs.ownSshAgent:
            sshAgent = GFApplication.instance().sshAgent
            if sshAgent:
                env |= sshAgent.environment()
                sshOptions += ["-o", "AddKeysToAgent=yes"]

        # Custom remote key file
        if remote:
            assert repo is not None
            assert not customKey
            customKey = RepoPrefs.getRemoteKeyFileForRepo(repo, remote)

        if customKey:
            sshOptions += ["-i", customKey]

        # Apply any custom OpenSSH options
        if sshOptions:
            # Get original ssh command
            if repo is not None:
                sshCommand = repo.get_config_value("core.sshCommand")
            else:
                sshCommand = GitConfigHelper.get_default_value("core.sshCommand")
            sshCommand = sshCommand or "/usr/bin/ssh"
            # Add custom options and join back into a string
            sshCommandTokens = shlex.split(sshCommand, posix=True) + sshOptions
            sshCommand = shlex.join(sshCommandTokens)
            # Pass to git (note: it's also possible to pass '-c core.sshCommand={sshCommand}')
            env["GIT_SSH_COMMAND"] = sshCommand

        tokens = gitProgram + list(args)

        if FLATPAK:
            tokens = ToolCommands.wrapFlatpakSpawn(tokens, workdir, detached=False, environment=env)

        process = GitDriver(self.parentWidget())
        process.setProgram(tokens[0])
        process.setArguments(tokens[1:])
        if workdir:
            process.setWorkingDirectory(workdir)

        # Forward custom environment variables
        processEnvironment = QProcessEnvironment.systemEnvironment()
        if env:
            for k, v in env.items():
                processEnvironment.insert(k, v)
        process.setProcessEnvironment(processEnvironment)

        process.progressMessage.connect(self.onGitProgressMessage)
        process.progressFraction.connect(self.onGitProgressFraction)
        yield from self.flowStartProcess(process, autoFail=autoFail)
        return process

    def flowDialog(self, dialog: QDialog, abortTaskIfRejected=True, proceedSignal=None):
        """
        Show a QDialog, then pause the coroutine until it's accepted or rejected.

        If abortTaskIfRejected is True, rejecting the dialog causes the task
        to be aborted altogether.

        This function is intended to be called by flow() with "yield from".
        """

        assert self._currentFlow is not None
        assert self._isRunningOnAppThread()  # we'll touch the UI

        yield from self.flowRequestForegroundUi()

        waitToken = FlowControlToken(FlowControlToken.Kind.WaitUserReady)
        didReject = False

        def onReject():
            nonlocal didReject
            didReject = True

        dialog.rejected.connect(onReject)
        dialog.finished.connect(self.uiReady)
        if proceedSignal:
            proceedSignal.connect(self.uiReady)

        dialog.show()
        installDialogReturnShortcut(dialog)

        yield waitToken

        dialog.rejected.disconnect(onReject)
        dialog.finished.disconnect(self.uiReady)
        if proceedSignal:
            proceedSignal.disconnect(self.uiReady)

        if abortTaskIfRejected and didReject:
            dialog.deleteLater()
            raise AbortTask("")

    def flowConfirm(
            self,
            title: str = "",
            text: str = "",
            buttonIcon: str = "",
            verb: str = "",
            cancelText: str = "",
            helpText: str = "",
            detailList: list[str] | None = None,
            dontShowAgainKey: str = "",
            canCancel: bool = True,
            icon: MessageBoxIconName | Literal[""] = "",
            checkbox: QCheckBox | None = None,
            actionButton: QPushButton | None = None,
    ):
        """
        Ask the user to confirm the operation via a message box.
        Interrupts flow() if the user denies.

        This function is intended to be called by flow() with "yield from".
        """

        assert self._currentFlow is not None
        assert self._isRunningOnAppThread()  # we'll touch the UI

        if dontShowAgainKey:
            from gitfourchette import settings
            if dontShowAgainKey in settings.prefs.dontShowAgain:
                logger.debug(f"Skipping dontShowAgainMessage: {text}")
                return

        if not title:
            title = self.name()

        if not verb and canCancel:
            verb = title

        buttonMask = QMessageBox.StandardButton.Ok
        if canCancel:
            icon = icon or "question"
            buttonMask |= QMessageBox.StandardButton.Cancel
        else:
            icon = icon or "information"

        qmb = asyncMessageBox(self.parentWidget(), icon, title, text, buttonMask)

        dontShowAgainCheckBox = None
        if dontShowAgainKey:
            assert not checkbox
            dontShowAgainPrompt = _("Don’t ask me to confirm this again") if canCancel else _("Don’t show this again")
            dontShowAgainCheckBox = QCheckBox(dontShowAgainPrompt, qmb)
            tweakWidgetFont(dontShowAgainCheckBox, 80)
            qmb.setCheckBox(dontShowAgainCheckBox)
        elif checkbox:
            qmb.setCheckBox(checkbox)

        # Using QMessageBox.StandardButton.Ok instead of QMessageBox.StandardButton.Discard
        # so it connects to the "accepted" signal.
        yes: QAbstractButton = qmb.button(QMessageBox.StandardButton.Ok)
        if buttonIcon:
            yes.setIcon(stockIcon(buttonIcon))
        if verb:
            yes.setText(verb)

        if cancelText:
            assert canCancel, "don't set cancelText when canCancel is False!"
            qmb.button(QMessageBox.StandardButton.Cancel).setText(cancelText)

        if actionButton:
            qmb.addButton(actionButton, QMessageBox.ButtonRole.ApplyRole)

        if helpText:
            hintButton = QHintButton(qmb, helpText)
            hintButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            hintButton.setAutoRaise(False)
            qmb.addButton(hintButton, QMessageBox.ButtonRole.HelpRole)
            hintButton.clicked.disconnect()  # Qt internally wires the button to close the dialog; undo that.
            hintButton.connectClicked()

        if detailList:
            addULToMessageBox(qmb, detailList)

        qmb.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        yield from self.flowDialog(qmb)

        if dontShowAgainKey and dontShowAgainCheckBox.isChecked():
            from gitfourchette import settings
            settings.prefs.dontShowAgain.append(dontShowAgainKey)
            settings.prefs.setDirty()

        return qmb.result()

    def checkPrereqs(self, prereqs=TaskPrereqs.Nothing):
        if prereqs == TaskPrereqs.Nothing:
            prereqs = self.prereqs()
        repo = self.repo

        if TaskPrereqs.NoConflicts in prereqs and repo.any_conflicts:
            raise AbortTask(_("Fix merge conflicts before performing this action."))

        if TaskPrereqs.NoUnborn in prereqs and repo.head_is_unborn:
            raise AbortTask(paragraphs(
                _("There are no commits in this repository yet."),
                _("Create the initial commit in this repository before performing this action.")))

        if TaskPrereqs.NoDetached in prereqs and repo.head_is_detached:
            raise AbortTask(paragraphs(
                _("You are in “detached HEAD” state."),
                _("Please switch to a local branch before performing this action.")))

        if TaskPrereqs.NoCherrypick in prereqs and repo.state() == RepositoryState.CHERRYPICK:
            raise AbortTask(paragraphs(
                _("You are in the middle of a cherry-pick."),
                _("Before performing this action, conclude the cherry-pick.")))

        if TaskPrereqs.NoStagedChanges in prereqs and repo.any_staged_changes:
            raise AbortTask(paragraphs(
                _("You have staged changes."),
                _("Before performing this action, commit your changes or stash them.")))


class RepoTaskRunner(QObject):
    ForceSerial = APP_NOTHREADS
    """
    Force tasks to run synchronously on the UI thread.
    Useful for debugging.
    Can be forced with command-line switch "--no-threads".
    """

    postTask = Signal(RepoTask)
    progress = Signal(str, bool)
    repoGone = Signal()
    ready = Signal()
    requestAttention = Signal()
    processStarted = Signal(QProcess, str)
    _aboutToProcessToken = Signal()

    _continueFlow = Signal(FlowControlToken)
    "Emitted from worker thread, connected to _iterateFlow."

    _workerThread: FlowWorkerThread

    _currentTask: RepoTask | None
    "Task that is currently running"

    _zombieTask: RepoTask | None
    "Task that is being interrupted"

    _currentTaskBenchmark: Benchmark
    "Context manager"

    def __init__(self, parent: QObject):
        super().__init__(parent)
        self.setObjectName("RepoTaskRunner")
        self._currentTask = None
        self._zombieTask = None
        self._currentTaskBenchmark = Benchmark("???")
        self.repoModel = None

        self._workerThread = FlowWorkerThread(self)
        self._workerThread.flow = None
        self._workerThread.tokenReady.connect(self._continueFlow)

    @property
    def currentTask(self):
        return self._currentTask

    def isBusy(self):
        return self._currentTask is not None or self._zombieTask is not None or self._workerThread.isRunning()

    def killCurrentTask(self):
        """
        Interrupt current task next time it yields a FlowControlToken.

        The task will not die immediately; use joinZombieTask() after killing
        the task to block the current thread until the task runner is empty.
        """
        if not self._currentTask:
            # Nothing to kill.
            return

        if not self._zombieTask:
            # Move the currently-running task to zombie mode.
            # It'll get deleted next time it yields a FlowControlToken.
            self._zombieTask = self._currentTask
        else:
            # There's already a zombie. This means that the current task hasn't
            # started yet - it's waiting on the zombie to die.
            # Just overwrite the current task, but let the zombie die cleanly.
            assert self._currentTask._currentIteration == 0, "_currentTask isn't supposed to have started yet!"
            self._currentTask.deleteLater()

        self._currentTask = None

    def joinZombieTask(self):
        """Block UI thread until the current zombie task is dead.
        Returns immediately if there's no zombie task."""

        assert onAppThread()
        while self._zombieTask:
            QThread.yieldCurrentThread()
            QThread.msleep(30)
            flags = QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
            flags |= QEventLoop.ProcessEventsFlag.WaitForMoreEvents
            QApplication.processEvents(flags, 30)
        self.joinWorkerThread()
        assert not self.isBusy()

    def joinWorkerThread(self):
        assert onAppThread()
        if self._workerThread.isRunning():
            self._workerThread.wait()
        assert not self._workerThread.isRunning()
        assert not self._workerThread.flow

    def blockUntilNextToken(self):
        block = QEventLoop()
        self._aboutToProcessToken.connect(block.quit)
        block.exec()

    def put(self, call: TaskInvocation):
        assert onAppThread()

        task = call.taskClass(self)
        if self.repoModel:
            task.setRepoModel(self.repoModel)

        # Get flow generator
        task._currentFlow = task.flow(*call.taskArgs, **call.taskKwargs)
        assert isinstance(task._currentFlow, Generator), "flow() must contain at least one yield statement"

        if not self._currentTask:
            self._currentTask = task
            self._startTask(task)

        elif task.canKill(self._currentTask):
            logger.info(f"Task {task} killed task {self._currentTask}")
            self.killCurrentTask()
            self._currentTask = task

        else:
            logger.info(f"Task {task} cannot kill task {self._currentTask}")
            message = _("Please wait for the current operation to complete ({0}).", hquo(self._currentTask.name()))
            showInformation(task.parentWidget(), _("Operation in progress"), "<html>" + message)

    def _startTask(self, task: RepoTask):
        assert self._currentTask == task
        assert task._currentFlow
        assert task.isRootTask

        logger.debug(f">>> {task}")

        self._currentTaskBenchmark.name = str(task)
        self._currentTaskBenchmark.__enter__()

        # Prepare internal signal for coroutine continuation
        self._continueFlow.connect(lambda result: self._iterateFlow(task, result))
        task.uiReady.connect(lambda: self._iterateFlow(task, FlowControlToken()))

        # Check task prerequisites
        try:
            task.checkPrereqs()
        except AbortTask as abort:
            self.reportAbortTask(task, abort)
            self._releaseTask(task)
            return

        # Prime the flow (i.e. start coroutine)
        self._iterateFlow(task, FlowControlToken())

    def _iterateFlow(self, task: RepoTask, token: FlowControlToken):
        while True:
            self._aboutToProcessToken.emit()

            assert onAppThread()
            task._currentIteration += 1

            # Let worker thread wrap up
            self.joinWorkerThread()

            assert not isinstance(token, Generator), \
                "You're trying to yield a nested generator. Did you mean 'yield from'?"
            assert isinstance(token, FlowControlToken), (
                f"In a RepoTask coroutine, you can only yield FlowControlToken. You yielded: {type(token).__name__}")

            # Wrap up zombie task (task that was interrupted earlier)
            if task is self._zombieTask:
                assert task is not self._currentTask
                self._releaseTask(task)
                task.deleteLater()

                # Another task is queued up, start it now
                if self._currentTask:
                    self._startTask(self._currentTask)
                return

            nextToken = self._processToken(task, token)
            if nextToken is None:
                break
            token = nextToken

        if not self.isBusy():  # might've queued up another task...
            self.ready.emit()

    def _processToken(self, task: RepoTask, token: FlowControlToken) -> FlowControlToken | None:
        flow = task._currentFlow
        assert flow is not None
        assert task is self._currentTask

        tk = token.flowControl
        TK = FlowControlToken.Kind

        if tk == TK.ContinueOnUiThread or (RepoTaskRunner.ForceSerial and tk == TK.ContinueOnWorkThread):
            # Get next continuation token on this thread then loop to beginning of _iterateFlow
            token = RepoTaskRunner._getNextToken(flow)
            assert token is not None, "Do not yield None from a RepoTask coroutine"
            return token

        elif tk == TK.WaitUserReady:
            self.progress.emit("", False)
            self.requestAttention.emit()
            # When user is ready, task.uiReady will fire, and we'll re-enter _iterateFlow

        elif tk == TK.WaitProcessReady:
            busyMessage = _("Busy: {0}…", task.name())
            self.progress.emit(busyMessage, True)

            if task.broadcastProcesses():
                process = task.currentProcess
                self.processStarted.emit(process, task.name())

            # In unit tests, block until the process has completed
            if RepoTaskRunner.ForceSerial:
                self.blockUntilNextToken()

        elif tk == TK.ContinueOnWorkThread:
            assert not RepoTaskRunner.ForceSerial
            busyMessage = _("Busy: {0}…", task.name())
            self.progress.emit(busyMessage, True)

            # Wrapper around `next(flow)`.
            # It will, in turn, emit _continueFlow, which will re-enter _iterateFlow.
            assert not self._workerThread.isRunning()
            self._workerThread.flow = flow
            self._workerThread.start()

        elif tk == TK.InterruptedByException:
            exception = token.exception
            assert exception is not None, "FlowControlToken(InterruptedByException) must provide an exception!"

            # Wait for worker thread to wrap up cleanly,
            # otherwise we'll still appear to be busy for postTask callbacks.
            self.joinWorkerThread()

            # Stop tracking this task
            self._releaseTask(task)

            if isinstance(exception, StopIteration):
                # No more steps in the flow. Task completed successfully.
                pass
            elif isinstance(exception, AbortTask):
                # Controlled exit, show message (if any)
                self.reportAbortTask(task, exception)
                task.onError(exception)  # Also let task clean up after itself
            elif isinstance(exception, RepoGoneError):
                # Repo directory vanished
                self.repoGone.emit()
            else:
                # Run task's error callback
                task.onError(exception)

            # Emit postTask signal whether the task succeeded or not
            self.postTask.emit(task)

            task.deleteLater()

            # Manual GC: After completing a task is an opportune time to collect garbage
            gcHint()

        else:
            raise NotImplementedError(f"Unsupported FlowControlToken {token.flowControl}")

        return None

    @staticmethod
    def _getNextToken(flow: RepoTask.FlowGeneratorType) -> FlowControlToken:
        try:
            token = next(flow)
        except BaseException as exception:
            token = FlowControlToken(FlowControlToken.Kind.InterruptedByException, exception)
        return token

    def _releaseTask(self, task: RepoTask):
        logger.debug(f"<<< {task}")
        self.progress.emit("", False)
        self._currentTaskBenchmark.__exit__(None, None, None)

        assert onAppThread()
        assert task is self._currentTask or task is self._zombieTask
        assert task.isRootTask

        # Clean up all tasks in the stack (remember, we're the root stack)
        assert task in task._taskStack
        while task._taskStack:
            task._popSubtask()

        self._continueFlow.disconnect()
        task.uiReady.disconnect()

        task._currentFlow = None

        if task is self._currentTask:
            self._currentTask = None
        elif task is self._zombieTask:
            self._zombieTask = None
        else:
            raise AssertionError("_releaseTask: task is neither current nor zombie")

    def reportAbortTask(self, task: RepoTask, exception: AbortTask):
        message = str(exception)
        if message and exception.asStatusMessage:
            self.progress.emit("\u26a0 " + message, False)
        elif message:
            qmb = asyncMessageBox(self.parent(), exception.icon, task.name(), message)
            if exception.details:
                qmb.setDetailedText(exception.details)
            qmb.show()


class TaskInvocation:
    invoker: QObject
    taskClass: type[RepoTask]
    taskArgs: tuple
    taskKwargs: dict[str, Any]

    def __init__(self, invoker: QObject, taskClass: type[RepoTask], *args, **kwargs):
        assert issubclass(taskClass, RepoTask)
        self.invoker = invoker
        self.taskClass = taskClass
        self.taskArgs = args
        self.taskKwargs = kwargs

    def __repr__(self):
        return f"{self.__class__.__name__}({self.taskClass.__name__})"

    @classmethod
    def initializeGlobalSignal(cls):
        class _InvokeSignalOwner(QObject):
            invoke = Signal(TaskInvocation)
        assert not hasattr(cls, "_invokeSignalOwner"), "global task invoke signal already initialized"
        cls._invokeSignalOwner = _InvokeSignalOwner(None)
        cls.invokeSignal = cls._invokeSignalOwner.invoke
        return cls.invokeSignal


RepoTaskSubtype = TypeVar('RepoTaskSubtype', bound=RepoTask)
