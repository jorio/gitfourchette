# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID, RepoModel
from gitfourchette.toolbox import *


class CommitLogFilter(QSortFilterProxyModel):
    repoModel: RepoModel
    shadowHiddenIds: set[Oid]

    def __init__(self, repoModel, parent):
        super().__init__(parent)
        self.repoModel = repoModel
        self.shadowHiddenIds = set()
        self.setDynamicSortFilter(True)
        self.updateHiddenCommits()  # prime hiddenIds

    @benchmark
    def updateHiddenCommits(self):
        hiddenIds = self.repoModel.hiddenCommits

        # Invalidating the filter can be costly, so avoid if possible
        if self.shadowHiddenIds == hiddenIds:
            return

        # Keep a copy so we can detect a change next time we're called
        self.shadowHiddenIds = set(hiddenIds)

        # Percolate the update to the model
        self.invalidateFilter()

    def filterAcceptsRow(self, sourceRow: int, sourceParent: QModelIndex) -> bool:
        try:
            commit = self.repoModel.commitSequence[sourceRow]
        except IndexError:
            # Probably an extra special row
            return True
        if commit.id == UC_FAKEID:
            return True
        return commit.id not in self.shadowHiddenIds
