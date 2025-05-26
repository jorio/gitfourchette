# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.blameview.blamemodel import BlameModel
from gitfourchette.blameview.blamescrubber import BlameScrubber
from gitfourchette.blameview.blametextedit import BlameTextEdit
from gitfourchette.graphview.commitlogmodel import CommitLogModel
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavHistory
from gitfourchette.porcelain import Oid
from gitfourchette.qt import *
from gitfourchette.repomodel import RepoModel
from gitfourchette.syntax import LexJobCache, LexerCache, LexJob
from gitfourchette.tasks import Jump
from gitfourchette.toolbox import *
from gitfourchette.trace import TraceNode, Trace, BlameCollection


class BlameWindow(QWidget):
    _currentBlameWindows = []
    "Currently open BlameWindows"

    def __init__(self, repoModel: RepoModel, taskInvoker: QWidget):
        # DON'T parent the window so it doesn't sit on top of MainWindow on Wayland
        super().__init__(None)

        # Keep reference around to avoid being GC'd instantly
        BlameWindow._currentBlameWindows.append(self)

        self.setObjectName("BlameWindow")

        self.model = BlameModel()
        self.model.taskInvoker = taskInvoker
        self.model.repoModel = repoModel

        self.navHistory = NavHistory()

        # Die in tandem with RepoWidget
        taskInvoker.destroyed.connect(self.close)

        self.textEdit = BlameTextEdit(self.model)
        self.textEdit.setUpAsDetachedWindow()
        self.textEdit.searchBar.lineEdit.setPlaceholderText(_("Find text in revision"))

        self.scrubber = BlameScrubber(self.model, self)
        self.scrubber.activated.connect(self.onScrubberActivated)

        self.jumpButton = QToolButton()
        self.jumpButton.setText(_("Jump"))
        self.jumpButton.setToolTip(_("View this commit in the repo"))
        self.jumpButton.setIcon(stockIcon("prefs-graph"))
        self.jumpButton.clicked.connect(lambda: self.jumpToCommit())

        self.olderButton = QToolButton()
        self.olderButton.setText(_("Older"))
        self.olderButton.clicked.connect(self.goOlder)
        self.olderButton.setToolTip(_("Go to older revision"))
        self.olderButton.setIcon(stockIcon("go-down-search"))

        self.newerButton = QToolButton()
        self.newerButton.setText(_("Newer"))
        self.newerButton.clicked.connect(self.goNewer)
        self.newerButton.setToolTip(_("Go to newer revision"))
        self.newerButton.setIcon(stockIcon("go-up-search"))

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
        assert self in self._currentBlameWindows
        self._currentBlameWindows.remove(self)
        super().closeEvent(event)

    # -------------------------------------------------------------------------

    def setTrace(self, trace: Trace, blameCollection: BlameCollection, startAt: Oid):
        self.model.trace = trace
        self.model.blameCollection = blameCollection

        startNode = self.scrubber.scrubberModel.setTrace(trace, startAt)
        self.setTraceNode(startNode)

    def saveFilePosition(self):
        currentLocator = self.textEdit.getPreciseLocator()
        self.navHistory.push(currentLocator)

    def setTraceNode(self, node: TraceNode, saveFilePositionFirst=True):
        # Stop lexing BEFORE changing the document!
        self.textEdit.highlighter.stopLexJobs()

        # Update current locator
        if saveFilePositionFirst:
            self.saveFilePosition()

        self.model.currentTraceNode = node
        self.model.currentBlame = self.model.blameCollection[node.blobId]

        with QSignalBlockerContext(self.scrubber):
            scrubberIndex = self.scrubber.findData(node.commitId, CommitLogModel.Role.Oid)
            self.scrubber.setCurrentIndex(scrubberIndex)

        blob = self.model.repo.peel_blob(node.blobId)
        data = blob.data

        if self.model.currentBlame.binary:
            text = _("Binary blob, {size} bytes, {hash}", size=len(data), hash=node.blobId)
        else:
            text = data.decode('utf-8', errors='replace')

        newLocator = self.model.currentLocator
        newLocator = self.navHistory.refine(newLocator)
        self.navHistory.push(newLocator)  # this should update in place

        self.textEdit.setPlainText(text)
        self.textEdit.currentLocator = newLocator
        self.textEdit.restorePosition(newLocator)

        self.textEdit.syncViewportMarginsWithGutter()
        self.setWindowTitle(_("Blame {path} @ {commit}", path=tquo(node.path), commit=shortHash(node.commitId)))

        # Install lex job
        lexJob = BlameWindow._getLexJob(node.path, node.blobId, text)
        if lexJob is not None:
            self.textEdit.highlighter.installLexJob(lexJob)
            self.textEdit.highlighter.rehighlight()

        self.syncNavButtons()
        print(self.navHistory.getTextLog())

    def syncNavButtons(self):
        index = self.scrubber.currentIndex()
        count = self.scrubber.count()

        self.newerButton.setEnabled(index != 0 and count >= 2)
        self.olderButton.setEnabled(index != count - 1)

        self.backButton.setEnabled(self.navHistory.canGoBack())
        self.forwardButton.setEnabled(self.navHistory.canGoForward())

    def goNewer(self):
        self.goNewerOrOlder(-1)

    def goOlder(self):
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
        self.setTraceNode(node, saveFilePositionFirst=False)

    def onScrubberActivated(self, index: int):
        node = self.getTraceNodeFromScrubberRow(index)
        self.setTraceNode(node)

    def getTraceNodeFromScrubberRow(self, index: int) -> TraceNode:
        return self.scrubber.itemData(index, CommitLogModel.Role.TraceNode)

    def jumpToCommit(self, locator: NavLocator = NavLocator.Empty):
        if locator == NavLocator.Empty:
            locator = self.model.currentLocator
        Jump.invoke(self.model.taskInvoker, locator)
        self.model.taskInvoker.activateWindow()

    @staticmethod
    def _getLexJob(path, blobId, data):
        if not settings.prefs.isSyntaxHighlightingEnabled():
            return None

        try:
            return LexJobCache.get(blobId)
        except KeyError:
            pass

        lexer = LexerCache.getLexerFromPath(path, settings.prefs.pygmentsPlugins)
        if lexer is None:
            return None

        lexJob = LexJob(lexer, data, blobId)
        if lexJob is None:
            return None

        LexJobCache.put(lexJob)
        return lexJob
