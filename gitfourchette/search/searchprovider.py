# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations  # TODO: Remove once we can drop support for Python <= 3.13

import enum

from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class SearchProvider(QObject):
    class TermStatus(enum.IntEnum):
        Unknown = enum.auto()
        "Term hasn't been evaluated yet"

        Loading = enum.auto()
        "Asynchronous search in progress"

        Good = enum.auto()
        "Term is known to have some matches"

        Bad = enum.auto()
        "Term is known to have no matches"

    _term: str
    _badStem: str
    _status: TermStatus

    def __init__(self, parent):
        super().__init__(parent)
        self._term = ""
        self._badStem = ""
        self._status = SearchProvider.TermStatus.Unknown
        self._frozen = False
        self.title = _("Find")

    def freeze(self, frozen: bool):
        self._frozen = frozen
        if frozen:
            self._cancel()

    def term(self) -> str:
        return "" if self._frozen else self._term

    def setTerm(self, term: str):
        term = term.strip().lower()
        self._term = term

        if term and self._badStem and self._badStem in term:
            # badStem is still in the search term: still bad
            assert self.isBad()
        else:
            self._badStem = ""
            self._status = SearchProvider.TermStatus.Unknown

        self._termChanged()

    def _enshrineBadTerm(self):
        self._status = SearchProvider.TermStatus.Bad
        if not self._badStem:
            self._badStem = self._term

    def invalidate(self):
        self._badStem = ""
        self._status = SearchProvider.TermStatus.Unknown

    def status(self) -> SearchProvider.TermStatus:
        return self._status

    def isEmpty(self) -> bool:
        return not bool(self._term)

    def isBad(self) -> bool:
        return self._status == SearchProvider.TermStatus.Bad

    def jump(self, forward: bool):
        if self.isEmpty():
            QApplication.beep()
            return

        if not self.isBad() and self._status != SearchProvider.TermStatus.Loading:
            self._jumpImpl(forward)

        if self.isBad():  # jumpImpl may have found that the term is bad
            # TODO: Tooltip instead?
            showInformation(self.parent(), self.title, self._notFoundMessage(self._term))

    def debounce(self, allowJump: bool):
        if self.isEmpty() or self.isBad():
            return

        self._debounceImpl(allowJump)

    # -------------------------------------------------------------------------
    # Override these

    def _cancel(self):
        pass

    def _notFoundMessage(self, term: str) -> str:
        return _("{text} not found.", text=bquo(term))

    def _termChanged(self):
        pass

    def _jumpImpl(self, forward: bool):
        raise NotImplementedError()

    def _debounceImpl(self, allowJump: bool):
        pass
