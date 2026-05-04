# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID, RepoModel
from gitfourchette.toolbox import *
from gitfourchette.toolbox.filterchangecontext import FilterChangeContext


class CommitLogFilter(QSortFilterProxyModel):
    repoModel: RepoModel
    shadowHiddenIds: set[Oid]

    def __init__(self, repoModel, parent):
        super().__init__(parent)
        self.repoModel = repoModel
        self.shadowHiddenIds = set()
        self.shadowPathspecFilterActive = False
        self.setDynamicSortFilter(True)

        self.updateHiddenCommits()  # prime hiddenIds
        self.updatePathspecFilter()

    @property
    def pathspecFilter(self):
        return self.repoModel.commitPathspecFilter

    @benchmark
    def updateHiddenCommits(self):
        hiddenIds = self.repoModel.hiddenCommits

        # Invalidating the filter can be costly, so avoid if possible
        if self.shadowHiddenIds == hiddenIds:
            return

        with FilterChangeContext(self):
            # Keep a copy so we can detect a change next time we're called
            self.shadowHiddenIds = set(hiddenIds)

    @benchmark
    def updatePathspecFilter(self):
        active = self.pathspecFilter.wantFilter()

        # Invalidating the filter can be costly, so avoid if possible
        if not active and active == self.shadowPathspecFilterActive:
            return

        with FilterChangeContext(self):
            self.shadowPathspecFilterActive = active

    def filterAcceptsRow(self, sourceRow: int, sourceParent: QModelIndex) -> bool:
        try:
            commit = self.repoModel.commitSequence[sourceRow]
        except IndexError:
            # Probably an extra special row
            return True

        if commit.id == UC_FAKEID:
            # Always ignore shadowHiddenIds for the workdir row (same as pre–file-search
            # behavior). UC_FAKEID can appear in hiddenCommits graph bookkeeping; it must
            # not hide the synthetic uncommitted row.
            if self.shadowPathspecFilterActive:
                return commit.id in self.pathspecFilter.matchingIds
            return True

        if commit.id in self.shadowHiddenIds:
            return False

        if self.shadowPathspecFilterActive:
            return commit.id in self.pathspecFilter.matchingIds

        return True
