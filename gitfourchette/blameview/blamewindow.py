# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.blameview.blamemodel import BlameModel
from gitfourchette.blameview.blametextedit import BlameTextEdit
from gitfourchette.filelists.filelistmodel import STATUS_ICON_LETTERS
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import Oid
from gitfourchette.qt import *
from gitfourchette.repomodel import RepoModel
from gitfourchette.tasks import Jump
from gitfourchette.toolbox import shortHash, messageSummary, stockIcon
from gitfourchette.trace import TraceNode, Trace, BlameCollection


class BlameWindow(QWidget):
    def __init__(self, repoModel: RepoModel, parent):
        super().__init__(parent)
        self.setObjectName("BlameWindow")

        self.model = BlameModel(repoModel, [], {})

        self.scrubber = QComboBox()
        self.scrubber.addItem(_("Loading…"))
        self.textEdit = BlameTextEdit(self.model)

        self.scrubber.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.scrubber.activated.connect(self.onScrubberActivated)

        self.jumpButton = QToolButton()
        self.jumpButton.setText(_("Jump"))
        self.jumpButton.setToolTip(_("Jump to this commit in the repo"))
        self.jumpButton.setIcon(stockIcon("go"))
        self.jumpButton.clicked.connect(self.jumpToCommit)
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

        topBar = QWidget()
        barLayout = QHBoxLayout(topBar)
        barLayout.addWidget(self.scrubber)
        barLayout.addWidget(self.jumpButton)
        barLayout.addWidget(self.olderButton)
        barLayout.addWidget(self.newerButton)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(QMargins())
        layout.addWidget(topBar)
        layout.addWidget(self.textEdit)
        layout.setSpacing(0)

        self.setTabOrder(self.scrubber, self.olderButton)
        self.setTabOrder(self.olderButton, self.newerButton)
        self.setTabOrder(self.newerButton, self.textEdit)

        self.textEdit.selectIndex.connect(self.selectIndex)

        self.setWindowModality(Qt.WindowModality.NonModal)

    def setTrace(self, trace: Trace, blameCollection: BlameCollection, startAt: Oid):
        self.model.trace = trace
        self.model.blameCollection = blameCollection

        self.scrubber.clear()

        startIndex = 0
        startNode = None
        for index, node in enumerate(trace):
            if node.commitId == startAt:
                startIndex = index
                startNode = node
            commit = self.model.repo.peel_commit(node.commitId)
            message, _ = messageSummary(commit.message)
            commitQdt = QDateTime.fromSecsSinceEpoch(commit.author.time, Qt.TimeSpec.OffsetFromUTC, commit.author.offset * 60)
            commitTimeStr = QLocale().toString(commitQdt, "yyyy-MM-dd")  # settings.prefs.shortTimeFormat)
            self.scrubber.addItem(f"{commitTimeStr} {shortHash(node.commitId)} {message}", userData=node)
            self.scrubber.setItemIcon(index, stockIcon("status_" + STATUS_ICON_LETTERS[int(node.status)]))

        self.scrubber.setCurrentIndex(startIndex)
        self.setTraceNode(startNode)
        self.syncNavButtons()

    def setTraceNode(self, node: TraceNode):
        self.model.commitId = node.commitId
        self.model.currentBlame = self.model.blameCollection[node.blobId]

        blob = self.model.repo.peel_blob(node.blobId)
        text = blob.data.decode('utf-8', errors='replace')
        self.textEdit.setPlainText(text)

        self.textEdit.gutter.syncModel()
        self.textEdit.syncModel()
        self.textEdit.syncViewportMarginsWithGutter()
        self.setWindowTitle(_("Blame: ") + node.path)

    def onScrubberActivated(self, index: int):
        point: TraceNode = self.scrubber.itemData(index)
        self.setTraceNode(point)
        self.syncNavButtons()

    def syncNavButtons(self):
        index = self.scrubber.currentIndex()
        count = self.scrubber.count()

        self.newerButton.setEnabled(index != 0 and count >= 2)
        self.olderButton.setEnabled(index != count - 1)

    def goNewer(self):
        index = self.scrubber.currentIndex()
        index -= 1
        if index < 0:
            return
        self.scrubber.setCurrentIndex(index)
        # QTimer.singleShot(1, lambda: self.onScrubberActivated(index))
        self.onScrubberActivated(index)

    def goOlder(self):
        index = self.scrubber.currentIndex()
        index += 1
        if index >= self.scrubber.count():
            return
        self.scrubber.setCurrentIndex(index)
        # QTimer.singleShot(1, lambda: self.onScrubberActivated(index))
        self.onScrubberActivated(index)

    def selectIndex(self, index: int):
        self.scrubber.setCurrentIndex(index)
        self.onScrubberActivated(index)

    def jumpToCommit(self):
        point: TraceNode = self.scrubber.currentData()
        Jump.invoke(self, NavLocator.inCommit(point.commitId, point.path))
