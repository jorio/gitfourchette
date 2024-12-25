# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import copy
import gc
import logging
import os
import re
from collections.abc import Sequence
from contextlib import suppress
from typing import Literal

import pygit2

from gitfourchette import settings
from gitfourchette import tasks
from gitfourchette.application import GFApplication
from gitfourchette.diffview.diffview import DiffView
from gitfourchette.exttools import openPrefsDialog
from gitfourchette.forms.aboutdialog import AboutDialog
from gitfourchette.forms.clonedialog import CloneDialog
from gitfourchette.forms.maintoolbar import MainToolBar
from gitfourchette.forms.prefsdialog import PrefsDialog
from gitfourchette.forms.searchbar import SearchBar
from gitfourchette.forms.welcomewidget import WelcomeWidget
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavContext, NavFlags
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repowidget import RepoWidget
from gitfourchette.tasks import TaskBook
from gitfourchette.toolbox import *
from gitfourchette.trash import Trash

logger = logging.getLogger(__name__)

USERS_GUIDE_URL = "https://gitfourchette.org/guide"


class NoRepoWidgetError(Exception):
    pass


class MainWindow(QMainWindow):
    welcomeStack: QStackedWidget
    welcomeWidget: WelcomeWidget
    tabs: QTabWidget2

    recentMenu: QMenu
    repoMenu: QMenu
    showStatusBarAction: QAction
    showMenuBarAction: QAction

    sharedSplitterSizes: dict[str, list[int]]

    def __init__(self):
        super().__init__()

        self.welcomeStack = QStackedWidget(self)
        self.setCentralWidget(self.welcomeStack)

        self.setObjectName("GFMainWindow")

        self.sharedSplitterSizes = {}

        self.setWindowTitle(qAppName())

        initialSize = .75 * QApplication.primaryScreen().availableSize()
        self.resize(initialSize)

        self.tabs = QTabWidget2(self)
        self.tabs.currentWidgetChanged.connect(self.onTabCurrentWidgetChanged)
        self.tabs.tabCloseRequested.connect(self.closeTab)
        self.tabs.tabContextMenuRequested.connect(self.onTabContextMenu)
        self.tabs.tabDoubleClicked.connect(self.onTabDoubleClicked)

        self.welcomeWidget = WelcomeWidget(self)
        self.welcomeWidget.newRepo.connect(self.newRepo)
        self.welcomeWidget.openRepo.connect(self.openDialog)
        self.welcomeWidget.cloneRepo.connect(self.cloneDialog)

        self.welcomeStack.addWidget(self.welcomeWidget)
        self.welcomeStack.addWidget(self.tabs)
        self.welcomeStack.setCurrentWidget(self.welcomeWidget)

        self.globalMenuBar = QMenuBar(self)
        self.globalMenuBar.setObjectName("GFMainMenuBar")
        self.setMenuBar(self.globalMenuBar)
        self.autoHideMenuBar = AutoHideMenuBar(self.globalMenuBar)

        self.statusBar2 = QStatusBar2(self)
        self.setStatusBar(self.statusBar2)

        self.mainToolBar = MainToolBar(self)
        self.addToolBar(self.mainToolBar)
        self.mainToolBar.openDialog.connect(self.openDialog)
        self.mainToolBar.openPrefs.connect(self.openPrefsDialog)
        self.mainToolBar.reveal.connect(lambda: self.currentRepoWidget().openRepoFolder())
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)

        self.fillGlobalMenuBar()

        self.setAcceptDrops(True)
        GFApplication.instance().installEventFilter(self)

        self.refreshPrefs()

    # -------------------------------------------------------------------------
    # Event filters & handlers

    def eventFilter(self, watched, event: QEvent):
        isPress = event.type() == QEvent.Type.MouseButtonPress
        isDblClick = event.type() == QEvent.Type.MouseButtonDblClick

        if event.type() == QEvent.Type.FileOpen:
            # Called if dragging something to dock icon on macOS.
            # Ignore in test mode - the test runner may send a bogus FileOpen before we're ready to process it.
            assert isinstance(event, QFileOpenEvent)
            if not settings.TEST_MODE:
                outcome = self.getDropOutcomeFromLocalFilePath(event.file())
                self.handleDrop(*outcome)

        elif event.type() == QEvent.Type.ApplicationStateChange:
            # Refresh current RepoWidget when the app regains the active state (foreground)
            if QGuiApplication.applicationState() == Qt.ApplicationState.ApplicationActive:
                QTimer.singleShot(0, self.onRegainForeground)

        elif (isPress or isDblClick) and self.isActiveWindow():
            # Intercept back/forward mouse clicks

            # As of PyQt6 6.5.1, QContextMenuEvent sometimes pretends that its event type is a MouseButtonDblClick
            if PYQT6 and not isinstance(event, QMouseEvent):
                return False

            assert isinstance(event, QMouseEvent)
            isBack = event.button() == Qt.MouseButton.BackButton
            isForward = event.button() == Qt.MouseButton.ForwardButton

            if isBack or isForward:
                if isPress:
                    with suppress(NoRepoWidgetError):
                        if isForward:
                            self.currentRepoWidget().navigateForward()
                        else:
                            self.currentRepoWidget().navigateBack()

                # Eat clicks or double-clicks of back and forward mouse buttons
                return True

        return False

    def keyReleaseEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Alt and self.autoHideMenuBar.enabled:
            self.autoHideMenuBar.toggle()
        else:
            super().keyReleaseEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        action, data = self.getDropOutcomeFromMimeData(event.mimeData())
        if action:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        action, data = self.getDropOutcomeFromMimeData(event.mimeData())
        event.setAccepted(True)  # keep dragged item from coming back to cursor on macOS
        self.handleDrop(action, data)

    def changeEvent(self, event: QEvent):
        if event.type() == QEvent.Type.PaletteChange:
            # Recolor some widgets when palette changes (light to dark or vice-versa).
            # Tested in KDE Plasma 6 and macOS 14.5.
            logger.debug("Dispatching restyle signal")
            GFApplication.instance().restyle.emit()

    # -------------------------------------------------------------------------
    # Menu bar

    def fillGlobalMenuBar(self):
        menubar = self.globalMenuBar
        menubar.clear()

        fileMenu = menubar.addMenu(_("&File"))
        editMenu = menubar.addMenu(_("&Edit"))
        viewMenu = menubar.addMenu(_("&View"))
        repoMenu = menubar.addMenu(_("&Repo"))
        helpMenu = menubar.addMenu(_("&Help"))

        fileMenu.setObjectName("MWFileMenu")
        editMenu.setObjectName("MWEditMenu")
        viewMenu.setObjectName("MWViewMenu")
        repoMenu.setObjectName("MWRepoMenu")
        helpMenu.setObjectName("MWHelpMenu")

        for menu in fileMenu, editMenu, viewMenu, repoMenu, helpMenu:
            menu.setToolTipsVisible(True)

        self.repoMenu = repoMenu

        # -------------------------------------------------------------

        ActionDef.addToQMenu(
            fileMenu,

            ActionDef(_("&New Repository…"), self.newRepo,
                      shortcuts=QKeySequence.StandardKey.New, icon="folder-new",
                      tip=_("Create an empty Git repo")),

            ActionDef(_("C&lone Repository…"), self.cloneDialog,
                      shortcuts="Ctrl+Shift+N", icon="folder-download",
                      tip=_("Download a Git repo and open it")),

            ActionDef.SEPARATOR,

            ActionDef(_("&Open Repository…"), self.openDialog,
                      shortcuts=QKeySequence.StandardKey.Open, icon="folder-open",
                      tip=_("Open a Git repo on your machine")),

            ActionDef(_("Open &Recent"),
                      icon="folder-open-recent",
                      tip=_("List of recently opened Git repos"),
                      objectName="RecentMenuPlaceholder"),

            ActionDef.SEPARATOR,

            TaskBook.action(self, tasks.ApplyPatchFile),
            TaskBook.action(self, tasks.ApplyPatchFileReverse),

            ActionDef.SEPARATOR,

            ActionDef(_("&Settings…"), self.openPrefsDialog,
                      shortcuts=QKeySequence.StandardKey.Preferences, icon="configure",
                      menuRole=QAction.MenuRole.PreferencesRole,
                      tip=_("Configure {app}", app=qAppName())),

            TaskBook.action(self, tasks.SetUpGitIdentity, taskArgs=('', False)
                            ).replace(menuRole=QAction.MenuRole.ApplicationSpecificRole),

            ActionDef.SEPARATOR,

            ActionDef(_("&Close Tab"), self.dispatchCloseCommand,
                      shortcuts=QKeySequence.StandardKey.Close, icon="document-close",
                      tip=_("Close current repository tab")),

            ActionDef(_("&Quit"), self.close,
                      shortcuts=QKeySequence.StandardKey.Quit, icon="application-exit",
                      tip=_("Quit {app}", app=qAppName()),
                      menuRole=QAction.MenuRole.QuitRole),
        )

        # -------------------------------------------------------------

        ActionDef.addToQMenu(
            editMenu,

            ActionDef(_("&Find…"), lambda: self.dispatchSearchCommand(),
                      shortcuts=GlobalShortcuts.find, icon="edit-find",
                      tip=_("Search for a piece of text in commit messages, the current diff, or the name of a file")),

            ActionDef(_("Find Next"), lambda: self.dispatchSearchCommand(SearchBar.Op.NEXT),
                      shortcuts=QKeySequence.StandardKey.FindNext,
                      tip=_("Find next occurrence")),

            ActionDef(_("Find Previous"), lambda: self.dispatchSearchCommand(SearchBar.Op.PREVIOUS),
                      shortcuts=QKeySequence.StandardKey.FindPrevious,
                      tip=_("Find previous occurrence"))
        )

        # -------------------------------------------------------------

        ActionDef.addToQMenu(
            repoMenu,
            *RepoWidget.contextMenuItemsByProxy(self, self.currentRepoWidget),
        )

        # -------------------------------------------------------------

        ActionDef.addToQMenu(
            viewMenu,
            self.mainToolBar.toggleViewAction(),
            ActionDef(englishTitleCase(_("Show status bar")), self.toggleStatusBar, objectName="ShowStatusBarAction"),
            ActionDef(englishTitleCase(_("Show menu bar")), self.toggleMenuBar, objectName="ShowMenuBarAction"),
            ActionDef.SEPARATOR,
            TaskBook.action(self, tasks.JumpToUncommittedChanges, accel="U"),
            TaskBook.action(self, tasks.JumpToHEAD, accel="H"),
            ActionDef.SEPARATOR,
            ActionDef(_("Focus on Sidebar"), self.focusSidebar, shortcuts="Alt+1"),
            ActionDef(_("Focus on Commit Log"), self.focusGraph, shortcuts="Alt+2"),
            ActionDef(_("Focus on File List"), self.focusFiles, shortcuts="Alt+3"),
            ActionDef(_("Focus on Code View"), self.focusDiff, shortcuts="Alt+4"),
            ActionDef.SEPARATOR,
            ActionDef(_("Next File"), self.nextFile, shortcuts="Ctrl+]"),
            ActionDef(_("Previous File"), self.previousFile, shortcuts="Ctrl+["),
            ActionDef.SEPARATOR,
            ActionDef(_("&Next Tab"), self.nextTab, shortcuts="Ctrl+Shift+]" if MACOS else "Ctrl+Tab"),
            ActionDef(_("&Previous Tab"), self.previousTab, shortcuts="Ctrl+Shift+[" if MACOS else "Ctrl+Shift+Tab"),
            ActionDef.SEPARATOR,
            TaskBook.action(self, tasks.JumpBack),
            TaskBook.action(self, tasks.JumpForward),
        )

        if settings.DEVDEBUG:
            a = viewMenu.addAction(_("Navigation Log"), lambda: logger.info(self.currentRepoWidget().navHistory.getTextLog()))
            a.setShortcut("Alt+Down")

        ActionDef.addToQMenu(
            viewMenu,

            ActionDef.SEPARATOR,

            ActionDef(
                _("&Refresh"),
                lambda: self.currentRepoWidget().refreshRepo(),
                shortcuts=GlobalShortcuts.refresh,
                icon="SP_BrowserReload",
                tip=_("Check for changes in the repo (on the local filesystem only – will not fetch remotes)"),
            ),

            ActionDef(
                _("Reloa&d"),
                lambda: self.currentRepoWidget().primeRepo(force=True),
                shortcuts="Ctrl+F5",
                tip=_("Reopen the repo from scratch"),
            ),
        )

        self.showStatusBarAction = viewMenu.findChild(QAction, "ShowStatusBarAction")
        self.showMenuBarAction = viewMenu.findChild(QAction, "ShowMenuBarAction")
        self.showMenuBarAction.setVisible(not MACOS)

        # -------------------------------------------------------------

        a = helpMenu.addAction(_("&About {0}", qAppName()), lambda: AboutDialog.popUp(self))
        a.setIcon(stockIcon("gitfourchette"))
        a.setMenuRole(QAction.MenuRole.AboutRole)

        a = helpMenu.addAction(_("{0} User’s Guide", qAppName()),
                               lambda: QDesktopServices.openUrl(QUrl(USERS_GUIDE_URL)))
        a.setIcon(stockIcon("help-contents"))

        helpMenu.addSeparator()

        a = helpMenu.addAction(_("Open Trash…"), self.openRescueFolder)
        a.setIcon(stockIcon("SP_TrashIcon"))
        a.setToolTip(_("Explore changes that you may have discarded by mistake"))

        a = helpMenu.addAction(_("Empty Trash…"), self.clearRescueFolder)
        a.setToolTip(_("Delete all discarded changes from the trash folder"))

        # -------------------------------------------------------------

        recentAction = fileMenu.findChild(QAction, "RecentMenuPlaceholder")
        self.recentMenu = QMenu(fileMenu)
        recentAction.setMenu(self.recentMenu)
        self.recentMenu.setObjectName("RecentMenu")
        self.recentMenu.setToolTipsVisible(True)
        self.fillRecentMenu()

        self.autoHideMenuBar.reconnectToMenus()

    def fillRecentMenu(self):
        def onClearRecents():
            settings.history.clearRepoHistory()
            settings.history.write()
            self.fillRecentMenu()

        self.recentMenu.clear()
        for path in settings.history.getRecentRepoPaths(settings.prefs.maxRecentRepos):
            nickname = settings.history.getRepoNickname(path, strict=True)
            caption = compactPath(path)
            if nickname:
                caption += f" ({tquo(nickname)})"
            caption = escamp(caption)
            action = self.recentMenu.addAction(caption, lambda p=path: self.openRepo(p, exactMatch=True))
            action.setToolTip(path)
        self.recentMenu.addSeparator()

        clearAction = self.recentMenu.addAction(_("Clear List"), onClearRecents)
        clearAction.setToolTip(_("Clear the list of recently opened repositories"))
        clearAction.setIcon(stockIcon("edit-clear-history"))

        self.welcomeWidget.ui.recentReposButton.setMenu(self.recentMenu)

        self.mainToolBar.recentAction.setMenu(self.recentMenu)

    def showMenuBarHiddenWarning(self):
        return showInformation(
            self, _("Menu bar hidden"),
            _("The menu bar is now hidden. Press the Alt key to toggle it."))

    # -------------------------------------------------------------------------
    # Tabs

    def currentRepoWidget(self) -> RepoWidget:
        rw = self.tabs.currentWidget()
        if rw is None:
            raise NoRepoWidgetError()
        assert isinstance(rw, RepoWidget)
        return rw

    def onTabCurrentWidgetChanged(self):
        try:
            w = self.currentRepoWidget()
        except NoRepoWidgetError:
            self.mainToolBar.observeRepoWidget(None)
            return

        # Get out of welcome widget
        self.welcomeStack.setCurrentWidget(self.tabs)

        # Refresh window title before loading
        w.refreshWindowChrome()
        self.mainToolBar.observeRepoWidget(w)

        if w.uiReady:
            # Refreshing the repo may lock up the UI for a split second.
            # Respond to tab change now to improve perceived snappiness.
            w.restoreSplitterStates()  # Restore splitters now to prevent flicker
            GFApplication.instance().processEventsNoInput()
        else:
            # setupUi may take a sec, so show placeholder widget now.
            w.setPlaceholderWidgetOpenRepoProgress()
            GFApplication.instance().processEventsNoInput()
            # And prime the UI
            w.setupUi()

        assert w.uiReady

        if w.isLoaded:
            # Trigger repo refresh.
            w.refreshRepo()
            w.refreshWindowChrome()
        elif w.allowAutoLoad:
            # Tab was lazy-loaded.
            w.primeRepo()

    def generateTabContextMenu(self, i: int):
        if i < 0:  # Right mouse button released outside tabs
            return None

        rw: RepoWidget = self.tabs.widget(i)
        menu = QMenu(self)
        menu.setObjectName("MWRepoTabContextMenu")

        anyOtherLoadedTabs = any(tab is not rw and tab.repoModel for tab in self.tabs.widgets())

        ActionDef.addToQMenu(
            menu,
            ActionDef(_("Close Tab"), lambda: self.closeTab(i), shortcuts=QKeySequence.StandardKey.Close),
            ActionDef(_("Close Other Tabs"), lambda: self.closeOtherTabs(i), enabled=self.tabs.count() > 1),
            ActionDef(_("Unload Other Tabs"), lambda: self.unloadOtherTabs(i), enabled=self.tabs.count() > 1 and anyOtherLoadedTabs),
            ActionDef.SEPARATOR,
            *rw.pathsMenuItems(),
            ActionDef.SEPARATOR,
            ActionDef(_("Configure Tabs…"), lambda: openPrefsDialog(self, "tabCloseButton")),
        )

        return menu

    def onTabContextMenu(self, globalPoint: QPoint, i: int):
        if i < 0:  # Right mouse button released outside tabs
            return

        menu = self.generateTabContextMenu(i)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.popup(globalPoint)

    def onTabDoubleClicked(self, i: int):
        if i < 0:
            return
        rw: RepoWidget = self.tabs.widget(i)
        if settings.prefs.doubleClickTabOpensFolder:
            rw.openRepoFolder()

    # -------------------------------------------------------------------------
    # Repo loading

    def openRepo(self, path: str, exactMatch=True) -> RepoWidget | None:
        try:
            rw = self._openRepo(path, exactMatch=exactMatch)
        except BaseException as exc:
            excMessageBox(
                exc,
                _("Open repository"),
                _("Couldn’t open the repository at {0}.", bquo(path)),
                parent=self,
                icon='warning')
            return None

        self.saveSession()
        return rw

    def _openRepo(self, path: str, foreground=True, tabIndex=-1, exactMatch=True, locator=NavLocator.Empty) -> RepoWidget:
        # Make sure the path exists
        if not os.path.exists(path):
            raise FileNotFoundError(_("There’s nothing at this path."))

        # Get the workdir
        if exactMatch:
            workdir = path
        else:
            with RepoContext(path) as repo:
                if repo.is_bare:
                    raise NotImplementedError(_("Sorry, {app} doesn’t support bare repositories.", app=qAppName()))
                workdir = repo.workdir

        # First check that we don't have a tab for this repo already
        for i in range(self.tabs.count()):
            existingRW: RepoWidget = self.tabs.widget(i)
            with suppress(FileNotFoundError):  # if existingRW has illegal workdir, this exception may be raised
                if os.path.samefile(workdir, existingRW.workdir):
                    existingRW.pendingLocator = locator
                    self.tabs.setCurrentIndex(i)
                    return existingRW

        # Create a RepoWidget
        rw = RepoWidget(self, workdir, lazy=not foreground)
        rw.setSharedSplitterSizes(self.sharedSplitterSizes)

        # Hook RepoWidget signals
        rw.nameChange.connect(lambda: self.onRepoNameChange(rw))
        rw.requestAttention.connect(lambda: self.onRepoRequestsAttention(rw))
        rw.openRepo.connect(lambda path, locator: self.openRepoNextTo(rw, path, locator))
        rw.openPrefs.connect(self.openPrefsDialog)

        rw.statusMessage.connect(self.statusBar2.showMessage)
        rw.busyMessage.connect(self.statusBar2.showBusyMessage)
        rw.clearStatus.connect(self.statusBar2.clearMessage)

        # Create a tab for the RepoWidget
        with QSignalBlockerContext(self.tabs):
            title = escamp(rw.getTitle())
            tabIndex = self.tabs.insertTab(tabIndex, rw, title)
            self.tabs.setTabTooltip(tabIndex, compactPath(workdir))
            if foreground:
                self.tabs.setCurrentIndex(tabIndex)
                self.mainToolBar.observeRepoWidget(rw)

        # Switch away from WelcomeWidget
        self.welcomeStack.setCurrentWidget(self.tabs)

        # Load repo now
        if foreground:
            rw.pendingLocator = locator
            self.onTabCurrentWidgetChanged()

        return rw

    # -------------------------------------------------------------------------

    def onRegainForeground(self):
        if QGuiApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
            return
        if not settings.prefs.autoRefresh:
            return
        with suppress(NoRepoWidgetError):
            self.currentRepoWidget().refreshRepo()

    def onRepoNameChange(self, rw: RepoWidget):
        self.refreshTabText(rw)
        if rw.isVisible():
            rw.refreshWindowChrome()
            rw.sidebar.sidebarModel.refreshRepoName()
        self.fillRecentMenu()

    def onRepoRequestsAttention(self, rw: RepoWidget):
        i = self.tabs.indexOf(rw)
        self.tabs.requestAttention(i)

    # -------------------------------------------------------------------------
    # View menu

    def toggleStatusBar(self):
        settings.prefs.showStatusBar = not settings.prefs.showStatusBar
        settings.prefs.setDirty()
        self.refreshPrefs("showStatusBar")

    def toggleMenuBar(self):
        settings.prefs.showMenuBar = not settings.prefs.showMenuBar
        settings.prefs.setDirty()
        self.refreshPrefs("showMenuBar")
        if not settings.prefs.showMenuBar:
            self.showMenuBarHiddenWarning()

    def selectUncommittedChanges(self):
        self.currentRepoWidget().jump(NavLocator.inWorkdir())

    def selectHead(self):
        self.currentRepoWidget().jump(NavLocator.inRef("HEAD"))

    def focusSidebar(self):
        self.currentRepoWidget().sidebar.setFocus()

    def focusGraph(self):
        self.currentRepoWidget().graphView.setFocus()

    def focusFiles(self):
        rw = self.currentRepoWidget()
        context = rw.navLocator.context
        if context == NavContext.COMMITTED:
            rw.committedFiles.setFocus()
        else:
            target = rw.stagedFiles if context == NavContext.STAGED else rw.dirtyFiles
            fallback = rw.dirtyFiles if context == NavContext.STAGED else rw.stagedFiles
            if not target.isEmpty() or fallback.isEmpty():
                target.setFocus()
            else:
                fallback.setFocus()

    def focusDiff(self):
        rw = self.currentRepoWidget()
        if rw.specialDiffView.isVisibleTo(rw):
            rw.specialDiffView.setFocus()
        elif rw.conflictView.isVisibleTo(rw):
            rw.conflictView.setFocus()
        else:
            rw.diffView.setFocus()

    def nextFile(self):
        self.currentRepoWidget().diffArea.selectNextFile(True)

    def previousFile(self):
        self.currentRepoWidget().diffArea.selectNextFile(False)

    # -------------------------------------------------------------------------
    # Help menu

    def openRescueFolder(self):
        trash = Trash.instance()
        if trash.exists():
            openFolder(trash.trashDir)
        else:
            showInformation(
                self,
                _("Open trash folder"),
                _("There’s no trash folder. Perhaps you haven’t discarded a change with {0} yet.", qAppName()))

    def clearRescueFolder(self):
        trash = Trash.instance()
        sizeOnDisk, patchCount = trash.size()

        if patchCount <= 0:
            showInformation(
                self,
                _("Clear trash folder"),
                _("There are no discarded changes to delete."))
            return

        humanSize = self.locale().formattedDataSize(sizeOnDisk)

        askPrompt = paragraphs(
            _n("Do you want to permanently delete <b>{n}</b> discarded patch?",
               "Do you want to permanently delete <b>{n}</b> discarded patches?", patchCount),
            _("This will free up {0} on disk.", escape(humanSize)),
            _("This cannot be undone!")
        )

        askConfirmation(
            parent=self,
            title=_("Clear trash folder"),
            text=askPrompt,
            callback=lambda: trash.clear(),
            okButtonText=_("Delete permanently"),
            okButtonIcon=stockIcon("SP_DialogDiscardButton"))

    # -------------------------------------------------------------------------
    # File menu callbacks

    def newRepo(self, path="", detectParentRepo=True, allowNonEmptyDirectory=False):
        if not path:
            qfd = PersistentFileDialog.saveFile(self, "NewRepo", _("New repository"))
            qfd.setFileMode(QFileDialog.FileMode.Directory)
            qfd.setLabelText(QFileDialog.DialogLabel.Accept, _("&Create repo here"))
            qfd.fileSelected.connect(self.newRepo)
            qfd.show()
            return

        parentRepo: str = ""
        if detectParentRepo:
            # macOS's native file picker may return a directory that doesn't
            # exist yet (it expects us to create it ourselves). libgit2 won't
            # detect the parent repo if the directory doesn't exist.
            parentDetectionPath = path
            if not os.path.exists(parentDetectionPath):
                parentDetectionPath = os.path.dirname(parentDetectionPath)

            parentRepo = pygit2.discover_repository(parentDetectionPath) or ""

        if not detectParentRepo or not parentRepo:
            if not allowNonEmptyDirectory and os.path.exists(path) and os.listdir(path):
                message = _("Are you sure you want to initialize a Git repository in {0}? "
                            "This directory isn’t empty.", bquo(path))
                askConfirmation(self, _("Directory isn’t empty"), message, messageBoxIcon='warning',
                                callback=lambda: self.newRepo(path, detectParentRepo, allowNonEmptyDirectory=True))
                return

            try:
                pygit2.init_repository(path)
                return self.openRepo(path, exactMatch=True)
            except Exception as exc:
                message = _("Couldn’t create an empty repository in {0}.", bquo(path))
                excMessageBox(exc, _("New repository"), message, parent=self, icon='warning')

        if parentRepo:
            myBasename = os.path.basename(path)

            parentRepo = os.path.normpath(parentRepo)
            parentWorkdir = os.path.dirname(parentRepo) if os.path.basename(parentRepo) == ".git" else parentRepo
            parentBasename = os.path.basename(parentWorkdir)

            if parentRepo == path or parentWorkdir == path:
                message = paragraphs(
                    _("A repository already exists here:"),
                    escape(compactPath(parentWorkdir)))
                qmb = asyncMessageBox(
                    self, 'information', _("Repository already exists"), message,
                    QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel)
                qmb.button(QMessageBox.StandardButton.Open).setText(_("&Open existing repo"))
                qmb.accepted.connect(lambda: self.openRepo(parentWorkdir, exactMatch=True))
                qmb.show()
            else:
                displayPath = compactPath(path)
                commonLength = len(os.path.commonprefix([displayPath, compactPath(parentWorkdir)]))
                i1 = commonLength - len(parentBasename)
                i2 = commonLength
                dp1 = escape(displayPath[: i1])
                dp2 = escape(displayPath[i1: i2])
                dp3 = escape(displayPath[i2:])
                muted = mutedTextColorHex(self)
                prettyPath = (f"<div style='white-space: pre;'>"
                              f"<span style='color: {muted};'>{dp1}</span>"
                              f"<b>{dp2}</b>"
                              f"<span style='color: {muted};'>{dp3}</span></div>")

                message = paragraphs(
                    _("An existing repository, {0}, was found in a parent folder of this location:", bquoe(parentBasename)),
                    prettyPath,
                    _("Are you sure you want to create {0} within the existing repo?", hquoe(myBasename)))

                qmb = asyncMessageBox(
                    self, 'information', _("Repository found in parent folder"), message,
                    QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)

                openButton = qmb.button(QMessageBox.StandardButton.Open)
                openButton.setText(_("&Open {0}", lquoe(parentBasename)))
                openButton.clicked.connect(lambda: self.openRepo(parentWorkdir, exactMatch=True))

                createButton = qmb.button(QMessageBox.StandardButton.Ok)
                createButton.setText(_("&Create {0}", lquoe(myBasename)))
                createButton.clicked.connect(lambda: self.newRepo(path, detectParentRepo=False))

                qmb.show()

    def cloneDialog(self, initialUrl: str = ""):
        dlg = CloneDialog(initialUrl, self)

        dlg.cloneSuccessful.connect(lambda path: self.openRepo(path))

        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.show()

    def openDialog(self):
        qfd = PersistentFileDialog.openDirectory(self, "NewRepo", _("Open repository"))
        qfd.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)  # don't leak dialog
        qfd.fileSelected.connect(lambda path: self.openRepo(path, exactMatch=False))
        qfd.show()

    # -------------------------------------------------------------------------
    # Tab management

    def dispatchCloseCommand(self):
        if self.isActiveWindow():
            self.closeCurrentTab()
        elif isinstance(QApplication.activeWindow(), DiffView):
            QApplication.activeWindow().close()

    def closeCurrentTab(self):
        if self.tabs.count() == 0:  # don't attempt to close if no tabs are open
            QApplication.beep()
            return

        self.closeTab(self.tabs.currentIndex())

    def closeTab(self, index: int, singleTab: bool = True):
        widget = self.tabs.widget(index)
        widget.close()  # will call RepoWidget.cleanup
        self.tabs.removeTab(index)
        widget.deleteLater()

        # If that was the last tab, back to welcome widget
        if self.tabs.count() == 0:
            self.welcomeStack.setCurrentWidget(self.welcomeWidget)
            self.setWindowTitle(qAppName())

        if singleTab:
            self.saveSession()
            gc.collect()

    def closeOtherTabs(self, index: int):
        # First, set this tab as active so an active tab that gets closed doesn't trigger other tabs to load.
        self.tabs.setCurrentIndex(index)

        # Now close all tabs in reverse order but skip the index we want to keep.
        start = self.tabs.count()-1
        for i in range(start, -1, -1):
            if i != index:
                self.closeTab(i, False)

        self.saveSession()
        gc.collect()

    def unloadOtherTabs(self, index: int):
        # First, set this tab as active so an active tab that gets closed doesn't trigger other tabs to load.
        self.tabs.setCurrentIndex(index)

        # Now close all tabs in reverse order but skip the index we want to keep.
        numUnloaded = 0
        for i in range(self.tabs.count()):
            if i == index:
                continue
            rw: RepoWidget = self.tabs.widget(i)
            if rw.repoModel:
                numUnloaded += 1
            rw.cleanup()

        self.statusBar2.showMessage(_n("{n} background tab unloaded.", "{n} background tabs unloaded.", numUnloaded))
        gc.collect()
        self.statusBar2.update()

    def closeAllTabs(self):
        start = self.tabs.count() - 1
        with QSignalBlockerContext(self.tabs):  # Don't let awaken unloaded tabs
            for i in range(start, -1, -1):  # Close tabs in reverse order
                self.closeTab(i, False)

        self.onTabCurrentWidgetChanged()

    def refreshTabText(self, rw):
        index = self.tabs.indexOf(rw)
        title = escamp(rw.getTitle())
        self.tabs.setTabText(index, title)

    def openRepoNextTo(self, rw, path: str, locator: NavLocator = NavLocator.Empty):
        index = self.tabs.indexOf(rw)
        if index >= 0:
            index += 1
        return self._openRepo(path, tabIndex=index, exactMatch=True, locator=locator)

    def nextTab(self):
        if self.tabs.count() == 0:
            QApplication.beep()
            return
        index = self.tabs.currentIndex()
        index += 1
        index %= self.tabs.count()
        self.tabs.setCurrentIndex(index)

    def previousTab(self):
        if self.tabs.count() == 0:
            QApplication.beep()
            return
        index = self.tabs.currentIndex()
        index += self.tabs.count() - 1
        index %= self.tabs.count()
        self.tabs.setCurrentIndex(index)

    # -------------------------------------------------------------------------
    # Session management

    def restoreSession(self, session: settings.Session):
        # Note: window geometry, despite being part of the session file, is
        # restored in application.py to avoid flashing a window with incorrect
        # dimensions on boot

        self.sharedSplitterSizes = copy.deepcopy(session.splitterSizes)

        # Stop here if there are no tabs to load
        if not session.tabs:
            return

        errors = []

        # We might not be able to load all tabs, so we may have to adjust the active tab index.
        activeTab = -1
        successfulRepos = []

        # Lazy-loading: prepare all tabs, but don't load the repos (foreground=False).
        for i, path in enumerate(session.tabs):
            try:
                newRepoWidget = self._openRepo(path, exactMatch=True, foreground=False)
            except (GitError, OSError, NotImplementedError) as exc:
                # GitError: most errors thrown by pygit2
                # OSError: e.g. permission denied
                # NotImplementedError: e.g. shallow/bare repos
                errors.append((path, exc))
                continue

            # _openRepo may still return None without throwing an exception in case of failure
            if newRepoWidget is None:
                continue

            successfulRepos.append(path)

            if i == session.activeTabIndex:
                activeTab = self.tabs.count()-1

        # If we failed to load anything, tell the user about it
        if errors:
            self._reportSessionErrors(errors)

        # Update history (don't write it yet - onTabCurrentWidgetChanged will do it below)
        for path in reversed(successfulRepos):
            settings.history.addRepo(path)
        self.fillRecentMenu()

        # Fall back to tab #0 if desired tab couldn't be restored (otherwise welcome page will stick around)
        if activeTab < 0 and len(successfulRepos) >= 1:
            activeTab = 0

        # Set current tab and load its repo.
        if activeTab >= 0:
            self.tabs.setCurrentIndex(activeTab)
            self.onTabCurrentWidgetChanged()  # needed to trigger loading on tab #0

    def _reportSessionErrors(self, errors: Sequence[tuple[str, BaseException]]):
        numErrors = len(errors)
        text = _n("The session couldn’t be restored fully because a repository failed to load:",
                  "The session couldn’t be restored fully because {n} repositories failed to load:", numErrors)
        qmb = asyncMessageBox(self, 'warning', _("Restore session"), text)
        addULToMessageBox(qmb, [f"<b>{compactPath(path)}</b><br>{exc}" for path, exc in errors])
        qmb.show()

    def saveSession(self, writeNow=False):
        session = settings.Session()
        session.windowGeometry = self.saveGeometry().data()
        session.splitterSizes = self.sharedSplitterSizes.copy()
        session.tabs = [self.tabs.widget(i).workdir for i in range(self.tabs.count())]
        session.activeTabIndex = self.tabs.currentIndex()
        session.setDirty()
        if writeNow:
            session.write()

    def closeEvent(self, event: QCloseEvent):
        QApplication.instance().removeEventFilter(self)

        # Save session before closing all tabs.
        self.saveSession(writeNow=True)

        # Close all tabs so RepoWidgets release all their resources.
        # Important so unit tests wind down properly!
        self.closeAllTabs()

        event.accept()

    # -------------------------------------------------------------------------
    # Drag and drop

    @staticmethod
    def getDropOutcomeFromLocalFilePath(path: str) -> tuple[Literal["", "patch", "open"], str]:
        if path.endswith(".patch"):
            return "patch", path
        else:
            return "open", path

    @staticmethod
    def getDropOutcomeFromMimeData(mime: QMimeData) -> tuple[Literal["", "patch", "open", "clone"], str]:
        if mime.hasUrls():
            try:
                url: QUrl = mime.urls()[0]
            except IndexError:
                return "", ""

            if url.isLocalFile():
                path = url.toLocalFile()
                return MainWindow.getDropOutcomeFromLocalFilePath(path)
            else:
                return "clone", url.toString()

        elif mime.hasText():
            text = mime.text()
            text = text.strip()
            if os.path.isabs(text) and os.path.exists(text):
                return "open", text
            elif text.startswith(("ssh://", "git+ssh://", "https://", "http://")):
                return "clone", text
            elif re.match(r"^[a-zA-Z0-9-_.]+@.+:.+", text):
                return "clone", text
            else:
                return "", text

        else:
            return "", ""

    def handleDrop(self, action: str, data: str):
        if action == "clone":
            self.cloneDialog(data)
        elif action == "open":
            self.openRepo(data, exactMatch=False)
        elif action == "patch":
            tasks.ApplyPatchFile.invoke(self, False, data)
        else:
            warnings.warn(f"Unsupported drag-and-drop outcome {action}")

    # -------------------------------------------------------------------------
    # Prefs

    def refreshPrefs(self, *prefDiff: str):
        app = GFApplication.instance()

        # Apply new style
        if "qtStyle" in prefDiff:
            app.applyQtStylePref(forceApplyDefault=True)

        if "verbosity" in prefDiff:
            app.applyLoggingLevelPref()

        if "language" in prefDiff:
            app.applyLanguagePref()
            self.fillGlobalMenuBar()

        if "maxRecentRepos" in prefDiff:
            self.fillRecentMenu()

        self.statusBar2.setVisible(settings.prefs.showStatusBar)
        self.statusBar2.enableMemoryIndicator(settings.DEVDEBUG)

        self.mainToolBar.setVisible(settings.prefs.showToolBar)

        self.tabs.refreshPrefs()
        self.autoHideMenuBar.refreshPrefs()
        for rw in self.tabs.widgets():
            rw.refreshPrefs(*prefDiff)

        self.showStatusBarAction.setCheckable(True)
        self.showStatusBarAction.setChecked(settings.prefs.showStatusBar)

        self.showMenuBarAction.setCheckable(True)
        self.showMenuBarAction.setChecked(settings.prefs.showMenuBar)

    def onAcceptPrefsDialog(self, prefDiff: dict):
        # Early out if the prefs didn't change
        if not prefDiff:
            return

        syntaxWasOff = settings.prefs.syntaxHighlighting == settings.PygmentsPresets.Off
        syntaxNowOff = prefDiff.get('syntaxHighlighting', '') == settings.PygmentsPresets.Off

        # Apply changes from prefDiff to the actual prefs
        for k, v in prefDiff.items():
            settings.prefs.__dict__[k] = v

        # Reset "don't show again" if necessary
        if settings.prefs.resetDontShowAgain:
            settings.prefs.dontShowAgain = []
            settings.prefs.resetDontShowAgain = False

        # Write prefs to disk
        settings.prefs.write()

        # Notify widgets
        self.refreshPrefs(*prefDiff.keys())

        # Warn if changed any setting that requires a reload
        autoReload = [
            # Those settings a reload of the current diff
            "showStrayCRs",
            "colorblind",
            "largeFileThresholdKB",
            "imageFileThresholdKB",
            "contextLines",
            "maxCommits",
            "renderSvg",
        ]

        # Force reloading the diff when toggling syntax highlighting.
        # If we're merely changing color schemes, a quick refreshPrefs suffices.
        if syntaxWasOff ^ syntaxNowOff:
            autoReload.append("syntaxHighlighting")

        warnIfChanged = [
            "chronologicalOrder",  # need to reload entire commit sequence
            "maxCommits",
        ]

        warnIfNeedRestart = [
            "language",
            "forceQtApi",
            "pygmentsPlugins",
        ]

        if "showMenuBar" in prefDiff and not prefDiff["showMenuBar"]:
            self.showMenuBarHiddenWarning()

        if any(k in warnIfNeedRestart for k in prefDiff):
            showInformation(
                self, _("Apply Settings"),
                _("You may need to restart {app} for the new settings to take effect fully.", app=qAppName()))
        elif any(k in warnIfChanged for k in prefDiff) and self.tabs.count():
            qmb = asyncMessageBox(
                self, "question", _("Apply Settings"),
                _("The new settings won’t take effect fully until you reload the current repositories."),
                buttons=QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            reloadButton = qmb.button(QMessageBox.StandardButton.Ok)
            reloadButton.setText(_("&Reload"))
            reloadButton.clicked.connect(lambda: self.unloadOtherTabs(self.tabs.currentIndex()))
            reloadButton.clicked.connect(lambda: self.currentRepoWidget().primeRepo(force=True))
            cancelButton = qmb.button(QMessageBox.StandardButton.Cancel)
            cancelButton.setText(_("&Not Now"))
            qmb.show()

        # If any changed setting matches autoReload, schedule a "forced" refresh of all loaded RepoWidgets
        if any(k in autoReload for k in prefDiff):
            for rw in self.tabs.widgets():
                assert isinstance(rw, RepoWidget)
                if not rw.isLoaded:
                    continue
                locator = rw.pendingLocator or rw.navLocator
                locator = locator.withExtraFlags(NavFlags.ForceDiff | NavFlags.ForceRecreateDocument)
                rw.refreshRepo(jumpTo=locator)

    def openPrefsDialog(self, focusOn: str = ""):
        dlg = PrefsDialog(self, focusOn)
        dlg.accepted.connect(lambda: self.onAcceptPrefsDialog(dlg.prefDiff))
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)  # don't leak dialog
        dlg.show()
        return dlg

    # -------------------------------------------------------------------------
    # Find

    def dispatchSearchCommand(self, op: SearchBar.Op = SearchBar.Op.START):
        activeWindow = QApplication.activeWindow()
        if activeWindow is self and self.currentRepoWidget():
            self.currentRepoWidget().dispatchSearchCommand(op)
        elif activeWindow.objectName() == DiffView.DetachedWindowObjectName:
            # Systems without a global main menu (i.e. anything but macOS)
            # take a different path to search a detached DiffView window.
            detachedDiffView: DiffView = activeWindow.findChild(DiffView)
            detachedDiffView.search(op)
        else:
            QApplication.beep()
