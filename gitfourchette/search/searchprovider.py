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

    statusChanged = Signal(TermStatus)

    _term: str
    _badStem: str
    _status: TermStatus

    def __init__(self, parent):
        super().__init__(parent)
        self._term = ""
        self._badStem = ""
        self._status = SearchProvider.TermStatus.Unknown
        self._wantFilter = False
        self._frozen = False

    def freeze(self, frozen: bool):
        self._frozen = frozen
        if frozen:
            self._cancel()

    def setFilterState(self, checked: bool):
        self._wantFilter = checked

    def term(self) -> str:
        return "" if self._frozen else self._term

    def setTerm(self, term: str):
        status1 = self._status

        with QSignalBlockerContext(self):  # Don't spam status updates
            term = term.strip().lower()
            self._term = term

            if term and self._badStem and self._badStem in term:
                # badStem is still in the search term: still bad
                assert self.isBad()
            else:
                self._badStem = ""
                self.setStatus(SearchProvider.TermStatus.Unknown)

            self._termChanged()

        if self._status != status1:
            self.statusChanged.emit(self._status)

    def _enshrineBadTerm(self):
        if not self._badStem:
            self._badStem = self._term
        self.setStatus(SearchProvider.TermStatus.Bad)

    def invalidate(self):
        self._badStem = ""
        self.setStatus(SearchProvider.TermStatus.Unknown)

    def status(self) -> SearchProvider.TermStatus:
        return self._status

    def setStatus(self, status: SearchProvider.TermStatus):
        if status != self._status:
            self._status = status
            self.statusChanged.emit(status)

    def isEmpty(self) -> bool:
        return not bool(self._term)

    def isBad(self) -> bool:
        return self._status == SearchProvider.TermStatus.Bad

    def isGoodAndNonEmpty(self) -> bool:
        return self._status == SearchProvider.TermStatus.Good and not self.isEmpty()

    # -------------------------------------------------------------------------
    # Override these

    def canFilter(self) -> bool:
        return False

    def _cancel(self):
        pass

    def notFoundMessage(self) -> str:
        return _("No results")

    def _termChanged(self):
        pass

    def prime(self, forwardHint: bool):
        """
        Called by SearchBar to kick off a (possibly asynchronous) query on the
        search term, which is guaranteed to be non-empty with non-Bad status.
        This function can be a no-op; otherwise, it should typically change the
        current status to Good, Bad, or Loading.
        """
        pass

    def jump(self, forward: bool):
        """
        Jump to the next or previous occurrence.
        The search term status is guaranteed to be Good here.
        """
        raise NotImplementedError()

    def isCurrentMatch(self) -> bool:
        """
        Does the current selection match the current search term?
        The search term status is guaranteed to be Good here.
        """
        raise NotImplementedError()
