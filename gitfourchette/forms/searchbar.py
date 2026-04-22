# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations  # TODO: Remove once we can drop support for Python <= 3.13

import enum

from gitfourchette import colors
from gitfourchette.forms.ui_searchbar import Ui_SearchBar
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.qt import *
from gitfourchette.search.searchprovider import SearchProvider
from gitfourchette.toolbox import *


class SearchBar(QWidget):
    class Op(enum.IntEnum):
        Start = enum.auto()
        Next = enum.auto()
        Previous = enum.auto()

    DebounceDelayMs = 250
    _ToolTipTag = "<!--SearchBarToolTip-->"

    buddy: QWidget
    """
    Widget in which the search is carried out.
    """

    provider: SearchProvider
    """
    Receives the search term as input, performs the actual search.
    """

    debounceTimer: QTimer
    """
    Schedules the SearchProvider to update the search results after the user
    stops typing.
    """

    nextDebounceAllowJump: bool
    """
    If True, debouncing will select the next occurrence of the search term, if
    found. Otherwise, the search term will be reevaluated without changing the
    selection. This flag is reset to True whenever a debounce is rescheduled.
    """

    @property
    def rawSearchTerm(self) -> str:
        return self.lineEdit.text()

    @property
    def lineEdit(self) -> QLineEdit:
        return self.ui.lineEdit

    @property
    def buttons(self):
        return self.ui.forwardButton, self.ui.backwardButton, self.ui.closeButton, self.ui.filterCheckBox

    def __init__(self, buddy: QWidget, provider: SearchProvider):
        super().__init__(buddy)

        self.setObjectName(f"SearchBar({buddy.objectName()})")
        self.provider = provider
        self.buddy = buddy

        self.provider.statusChanged.connect(self.onProviderStatusChanged)

        self.ui = Ui_SearchBar()
        self.ui.setupUi(self)

        self.lineEdit.addAction(stockIcon("magnifying-glass"), QLineEdit.ActionPosition.LeadingPosition)
        self.loupe = self.lineEdit.actions()[0]

        self.lineEdit.textChanged.connect(self.onSearchTextChanged)
        self.ui.filterCheckBox.toggled.connect(self.onFilterCheckBoxToggled)

        self.ui.closeButton.clicked.connect(self.bail)
        self.ui.forwardButton.clicked.connect(self.runSearchForward)
        self.ui.backwardButton.clicked.connect(self.runSearchBackward)

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

        self.debounceTimer = QTimer(self)
        self.debounceTimer.setSingleShot(True)
        self.debounceTimer.setInterval(self.DebounceDelayMs if not APP_TESTMODE else 0)
        self.debounceTimer.timeout.connect(self.onDebounce)

        self.nextDebounceAllowJump = True

        tweakWidgetFont(self.ui.lineEdit, 85)
        tweakWidgetFont(self.ui.filterCheckBox, 85)

        withChildren = Qt.ShortcutContext.WidgetWithChildrenShortcut
        makeWidgetShortcut(self, self.onEnterShortcut, "Return", "Enter", context=withChildren)
        makeWidgetShortcut(self, self.onShiftEnterShortcut, "Shift+Return", "Shift+Enter", context=withChildren)
        makeWidgetShortcut(self, self.bail, "Escape", context=withChildren)

    def onEnterShortcut(self):
        self.lineEdit.selectAll()
        self.runSearchForward()

    def onShiftEnterShortcut(self):
        self.lineEdit.selectAll()
        self.runSearchBackward()

    def runSearchForward(self):
        self.runSearch(True)

    def runSearchBackward(self):
        self.runSearch(False)

    def runSearch(self, forward: bool):
        self.debounceTimer.stop()
        self.hideToolTip()

        if not self.provider.isEmpty() and not self.provider.isBad():
            self.provider.jump(forward)

        if self.provider.isEmpty():
            QApplication.beep()
        elif self.provider.isBad():
            self.showToolTip(self.provider.notFoundMessage())

    def onDebounce(self):
        assert self.isVisible(), "don't debounce while invisible"

        self.hideToolTip()

        if not self.provider.isEmpty() and not self.provider.isBad():
            self.provider.debounce(self.nextDebounceAllowJump)

    def showEvent(self, event: QShowEvent):
        self.provider.freeze(False)
        self.reevaluateSearchTerm()
        super().showEvent(event)

    def hideEvent(self, event: QHideEvent):
        self.provider.freeze(True)
        self.debounceTimer.stop()
        super().hideEvent(event)

    def hideOrBeep(self):
        if self.isVisible():  # close search bar if it doesn't have focus
            self.bail()
        else:
            QApplication.beep()

    def popUp(self, op: SearchBar.Op):
        wasHidden = self.isHidden()
        self.show()

        for button in self.buttons:
            button.setMaximumHeight(self.lineEdit.height())

        self.lineEdit.setFocus(Qt.FocusReason.PopupFocusReason)

        if op == SearchBar.Op.Start or wasHidden:
            self.lineEdit.selectAll()

        # Explicit jump next/previous
        if op == SearchBar.Op.Next:
            self.onEnterShortcut()
        elif op == SearchBar.Op.Previous:
            self.onShiftEnterShortcut()

    def bail(self):
        self.debounceTimer.stop()
        self.buddy.setFocus(Qt.FocusReason.PopupFocusReason)
        self.hide()

    def onSearchTextChanged(self, text: str):
        assert self.isVisible()
        self.hideToolTip()

        self.provider.setTerm(text)

        # Schedule a debounce
        self.nextDebounceAllowJump = True
        self.debounceTimer.start()

    def onFilterCheckBoxToggled(self):
        assert self.isVisible()
        self.provider.setFilterState(self.ui.filterCheckBox.isChecked())

    def reevaluateSearchTerm(self):
        # Clear bad stem, if any
        self.provider.invalidate()

        if not self.isVisible():
            return

        # Re-evaluate search term. This will schedule a debounce,
        # but prevent the subsequent jump.
        self.onSearchTextChanged(self.rawSearchTerm)
        self.nextDebounceAllowJump = False

    def isRed(self) -> bool:
        return "true" == self.property("red")

    def onProviderStatusChanged(self, status: SearchProvider.TermStatus):
        self.hideToolTip()

        red = status == SearchProvider.TermStatus.Bad
        wasRed = self.isRed()
        self.setProperty("red", "true" if red else "false")
        if wasRed ^ red:  # trigger stylesheet refresh
            self.setStyleSheet("* {}")

        loupeIcon = "magnifying-glass-wait" if status == SearchProvider.TermStatus.Loading else "magnifying-glass"
        self.loupe.setIcon(stockIcon(loupeIcon))

        with QSignalBlockerContext(self.ui.filterCheckBox):
            self.ui.filterCheckBox.setVisible(self.provider.canFilter())

    def showToolTip(self, text: str):
        pos = QPoint(0, 0)

        # Hack: when the cursor is "above" the tooltip, then Qt makes the
        # tooltip vanish quickly. So try to avoid spawning the tooltip on top
        # of the cursor.
        if self.geometry().adjusted(0, 0, 0, 32).contains(self.mapFromGlobal(QCursor.pos())):
            pos.setY(-int(self.height() * 2.2))

        pos = self.mapToGlobal(pos)
        QToolTip.showText(pos, f"<p style='white-space: pre;'>{text}{self._ToolTipTag}", self)

    def hideToolTip(self):
        if QToolTip.isVisible() and QToolTip.text().endswith(self._ToolTipTag):
            QToolTip.hideText()

    @staticmethod
    def highlightNeedle(painter: QPainter, rect: QRect, text: str,
                        needlePos: int = 0, needleLen: int = -1,
                        widthUpToNeedle: int = -1, widthPastNeedle: int = -1,
                        lBleed: int = 2, rBleed: int = 2):
        """
        Helper function to render "found needle" text in the buddy widget's item
        delegate.
        """

        if needleLen < 0:
            needleLen = len(text)

        if widthUpToNeedle < 0 or widthPastNeedle < 0:
            fontMetrics = painter.fontMetrics()
            widthUpToNeedle = fontMetrics.horizontalAdvance(text, needlePos)
            widthPastNeedle = fontMetrics.horizontalAdvance(text, needlePos + needleLen)
        needleWidth = widthPastNeedle - widthUpToNeedle

        needleRect = QRect(rect.left() + widthUpToNeedle, rect.top(), needleWidth, rect.height())
        hiliteRect = QRectF(needleRect).marginsAdded(QMarginsF(lBleed, -1, rBleed, -1))

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
