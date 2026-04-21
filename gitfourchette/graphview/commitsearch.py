# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import re
import typing
from collections.abc import Iterable

from gitfourchette import settings
from gitfourchette.graphview.commitlogmodel import CommitLogModel
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID, CommitPathspecFilter
from gitfourchette.search.itemviewsearchprovider import ItemViewSearchProvider
from gitfourchette.tasks import QueryCommitsTouchingPath
from gitfourchette.toolbox import *

if typing.TYPE_CHECKING:
    from gitfourchette.graphview.graphview import GraphView


class CommitSearch(ItemViewSearchProvider):
    PathspecPrefix = "/f"
    HashPattern = re.compile(r"[0-9a-fA-F]{1,40}")

    _buddy: GraphView
    _likelyHash: bool
    _pathspec: str
    _pathspecFilter: CommitPathspecFilter

    def __init__(self, pathspecFilter: CommitPathspecFilter, parent: GraphView):
        super().__init__(parent)
        self._likelyHash = False
        self._pathspec = ""
        self._pathspecFilter = pathspecFilter

    # -------------------------------------------------------------------------
    # ItemViewSearchProvider implementation

    def _walkModelImpl(self, rows: Iterable[int]) -> QModelIndex:
        assert self._term
        assert self._term == self._term.lower(), "search term should have been sanitized"
        assert self._status != self.TermStatus.Loading

        if self._term.startswith(self.PathspecPrefix):
            return self._findPathspec(rows)
        else:
            return self._findHashMessageAuthor(rows)

    def _findHashMessageAuthor(self, rows: Iterable[int]) -> QModelIndex:
        model = self.buddyModel

        for i in rows:
            index = model.index(i, 0)
            commit = model.data(index, CommitLogModel.Role.Commit)
            if commit is None or commit.id == UC_FAKEID:
                continue
            if self._likelyHash and str(commit.id).startswith(self._term):
                return index
            if self._term in commit.message.lower():
                return index
            if self._term in abbreviatePerson(commit.author, settings.prefs.authorDisplayStyle).lower():
                return index

        raise KeyError()

    def _findPathspec(self, rows: Iterable[int]) -> QModelIndex:
        # User hasn't entered their term yet
        if not self._pathspec:
            raise KeyError("No pathspec yet")

        cpf = self._pathspecFilter
        model = self.buddyModel

        # We should be ready now
        assert cpf.isReady()
        assert self._status != self.TermStatus.Loading

        for i in rows:
            index = model.index(i, 0)
            oid = model.data(index, CommitLogModel.Role.Oid)
            if oid is not None and oid in cpf.matchingIds:
                return index

        raise KeyError()

    # -------------------------------------------------------------------------
    # SearchProvider implementation

    def canFilter(self) -> bool:
        return self._term.startswith(self.PathspecPrefix)

    def notFoundMessage(self) -> str:
        message = super().notFoundMessage()

        repoModel = self._buddy.repoModel
        limitations = []

        if repoModel.hiddenCommits:
            limitations.append(_("hidden branches"))

        if repoModel.truncatedHistory:
            limitations.append(_("truncated history"))
        elif repoModel.repo.is_shallow:
            limitations.append(_("shallow clone"))

        if limitations:
            message += (f" <span style='color: {mutedToolTipColorHex()}'>" +
                        _("(search limited by {0})", ", ".join(limitations)))

        return message

    def _termChanged(self):
        super()._termChanged()

        term = self._term
        self._likelyHash = (0 < len(term) <= 40) and bool(self.HashPattern.match(term))

        if term.startswith(self.PathspecPrefix):
            self.invalidate()  # HACK: Always invalidate badStem when changing file searches
            self._pathspec = term.removeprefix(self.PathspecPrefix).strip()
            self._status = self.TermStatus.Loading if self._pathspec else self.TermStatus.Unknown
        else:
            self._pathspec = ""

        # Always invalidate pathspec filter when changing search term
        self._pathspecFilter.clear()

    def _debounceImpl(self, allowJump: bool):
        if self._term.startswith(self.PathspecPrefix):
            if self._pathspec:  # Don't start empty query if user isn't done typing
                self._status = self.TermStatus.Loading
                QueryCommitsTouchingPath.invoke(self._buddy, self._pathspec,
                                                lambda: self._onFileSearchComplete(allowJump))
        else:
            super()._debounceImpl(allowJump)

    def _cancel(self):
        # This will squelch _onFileSearchComplete
        # TODO: Keep track of the task and interrupt it
        self._pathspecFilter.clear()
        if self._wantFilter:
            self._buddy.clFilter.invalidateFilter()

    def _onFileSearchComplete(self, allowJump):
        assert not self._frozen
        cpf = self._pathspecFilter
        cpf.filterOnly = self._wantFilter
        # TODO: I guess we should look at the workdir, too...or drop the workdir stuff altogether
        self._status = self.TermStatus.Good if cpf.matchingIds else self.TermStatus.Bad
        self.repaintBuddy()  # for dimming
        # TODO: would be nice to emit a signal instead of doing this ourselves
        self._buddy.searchBar.syncStylingWithProviderState()
        # TODO: what about when the filter is toggled?
        if cpf.wantFilter():
            self._buddy.clFilter.invalidateFilter()
        super()._debounceImpl(allowJump)

    def setFilterState(self, checked: bool):
        super().setFilterState(checked)
        self._pathspecFilter.filterOnly = self._wantFilter
        self._buddy.clFilter.invalidateFilter()
