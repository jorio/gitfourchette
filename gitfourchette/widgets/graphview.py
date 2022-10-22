from gitfourchette import porcelain
from gitfourchette import settings
from gitfourchette.qt import *
from gitfourchette.util import messageSummary, fplural, shortHash, stockIcon
from gitfourchette.widgets.brandeddialog import showTextInputDialog
from gitfourchette.widgets.graphdelegate import GraphDelegate
from gitfourchette.widgets.resetheaddialog import ResetHeadDialog
from html import escape
import pygit2


class CommitLogModel(QAbstractListModel):
    _commitSequence: list[pygit2.Commit] | None

    def __init__(self, parent):
        super().__init__(parent)
        self._commitSequence = None

    @property
    def isValid(self):
        return self._commitSequence is not None

    def clear(self):
        self.setCommitSequence(None)

    def setCommitSequence(self, newCommitSequence: list[pygit2.Commit] | None):
        self.beginResetModel()
        self._commitSequence = newCommitSequence
        self.endResetModel()

    def refreshTopOfCommitSequence(self, nRemovedRows, nAddedRows, newCommitSequence: list[pygit2.Commit]):
        parent = QModelIndex()  # it's not a tree model so there's no parent

        self._commitSequence = newCommitSequence

        # DON'T interleave beginRemoveRows/beginInsertRows!
        # It'll crash with QSortFilterProxyModel!
        self.beginRemoveRows(parent, 1, nRemovedRows)
        self.endRemoveRows()

        self.beginInsertRows(parent, 1, nAddedRows)
        self.endInsertRows()

    def rowCount(self, *args, **kwargs) -> int:
        if not self.isValid:
            return 0
        else:
            return 1 + len(self._commitSequence)

    def data(self, index: QModelIndex, role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole):
        if not self.isValid:
            return None

        if index.row() == 0:
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            return self._commitSequence[index.row() - 1]  # TODO: this shouldn't be DisplayRole!
        elif role == Qt.ItemDataRole.UserRole:
            return self._commitSequence[index.row()]
        elif role == Qt.ItemDataRole.SizeHintRole:
            parentWidget: QWidget = self.parent()
            return QSize(-1, parentWidget.fontMetrics().height())
        else:
            return None


class CommitFilter(QSortFilterProxyModel):
    hiddenOids: set[pygit2.Oid]

    def __init__(self, parent):
        super().__init__(parent)
        self.hiddenOids = set()
        self.setDynamicSortFilter(True)

    @property
    def clModel(self) -> CommitLogModel:
        return self.sourceModel()

    def setHiddenCommits(self, hiddenCommits: set[pygit2.Oid]):
        self.hiddenOids = hiddenCommits

    def filterAcceptsRow(self, sourceRow: int, sourceParent: QModelIndex) -> bool:
        if sourceRow == 0:  # Uncommitted Changes
            return True

        commit = self.clModel._commitSequence[sourceRow - 1]  # -1 to account for Uncommited Changes
        return commit.oid not in self.hiddenOids


