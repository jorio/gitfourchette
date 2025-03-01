# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import enum
import re
from collections.abc import Callable

from gitfourchette import colors
from gitfourchette.forms.ui_searchbar import Ui_SearchBar
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.settings import TEST_MODE
from gitfourchette.toolbox import *

SEARCH_PULSE_DELAY = 250
LIKELY_HASH_PATTERN = re.compile(r"[0-9A-Fa-f]{1,40}")


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
    Must implement the `searchRange` callback. """

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

    @property
    def rawSearchTerm(self) -> str:
        return self.lineEdit.text()

    @property
    def lineEdit(self) -> QLineEdit:
        return self.ui.lineEdit

    @property
    def textChanged(self) -> SignalInstance:
        return self.lineEdit.textChanged

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

        self.lineEdit.setStyleSheet("border: 1px solid gray; border-radius: 5px;")
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

        appendShortcutToToolTip(self.ui.backwardButton, QKeySequence.StandardKey.FindPrevious)
        appendShortcutToToolTip(self.ui.forwardButton, QKeySequence.StandardKey.FindNext)
        appendShortcutToToolTip(self.ui.closeButton, Qt.Key.Key_Escape)

        self.searchTerm = ""
        self.searchTermBadStem = ""
        self.searchTermLooksLikeHash = False

        self.searchPulseTimer = QTimer(self)
        self.searchPulseTimer.setSingleShot(True)
        self.searchPulseTimer.setInterval(SEARCH_PULSE_DELAY if not TEST_MODE else 0)
        self.searchPulseTimer.timeout.connect(self.searchPulse)

        tweakWidgetFont(self.lineEdit, 85)

        shortcuts = [
            makeWidgetShortcut(self, self.onEnterShortcut, "Return", "Enter"),
            makeWidgetShortcut(self, self.onShiftEnterShortcut, "Shift+Return", "Shift+Enter"),
            makeWidgetShortcut(self, self.bail, "Escape"),
        ]
        for shortcut in shortcuts:
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

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

        # Don't re-trigger a search if the new search term contains a known-bad stem.
        badStem = self.searchTermBadStem
        stillBad = newTerm and badStem and badStem in newTerm

        if not stillBad:
            self.turnRed(False)

        self.searchTerm = newTerm
        self.searchTermChanged.emit(newTerm)

        if self.detectHashes and 0 < len(newTerm) <= 40:
            self.searchTermLooksLikeHash = bool(re.match(LIKELY_HASH_PATTERN, text))

        if newTerm and not stillBad:
            self.searchPulseTimer.start()
        else:
            self.searchPulseTimer.stop()

    def isRed(self) -> bool:
        return "true" == self.property("red")

    def turnRed(self, red=True):
        wasRed = self.property("red") == "true"
        self.setProperty("red", "true" if red else "false")
        if wasRed ^ red:  # trigger stylesheet refresh
            self.setStyleSheet("* {}")
            if red:
                self.searchTermBadStem = self.searchTerm
            else:
                self.searchTermBadStem = ""

    def searchRange(self, r: range) -> QModelIndex | None:
        """ Proxy for buddy.searchRange """
        assert hasattr(self.buddy, "searchRange"), "missing searchRange callback"
        return self.buddy.searchRange(r)

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
        assert hasattr(view, "searchRange"), "missing searchRange callback"

        self.textChanged.connect(lambda: view.model().layoutChanged.emit())  # Redraw graph view (is this efficient?)
        self.searchNext.connect(lambda: self.searchItemView(SearchBar.Op.Next))
        self.searchPrevious.connect(lambda: self.searchItemView(SearchBar.Op.Previous))
        self.searchPulse.connect(self.pulseItemView)

    def searchItemView(self, op: Op, wrappedFrom=-1, wrapCount=0) -> QModelIndex:
        NOT_FOUND = QModelIndex_default

        view = self.buddy
        assert isinstance(view, QAbstractItemView)

        model = view.model()  # use the view's top-level model to only search filtered rows

        self.popUp(forceSelectAll=op == SearchBar.Op.Start)

        if op == SearchBar.Op.Start:
            return NOT_FOUND

        if not self.searchTerm:  # user probably hit F3 without having searched before
            return NOT_FOUND

        didWrap = wrapCount > 0

        # Find start bound of search range
        if not didWrap and len(view.selectedIndexes()) != 0:
            start = view.currentIndex().row()
        elif op == SearchBar.Op.Next:
            start = -1  # offset +1 to get 0 in searchRange initialization
        else:
            start = model.rowCount()

        # Find stop bound of search range
        if didWrap:
            last = wrappedFrom
        elif op == SearchBar.Op.Next:
            last = model.rowCount() - 1
        else:
            last = 0

        # Set up range
        if op == SearchBar.Op.Next:
            searchRange = range(start + 1, last + 1)
        else:
            searchRange = range(start - 1, last - 1, -1)

        # Perform search within valid range
        if searchRange:
            index = self.searchRange(searchRange)

            # A valid index was found in the range, select it
            if index is not None and index.isValid():
                view.setCurrentIndex(index)
                return index

        # No valid index from this point on
        if not didWrap:
            # Wrap around once
            wrapCount += 1
            self.searchItemView(op, wrappedFrom=start, wrapCount=wrapCount)
        else:
            title = self.lineEdit.placeholderText().split("\x9C")[0]
            message = self.notFoundMessage(self.rawSearchTerm)
            qmb = asyncMessageBox(self, 'information', title, message)
            qmb.show()

        return NOT_FOUND

    def pulseItemView(self):
        view = self.buddy
        assert isinstance(view, QAbstractItemView)

        def generateSearchRanges():
            rowCount = view.model().rowCount()

            # If the view is empty, don't yield bogus ranges
            if rowCount == 0:
                return

            # First see if in visible range
            visibleRange = itemViewVisibleRowRange(view)
            yield visibleRange

            # It's not visible, so search below visible range first
            yield range(visibleRange.stop, rowCount)

            # Finally, search above the visible range
            yield range(0, visibleRange.start)

        for searchRange in generateSearchRanges():
            # Don't bother with search callback if range is empty
            if not searchRange:
                continue

            index = self.searchRange(searchRange)
            if index is not None and index.isValid():
                view.setCurrentIndex(index)
                return index

        self.turnRed()

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
