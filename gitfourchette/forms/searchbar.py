# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import enum
import itertools
import logging
import re
from collections.abc import Callable, Iterable

from gitfourchette import colors
from gitfourchette.forms.ui_searchbar import Ui_SearchBar
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)

SEARCH_PULSE_DELAY = 250
LIKELY_HASH_PATTERN = re.compile(r"[0-9A-Fa-f]{1,40}")


class SearchResultsNotReady(Exception):
    pass


class SearchBar(QWidget):
    class Op(enum.IntEnum):
        Start = enum.auto()
        Next = enum.auto()
        Previous = enum.auto()

    searchNext = Signal()
    searchPrevious = Signal()
    searchPulse = Signal()
    visibilityChanged = Signal(bool)
    searchTermChanged = Signal(str)

    buddy: QWidget
    """ Widget in which the search is carried out.
    Must implement the `searchRows` callback. """

    detectHashes: bool
    """ Try to optimize for 40-character SHA-1 hashes.
    Set this flag before initiating a search.
    Will cause `searchTermLooksLikeHash` to be updated. """

    searchTerm: str
    """ Sanitized search term (lowercase, stripped whitespace).
    Updated when the user edits the QLineEdit. """

    searchTermBadStem: str
    """ Substring of the current term for which we know there aren't any
    matches. """

    searchTermLooksLikeHash: bool
    """ True if the search term looks like the start of a 40-character SHA-1 hash.
    Updated at the same time as searchTerm if detectHashes was enabled beforehand. """

    searchPulseTimer: QTimer

    notFoundMessage: Callable[[str], str]
    """ Callback that generates "not found" text. """

    selectNextOccurrenceOnPulse: bool
    """ If True, searchPulseTimer's callback will select the next occurrence of
    the search term (if found) in the buddy widget. Otherwise, the search term
    will be reevaluated without changing the selection. This flag is reset to
    True whenever searchPulseTimer is retriggered. """

    @property
    def rawSearchTerm(self) -> str:
        return self.lineEdit.text()

    @property
    def lineEdit(self) -> QLineEdit:
        return self.ui.lineEdit

    @property
    def buttons(self):
        return self.ui.forwardButton, self.ui.backwardButton, self.ui.closeButton

    def __init__(self, buddy: QWidget, placeholderText: str):
        super().__init__(buddy)

        self.setObjectName(f"SearchBar({buddy.objectName()})")
        self.buddy = buddy
        self.detectHashes = False
        self.notFoundMessage = SearchBar.defaultNotFoundMessage

        self.ui = Ui_SearchBar()
        self.ui.setupUi(self)

        self.lineEdit.setPlaceholderText(placeholderText)
        self.lineEdit.addAction(stockIcon("magnifying-glass"), QLineEdit.ActionPosition.LeadingPosition)
        self.lineEdit.textChanged.connect(self.onSearchTextChanged)

        self.ui.closeButton.clicked.connect(self.bail)
        self.ui.forwardButton.clicked.connect(self.searchNext)
        self.ui.backwardButton.clicked.connect(self.searchPrevious)

        self.ui.forwardButton.setIcon(stockIcon("go-down-search"))
        self.ui.backwardButton.setIcon(stockIcon("go-up-search"))
        self.ui.closeButton.setIcon(stockIcon("dialog-close"))

        # The size of the buttons is readjusted after show(),
        # so prevent visible popping when booting up for the first time.
        for button in self.buttons:
            button.setMaximumHeight(1)

        appendShortcutToToolTip(self.ui.backwardButton, GlobalShortcuts.findPrevious[0])
        appendShortcutToToolTip(self.ui.forwardButton, GlobalShortcuts.findNext[0])
        appendShortcutToToolTip(self.ui.closeButton, Qt.Key.Key_Escape)

        self.searchTerm = ""
        self.searchTermBadStem = ""
        self.searchTermLooksLikeHash = False
        self.selectNextOccurrenceOnPulse = True

        self.searchPulseTimer = QTimer(self)
        self.searchPulseTimer.setSingleShot(True)
        self.searchPulseTimer.setInterval(SEARCH_PULSE_DELAY if not APP_TESTMODE else 0)
        self.searchPulseTimer.timeout.connect(self.searchPulse)

        tweakWidgetFont(self.lineEdit, 85)

        withChildren = Qt.ShortcutContext.WidgetWithChildrenShortcut
        makeWidgetShortcut(self, self.onEnterShortcut, "Return", "Enter", context=withChildren)
        makeWidgetShortcut(self, self.onShiftEnterShortcut, "Shift+Return", "Shift+Enter", context=withChildren)
        makeWidgetShortcut(self, self.bail, "Escape", context=withChildren)

    def onEnterShortcut(self):
        self.lineEdit.selectAll()
        if not self.searchTerm:
            QApplication.beep()
        else:
            self.searchNext.emit()

    def onShiftEnterShortcut(self):
        self.lineEdit.selectAll()
        if not self.searchTerm:
            QApplication.beep()
        else:
            self.searchPrevious.emit()

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self.visibilityChanged.emit(True)

    def hideEvent(self, event: QHideEvent):
        super().hideEvent(event)
        self.visibilityChanged.emit(False)

    def hideOrBeep(self):
        if self.isVisible():  # close search bar if it doesn't have focus
            self.hide()
        else:
            QApplication.beep()

    def popUp(self, forceSelectAll=False):
        wasHidden = self.isHidden()
        self.show()

        for button in self.buttons:
            button.setMaximumHeight(self.lineEdit.height())

        self.lineEdit.setFocus(Qt.FocusReason.PopupFocusReason)

        if forceSelectAll or wasHidden:
            self.lineEdit.selectAll()

    def bail(self):
        self.searchPulseTimer.stop()
        self.buddy.setFocus(Qt.FocusReason.PopupFocusReason)
        self.hide()

    def onSearchTextChanged(self, text: str):
        newTerm = text.strip().lower()
        self.searchTerm = newTerm

        # Emit searchTermChanged now to let anyone invalidate the badStem
        self.searchTermChanged.emit(newTerm)

        # Don't re-trigger a search if the new search term contains a known-bad stem.
        badStem = self.searchTermBadStem
        stillBad = newTerm and badStem and badStem in newTerm

        if not stillBad:
            self.setRed(False)

        if self.detectHashes and 0 < len(newTerm) <= 40:
            self.searchTermLooksLikeHash = bool(re.match(LIKELY_HASH_PATTERN, text))

        if newTerm and not stillBad:
            self.selectNextOccurrenceOnPulse = True
            self.searchPulseTimer.start()
        else:
            self.searchPulseTimer.stop()

    def reevaluateSearchTerm(self):
        self.invalidateBadStem()
        if self.isVisible():
            self.onSearchTextChanged(self.rawSearchTerm)
            self.selectNextOccurrenceOnPulse = False

    def isRed(self) -> bool:
        return "true" == self.property("red")

    def setRed(self, red=True):
        wasRed = self.property("red") == "true"
        self.setProperty("red", "true" if red else "false")
        if wasRed ^ red:  # trigger stylesheet refresh
            self.setStyleSheet("* {}")
            if red:
                self.searchTermBadStem = self.searchTerm
            else:
                self.searchTermBadStem = ""

    def searchRows(self, rows: Iterable[int]) -> QModelIndex | None:
        """ Proxy for buddy.searchRows """
        try:
            callback = self.buddy.searchRows
        except AttributeError as ae:
            raise AttributeError("buddy missing searchRows callback") from ae
        return callback(rows)

    @staticmethod
    def defaultNotFoundMessage(searchTerm: str) -> str:
        return _("{text} not found.", text=bquo(searchTerm))

    def invalidateBadStem(self):
        self.searchTermBadStem = ""

    # --------------------------------
    # Ready-made QAbstractItemView search flow

    def setUpItemViewBuddy(self):
        view = self.buddy
        assert isinstance(view, QAbstractItemView)
        assert hasattr(view, "searchRows"), "buddy missing searchRows callback"

        self.searchTermChanged.connect(lambda: view.viewport().update())  # Repaint buddy
        self.searchNext.connect(lambda: self.searchItemView(SearchBar.Op.Next))
        self.searchPrevious.connect(lambda: self.searchItemView(SearchBar.Op.Previous))
        self.searchPulse.connect(self.pulseItemView)

    def searchItemView(self, op: Op) -> QModelIndex:
        NOT_FOUND = QModelIndex_default

        view = self.buddy
        assert isinstance(view, QAbstractItemView)

        model = view.model()  # use the view's top-level model to only search filtered rows
        numRows = model.rowCount()

        self.popUp(forceSelectAll=op == SearchBar.Op.Start)

        if op == SearchBar.Op.Start:
            return NOT_FOUND

        if not self.searchTerm:  # user probably hit F3 without having searched before
            return NOT_FOUND

        # Find start bound of search range
        if len(view.selectedIndexes()) != 0:
            start = view.currentIndex().row()
        elif op == SearchBar.Op.Next:
            start = -1  # range initialization adds +1 below, so we'll start at row 0
        else:
            start = numRows

        # Set up range
        if op == SearchBar.Op.Next:
            range1 = range(start + 1, numRows)
            range2 = range(0, start + 1)
        else:
            range1 = range(start - 1, -1, -1)
            range2 = range(numRows - 1, start - 1, -1)

        # Perform search within valid range
        rowsGen = itertools.chain(range1, range2)
        index = self.searchRows(rowsGen)

        # A valid index was found in the range, select it
        if index is not None and index.isValid():
            view.setCurrentIndex(index)
            return index

        # No valid index from this point on
        title = self.lineEdit.placeholderText().split("\x9C")[0]
        message = self.notFoundMessage(self.rawSearchTerm)
        qmb = asyncMessageBox(self, 'information', title, message)
        qmb.show()

        return NOT_FOUND

    def pulseItemView(self):
        # Kill timer, in case we were called manually
        self.searchPulseTimer.stop()

        view = self.buddy
        assert isinstance(view, QAbstractItemView)
        rowCount = view.model().rowCount()

        # If the view is empty, don't yield bogus ranges
        if rowCount == 0:
            index = None
        else:
            # 1. First, search within visible range
            # 2. Then, search below visible range
            # 3. Finally, search above visible range
            visible = itemViewVisibleRowRange(view)
            below = range(visible.stop, rowCount)
            above = range(0, visible.start)

            rowsGen = itertools.chain(visible, below, above)
            try:
                index = self.searchRows(rowsGen)
            except SearchResultsNotReady:
                logger.debug("Search results not ready.")
                return

        if index is None or not index.isValid():
            self.setRed()
        elif self.selectNextOccurrenceOnPulse:
            view.setCurrentIndex(index)

    @staticmethod
    def highlightNeedle(painter: QPainter, rect: QRect, text: str,
                        needlePos: int, needleLen: int,
                        widthUpToNeedle: int = -1, widthPastNeedle: int = -1):

        if widthUpToNeedle < 0 or widthPastNeedle < 0:
            fontMetrics = painter.fontMetrics()
            widthUpToNeedle = fontMetrics.horizontalAdvance(text, needlePos)
            widthPastNeedle = fontMetrics.horizontalAdvance(text, needlePos + needleLen)
        needleWidth = widthPastNeedle - widthUpToNeedle

        needleRect = QRect(rect.left() + widthUpToNeedle, rect.top(), needleWidth, rect.height())
        hiliteRect = QRectF(needleRect).marginsAdded(QMarginsF(2, -1, 2, -1))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Yellow rounded rect
        path = QPainterPath()
        path.addRoundedRect(hiliteRect, 4, 4)
        painter.fillPath(path, colors.yellow)

        # Re-draw needle on top of highlight rect
        painter.setPen(Qt.GlobalColor.black)  # force black-on-yellow regardless of dark/light theme
        needleText = text[needlePos:needlePos + needleLen]
        painter.drawText(needleRect, Qt.AlignmentFlag.AlignCenter, needleText)

        painter.restore()
