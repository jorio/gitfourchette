# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import fnmatch

from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID, RepoModel
from gitfourchette.toolbox import *


def _delta_path_matches_needle(path: str, needle_lower: str) -> bool:
    """Match a repo-relative path against the same pattern style as ``git log -- <pathspec>`` for common cases: substring, or fnmatch when the pattern contains glob syntax."""
    if not path or not needle_lower:
        return False
    pl = path.lower()
    nl = needle_lower
    if any(c in nl for c in "*?["):
        normalized = pl.replace("\\", "/")
        base = normalized.rsplit("/", 1)[-1]
        return fnmatch.fnmatch(normalized, nl) or fnmatch.fnmatch(base, nl)
    return nl in pl


def workdir_matches_path_needle(repoModel: RepoModel, needle_lower: str) -> bool:
    if not needle_lower or not repoModel.workdirStatusReady:
        return False
    for d in repoModel.workdirUnstagedDeltas + repoModel.workdirStagedDeltas:
        if _delta_path_matches_needle(d.new.path, needle_lower) or _delta_path_matches_needle(d.old.path, needle_lower):
            return True
    return False


class CommitLogFilter(QSortFilterProxyModel):
    repoModel: RepoModel
    shadowHiddenIds: set[Oid]

    _fp_needle: str
    _fp_match_oids: frozenset[Oid] | None
    _fp_query_pending: bool
    _fp_filter_only: bool

    def __init__(self, repoModel, parent):
        super().__init__(parent)
        self.repoModel = repoModel
        self.shadowHiddenIds = set()
        self._fp_needle = ""
        self._fp_match_oids = None
        self._fp_query_pending = False
        self._fp_filter_only = False
        self.setDynamicSortFilter(True)
        self.updateHiddenCommits()  # prime hiddenIds

    def setFilePathSearchState(
            self,
            *,
            needle: str,
            match_oids: frozenset[Oid] | None,
            query_pending: bool,
            filter_only: bool,
    ):
        needle = needle.strip().lower()
        self._fp_needle = needle
        self._fp_match_oids = match_oids
        self._fp_query_pending = query_pending
        self._fp_filter_only = filter_only
        self.invalidateFilter()

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

        if commit.id == UC_FAKEID:
            # Always ignore shadowHiddenIds for the workdir row (same as pre–file-search
            # behavior). UC_FAKEID can appear in hiddenCommits graph bookkeeping; it must
            # not hide the synthetic uncommitted row.
            if self._fp_needle and self._fp_filter_only:
                return workdir_matches_path_needle(self.repoModel, self._fp_needle)
            return True

        if commit.id in self.shadowHiddenIds:
            return False

        if self._fp_needle and self._fp_filter_only:
            if self._fp_query_pending:
                return False
            if self._fp_match_oids is None:
                return True
            return commit.id in self._fp_match_oids

        return True
