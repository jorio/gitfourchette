# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations  # TODO: Remove once we can drop support for Python <= 3.13

import typing

from gitfourchette.qt import *
from gitfourchette.search.searchprovider import SearchProvider

if typing.TYPE_CHECKING:
    from gitfourchette.codeview.codeview import CodeView


class CodeSearch(SearchProvider):
    _buddy: CodeView

    def __init__(self, parent: CodeView):
        super().__init__(parent)
        self._buddy = parent

    def invalidate(self):
        super().invalidate()
        self._buddy.highlighter.setSearchTerm("")

    def _termChanged(self):
        numOccurrences = self._buddy.highlighter.setSearchTerm(self._term)

        if not self._term:  # Empty
            self.setStatus(SearchProvider.TermStatus.Unknown)
        elif numOccurrences == 0:
            self._enshrineBadTerm()
        else:
            self.setStatus(SearchProvider.TermStatus.Good)

    def isCurrentMatch(self) -> bool:
        assert self.isGoodAndNonEmpty()
        cursor: QTextCursor = self._buddy.textCursor()
        return cursor.selectedText().lower().startswith(self._term)

    def jump(self, forward: bool):
        assert self.isGoodAndNonEmpty()

        startCursor = self._buddy.textCursor()
        document = self._buddy.document()
        findFlags = [] if forward else [QTextDocument.FindFlag.FindBackward]

        for _wrap in range(2):  # Wrap around at most once
            newCursor = document.find(self._term, startCursor, *findFlags)

            if newCursor and not newCursor.isNull():  # extra isNull check needed for PyQt5 & PyQt6
                self._buddy.setTextCursor(newCursor)
                assert self.isCurrentMatch()
                return

            # Wrap
            startCursor.movePosition(QTextCursor.MoveOperation.Start if forward else QTextCursor.MoveOperation.End)
