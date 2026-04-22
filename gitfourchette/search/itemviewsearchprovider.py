# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import itertools
from collections.abc import Iterable

from gitfourchette.qt import *
from gitfourchette.search.searchprovider import SearchProvider


class ItemViewSearchProvider(SearchProvider):
    _buddy: QAbstractItemView

    def __init__(self, parent):
        super().__init__(parent)
        assert isinstance(parent, QAbstractItemView)
        self._buddy = parent
        self.dataRole = Qt.ItemDataRole.DisplayRole

    @property
    def buddyModel(self):
        # To filter out hidden rows, don't use _buddy.clModel directly
        return self._buddy.model()

    def _walk(self, forward: bool, jump: bool, skipCurrent: bool):
        """
        Do not override!
        """

        assert self._status != self.TermStatus.Loading

        # -------------------
        # Get row generator

        numRows = self.buddyModel.rowCount()

        # Find start bound of search range
        if self._buddy.selectedIndexes():
            start = self._buddy.currentIndex().row()
            start += 0 if not skipCurrent else 1 if forward else -1
        elif forward:
            start = 0
        else:
            start = numRows - 1

        if forward:
            range1 = range(start, numRows)
            range2 = range(0, start)
        else:
            range1 = range(start, -1, -1)
            range2 = range(numRows - 1, start, -1)

        rows = itertools.chain(range1, range2)

        # -------------------
        # Walk the model

        try:
            index = self._walkModelImpl(rows)
        except KeyError:
            self._enshrineBadTerm()
            return

        # -------------------
        # We've got a matching index

        assert index.isValid()
        self.setStatus(SearchProvider.TermStatus.Good)

        if jump:
            self._buddy.setCurrentIndex(index)

    def _walkModelImpl(self, rows: Iterable[int]) -> QModelIndex:
        """
        Iterate on the buddy's model until a matching row is found.
        Raise KeyError if not found.
        Your provider must either set a valid dataRole, or override this method.
        """

        assert self.dataRole != Qt.ItemDataRole.DisplayRole, "set up a proper data role for search"
        assert self._term, "don't search for an empty term"
        assert self._term == self._term.lower(), "search term should have been sanitized"
        assert self._status != self.TermStatus.Loading

        model = self.buddyModel
        for i in rows:
            index = model.index(i, 0)
            data = model.data(index, self.dataRole)
            if data and self._term in data.lower():
                return index

        raise KeyError()

    # -------------------------------------------------------------------------
    # SearchProvider implementation

    def _termChanged(self):
        # Repaint buddy to refresh any highlighting
        self._buddy.viewport().update()

    def _jumpImpl(self, forward: bool):
        self._walk(forward=forward, jump=True, skipCurrent=True)

    def _debounceImpl(self, allowJump: bool):
        if not allowJump:
            # TODO: Hack to pass testReevaluateFileListSearchTermAcrossCommits.
            #       How about new callback to prime the search instead of debounce(false)?
            if self._status == self.TermStatus.Unknown:
                self._walk(forward=True, jump=False, skipCurrent=False)
            return

        # Stay on current item if it already matches, otherwise jump to next item
        self._walk(forward=True, jump=True, skipCurrent=False)
