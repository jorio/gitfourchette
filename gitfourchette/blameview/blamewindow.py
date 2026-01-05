# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.application import GFApplication
from gitfourchette.blameview.blamemodel import BlameModel, TraceNode
from gitfourchette.blameview.blamescrubber import BlameScrubber
from gitfourchette.blameview.blametextedit import BlameTextEdit
from gitfourchette.blameview.blamebusyspinner import BlameBusySpinner
from gitfourchette.graphview.commitlogmodel import CommitLogModel
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavHistory, NavFlags
from gitfourchette.qt import *
from gitfourchette.tasks import Jump
from gitfourchette.toolbox import *


class BlameWindow(QWidget):
    _currentBlameWindows = []
    "Currently open BlameWindows"

    def __init__(self, blameModel: BlameModel):
        # DON'T parent the window so it doesn't sit on top of MainWindow on Wayland
        super().__init__(None)

        # Keep reference around to avoid being GC'd instantly
        BlameWindow._currentBlameWindows.append(self)

        self.setObjectName("BlameWindow")

        self.model = blameModel

        self.navHistory = NavHistory()

        # Die in tandem with RepoWidget
        blameModel.taskInvoker.destroyed.connect(self.close)

        self.textEdit = BlameTextEdit(blameModel, self)
        self.textEdit.setUpAsDetachedWindow()

        self.scrubber = BlameScrubber(blameModel, self)
        self.scrubber.activated.connect(self.onScrubberActivated)

        self.jumpButton = QToolButton()
        self.jumpButton.setText(_("Jump"))
        self.jumpButton.setToolTip(_("View this commit in the repo"))
        self.jumpButton.setIcon(stockIcon("go-window@20px"))
        self.jumpButton.clicked.connect(lambda: self.jumpToCommit())

        oldNewTipTemplate = (f"<p style='white-space: pre'>{{0}}<br>"
                             f"<span style='color: {mutedToolTipColorHex()}'>({_('Shift+Click:')} {{1}})</span>")

        self.olderButton = QToolButton()
        self.olderButton.setText(_("Older"))
        self.olderButton.clicked.connect(self.goOlder)
        self.olderButton.setToolTip(oldNewTipTemplate.format(_("Go to next older revision"), _("Jump to bottom")))
        self.olderButton.setIcon(stockIcon("go-older"))

        self.newerButton = QToolButton()
        self.newerButton.setText(_("Newer"))
        self.newerButton.clicked.connect(self.goNewer)
        self.newerButton.setToolTip(oldNewTipTemplate.format(_("Go to next newer revision"), _("Jump to top")))
        self.newerButton.setIcon(stockIcon("go-newer"))

        self.backButton = QToolButton()
        self.backButton.setText(_("Back"))
        self.backButton.clicked.connect(self.goBack)
        self.backButton.setToolTip(_("Navigate back"))
        self.backButton.setIcon(stockIcon("back"))

        self.forwardButton = QToolButton()
        self.forwardButton.setText(_("Forward"))
        self.forwardButton.clicked.connect(self.goForward)
        self.forwardButton.setToolTip(_("Navigate forward"))
        self.forwardButton.setIcon(stockIcon("forward"))

        topBar = QToolBar()
        topBar.setIconSize(QSize(20, 20))
        topBar.addWidget(self.backButton)
        topBar.addWidget(self.forwardButton)
        topBar.addSeparator()
        topBar.addWidget(self.newerButton)
        topBar.addWidget(self.olderButton)
        topBar.addWidget(self.scrubber)
        topBar.addWidget(self.jumpButton)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(QMargins())
        layout.addWidget(topBar)
        layout.addWidget(self.textEdit.searchBar)
        layout.addWidget(self.textEdit)
        layout.setSpacing(0)

        self.setTabOrder(self.scrubber, self.olderButton)
        self.setTabOrder(self.olderButton, self.newerButton)
        self.setTabOrder(self.newerButton, self.textEdit)

        self.textEdit.selectNode.connect(self.setTraceNode)
        self.textEdit.jumpToCommit.connect(self.jumpToCommit)

        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlags(Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        self.busySpinner = BlameBusySpinner(self.textEdit)
        self.textEdit.sizeChanged.connect(self.busySpinner.reposition)

        app = GFApplication.instance()
        app.mouseSideButtonPressed.connect(self.onMouseSideButtonPressed)

    # -------------------------------------------------------------------------
    # Event filters & handlers

    def onMouseSideButtonPressed(self, forward: bool):
        if not self.isActiveWindow():
            return
        delta = [-1, 1][forward]
        self.goBackOrForwardDelta(delta)

    def closeEvent(self, event: QCloseEvent):
        if (self.model.currentTask is not None
                and self.model.currentTask() is self.repoWidget.taskRunner.currentTask):
            self.repoWidget.taskRunner.killCurrentTask()
            self.repoWidget.taskRunner.joinKilledTask()

        assert self in self._currentBlameWindows
        self._currentBlameWindows.remove(self)
        super().closeEvent(event)

    # -------------------------------------------------------------------------

    def saveFilePosition(self) -> NavLocator:
        currentLocator = self.textEdit.preciseLocator()
        self.navHistory.push(currentLocator)
        return currentLocator

    def setTraceNode(self, node: TraceNode, saveFilePositionFirst=True, transposeFilePosition=True):
        from gitfourchette.tasks.blametasks import AnnotateFile
        AnnotateFile.invoke(
            self.repoWidget,
            self,
            node,
            saveFilePositionFirst,
            transposeFilePosition)

    def syncNavButtons(self):
        index = self.scrubber.currentIndex()
        count = self.scrubber.count()

        self.newerButton.setEnabled(index != 0 and count >= 2)
        self.olderButton.setEnabled(index != count - 1)

        self.backButton.setEnabled(self.navHistory.canGoBack())
        self.forwardButton.setEnabled(self.navHistory.canGoForward())

    def goNewer(self):
        if QGuiApplication.keyboardModifiers() == Qt.KeyboardModifier.ShiftModifier:
            topNode = self.model.nodeSequence[0]
            self.setTraceNode(topNode)
        else:
            self.goNewerOrOlder(-1)

    def goOlder(self):
        if QGuiApplication.keyboardModifiers() == Qt.KeyboardModifier.ShiftModifier:
            bottomNode = self.model.nodeSequence[-1]
            self.setTraceNode(bottomNode)
        else:
            self.goNewerOrOlder(1)

    def goBack(self):
        self.goBackOrForwardDelta(-1)

    def goForward(self):
        self.goBackOrForwardDelta(1)

    def goNewerOrOlder(self, delta: int):
        index = self.scrubber.currentIndex()
        index += delta
        assert 0 <= index < self.scrubber.count()
        node = self.getTraceNodeFromScrubberRow(index)
        self.setTraceNode(node)

    def goBackOrForwardDelta(self, delta: int):
        self.saveFilePosition()
        locator = self.navHistory.navigateDelta(delta)
        if not locator:
            return
        node = self.model.trace.nodeForCommit(locator.commit)
        self.setTraceNode(node, saveFilePositionFirst=False, transposeFilePosition=False)

    def onScrubberActivated(self, index: int):
        node = self.getTraceNodeFromScrubberRow(index)
        self.setTraceNode(node)

    def getTraceNodeFromScrubberRow(self, index: int) -> TraceNode:
        return self.scrubber.itemData(index, CommitLogModel.Role.TraceNode)

    def jumpToCommit(self, locator: NavLocator = NavLocator.Empty):
        if locator == NavLocator.Empty:
            locator = self.model.currentLocator
        locator = locator.withExtraFlags(NavFlags.ActivateWindow)
        Jump.invoke(self.model.taskInvoker, locator)
