# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations  # TODO: Remove once we can drop support for Python <= 3.13

import typing

from gitfourchette.localization import _
from gitfourchette.qt import *
from gitfourchette.search.searchprovider import SearchProvider

if typing.TYPE_CHECKING:
    from gitfourchette.codeview.codeview import CodeView


class CodeSearch(SearchProvider):
    _buddy: CodeView

    def __init__(self, parent: CodeView):
        super().__init__(parent)
        self._buddy = parent
        self.title = _("Find code")

    def _cancel(self):
        self._buddy.highlighter.setSearchTerm("")

    def _termChanged(self):
        numOccurrences = self._buddy.highlighter.setSearchTerm(self._term)

        if self._term and numOccurrences == 0:
            self._enshrineBadTerm()
        else:
            self._status = SearchProvider.TermStatus.Good

    def _jumpImpl(self, forward: bool):
        assert not self.isEmpty()
        assert not self.isBad()

        startCursor = self._buddy.textCursor()
        document = self._buddy.document()
        findFlags = [] if forward else [QTextDocument.FindFlag.FindBackward]

        for _wrap in range(2):  # Wrap around at most once
            newCursor = document.find(self._term, startCursor, *findFlags)

            if newCursor and not newCursor.isNull():  # extra isNull check needed for PyQt5 & PyQt6
                self._buddy.setTextCursor(newCursor)
                return

            # Wrap
            startCursor.movePosition(QTextCursor.MoveOperation.Start if forward else QTextCursor.MoveOperation.End)

    def _debounceImpl(self, allowJump: bool):
        assert not self.isEmpty()
        assert not self.isBad()

        if not allowJump:
            return

        if self._buddy.textCursor().selectedText().lower().startswith(self._term):
            return

        self._jumpImpl(True)
