# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations  # TODO: Remove once we can drop support for Python <= 3.13

import typing
from collections.abc import Iterable

from gitfourchette.graphview.commitinfosearch import CommitInfoSearch
from gitfourchette.graphview.commitlogmodel import CommitLogModel
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavFlags
from gitfourchette.qt import *
from gitfourchette.repomodel import CommitPathspecFilter, UC_FAKEID
from gitfourchette.search.itemviewsearchprovider import ItemViewSearchProvider
from gitfourchette.tasks import QueryCommitsTouchingPath, Jump

if typing.TYPE_CHECKING:
    from gitfourchette.graphview.graphview import GraphView


class CommitFileSearch(ItemViewSearchProvider):
    _buddy: GraphView
    _pathspecFilter: CommitPathspecFilter

    def __init__(self, parent: GraphView):
        super().__init__(parent)
        self._pathspecFilter = parent.repoModel.commitPathspecFilter
        self._pathspecFilter.resultsUpdated.connect(self._gotResults)

    def _gotResults(self):
        if self._frozen:
            return

        cpf = self._pathspecFilter
        assert cpf.isReady()
        cpf.filterOnly = self._wantFilter

        if self._wantFilter:
            self._buddy.clFilter.invalidateFilter()
        self._buddy.viewport().update()

        self.setStatus(self.TermStatus.Good if cpf.matchingIds else self.TermStatus.Bad)

    # -------------------------------------------------------------------------
    # ItemViewSearchProvider implementation

    def _walkModelImpl(self, rows: Iterable[int]) -> QModelIndex:
        # We should be ready now
        assert self._pathspecFilter.isReady()
        assert self._status != self.TermStatus.Loading

        model = self.buddyModel

        for i in rows:
            index = model.index(i, 0)
            oid = model.data(index, CommitLogModel.Role.Oid)
            if oid in self._pathspecFilter.matchingIds:
                return index

        raise KeyError()

    def _jumpToIndex(self, index: QModelIndex):
        oid = self.buddyModel.data(index, CommitLogModel.Role.Oid)
        if oid == UC_FAKEID:
            delta = self._buddy.repoModel.workdirMatchesPathNeedle(self._term)
            locator = NavLocator(delta.context, oid, delta.new.path)
        else:
            locator = NavLocator.inCommit(oid, self._term).withExtraFlags(NavFlags.FuzzyPath)
        Jump.invoke(self._buddy, locator)

    # -------------------------------------------------------------------------
    # SearchProvider implementation

    def longTitle(self) -> str:
        return _("Find path touched by commits")

    def shortTitle(self) -> str:
        return _("Path")

    def keyboardShortcut(self) -> str:
        return "Alt+P"

    def invalidate(self):
        wasFiltering = self._pathspecFilter.wantFilter() and self._pathspecFilter.isReady()
        self._buddy.repoWidget.taskRunner.killTaskClass(QueryCommitsTouchingPath)
        self._pathspecFilter.clear()
        if wasFiltering:
            self._buddy.clFilter.invalidateFilter()

        super().invalidate()

    def canFilter(self) -> bool:
        return True

    def notFoundMessage(self) -> str:
        message = super().notFoundMessage()
        return CommitInfoSearch.makeNotFoundMessage(message, self._buddy.repoModel)

    def _termChanged(self):
        super()._termChanged()

        # Surround with wildcards
        if self._term:
            self._term = f"*{self._term}*"

        # HACK: Always invalidate badStem when changing file searches
        # This also invalidates the pathspec filter
        self.invalidate()

    def prime(self, forwardHint: bool):
        assert self._term
        self.setStatus(self.TermStatus.Loading)
        QueryCommitsTouchingPath.invoke(self._buddy, self._term)

    def setFilterState(self, checked: bool):
        super().setFilterState(checked)
        self._pathspecFilter.filterOnly = self._wantFilter
        self._buddy.clFilter.invalidateFilter()
