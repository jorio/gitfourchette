# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import enum
import itertools
import typing

from gitfourchette.forms.ui_commitfilesearchbar import Ui_CommitFileSearchBar
from gitfourchette.graphview.commitlogmodel import CommitLogModel, SpecialRow
from gitfourchette.localization import *
from gitfourchette.porcelain import Oid
from gitfourchette.qt import *
from gitfourchette.tasks.misctasks import QueryCommitsTouchingPath
from gitfourchette.toolbox import *

if typing.TYPE_CHECKING:
    from gitfourchette.graphview.graphview import GraphView

FILE_SEARCH_DEBOUNCE_MS = 280


class CommitFileSearchBar(QWidget):
    class Op(enum.IntEnum):
        Next = enum.auto()
        Previous = enum.auto()

    graphView: GraphView

    _requestSeq: int
    _matchOids: frozenset[Oid] | None
    _queryPending: bool
    _needle: str

    def __init__(self, graphView: GraphView):
        super().__init__(graphView)

        self.setObjectName(f"CommitFileSearchBar({graphView.objectName()})")
        self.graphView = graphView

        self._requestSeq = 0
        self._matchOids = None
        self._queryPending = False
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

        tweakWidgetFont(self.ui.lineEdit, 85)

        withChildren = Qt.ShortcutContext.WidgetWithChildrenShortcut
        makeWidgetShortcut(self, lambda: self.jumpToMatch(self.Op.Next), "Return", "Enter", context=withChildren)
        makeWidgetShortcut(self, lambda: self.jumpToMatch(self.Op.Previous), "Shift+Return", "Shift+Enter", context=withChildren)
        makeWidgetShortcut(self, self.bail, "Escape", context=withChildren)

    @property
    def repoModel(self):
        return self.graphView.repoModel

    @property
    def lineEdit(self) -> QLineEdit:
        return self.ui.lineEdit

    @property
    def filterOnly(self) -> bool:
        return self.ui.filterOnlyCheckBox.isChecked()

    def prepareForDeletion(self):
        self._debounce.stop()
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

    def shouldDimIndex(self, index: QModelIndex) -> bool:
        if (not self.isVisible()
                or self.filterOnly
                or not self._needle
                or self._queryPending
                or self._matchOids is None):
            return False

        return not self.indexMatchesFileSearch(index)

    def indexMatchesFileSearch(self, index: QModelIndex) -> bool:
        """
        Whether this row counts as touching the path for next/prev navigation.
        """

        if (not index.isValid()
                or not self._needle
                or self._queryPending
                or self._matchOids is None):
            return False

        specialRow: SpecialRow = index.data(CommitLogModel.Role.SpecialRow)

        if specialRow == SpecialRow.UncommittedChanges:
            return self.repoModel.workdirMatchesPathNeedle(self._needle)

        if specialRow == SpecialRow.Commit:
            oid: Oid = index.data(CommitLogModel.Role.Oid)
            assert oid is not None
            return oid in self._matchOids

        return False

    def jumpToMatch(self, op: Op):
        gv = self.graphView
        model = gv.model()
        numRows = model.rowCount()
        if not self._needle or self._queryPending or self._matchOids is None:
            QApplication.beep()
            return

        if not gv.selectedIndexes():
            start = -1 if op == self.Op.Next else numRows
        else:
            start = gv.currentIndex().row()

        if op == self.Op.Next:
            range1 = range(start + 1, numRows)
            range2 = range(0, start + 1)
        else:
            range1 = range(start - 1, -1, -1)
            range2 = range(numRows - 1, start - 1, -1)

        for row in itertools.chain(range1, range2):
            index = model.index(row, 0)
            if self.indexMatchesFileSearch(index):
                gv.setCurrentIndex(index)
                return

        raw = self.lineEdit.text().strip()
        title = _("Find commits by changed file")
        message = _("{text} not found.", text=bquo(raw))
        qmb = asyncMessageBox(self, "information", title, message)
        qmb.show()

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self._pushStateToFilter()

    def hideEvent(self, event: QHideEvent):
        super().hideEvent(event)
        self._fullReset(clearLineEdit=True)

    def onQueryCommitsTouchingPathFinished(self, requestId: int, matchingOids: set[Oid]):
        if self.graphView is None:
            return
        if requestId != self._requestSeq:
            return
        self._queryPending = False
        self._matchOids = frozenset(matchingOids)
        self._pushStateToFilter()

    def _onTextChanged(self, text: str):
        self._needle = text.strip().lower()

        if self._needle:
            self._debounce.start()
        else:
            self._fullReset(clearLineEdit=False)

    def _onFilterOnlyToggled(self, _checked: bool):
        self._pushStateToFilter()

    def _startQuery(self):
        raw = self.ui.lineEdit.text().strip()
        if not raw:
            return

        self._requestSeq += 1
        self._queryPending = True
        self._matchOids = None
        self._pushStateToFilter()
        QueryCommitsTouchingPath.invoke(self.graphView, raw, self._requestSeq)

    def _pushStateToFilter(self):
        if self.graphView is None:
            return
        self.graphView.clFilter.setFilePathSearchState(
            needle=self._needle,
            matchOids=self._matchOids,
            queryPending=self._queryPending,
            filterOnly=self.filterOnly and bool(self._needle),
        )
        self.graphView.viewport().update()

    def _fullReset(self, clearLineEdit=False):
        self._debounce.stop()
        if clearLineEdit:
            with QSignalBlockerContext(self.ui.lineEdit):
                self.ui.lineEdit.clear()
        self._needle = ""
        self._queryPending = False
        self._matchOids = None
        self._requestSeq += 1
        self._pushStateToFilter()
