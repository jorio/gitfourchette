# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import enum
from contextlib import suppress

from gitfourchette.forms.ui_commitfilesearchbar import Ui_CommitFileSearchBar
from gitfourchette.graphview.commitlogfilter import workdir_matches_path_needle
from gitfourchette.graphview.commitlogmodel import CommitLogModel, SpecialRow
from gitfourchette.localization import *
from gitfourchette.porcelain import Oid
from gitfourchette.qt import *
from gitfourchette.tasks.misctasks import QueryCommitsTouchingPath
from gitfourchette.toolbox import *

FILE_SEARCH_DEBOUNCE_MS = 280


class CommitFileSearchBar(QWidget):
    class Op(enum.IntEnum):
        Next = enum.auto()
        Previous = enum.auto()

    graphView: QWidget
    """ GraphView; kept as QWidget to avoid circular imports in type checkers. """

    _request_seq: int
    _match_oids: frozenset[Oid] | None
    _query_pending: bool
    _needle: str

    def __init__(self, graphView: QWidget):
        super().__init__(graphView)

        self.setObjectName(f"CommitFileSearchBar({graphView.objectName()})")
        self.graphView = graphView

        self._request_seq = 0
        self._match_oids = None
        self._query_pending = False
        self._needle = ""

        self.ui = Ui_CommitFileSearchBar()
        self.ui.setupUi(self)

        self.ui.lineEdit.setStyleSheet("border: 1px solid gray; border-radius: 5px;")
        self.ui.lineEdit.addAction(stockIcon("magnifying-glass"), QLineEdit.ActionPosition.LeadingPosition)

        self.ui.closeButton.clicked.connect(self.bail)
        self.ui.forwardButton.clicked.connect(lambda: self.jumpToMatch(self.Op.Next))
        self.ui.backwardButton.clicked.connect(lambda: self.jumpToMatch(self.Op.Previous))
        self.ui.filterOnlyCheckBox.toggled.connect(self._onFilterOnlyToggled)

        self.ui.forwardButton.setIcon(stockIcon("go-down-search"))
        self.ui.backwardButton.setIcon(stockIcon("go-up-search"))
        self.ui.closeButton.setIcon(stockIcon("dialog-close"))

        for button in (self.ui.forwardButton, self.ui.backwardButton, self.ui.closeButton):
            button.setMaximumHeight(1)

        appendShortcutToToolTip(self.ui.closeButton, Qt.Key.Key_Escape)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(FILE_SEARCH_DEBOUNCE_MS if not APP_TESTMODE else 0)
        self._debounce.timeout.connect(self._startQuery)

        self.ui.lineEdit.textChanged.connect(self._onTextChanged)

        graphView.repoWidget.taskRunner.postTask.connect(self.onQueryCommitsTouchingPathFinished)

        tweakWidgetFont(self.ui.lineEdit, 85)

        withChildren = Qt.ShortcutContext.WidgetWithChildrenShortcut
        makeWidgetShortcut(self, lambda: self.jumpToMatch(self.Op.Next), "Return", "Enter", context=withChildren)
        makeWidgetShortcut(self, lambda: self.jumpToMatch(self.Op.Previous), "Shift+Return", "Shift+Enter", context=withChildren)
        makeWidgetShortcut(self, self.bail, "Escape", context=withChildren)

    @property
    def lineEdit(self) -> QLineEdit:
        return self.ui.lineEdit

    @property
    def filterOnly(self) -> bool:
        return self.ui.filterOnlyCheckBox.isChecked()

    def prepareForDeletion(self):
        self._debounce.stop()
        with suppress(TypeError, RuntimeError):
            self.graphView.repoWidget.taskRunner.postTask.disconnect(self.onQueryCommitsTouchingPathFinished)
        self.graphView = None

    def popUp(self, forceSelectAll: bool = False):
        wasHidden = self.isHidden()
        self.show()
        h = self.ui.lineEdit.height()
        for button in (self.ui.forwardButton, self.ui.backwardButton, self.ui.closeButton):
            button.setMaximumHeight(h)
        self.ui.lineEdit.setFocus(Qt.FocusReason.PopupFocusReason)
        if forceSelectAll or wasHidden:
            self.ui.lineEdit.selectAll()
        self._pushStateToFilter()

    def bail(self):
        self.hide()
        if self.graphView is not None:
            self.graphView.setFocus(Qt.FocusReason.PopupFocusReason)

    def shouldDimRow(self, oid: Oid | None, special_row: SpecialRow) -> bool:
        if not self.isVisible() or not self._needle:
            return False
        if self.filterOnly:
            return False
        if self._query_pending:
            return False
        if self._match_oids is None:
            return False
        if special_row in (SpecialRow.TruncatedHistory, SpecialRow.EndOfShallowHistory):
            return False
        if special_row == SpecialRow.UncommittedChanges:
            return not self._workdirMatchesNeedle()
        if special_row == SpecialRow.Commit and oid is not None:
            return oid not in self._match_oids
        return False

    def rowMatchesFileSearch(self, oid: Oid | None, special_row: SpecialRow) -> bool:
        """Whether this row counts as touching the path for next/prev navigation."""
        if not self._needle or self._query_pending or self._match_oids is None:
            return False
        if special_row in (SpecialRow.TruncatedHistory, SpecialRow.EndOfShallowHistory):
            return False
        if special_row == SpecialRow.UncommittedChanges:
            return self._workdirMatchesNeedle()
        if special_row == SpecialRow.Commit and oid is not None:
            return oid in self._match_oids
        return False

    def jumpToMatch(self, op: Op):
        gv = self.graphView
        model = gv.model()
        term = self._needle
        if not term:
            QApplication.beep()
            return

        if self._query_pending or self._match_oids is None:
            QApplication.beep()
            return

        def rowIsMatch(row: int) -> bool:
            idx = model.index(row, 0)
            if not idx.isValid():
                return False
            sr: SpecialRow = idx.data(CommitLogModel.Role.SpecialRow)
            oid = idx.data(CommitLogModel.Role.Oid)
            return self.rowMatchesFileSearch(oid, sr)

        if not gv.selectedIndexes():
            start = -1 if op == self.Op.Next else model.rowCount()
        else:
            start = gv.currentIndex().row()

        if op == self.Op.Next:
            for row in range(start + 1, model.rowCount()):
                if rowIsMatch(row):
                    idx = model.index(row, 0)
                    gv.setCurrentIndex(idx)
                    return
            for row in range(0, start + 1):
                if rowIsMatch(row):
                    idx = model.index(row, 0)
                    gv.setCurrentIndex(idx)
                    return
        else:
            for row in range(start - 1, -1, -1):
                if rowIsMatch(row):
                    idx = model.index(row, 0)
                    gv.setCurrentIndex(idx)
                    return
            for row in range(model.rowCount() - 1, start - 1, -1):
                if rowIsMatch(row):
                    idx = model.index(row, 0)
                    gv.setCurrentIndex(idx)
                    return

        raw = self.ui.lineEdit.text().strip()
        title = _("Find commits by changed file")
        message = _("{0} not found.", text=bquo(raw))
        qmb = asyncMessageBox(self, "information", title, message)
        qmb.show()

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self._pushStateToFilter()

    def hideEvent(self, event: QHideEvent):
        super().hideEvent(event)
        self._fullReset()

    def onQueryCommitsTouchingPathFinished(self, task):
        if self.graphView is None:
            return
        if not isinstance(task, QueryCommitsTouchingPath):
            return
        if task.request_id != self._request_seq:
            return
        self._query_pending = False
        self._match_oids = task.matching_oids
        self._pushStateToFilter()
        self.graphView.viewport().update()

    def _repoModel(self):
        return self.graphView.repoModel

    def _workdirMatchesNeedle(self) -> bool:
        return workdir_matches_path_needle(self._repoModel(), self._needle)

    def _onTextChanged(self, _text: str):
        self._debounce.stop()
        raw = self.ui.lineEdit.text()
        self._needle = raw.strip().lower()
        if not raw.strip():
            self._request_seq += 1
            self._query_pending = False
            self._match_oids = None
            self._pushStateToFilter()
            if self.graphView is not None:
                self.graphView.viewport().update()
            return
        self._debounce.start()

    def _onFilterOnlyToggled(self, _checked: bool):
        self._pushStateToFilter()

    def _startQuery(self):
        raw = self.ui.lineEdit.text().strip()
        if not raw:
            return

        self._request_seq += 1
        rid = self._request_seq
        self._query_pending = True
        self._match_oids = None
        self._pushStateToFilter()
        QueryCommitsTouchingPath.invoke(self.graphView, raw, rid)

    def _pushStateToFilter(self):
        if self.graphView is None:
            return
        flt = self.graphView.clFilter
        flt.setFilePathSearchState(
            needle=self._needle,
            match_oids=self._match_oids,
            query_pending=self._query_pending,
            filter_only=self.filterOnly and bool(self._needle),
        )

    def _fullReset(self):
        self._debounce.stop()
        with QSignalBlockerContext(self.ui.lineEdit):
            self.ui.lineEdit.clear()
        self._needle = ""
        self._query_pending = False
        self._match_oids = None
        self._request_seq += 1
        if self.graphView is not None:
            self.graphView.clFilter.setFilePathSearchState(
                needle="",
                match_oids=None,
                query_pending=False,
                filter_only=False,
            )
