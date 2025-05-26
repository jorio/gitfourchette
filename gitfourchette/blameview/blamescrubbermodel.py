# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.blameview.blamemodel import BlameModel
from gitfourchette.filelists.filelistmodel import STATUS_ICON_LETTERS
from gitfourchette.graphview.commitlogmodel import CommitLogModel, SpecialRow
from gitfourchette.porcelain import Oid
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID
from gitfourchette.toolbox import stockIcon, onAppThread
from gitfourchette.trace import Trace, TraceNode


class BlameScrubberModel(QAbstractListModel):
    blameModel: BlameModel
    nodes: list[TraceNode]

    def __init__(self, parent):
        super().__init__(parent)
        if APP_DEBUG and HAS_QTEST:
            self.modelTester = QAbstractItemModelTester(self)

    def setTrace(self, trace: Trace, startAt: Oid):
        self.nodes = []

        startNode = trace.first  # fall back to newest commit

        for node in trace:
            if node.commitId == startAt:
                startNode = node
            self.nodes.append(node)

        self.modelReset.emit()
        return startNode

    def columnCount(self, parent = ...):
        return 1

    def rowCount(self, parent = ...) -> int:
        try:
            return len(self.nodes)
        except AttributeError:
            return 0

    def data(self, index: QModelIndex, role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole):
        assert index.isValid()
        row = index.row()
        node = self.nodes[row]

        if role == Qt.ItemDataRole.DisplayRole:
            # if APP_TESTMODE:
            assert self.blameModel
            assert self.blameModel.repo, f"{len(self.nodes)} {self.blameModel.repoModel.repo} {self.blameModel.repoModel.refs} {self.blameModel.currentTraceNode}"
            if node.commitId == UC_FAKEID:
                return "UNCOMMITTED CHANGES IN WORKING DIRECTORY"
            return self.blameModel.repo.peel_commit(node.commitId).message

        elif role == CommitLogModel.Role.Commit:
            assert onAppThread()
            assert self.blameModel
            assert self.blameModel.repo
            if node.commitId == UC_FAKEID:
                return None
            return self.blameModel.repo.peel_commit(node.commitId)

        elif role == CommitLogModel.Role.Oid:
            return node.commitId

        elif role == CommitLogModel.Role.SpecialRow:
            return SpecialRow.UncommittedChanges if node.commitId == UC_FAKEID else SpecialRow.Commit

        elif role == CommitLogModel.Role.TraceNode:
            return node

        elif role == Qt.ItemDataRole.DecorationRole:
            # TODO: display those in delegate!
            return stockIcon("status_" + STATUS_ICON_LETTERS[int(node.status)])

        return None
