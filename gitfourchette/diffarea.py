# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import typing
from typing import Literal

from gitfourchette.diffview.diffview import DiffView
from gitfourchette.diffview.specialdiffview import SpecialDiffView
from gitfourchette.filelists.committedfiles import CommittedFiles
from gitfourchette.filelists.dirtyfiles import DirtyFiles
from gitfourchette.filelists.filelist import FileList
from gitfourchette.filelists.stagedfiles import StagedFiles
from gitfourchette.forms.banner import Banner
from gitfourchette.forms.conflictview import ConflictView
from gitfourchette.forms.contextheader import ContextHeader
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.nav import NavContext, NavLocator, NavFlags
from gitfourchette.qt import *
from gitfourchette.tasks import TaskBook, AmendCommit, NewCommit, NewStash
from gitfourchette.toolbox import *

FileStackPage = Literal["workdir", "commit"]
DiffStackPage = Literal["text", "special", "conflict"]

FILEHEADER_HEIGHT = 24

logger = logging.getLogger(__name__)


def gridPadding():
    return QSpacerItem(3, 1, QSizePolicy.Policy.Fixed)


class DiffArea(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("CommitExplorer")

        fileStack = self._makeFileStack()
        diffContainer = self._makeDiffContainer()

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setObjectName("Split_DiffArea")

        contextHeader = ContextHeader(self)

        diffBanner = Banner(self, orientation=Qt.Orientation.Horizontal)
        diffBanner.setProperty("class", "diff")
        diffBanner.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)
        layout.addWidget(contextHeader)
        layout.addWidget(diffBanner)
        layout.addWidget(QFaintSeparator(self))
        layout.addWidget(splitter, 1)

        splitter.addWidget(fileStack)
        splitter.addWidget(diffContainer)
        splitter.setSizes([260, 500])
        splitter.setStretchFactor(0, 0)  # don't auto-stretch file lists when resizing window
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)

        self.fileStack = fileStack
        self.diffBanner = diffBanner
        self.contextHeader = contextHeader

        for passiveWidget in (
                self.diffHeader,
                self.committedHeader,
                self.dirtyHeader,
                self.stagedHeader
        ):
            passiveWidget.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        # Ignore height in size policy to keep DiffArea from jumping around when we're showing a banner.
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Ignored)
        self.setMinimumHeight(175)

    # -------------------------------------------------------------------------
    # Constructor helpers

    def _makeFileStack(self):
        dirtyContainer = self._makeDirtyContainer()
        stageContainer = self._makeStageContainer()
        committedFilesContainer = self._makeCommittedFilesContainer()

        stagingSplitter = QSplitter(Qt.Orientation.Vertical, self)
        stagingSplitter.addWidget(dirtyContainer)
        stagingSplitter.addWidget(stageContainer)
        stagingSplitter.setObjectName("Split_Staging")
        stagingSplitter.setChildrenCollapsible(False)

        fileStack = QStackedWidget()
        fileStack.addWidget(stagingSplitter)
        fileStack.addWidget(committedFilesContainer)
        return fileStack

    def _makeDirtyContainer(self):
        header = QElidedLabel(" ")
        header.setObjectName("dirtyHeader")
        header.setToolTip(_("Unstaged files: will not be included in the commit unless you stage them."))
        header.setMinimumHeight(FILEHEADER_HEIGHT)
        header.setEnabled(False)

        dirtyFiles = DirtyFiles(self)

        stageButton = QToolButton()
        stageButton.setObjectName("stageButton")
        stageButton.setText(_("Stage"))
        stageButton.setIcon(stockIcon("git-stage"))
        stageButton.setToolTip(_("Stage selected files"))
        appendShortcutToToolTip(stageButton, GlobalShortcuts.stageHotkeys[0])

        discardButton = QToolButton()
        discardButton.setObjectName("discardButton")
        discardButton.setText(_("Discard"))
        discardButton.setIcon(stockIcon("git-discard"))
        discardButton.setToolTip(_("Discard changes in selected files"))
        appendShortcutToToolTip(discardButton, GlobalShortcuts.discardHotkeys[0])

        container = QWidget()
        layout = QGridLayout(container)
        layout.setSpacing(0)  # automatic frameless list views on KDE Plasma 6 Breeze
        layout.setContentsMargins(QMargins())
        # Row 0
        layout.addItem(gridPadding(),           0, 0)
        layout.addWidget(header,                0, 1)
        layout.addWidget(stageButton,           0, 2)
        layout.addWidget(discardButton,         0, 3)
        # Row 1
        layout.addItem(QSpacerItem(1, 1),       1, 0, 1, 4)
        # Row 2
        layout.addWidget(dirtyFiles.searchBar,  2, 0, 1, 4)
        # Row 3
        layout.addWidget(dirtyFiles,            3, 0, 1, 4)
        layout.setRowStretch(3, 100)

        stageButton.clicked.connect(dirtyFiles.stage)
        discardButton.clicked.connect(dirtyFiles.discard)
        dirtyFiles.selectedCountChanged.connect(lambda n: stageButton.setEnabled(n > 0))
        dirtyFiles.selectedCountChanged.connect(lambda n: discardButton.setEnabled(n > 0))

        self.dirtyFiles = dirtyFiles
        self.dirtyHeader = header
        self.stageButton = stageButton
        self.discardButton = discardButton

        return container

    def _makeStageContainer(self):
        header = QElidedLabel(" ")
        header.setObjectName("stagedHeader")
        header.setToolTip(_("Staged files: will be included in the commit."))
        header.setMinimumHeight(FILEHEADER_HEIGHT)
        header.setEnabled(False)

        stagedFiles = StagedFiles(self)

        unstageButton = QToolButton()
        unstageButton.setObjectName("unstageButton")
        unstageButton.setText(_("Unstage"))
        unstageButton.setIcon(stockIcon("git-unstage"))
        unstageButton.setToolTip(_("Unstage selected files"))
        appendShortcutToToolTip(unstageButton, GlobalShortcuts.discardHotkeys[0])

        commitButton = QToolButton()
        commitButton.setObjectName("commitButton")
        commitButton.setText(_p("verb", "Commit"))
        commitButton.setIcon(stockIcon("git-commit", "gray=#599E5E"))
        commitButton.setToolTip(appendShortcutToToolTipText(TaskBook.tips[NewCommit], TaskBook.shortcuts[NewCommit][0]))
        commitButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        commitButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        commitButton.setAutoRaise(True)
        commitButton.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        commitButton.setMaximumHeight(FILEHEADER_HEIGHT)
        commitButton.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        # Connect signals
        unstageButton.clicked.connect(stagedFiles.unstage)
        stagedFiles.selectedCountChanged.connect(lambda n: unstageButton.setEnabled(n > 0))

        commitButton.clicked.connect(lambda: NewCommit.invoke(self))
        commitButtonMenu = ActionDef.makeQMenu(
            commitButton,
            [
                TaskBook.action(self, NewCommit),
                TaskBook.action(self, AmendCommit),
                TaskBook.action(self, NewStash),
            ])
        # Prevent shortcuts from taking over
        for action in commitButtonMenu.actions():
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        commitButton.setMenu(commitButtonMenu)

        # Lay out container
        container = QWidget()
        layout = QGridLayout(container)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)  # automatic frameless list views on KDE Plasma 6 Breeze
        # Row 0
        layout.addItem(gridPadding(),           0, 0)
        layout.addWidget(header,                0, 1)
        layout.addWidget(unstageButton,         0, 2)
        # Row 1
        layout.addItem(QSpacerItem(1, 1),       1, 0)
        # Row 2
        layout.addWidget(stagedFiles.searchBar, 2, 0, 1, 3)  # row col rowspan colspan
        layout.addWidget(stagedFiles,           3, 0, 1, 3)
        layout.addWidget(commitButton,          4, 0, 1, 3)
        layout.setRowStretch(3, 100)

        # Save references
        self.stagedHeader = header
        self.stagedFiles = stagedFiles
        self.unstageButton = unstageButton
        self.commitButton = commitButton

        return container

    def _makeCommittedFilesContainer(self):
        committedFiles = CommittedFiles(self)

        header = QElidedLabel(" ")
        header.setObjectName("committedHeader")
        header.setMinimumHeight(FILEHEADER_HEIGHT)
        header.setEnabled(False)

        container = QWidget()
        layout = QGridLayout(container)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)  # automatic frameless list views on KDE Plasma 6 Breeze
        layout.addItem(gridPadding(),               0, 0)
        layout.addWidget(header,                    0, 1)
        layout.addItem(gridPadding(),               0, 2)
        layout.addWidget(committedFiles.searchBar,  1, 0, 1, 3)
        layout.addItem(QSpacerItem(1, 1),           2, 0, 1, 3)
        layout.addWidget(committedFiles,            3, 0, 1, 3)

        self.committedFiles = committedFiles
        self.committedHeader = header
        return container

    def _makeDiffContainer(self):
        header = QLabel(" ")
        header.setObjectName("diffHeader")
        header.setMinimumHeight(FILEHEADER_HEIGHT)
        header.setContentsMargins(4, 0, 4, 0)
        # Don't let header dictate window width if displaying long filename
        header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)

        topContainer = QWidget()
        topLayout = QHBoxLayout(topContainer)
        topLayout.setContentsMargins(0, 0, 0, 0)
        topLayout.addWidget(header)

        diff = DiffView()

        diffViewContainer = QWidget()
        diffViewContainerLayout = QVBoxLayout(diffViewContainer)
        diffViewContainerLayout.setSpacing(0)
        diffViewContainerLayout.setContentsMargins(0, 0, 0, 0)
        diffViewContainerLayout.addWidget(diff.searchBar)
        diffViewContainerLayout.addWidget(diff)

        specialDiff = SpecialDiffView()

        conflict = ConflictView()
        conflictScroll = QScrollArea()
        conflictScroll.setWidget(conflict)
        conflictScroll.setWidgetResizable(True)

        stack = QStackedWidget()
        # Add widgets in same order as DiffStackPage
        stack.addWidget(diffViewContainer)
        stack.addWidget(specialDiff)
        stack.addWidget(conflictScroll)
        stack.setCurrentIndex(0)

        stackContainer = QWidget()
        layout = QVBoxLayout(stackContainer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.addWidget(topContainer)
        layout.addWidget(stack)

        self.diffHeader = header
        self.diffStack = stack
        self.conflictView = conflict
        self.specialDiffView = specialDiff
        self.diffView = diff

        return stackContainer

    def applyCustomStyling(self):
        for smallButton in self.discardButton, self.unstageButton, self.stageButton:
            smallButton.setMaximumHeight(FILEHEADER_HEIGHT)
            smallButton.setEnabled(False)
            smallButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            smallButton.setAutoRaise(True)
            smallButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        for button in self.stageButton, self.unstageButton:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        # Smaller font for header text
        for smallWidget in (
                self.contextHeader,
                self.diffHeader,
                self.committedHeader,
                self.dirtyHeader,
                self.stagedHeader,
                self.stageButton,
                self.unstageButton,
                self.discardButton,
        ):
            tweakWidgetFont(smallWidget, 90)

    # -------------------------------------------------------------------------
    # File navigation

    def selectNextFile(self, down=True):
        page = self.fileStackPage()
        widgets: list[FileList]
        if page == "commit":
            widgets = [self.committedFiles]
        elif page == "workdir":
            widgets = [self.dirtyFiles, self.stagedFiles]
        else:
            raise NotImplementedError(f"Unknown FileStackPage {page}")

        numWidgets = len(widgets)
        selections = [w.selectedIndexes() for w in widgets]
        lengths = [w.model().rowCount() for w in widgets]

        # find widget to start from: topmost widget that has any selection
        leader = -1
        for i, selection in enumerate(selections):
            if selection:
                leader = i
                break

        if leader < 0:
            # selection empty; pick first non-empty widget as leader
            leader = 0
            row = 0
            while (leader < numWidgets) and (lengths[leader] == 0):
                leader += 1
        else:
            # get selected row in leader widget - TODO: this may not be accurate when multiple rows are selected
            row = selections[leader][-1].row()

            if down:
                row += 1
                while (leader < numWidgets) and (row >= lengths[leader]):
                    # out of rows in leader widget; jump to first row in next widget
                    leader += 1
                    row = 0
            else:
                row -= 1
                while (leader >= 0) and (row < 0):
                    # out of rows in leader widget; jump to last row in prev widget
                    leader -= 1
                    if leader >= 0:
                        row = lengths[leader] - 1

        # if we have a new valid selection, apply it, otherwise bail
        if 0 <= leader < numWidgets and 0 <= row < lengths[leader]:
            widgets[leader].setFocus()
            with QSignalBlockerContext(widgets[leader]):
                widgets[leader].clearSelection()
            widgets[leader].selectRow(row)
        else:
            # No valid selection
            QApplication.beep()

            # Focus on the widget that has some selected files in it
            for w in widgets:
                if len(w.selectedIndexes()) > 0:
                    w.setFocus()
                    break

    def fileListByContext(self, context: NavContext) -> FileList:
        if context == NavContext.STAGED:
            return self.stagedFiles
        elif context == NavContext.UNSTAGED:
            return self.dirtyFiles
        else:
            return self.committedFiles

    def setUpForLocator(self, locator: NavLocator) -> NavLocator:
        """
        Show relevant FileList widget, select correct file in it,
        and adjust auxiliary widgets (stage/unstage/discard buttons).

        If the desired path isn't available in the FileList,
        returns a new locator with a blank path.
        """
        fileList = self.fileListByContext(locator.context)

        with QSignalBlockerContext(self.dirtyFiles, self.stagedFiles, self.committedFiles):
            # Select correct row in FileList
            hasFile = False
            if locator.path:
                # Fix multiple "ghost" selections in DirtyFiles/StagedFiles with JumpBackOrForward.
                if not locator.hasFlags(NavFlags.AllowMultiSelect):
                    fileList.clearSelection()
                # Select the file, if possible
                hasFile = fileList.selectFile(locator.path)

            # Blank selection?
            if not hasFile:
                locator = locator.replace(path="")
                fileList.clearSelection()

            # Special treatment for workdir
            if locator.context.isWorkdir():
                staged = locator.context == NavContext.STAGED

                # Sync workdir buttons
                self.stageButton.setEnabled(hasFile and not staged)
                self.discardButton.setEnabled(hasFile and not staged)
                self.unstageButton.setEnabled(hasFile and staged)

                # Clear selection in opposite FileList
                oppositeFileList = self.dirtyFiles if staged else self.stagedFiles
                oppositeFileList.clearSelection()
                if hasFile:
                    oppositeFileList.highlightCounterpart(locator)

            # Set correct card in fileStack (after selecting the file to avoid flashing)
            self.setFileStackPageByContext(locator.context)

        return locator

    # -------------------------------------------------------------------------
    # Clear

    def clear(self):
        with QSignalBlockerContext(self.committedFiles, self.dirtyFiles, self.stagedFiles):
            self.committedFiles.clear()
            self.dirtyFiles.clear()
            self.stagedFiles.clear()
            self.clearDocument()

    def clearDocument(self, sourceFileList: FileList | None = None):
        # Ignore clear request if it comes from a widget that doesn't have focus
        if sourceFileList and not sourceFileList.hasFocus():
            return

        # Enter empty special page
        self.specialDiffView.clear()
        self.setDiffStackPage("special")

        # Might as well free up any memory taken by DiffView document
        self.diffView.clear()

        self.diffHeader.setText(" ")

        if sourceFileList:
            locator = NavLocator(sourceFileList.navContext, sourceFileList.commitId)
        else:
            locator = NavLocator(NavContext.WORKDIR if self.fileStackPage() else NavContext.COMMITTED)
        self.setUpForLocator(locator)

    # -------------------------------------------------------------------------
    # Stacked widget helpers

    @property
    def _fileStackPageValues(self):
        return typing.get_args(FileStackPage)

    def fileStackPage(self) -> FileStackPage:
        return self._fileStackPageValues[self.fileStack.currentIndex()]

    def setFileStackPage(self, p: FileStackPage):
        self.fileStack.setCurrentIndex(self._fileStackPageValues.index(p))

    def setFileStackPageByContext(self, context: NavContext):
        page: FileStackPage = "workdir" if context.isWorkdir() else "commit"
        self.setFileStackPage(page)

    @property
    def _diffStackPageValues(self):
        return typing.get_args(DiffStackPage)

    def diffStackPage(self) -> DiffStackPage:
        return self._diffStackPageValues[self.diffStack.currentIndex()]

    def setDiffStackPage(self, p: DiffStackPage):
        self.diffStack.setCurrentIndex(self._diffStackPageValues.index(p))
