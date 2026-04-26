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
        self._startHint = (-1, True)

    @property
    def buddyModel(self):
        # To filter out hidden rows, don't use _buddy.clModel directly
        return self._buddy.model()

    def _currentRow(self):
        return self._buddy.currentIndex().row() if self._buddy.selectedIndexes() else -1

    def _walk(self, forward: bool, jump: bool, skipCurrent: bool, startHint: int = -1):
        """
        Do not override!
        """

        assert self._status != self.TermStatus.Loading

        # -------------------
        # Get row generator

        numRows = self.buddyModel.rowCount()
        currentRow = self._currentRow()

        # Find start bound of search range
        if startHint >= 0:
            start = startHint
        elif currentRow >= 0:
            start = currentRow
        elif forward:
            start = 0
        else:
            start = numRows - 1

        if skipCurrent and start == currentRow:
            start += 1 if forward else -1
            start %= numRows

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
            return -1

        # -------------------
        # We've got a matching index

        assert index.isValid()
        self.setStatus(SearchProvider.TermStatus.Good)

        if jump:
            self._jumpToIndex(index)

        return index.row()

    def _jumpToIndex(self, index: QModelIndex):
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

    def prime(self, forwardHint: bool):
        i = self._walk(forwardHint, False, False, -1)
        self._startHint = (i, forwardHint)

    def jump(self, forward: bool):
        assert self.isGoodAndNonEmpty()
        rowHint, rowHintForward = self._startHint
        if not (rowHint >= 0 and rowHintForward == forward):
            rowHint = -1
        rowHint = self._walk(forward, True, True, rowHint)
        self._startHint = (rowHint, forward)

    def invalidate(self):
        super().invalidate()
        self._startHint = (-1, True)

    def isCurrentMatch(self) -> bool:
        row = self._currentRow()
        if row < 0:
            return False
        try:
            self._walkModelImpl([row])
            return True
        except KeyError:
            return False