class GraphView(QListView):
    uncommittedChangesClicked = Signal()
    emptyClicked = Signal()
    commitClicked = Signal(pygit2.Oid)
    resetHead = Signal(pygit2.Oid, str, bool)
    newBranchFromCommit = Signal(pygit2.Oid)
    checkoutCommit = Signal(pygit2.Oid)
    revertCommit = Signal(pygit2.Oid)

    clModel: CommitLogModel
    clFilter: CommitFilter

    def __init__(self, parent):
        super().__init__(parent)

        self.clModel = CommitLogModel(self)
        self.clFilter = CommitFilter(self)
        self.clFilter.setSourceModel(self.clModel)

        self.setModel(self.clFilter)

        self.repoWidget = parent
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # prevents double-clicking to edit row text
        self.setItemDelegate(GraphDelegate(parent, parent=self))

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        getInfoAction = QAction("Get &Info...", self)
        getInfoAction.setIcon(stockIcon(QStyle.StandardPixmap.SP_MessageBoxInformation))
        getInfoAction.triggered.connect(self.getInfoOnCurrentCommit)
        self.addAction(getInfoAction)
        checkoutAction = QAction("&Check Out...", self)
        checkoutAction.triggered.connect(lambda: self.checkoutCommit.emit(self.currentCommitOid))
        self.addAction(checkoutAction)
        cherrypickAction = QAction("Cherry &Pick...", self)
        cherrypickAction.triggered.connect(self.cherrypickCurrentCommit)
        self.addAction(cherrypickAction)
        revertAction = QAction("Re&vert...", self)
        revertAction.triggered.connect(lambda: self.revertCommit.emit(self.currentCommitOid))
        self.addAction(revertAction)
        branchAction = QAction("Start &Branch from Here...", self)
        branchAction.triggered.connect(lambda: self.newBranchFromCommit.emit(self.currentCommitOid))
        self.addAction(branchAction)
        resetAction = QAction(F"&Reset HEAD to Here...", self)
        resetAction.triggered.connect(self.resetHeadFlow)
        self.addAction(resetAction)
        copyHashAction = QAction("Copy Commit &Hash", self)
        copyHashAction.triggered.connect(self.copyCommitHashToClipboard)
        self.addAction(copyHashAction)

    def clear(self):
        self.setCommitSequence(None)

    def setHiddenCommits(self, hiddenCommits: set[pygit2.Oid]):
        self.clFilter.setHiddenCommits(hiddenCommits)  # update filter BEFORE updating model
        self.clFilter.invalidateFilter()

    def setCommitSequence(self, commitSequence: list[pygit2.Commit] | None):
        self.clModel.setCommitSequence(commitSequence)
        self.onSetCurrent()

    def refreshTopOfCommitSequence(self, nRemovedRows: int, nAddedRows: int, commitSequence: list[pygit2.Commit]):
        self.clModel.refreshTopOfCommitSequence(nRemovedRows, nAddedRows, commitSequence)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        self.getInfoOnCurrentCommit()

    def keyPressEvent(self, event: QKeyEvent):
        k = event.key()
        if k in settings.KEYS_ACCEPT:
            self.getInfoOnCurrentCommit()
        else:
            super().keyPressEvent(event)

    @property
    def repo(self) -> pygit2.Repository:
        return self.repoWidget.state.repo

    @property
    def currentCommitOid(self) -> pygit2.Oid:
        if not self.currentIndex().isValid():
            return
        data: pygit2.Commit = self.currentIndex().data()
        if not data:  # Uncommitted Changes has no bound data
            return
        return data.oid

    def getInfoOnCurrentCommit(self):
        oid = self.currentCommitOid
        if not oid:
            return

        def formatSignature(sig: pygit2.Signature):
            qdt = QDateTime.fromSecsSinceEpoch(sig.time, Qt.TimeSpec.OffsetFromUTC, sig.offset * 60)
            return F"{escape(sig.name)} &lt;{escape(sig.email)}&gt;<br>" \
                   + escape(QLocale.system().toString(qdt, QLocale.FormatType.LongFormat))

        # TODO: we should probably run this as a worker; simply adding "with self.repoWidget.state.mutexLocker()" blocks the UI thread ... which also blocks the worker in the background! Is the qthreadpool given "time to breathe" by the GUI thread?

        commit: pygit2.Commit = self.currentIndex().data()

        summary, contd = messageSummary(commit.message)

        postSummary = ""
        nLines = len(commit.message.rstrip().split('\n'))
        if contd:
            postSummary = F"<br>\u25bc <i>click &ldquo;Show Details&rdquo; to reveal full message " \
                  F"({nLines} lines)</i>"

        parentHashes = [shortHash(p) for p in commit.parent_ids]
        parentLabelMarkup = escape(fplural('# Parent^s', len(parentHashes)))
        parentValueMarkup = escape(', '.join(parentHashes))

        #childHashes = [shortHash(c) for c in commit.children]
        #childLabelMarkup = escape(fplural('# Child^ren', len(childHashes)))
        #childValueMarkup = escape(', '.join(childHashes))

        authorMarkup = formatSignature(commit.author)

        if commit.author == commit.committer:
            committerMarkup = F"<i>(same as author)</i>"
        else:
            committerMarkup = formatSignature(commit.committer)

        diffs = porcelain.loadCommitDiffs(self.repo, oid)
        '''
        statsMarkup = (
                fplural("<b>#</b> changed file^s", sum(diff.stats.files_changed for diff in diffs)) +
                fplural("<br/><b>#</b> insertion^s", sum(diff.stats.insertions for diff in diffs)) +
                fplural("<br/><b>#</b> deletion^s", sum(diff.stats.deletions for diff in diffs))
        )
        '''

        markup = F"""<big>{summary}</big>{postSummary}
            <br>
            <table>
            <tr><td><b>Full Hash </b></td><td>{commit.oid.hex}</td></tr>
            <tr><td><b>{parentLabelMarkup} </b></td><td>{parentValueMarkup}</td></tr>
            <tr><td><b>Author </b></td><td>{authorMarkup}</td></tr>
            <tr><td><b>Committer </b></td><td>{committerMarkup}</td></tr>
            </table>"""
            # <tr><td><b>Debug</b></td><td>
            #     batch {data.batchID},
            #     offset {self.repoWidget.state.batchOffsets[data.batchID]+data.offsetInBatch}
            #     ({self.repoWidget.state.getCommitSequentialIndex(data.hexsha)})
            #     </td></tr>

        title = F"Commit info {shortHash(commit.oid)}"

        details = commit.message if contd else None

        messageBox = QMessageBox(QMessageBox.Icon.Information, title, markup, parent=self)
        messageBox.setDetailedText(details)
        messageBox.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)  # don't leak dialog
        messageBox.show()

    def cherrypickCurrentCommit(self):
        oid = self.currentCommitOid
        if not oid:
            return

        def work():
            self.repo.git.cherry_pick(oid)

        def onComplete(_):
            self.repoWidget.quickRefresh()
            self.selectCommit(oid)

        self.repoWidget._startAsyncWorker(1000, work, onComplete, F"Cherry-picking “{shortHash(oid)}”")

    def resetHeadFlow(self):
        oid = self.currentCommitOid
        if not oid:
            return

        dlg = ResetHeadDialog(oid, parent=self)

        def onAccept():
            resetMode = dlg.activeMode
            recurse = dlg.recurseSubmodules
            self.resetHead.emit(oid, resetMode, recurse)

        dlg.accepted.connect(onAccept)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)  # don't leak dialog
        dlg.show()

    def copyCommitHashToClipboard(self):
        oid = self.currentCommitOid
        if not oid:  # uncommitted changes
            return

        QApplication.clipboard().setText(oid.hex)

    def selectionChanged(self, selected: QItemSelection, deselected: QItemSelection):
        # do standard callback, such as scrolling the viewport if reaching the edges, etc.
        super().selectionChanged(selected, deselected)

        if len(selected.indexes()) == 0:
            self.onSetCurrent(None)
        else:
            self.onSetCurrent(selected.indexes()[0])

    def onSetCurrent(self, current=None):
        if current is None or not current.isValid():
            self.emptyClicked.emit()
        elif current.row() == 0:  # uncommitted changes
            self.uncommittedChangesClicked.emit()
        else:
            self.commitClicked.emit(current.data().oid)

    def selectUncommittedChanges(self):
        self.setCurrentIndex(self.model().index(0, 0))

    def selectCommit(self, oid: pygit2.Oid):
        try:
            rawIndex = self.repoWidget.state.getCommitSequentialIndex(oid)
        except KeyError:
            QMessageBox.warning(self, "pygit2.Commit not found",
                                F"pygit2.Commit not found or not loaded:\n{oid.hex}")
            return False

        newSourceIndex = self.clModel.index(1 + rawIndex, 0)
        newFilterIndex = self.clFilter.mapFromSource(newSourceIndex)

        if self.currentIndex().row() != newFilterIndex.row():
            self.setCurrentIndex(newFilterIndex)
        return True
