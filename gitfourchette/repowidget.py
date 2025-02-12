# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import os
from contextlib import suppress

from gitfourchette import settings
from gitfourchette import tasks
from gitfourchette.diffarea import DiffArea
from gitfourchette.diffview.diffdocument import DiffDocument
from gitfourchette.diffview.diffview import DiffView
from gitfourchette.diffview.specialdiff import ShouldDisplayPatchAsImageDiff
from gitfourchette.exttools import PREFKEY_MERGETOOL, openInTextEditor, openInExternalTool
from gitfourchette.forms.banner import Banner
from gitfourchette.forms.openrepoprogress import OpenRepoProgress
from gitfourchette.forms.searchbar import SearchBar
from gitfourchette.forms.unloadedrepoplaceholder import UnloadedRepoPlaceholder
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.graphview.graphview import GraphView
from gitfourchette.localization import *
from gitfourchette.nav import NavHistory, NavLocator, NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import RepoModel, UC_FAKEID
from gitfourchette.sidebar.sidebar import Sidebar
from gitfourchette.tasks import RepoTask, TaskEffects, TaskBook, AbortMerge, RepoTaskRunner
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables

logger = logging.getLogger(__name__)


class RepoWidget(QStackedWidget):
    nameChange = Signal()
    openRepo = Signal(str, NavLocator)
    openPrefs = Signal(str)
    locatorChanged = Signal(NavLocator)
    historyChanged = Signal()
    requestAttention = Signal()
    becameVisible = Signal()

    busyMessage = Signal(str)
    statusMessage = Signal(str)
    clearStatus = Signal()

    repoModel: RepoModel

    pendingPath: str
    "Path of the repository if it isn't loaded yet (state=None)"

    pendingLocator: NavLocator
    pendingEffects: TaskEffects

    allowAutoLoad: bool

    navLocator: NavLocator
    navHistory: NavHistory

    splittersToSave: list[QSplitter]
    sharedSplitterSizes: dict[str, list[int]]
    centralSplitSizesBackup: list[int]

    def __del__(self):
        logger.debug(f"__del__ RepoWidget {self.pendingPath}")

    def __bool__(self):
        """ Override QStackedWidget.__bool__ so we can do quick None comparisons """
        return True

    @property
    def repo(self) -> Repo:
        if self.repoModel is None:
            return None
        return self.repoModel.repo

    @property
    def isLoaded(self):
        return self.repoModel is not None

    @property
    def isPriming(self):
        task = self.repoTaskRunner.currentTask
        priming = isinstance(task, tasks.PrimeRepo)
        return priming

    @property
    def workdir(self):
        if self.repoModel:
            return os.path.normpath(self.repoModel.repo.workdir)
        else:
            return self.pendingPath

    @property
    def superproject(self):
        if self.repoModel:
            return self.repoModel.superproject
        else:
            return settings.history.getRepoSuperproject(self.workdir)

    def __init__(self, parent: QWidget, pendingWorkdir: str, lazy=False):
        super().__init__(parent)
        self.setObjectName("RepoWidget")

        # Use RepoTaskRunner to schedule git operations to run on a separate thread.
        self.repoTaskRunner = tasks.RepoTaskRunner(self)
        self.repoTaskRunner.postTask.connect(self.refreshPostTask)
        self.repoTaskRunner.progress.connect(self.onRepoTaskProgress)
        self.repoTaskRunner.repoGone.connect(self.onRepoGone)
        self.repoTaskRunner.requestAttention.connect(self.requestAttention)

        self.repoModel = None
        self.pendingPath = os.path.normpath(pendingWorkdir)
        self.pendingLocator = NavLocator()
        self.pendingEffects = TaskEffects.Nothing
        self.pendingStatusMessage = ""
        self.allowAutoLoad = True

        self.busyCursorDelayer = QTimer(self)
        self.busyCursorDelayer.setSingleShot(True)
        self.busyCursorDelayer.setInterval(100)
        self.busyCursorDelayer.timeout.connect(lambda: self.setCursor(Qt.CursorShape.BusyCursor))

        self.navLocator = NavLocator()
        self.navHistory = NavHistory()

        self.sharedSplitterSizes = {}  # To be replaced with a shared reference
        self.centralSplitSizesBackup = []

        self.uiReady = False
        self.mainWidgetPlaceholder = None

        if not lazy:
            self.setupUi()
        else:
            # To save some time on boot, we'll call setupUi later if this isn't the foreground RepoWidget.
            # Create placeholder for the main UI until setupUi is called.
            # This is because remove/setPlaceholderWidget expects QStackedLayout slot 0 to be taken by the main UI.
            self.mainWidgetPlaceholder = QWidget(self)
            self.addWidget(self.mainWidgetPlaceholder)

    def setupUi(self):
        if self.uiReady:
            return

        mainLayout = self.layout()
        assert isinstance(mainLayout, QStackedLayout)

        if not mainLayout.isEmpty():
            assert mainLayout.widget(0) is self.mainWidgetPlaceholder
            mainLayout.removeWidget(self.mainWidgetPlaceholder)
            self.mainWidgetPlaceholder.deleteLater()
            self.mainWidgetPlaceholder = None

        # ----------------------------------
        # Splitters

        sideSplitter = QSplitter(Qt.Orientation.Horizontal, self)
        sideSplitter.setObjectName("Split_Side")

        centralSplitter = QSplitter(Qt.Orientation.Vertical, self)
        centralSplitter.setObjectName("Split_Central")
        self.centralSplitter = centralSplitter

        mainLayout.insertWidget(0, sideSplitter)

        # ----------------------------------
        # Build widgets

        sidebarContainer = self._makeSidebarContainer()
        graphContainer = self._makeGraphContainer()

        self.diffArea = DiffArea(self)
        # Bridges for legacy code
        self.dirtyFiles = self.diffArea.dirtyFiles
        self.stagedFiles = self.diffArea.stagedFiles
        self.committedFiles = self.diffArea.committedFiles
        self.diffView = self.diffArea.diffView
        self.specialDiffView = self.diffArea.specialDiffView
        self.conflictView = self.diffArea.conflictView
        self.diffBanner = self.diffArea.diffBanner

        # ----------------------------------
        # Add widgets in splitters

        sideSplitter.addWidget(sidebarContainer)
        sideSplitter.addWidget(centralSplitter)
        sideSplitter.setSizes([220, 500])
        sideSplitter.setStretchFactor(0, 0)  # don't auto-stretch sidebar when resizing window
        sideSplitter.setStretchFactor(1, 1)
        sideSplitter.setChildrenCollapsible(False)

        centralSplitter.addWidget(graphContainer)
        centralSplitter.addWidget(self.diffArea)
        centralSplitter.setSizes([100, 150])
        centralSplitter.setCollapsible(0, True)  # Let DiffArea be maximized, thereby hiding the graph
        centralSplitter.setCollapsible(1, False)  # DiffArea can never be collapsed
        self.centralSplitSizesBackup = centralSplitter.sizes()
        self.diffArea.contextHeader.maximizeButton.clicked.connect(self.maximizeDiffArea)
        centralSplitter.splitterMoved.connect(self.syncDiffAreaMaximizeButton)

        splitters: list[QSplitter] = self.findChildren(QSplitter)
        assert all(s.objectName() for s in splitters), "all splitters must be named, or state saving won't work!"
        self.splittersToSave = splitters

        # ----------------------------------
        # Connect signals

        # save splitter state in splitterMoved signal
        for splitter in self.splittersToSave:
            splitter.splitterMoved.connect(lambda pos, index, s=splitter: self.saveSplitterState(s))

        for fileList in self.dirtyFiles, self.stagedFiles, self.committedFiles:
            # File list view selections are mutually exclusive.
            fileList.nothingClicked.connect(lambda fl=fileList: self.diffArea.clearDocument(fl))
            fileList.statusMessage.connect(self.statusMessage)
            fileList.openSubRepo.connect(lambda path: self.openRepo.emit(self.repo.in_workdir(path), NavLocator()))

        self.graphView.linkActivated.connect(self.processInternalLink)
        self.graphView.statusMessage.connect(self.statusMessage)

        self.diffArea.committedFiles.openDiffInNewWindow.connect(self.loadPatchInNewWindow)
        self.diffArea.conflictView.openPrefs.connect(self.openPrefs)
        self.diffArea.diffView.contextualHelp.connect(self.statusMessage)
        self.diffArea.specialDiffView.linkActivated.connect(self.processInternalLink)

        self.sidebar.statusMessage.connect(self.statusMessage)
        self.sidebar.toggleHideRefPattern.connect(self.toggleHideRefPattern)
        self.sidebar.openSubmoduleRepo.connect(self.openSubmoduleRepo)
        self.sidebar.openSubmoduleFolder.connect(self.openSubmoduleFolder)

        # ----------------------------------

        self.restoreSplitterStates()

        # ----------------------------------
        # Prepare placeholder "opening repository" widget

        self.setPlaceholderWidgetOpenRepoProgress()

        # ----------------------------------
        # Styling

        # Huh? Gotta refresh the stylesheet after calling setupUi on a lazy-inited RepoWidget,
        # otherwise fonts somehow appear slightly too large within the RepoWidget on macOS.
        self.setStyleSheet("* {}")

        # Remove sidebar frame
        self.sidebar.setFrameStyle(QFrame.Shape.NoFrame)

        # Smaller fonts in diffArea buttons
        self.diffArea.applyCustomStyling()

        setTabOrder(
            self.sidebar,
            self.graphView,
            self.diffArea.committedFiles,
            self.diffArea.dirtyFiles,
            self.diffArea.stagedFiles,
            self.diffArea.diffView,
            self.diffArea.specialDiffView,
            self.diffArea.conflictView,
        )

        # ----------------------------------
        # We're ready

        self.uiReady = True

    def updateBoundRepo(self):
        repo = self.repo
        if not self.uiReady:
            return
        for w in (
            self.diffArea.dirtyFiles,
            self.diffArea.stagedFiles,
            self.diffArea.committedFiles,
            self.diffArea.conflictView,
        ):
            w.repo = repo

    # -------------------------------------------------------------------------
    # Initial layout

    def _makeGraphContainer(self):
        graphView = GraphView(self)
        graphView.searchBar.notFoundMessage = self.commitNotFoundMessage

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(graphView.searchBar)
        layout.addWidget(graphView)

        self.graphView = graphView
        return container

    def _makeSidebarContainer(self):
        sidebar = Sidebar(self)

        banner = Banner(self, orientation=Qt.Orientation.Vertical)
        banner.setProperty("class", "merge")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)
        layout.addWidget(sidebar)
        layout.addWidget(banner)

        self.sidebar = sidebar
        self.mergeBanner = banner

        return container

    # -------------------------------------------------------------------------
    # Tasks

    def runTask(self, taskClass: type[RepoTask], *args, **kwargs) -> RepoTask:
        assert issubclass(taskClass, RepoTask)

        # Initialize the task
        task = taskClass(self.repoTaskRunner)
        task.setRepoModel(self.repoModel)

        # Enqueue the task
        self.repoTaskRunner.put(task, *args, **kwargs)

        return task

    # -------------------------------------------------------------------------
    # Initial repo priming

    def primeRepo(self, path: str = "", force: bool = False, maxCommits: int = -1):
        if not force and self.isLoaded:
            warnings.warn(f"Repo already primed! {path}")
            return None

        # Save prefs before force-reloading the repo.
        if force and self.isLoaded:
            self.repoModel.prefs.write()

        primingTask = self.repoTaskRunner.currentTask
        if isinstance(primingTask, tasks.PrimeRepo):
            logger.debug(f"Repo is being primed: {path}")
            return primingTask

        path = path or self.pendingPath
        assert path
        return self.runTask(tasks.PrimeRepo, path=path, maxCommits=maxCommits)

    # -------------------------------------------------------------------------
    # Splitter state

    def setSharedSplitterSizes(self, splitterSizes: dict[str, list[int]]):
        self.sharedSplitterSizes = splitterSizes
        if self.uiReady:
            self.restoreSplitterStates()

    def saveSplitterState(self, splitter: QSplitter):
        # QSplitter.saveState() saves a bunch of properties that we may want to
        # override in later versions, such as whether child widgets are
        # collapsible, the width of the splitter handle, etc. So, don't use
        # saveState(); instead, save the raw sizes for predictable results.
        name = splitter.objectName()
        sizes = splitter.sizes()[:]
        self.sharedSplitterSizes[name] = sizes

    def restoreSplitterStates(self):
        for splitter in self.splittersToSave:
            with suppress(KeyError):
                name = splitter.objectName()
                sizes = self.sharedSplitterSizes[name]
                splitter.setSizes(sizes)
        self.syncDiffAreaMaximizeButton()

    def isDiffAreaMaximized(self):
        sizes = self.centralSplitter.sizes()
        return sizes[0] == 0

    def maximizeDiffArea(self):
        if self.isDiffAreaMaximized():
            # Diff area was maximized - restore non-collapsed sizes
            newSizes = self.centralSplitSizesBackup
        else:
            # Maximize diff area - back up current sizes
            self.centralSplitSizesBackup = self.centralSplitter.sizes()
            newSizes = [0, 1]
        self.centralSplitter.setSizes(newSizes)
        self.saveSplitterState(self.centralSplitter)
        self.syncDiffAreaMaximizeButton()

    def syncDiffAreaMaximizeButton(self):
        isMaximized = self.isDiffAreaMaximized()
        self.diffArea.contextHeader.maximizeButton.setChecked(isMaximized)

    # -------------------------------------------------------------------------
    # Placeholder widgets

    @property
    def mainStack(self) -> QStackedLayout:
        layout = self.layout()
        assert isinstance(layout, QStackedLayout)
        return layout

    def removePlaceholderWidget(self):
        self.mainStack.setCurrentIndex(0)
        while self.mainStack.count() > 1:
            i = self.mainStack.count() - 1
            w = self.mainStack.widget(i)
            logger.debug(f"Removing modal placeholder widget: {w.objectName()}")
            self.mainStack.removeWidget(w)
            w.deleteLater()
        assert self.mainStack.count() <= 1

    def setPlaceholderWidget(self, w):
        if w is not self.placeholderWidget:
            self.removePlaceholderWidget()
            self.mainStack.addWidget(w)
        self.mainStack.setCurrentWidget(w)
        assert self.mainStack.currentIndex() != 0
        assert self.mainStack.count() <= 2

    def setPlaceholderWidgetOpenRepoProgress(self):
        pw = self.placeholderWidget
        if not isinstance(pw, OpenRepoProgress):
            name = self.getTitle()
            pw = OpenRepoProgress(self, name)
        self.setPlaceholderWidget(pw)
        return pw

    @property
    def placeholderWidget(self):
        if self.mainStack.count() > 1:
            return self.mainStack.widget(1)
        return None

    # -------------------------------------------------------------------------
    # Navigation

    def saveFilePositions(self):
        if self.navHistory.isWriteLocked():
            warnings.warn("Ignoring saveFilePositions because history is locked")
            return

        if self.diffView.isVisibleTo(self):
            newLocator = self.diffView.getPreciseLocator()
            if not newLocator.isSimilarEnoughTo(self.navLocator):
                warnings.warn(f"RepoWidget/DiffView locator mismatch: {self.navLocator} vs. {newLocator}")
        else:
            newLocator = self.navLocator.coarse()

        self.navHistory.push(newLocator)
        self.navLocator = newLocator
        return self.navLocator

    def jump(self, locator: NavLocator, check=False):
        self.runTask(tasks.Jump, locator)
        if check:
            self.repoTaskRunner.joinWorkerThread()
            assert self.navLocator.isSimilarEnoughTo(locator), f"failed to jump to: {locator}"

    def navigateBack(self):
        self.runTask(tasks.JumpBackOrForward, -1)

    def navigateForward(self):
        self.runTask(tasks.JumpBackOrForward, 1)

    # -------------------------------------------------------------------------

    def __repr__(self):
        return f"RepoWidget({self.getTitle()})"

    def getTitle(self) -> str:
        if self.repoModel:
            return self.repoModel.shortName
        elif self.pendingPath:
            return settings.history.getRepoTabName(self.pendingPath)
        else:
            return "???"

    def closeEvent(self, event: QCloseEvent):
        """ Called when closing a repo tab """
        # Don't bother with the placeholder since we'll disappear immediately
        self.cleanup(installPlaceholder=False)

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self.becameVisible.emit()

    def cleanup(self, message: str = "", allowAutoReload: bool = True, installPlaceholder: bool = True):
        assert onAppThread()

        # Kill any ongoing task then block UI thread until the task dies cleanly
        self.repoTaskRunner.killCurrentTask()
        self.repoTaskRunner.joinZombieTask()

        # Don't bother with the placeholder widget if we've been lazy-initialized
        installPlaceholder &= self.uiReady
        hasRepo = self.repoModel is not None and self.repoModel.repo is not None

        # Save sidebar collapse cache (if our UI has settled)
        if hasRepo and self.uiReady:
            uiPrefs = self.repoModel.prefs
            if self.sidebar.sidebarModel.collapseCacheValid:
                uiPrefs.collapseCache = set(self.sidebar.sidebarModel.collapseCache)
            else:
                uiPrefs.collapseCache = set()
            try:
                uiPrefs.write()
            except OSError as e:
                logger.warning(f"OSError when writing prefs: {e}")

        # Clear UI
        if installPlaceholder:
            self.diffArea.clear()
            with QSignalBlockerContext(self.graphView, self.sidebar):
                self.graphView.clear()
                self.sidebar.model().clear()

        # Let repo wrap up
        if hasRepo:
            # Save path if we want to reload the repo later
            self.pendingPath = os.path.normpath(self.repoModel.repo.workdir)
            self.allowAutoLoad = allowAutoReload

            # Free the repository
            self.repoModel.repo.free()
            self.repoModel.repo = None
            logger.info(f"Repository freed: {self.pendingPath}")

        # Forget RepoModel
        self.repoModel = None
        self.updateBoundRepo()

        # Install placeholder widget
        if installPlaceholder:
            placeholder = UnloadedRepoPlaceholder(self)
            placeholder.ui.nameLabel.setText(self.getTitle())
            placeholder.ui.loadButton.clicked.connect(lambda: self.primeRepo())
            placeholder.ui.icon.setVisible(False)
            self.setPlaceholderWidget(placeholder)

            if message:
                placeholder.ui.label.setText(message)

            if not allowAutoReload:
                placeholder.ui.icon.setText("")
                placeholder.ui.icon.setPixmap(stockIcon("image-missing").pixmap(96))
                placeholder.ui.icon.setVisible(True)
                placeholder.ui.loadButton.setText(_("Try to reload"))

            # Clean up status bar if there were repo-specific warnings in it
            if self.isVisible():
                self.refreshWindowChrome()

    def loadPatchInNewWindow(self, patch: Patch, locator: NavLocator):
        try:
            diffDocument = DiffDocument.fromPatch(patch, locator)
        except Exception as exc:
            excMessageBox(exc, _("Open diff in new window"),
                          _("Only text diffs may be opened in a separate window."),
                          showExcSummary=not isinstance(exc, ShouldDisplayPatchAsImageDiff),
                          icon='information')
            return

        diffWindow = QWidget(self)
        diffWindow.setObjectName(DiffView.DetachedWindowObjectName)
        diffWindow.setWindowTitle(locator.asTitle())
        diffWindow.setWindowFlag(Qt.WindowType.Window, True)
        diffWindow.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(diffWindow)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)
        diff = DiffView(diffWindow)
        diff.isDetachedWindow = True
        diff.setFrameStyle(QFrame.Shape.NoFrame)
        diff.replaceDocument(self.repo, patch, locator, diffDocument)
        layout.addWidget(diff)
        layout.addWidget(diff.searchBar)
        diffWindow.resize(550, 700)
        diffWindow.show()

    def openSubmoduleRepo(self, submoduleKey: str):
        path = self.repo.get_submodule_workdir(submoduleKey)
        self.openRepo.emit(path, NavLocator())

    def openSubmoduleFolder(self, submoduleKey: str):
        path = self.repo.get_submodule_workdir(submoduleKey)
        openFolder(path)

    def openRepoFolder(self):
        openFolder(self.workdir)

    def openTerminal(self):
        openInExternalTool(
            parent=self, prefKey="terminal",
            replacements={"$P?": self.workdir}, positional=[],
            cwd=self.workdir, detached=True)

    def openSuperproject(self):
        superproject = self.superproject
        if superproject:
            self.openRepo.emit(superproject, NavLocator())
        else:
            showInformation(self, _("Open Superproject"), _("This repository does not have a superproject."))

    def copyRepoPath(self):
        text = self.workdir
        QApplication.clipboard().setText(text)
        self.statusMessage.emit(clipboardStatusMessage(text))

    def openGitignore(self):
        self._openLocalConfigFile(self.repo.in_workdir(".gitignore"))

    def openLocalConfig(self):
        self._openLocalConfigFile(os.path.join(self.repo.path, "config"))

    def openLocalExclude(self):
        self._openLocalConfigFile(os.path.join(self.repo.path, "info", "exclude"))

    def _openLocalConfigFile(self, fullPath: str):
        def createAndOpen():
            open(fullPath, "ab").close()
            openInTextEditor(self, fullPath)

        if not os.path.exists(fullPath):
            basename = os.path.basename(fullPath)
            askConfirmation(
                self,
                _("Open {0}", tquo(basename)),
                paragraphs(
                    _("File {0} does not exist.", bquo(fullPath)),
                    _("Do you want to create it?")),
                okButtonText=_("Create {0}", lquo(basename)),
                callback=createAndOpen)
        else:
            openInTextEditor(self, fullPath)

    # -------------------------------------------------------------------------
    # Entry point for generic "Find" command

    def dispatchSearchCommand(self, op: SearchBar.Op):
        searchBars = {
            self.diffArea.dirtyFiles: self.diffArea.dirtyFiles.searchBar,
            self.diffArea.stagedFiles: self.diffArea.stagedFiles.searchBar,
            self.diffArea.committedFiles: self.diffArea.committedFiles.searchBar,
            self.diffArea.diffView: self.diffArea.diffView.searchBar,
        }

        # Find a sink to redirect search to
        focus = self.focusWidget()
        for sink, searchBar in searchBars.items():
            # Stop scanning if this sink or searchBar have focus
            if sink.isVisibleTo(self) and (focus is sink or focus is searchBar.lineEdit):
                break
        else:
            # Fall back to searching GraphView if nothing has focus
            sink = self.graphView
            searchBar = self.graphView.searchBar

        # Forward search
        if isinstance(sink, QAbstractItemView):
            searchBar.searchItemView(op)
        else:
            sink.search(op)

    def commitNotFoundMessage(self, searchTerm: str) -> str:
        if self.repoModel.hiddenCommits:
            message = _("{0} not found among the branches that aren’t hidden.")
        else:
            message = _("{0} not found.")
        message = message.format(bquo(searchTerm))

        if self.repoModel.truncatedHistory:
            note = _n("Note: The search was limited to the top commit because the commit history is truncated.",
                      "Note: The search was limited to the top {n} commits because the commit history is truncated.",
                      self.repoModel.numRealCommits)
            message += f"<p>{note}</p>"
        elif self.repoModel.repo.is_shallow:
            note = _n("Note: The search was limited to the single commit available in this shallow clone.",
                      "Note: The search was limited to the {n} commits available in this shallow clone.",
                      self.repoModel.numRealCommits)
            message += f"<p>{note}</p>"

        return message

    # -------------------------------------------------------------------------

    def toggleHideRefPattern(self, refPattern: str):
        assert refPattern.startswith("refs/")
        self.repoModel.toggleHideRefPattern(refPattern)
        self.graphView.clFilter.setHiddenCommits(self.repoModel.hiddenCommits)

        # Hide/draw refboxes for commits that are shared by non-hidden refs
        self.graphView.viewport().update()

    # -------------------------------------------------------------------------

    def setInitialFocus(self):
        """
        Focus on some useful widget within RepoWidget.
        Intended to be called immediately after loading a repo.
        """
        if not self.focusWidget():  # only if nothing has the focus yet
            self.graphView.setFocus()

    def refreshRepo(self, effects: TaskEffects = TaskEffects.DefaultRefresh, jumpTo: NavLocator = NavLocator.Empty):
        """Refresh the repo as soon as possible."""

        if (not self.isLoaded) or self.isPriming:
            return
        assert self.repoModel is not None

        if not self.isVisible() or self.repoTaskRunner.isBusy():
            # Can't refresh right now. Stash the effect bits for later.
            logger.debug(f"Stashing refresh bits {repr(effects)}")
            self.pendingEffects |= effects
            if jumpTo:
                warnings.warn(f"Ignoring post-refresh jump {jumpTo} because can't refresh yet")
            return

        # Consume pending effect bits, if any
        if self.pendingEffects != TaskEffects.Nothing:
            logger.debug(f"Consuming pending refresh bits {self.pendingEffects}")
            effects |= self.pendingEffects
            self.pendingEffects = TaskEffects.Nothing

        # Consume pending locator, if any
        if self.pendingLocator:
            if not jumpTo:
                jumpTo = self.pendingLocator
            else:
                warnings.warn(f"Ignoring pendingLocator {self.pendingLocator} - overridden by {jumpTo}")
            self.pendingLocator = NavLocator()  # Consume it

        # Invoke refresh task
        if effects != TaskEffects.Nothing:
            tasks.RefreshRepo.invoke(self, effects, jumpTo)
        elif jumpTo:
            tasks.Jump.invoke(self, jumpTo)
        else:
            # End of refresh chain.
            if self.pendingStatusMessage:
                self.statusMessage.emit(self.pendingStatusMessage)
                self.pendingStatusMessage = ""

    def refreshWindowChrome(self):
        shortname = self.getTitle()
        inBrackets = ""
        suffix = ""
        repo = self.repo

        if not repo:
            pass
        elif repo.head_is_unborn:
            inBrackets = _("Unborn HEAD")
        elif repo.head_is_detached:
            oid = repo.head_commit_id
            inBrackets = _("Detached HEAD") + " @ " + shortHash(oid)
        else:
            with suppress(GitError):
                inBrackets = repo.head_branch_shorthand

        if settings.DEVDEBUG:
            chain = []
            if settings.TEST_MODE:
                chain.append("TEST_MODE")
            if RepoTaskRunner.ForceSerial:
                chain.append("SYNC_TASKS")
            chain.append(f"PID {os.getpid()}")
            chain.append(QT_BINDING)
            suffix += " - " + ", ".join(chain)

        if inBrackets:
            suffix = F" [{inBrackets}]{suffix}"

        self.window().setWindowTitle(shortname + suffix)

        # Refresh state banner (merging, cherrypicking, reverting, etc.)
        self.refreshBanner()

    def refreshBanner(self):
        if not self.uiReady:
            return
        elif not self.repo:
            self.mergeBanner.setVisible(False)
            return

        repo = self.repo

        rstate = repo.state() if repo else RepositoryState.NONE

        bannerTitle = TrTables.enum(rstate) if rstate != RepositoryState.NONE else ""
        bannerText = ""
        bannerHeeded = False
        bannerAction = ""
        bannerCallback = None

        def abortMerge():
            self.runTask(AbortMerge)

        if rstate == RepositoryState.MERGE:
            try:
                mergehead = self.repoModel.mergeheads[0]
                name = self.repoModel.refsAt[mergehead][0]
                name = RefPrefix.split(name)[1]
                bannerTitle = _("Merging {0}", bquo(name))
            except (IndexError, KeyError):
                pass

            if not repo.any_conflicts:
                bannerText += _("All conflicts fixed. Commit to conclude.")
                bannerHeeded = True
            else:
                bannerText += _("Conflicts need fixing.")

            bannerAction = englishTitleCase(_("Abort merge"))
            bannerCallback = abortMerge

        elif rstate == RepositoryState.CHERRYPICK:
            if not repo.any_conflicts:
                bannerText += _("Commit to conclude the cherry-pick.")
                bannerHeeded = True
            else:
                bannerText += _("Conflicts need fixing.")

            bannerAction = englishTitleCase(_("Abort cherry-pick"))
            bannerCallback = abortMerge

        elif rstate == RepositoryState.REVERT:
            if not repo.any_conflicts:
                bannerText += _("Commit to conclude the revert.")
                bannerHeeded = True
            else:
                bannerText += _("Conflicts need fixing.")

            bannerAction = englishTitleCase(_("Abort revert"))
            bannerCallback = abortMerge

        elif rstate == RepositoryState.NONE:
            if repo.any_conflicts:
                bannerTitle = _("Conflicts")
                bannerText = _("Fix the conflicts among the uncommitted changes.")
                bannerAction = englishTitleCase(_("Reset index"))
                bannerCallback = abortMerge

        else:
            bannerTitle = _("Warning")
            bannerText = _(
                "The repo is currently in state {state}, which {app} doesn’t support yet. "
                "Use <code>git</code> on the command line to continue.",
                app=qAppName(), state=bquo(TrTables.enum(rstate)))

        if bannerText or bannerTitle:
            self.mergeBanner.popUp(bannerTitle, bannerText, heeded=bannerHeeded, canDismiss=False)
            if bannerAction:
                self.mergeBanner.addButton(bannerAction, bannerCallback)
        else:
            self.mergeBanner.setVisible(False)

    def refreshNumUncommittedChanges(self):
        self.sidebar.repaintUncommittedChanges()
        self.graphView.repaintCommit(UC_FAKEID)

    # -------------------------------------------------------------------------

    def selectRef(self, refName: str):
        oid = self.repo.commit_id_from_refname(refName)
        self.jump(NavLocator(NavContext.COMMITTED, commit=oid))

    # -------------------------------------------------------------------------

    def refreshPostTask(self, task: tasks.RepoTask):
        if task.postStatus:
            self.pendingStatusMessage = task.postStatus
        self.refreshRepo(task.effects, task.jumpTo)

    def onRepoTaskProgress(self, progressText: str, withSpinner: bool = False):
        if withSpinner:
            self.busyMessage.emit(progressText)
        elif progressText:
            self.statusMessage.emit(progressText)
        else:
            self.clearStatus.emit()

        if not withSpinner:
            self.busyCursorDelayer.stop()
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif not self.busyCursorDelayer.isActive():
            self.busyCursorDelayer.start()

    def onRepoGone(self):
        message = _("Repository folder went missing:") + "\n" + escamp(self.pendingPath)

        # Unload the repo
        self.cleanup(message=message, allowAutoReload=False)

        # Update window chrome
        self.nameChange.emit()

    def refreshPrefs(self, *prefDiff: str):
        if not self.uiReady:
            return

        self.diffView.refreshPrefs()
        self.specialDiffView.refreshPrefs()
        self.graphView.refreshPrefs()
        if PREFKEY_MERGETOOL in prefDiff:
            self.conflictView.refreshPrefs()
        self.sidebar.refreshPrefs()
        self.dirtyFiles.refreshPrefs()
        self.stagedFiles.refreshPrefs()
        self.committedFiles.refreshPrefs()

        # Reflect any change in titlebar prefs
        if self.isVisible():
            self.refreshWindowChrome()

    # -------------------------------------------------------------------------

    def processInternalLink(self, url: QUrl | str):
        if not isinstance(url, QUrl):
            url = QUrl(url)

        if url.isLocalFile():
            locator = NavLocator()
            fragment = url.fragment()
            if fragment:
                with suppress(ValueError):
                    locator = NavLocator.inCommit(Oid(hex=fragment))

            self.openRepo.emit(url.toLocalFile(), locator)
            return

        if url.scheme() != APP_URL_SCHEME:
            warnings.warn(f"Unsupported scheme in internal link: {url.toDisplayString()}")
            return

        logger.info(f"Internal link: {url.toDisplayString()}")

        simplePath = url.path().removeprefix("/")
        kwargs = dict(QUrlQuery(url).queryItems(QUrl.ComponentFormattingOption.FullyDecoded))

        if url.authority() == NavLocator.URL_AUTHORITY:
            locator = NavLocator.parseUrl(url)
            self.jump(locator)
        elif url.authority() == "expandlog":
            # After loading, jump back to what is currently the last commit
            self.pendingLocator = NavLocator.inCommit(self.repoModel.commitSequence[-1].id)
            # Reload the repo
            maxCommits = int(kwargs.get("n", self.repoModel.nextTruncationThreshold))
            self.primeRepo(force=True, maxCommits=maxCommits)
        elif url.authority() == "opensubfolder":
            p = self.repo.in_workdir(simplePath)
            self.openRepo.emit(p, NavLocator())
        elif url.authority() == "prefs":
            self.openPrefs.emit(simplePath)
        elif url.authority() == "exec":
            cmdName = simplePath
            taskClass = tasks.__dict__[cmdName]
            self.runTask(taskClass, **kwargs)
        else:
            warnings.warn(f"Unsupported authority in internal link: {url.toDisplayString()}")

    # -------------------------------------------------------------------------

    def contextMenuItems(self):
        return self.contextMenuItemsByProxy(self, lambda: self)

    def pathsMenuItems(self):
        return self.pathsMenuItemsByProxy(self, lambda: self)

    @classmethod
    def contextMenuItemsByProxy(cls, invoker, proxy):
        return [
            TaskBook.action(invoker, tasks.NewCommit, accel="C"),
            TaskBook.action(invoker, tasks.AmendCommit, accel="A"),
            TaskBook.action(invoker, tasks.NewStash),

            ActionDef.SEPARATOR,

            TaskBook.action(invoker, tasks.NewBranchFromHead, accel="B"),
            TaskBook.action(invoker, tasks.FetchRemotes, accel="F"),
            TaskBook.action(invoker, tasks.PullBranch, accel="L"),
            TaskBook.action(invoker, tasks.PushBranch, accel="P"),

            TaskBook.action(invoker, tasks.NewRemote),

            ActionDef.SEPARATOR,

            TaskBook.action(invoker, tasks.RecallCommit),

            ActionDef.SEPARATOR,

            *cls.pathsMenuItemsByProxy(invoker, proxy),

            ActionDef.SEPARATOR,

            TaskBook.action(invoker, tasks.EditRepoSettings),

            ActionDef(
                _("&Local Config Files"),
                submenu=[
                    ActionDef(".gitignore", lambda: proxy().openGitignore()),
                    ActionDef("config", lambda: proxy().openLocalConfig()),
                    ActionDef("exclude", lambda: proxy().openLocalExclude()),
                ]),
        ]

    @classmethod
    def pathsMenuItemsByProxy(cls, invoker, proxy):
        superprojectLabel = _("Open Superproject")
        superprojectEnabled = True

        if isinstance(invoker, cls):
            superproject = invoker.superproject
            superprojectEnabled = bool(superproject)
            if superprojectEnabled:
                superprojectName = settings.history.getRepoTabName(superproject)
                superprojectLabel = _("Open Superproject {0}", lquo(superprojectName))

        return [
            ActionDef(
                _("&Open Repo Folder"),
                lambda: proxy().openRepoFolder(),
                icon="reveal",
                shortcuts=GlobalShortcuts.openRepoFolder,
                tip=_("Open this repo’s working directory in the system’s file manager"),
            ),

            ActionDef(
                _("Open &Terminal"),
                lambda: proxy().openTerminal(),
                icon="terminal",
                shortcuts=GlobalShortcuts.openTerminal,
                tip=_("Open a terminal in the repo’s working directory"),
            ),

            ActionDef(
                _("Cop&y Repo Path"),
                lambda: proxy().copyRepoPath(),
                tip=_("Copy the absolute path to this repo’s working directory to the clipboard"),
            ),

            ActionDef(
                superprojectLabel,
                lambda: proxy().openSuperproject(),
                enabled=superprojectEnabled,
            ),
        ]
