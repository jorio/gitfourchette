# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
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

        # Begin invalidating filter
        self.beginFilterChange()

        # Keep a copy so we can detect a change next time we're called
        self.shadowHiddenIds = set(hiddenIds)

        # Percolate the update to the model
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, sourceRow: int, sourceParent: QModelIndex) -> bool:
        try:
            commit = self.repoModel.commitSequence[sourceRow]
        except IndexError:
            # Probably an extra special row
            return True

        pathspecFilter = self.repoModel.commitPathspecFilter

        if commit.id == UC_FAKEID:
            # Always ignore shadowHiddenIds for the workdir row (same as pre–file-search
            # behavior). UC_FAKEID can appear in hiddenCommits graph bookkeeping; it must
            # not hide the synthetic uncommitted row.
            if pathspecFilter.wantFilter():
                return self.repoModel.workdirMatchesPathNeedle(pathspecFilter.needle)
            return True

        if commit.id in self.shadowHiddenIds:
            return False

        if pathspecFilter.wantFilter():
            return commit.id in pathspecFilter.matchingIds

        return True
