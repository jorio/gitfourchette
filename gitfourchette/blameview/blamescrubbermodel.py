# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.blameview.blamemodel import BlameModel
from gitfourchette.graphview.commitlogmodel import CommitLogModel, SpecialRow
from gitfourchette.localization import _
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID
from gitfourchette.toolbox import onAppThread


class BlameScrubberModel(QAbstractListModel):
    blameModel: BlameModel

    def __init__(self, blameModel: BlameModel, parent: QWidget):
        self.blameModel = blameModel

        super().__init__(parent)

        if APP_DEBUG and HAS_QTEST:
            self.modelTester = QAbstractItemModelTester(self)

    def columnCount(self, parent = ...):
        return 1

    def rowCount(self, parent = ...) -> int:
        return len(self.blameModel.revList.sequence)

    def data(self, index: QModelIndex, role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole):
        assert index.isValid()

        row = index.row()
        revision = self.blameModel.revList.sequence[row]

        if APP_TESTMODE and role == Qt.ItemDataRole.DisplayRole:
            # DisplayRole is intended as a unit test helper only.
            # BlameScrubberDelegate doesn't render this role.
            if revision.commitId == UC_FAKEID:  # for unit tests
                return _("Uncommitted Changes in Working Directory")
            return self.blameModel.repo.peel_commit(revision.commitId).message

        elif role == CommitLogModel.Role.Commit:
            assert onAppThread()
            try:
                return self.blameModel.repo.peel_commit(revision.commitId)
            except KeyError:
                return None

        elif role == CommitLogModel.Role.Oid:
            return revision.commitId

        elif role == CommitLogModel.Role.SpecialRow:
            return SpecialRow.UncommittedChanges if revision.commitId == UC_FAKEID else SpecialRow.Commit

        elif role == CommitLogModel.Role.BlameRevision:
            return revision

        return None
