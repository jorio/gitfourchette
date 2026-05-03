# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations  # TODO: Remove once we can drop support for Python <= 3.13

import enum
import logging

from gitfourchette import colors
from gitfourchette.forms.ui_searchbar import Ui_SearchBar
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.search.searchprovider import SearchProvider
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)


class SearchBar(QWidget):
    class Op(enum.IntEnum):
        Start = enum.auto()
        Next = enum.auto()
        Previous = enum.auto()

    DebounceDelayMs = 250
    MacToolTipQuirks = MACOS
    _ToolTipTag = "<!--SearchBarToolTip-->"

    buddy: QWidget
    """
    Widget in which the search is carried out.
    """

    provider: SearchProvider | None
    """
    Current search provider.
    Receives the search term as input, performs the actual search.
    """

    providers: tuple[SearchProvider]
    """
    All search providers supported by this search bar.
    """

    debounceTimer: QTimer
    """
    Schedules the SearchProvider to update the search results after the user
    stops typing.
    """

    autoJumpWhenResultsComeIn: bool
    """
    If True, debouncing will jump to an occurrence of the search term, if found.
    Otherwise, the search term will be reevaluated without changing the
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
        return (self.ui.providerChooser,
                self.ui.forwardButton,
                self.ui.backwardButton,
                self.ui.closeButton,
                self.ui.filterCheckBox)

    def __init__(self, buddy: QWidget, *providers: SearchProvider):
        super().__init__(buddy)

        self.setObjectName(f"SearchBar({buddy.objectName()})")
        self.buddy = buddy

        self.ui = Ui_SearchBar()
        self.ui.setupUi(self)

        self.lineEdit.addAction(stockIcon("magnifying-glass"), QLineEdit.ActionPosition.LeadingPosition)
        self.loupe: QAction = self.lineEdit.actions()[0]

        self.lineEdit.textChanged.connect(self.onSearchTextChanged)
        self.ui.filterCheckBox.toggled.connect(self.onFilterCheckBoxToggled)

        self.ui.closeButton.clicked.connect(self.bail)
        self.ui.forwardButton.clicked.connect(self.runSearchForward)
        self.ui.backwardButton.clicked.connect(self.runSearchBackward)

        self.ui.forwardButton.setIcon(stockIcon("go-down-search"))
        self.ui.backwardButton.setIcon(stockIcon("go-up-search"))
        self.ui.closeButton.setIcon(stockIcon("dialog-close"))

        self._providerChooserMenu = QMenu(self)
        self._providerChooserMenu.addSection(_p("SearchBar", "Search scope"))
        self._providerChooserActionGroup = QActionGroup(self)
        self.ui.providerChooser.setMenu(self._providerChooserMenu)
        self.ui.providerChooser.setVisible(False)
        self.ui.providerChooser.setFixedWidth(80)

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

        self.autoJumpWhenResultsComeIn = True

        tweakWidgetFont(self.ui.lineEdit, 85)
        tweakWidgetFont(self.ui.filterCheckBox, 85)
        tweakWidgetFont(self.ui.providerChooser, 85)

        withChildren = Qt.ShortcutContext.WidgetWithChildrenShortcut
        makeWidgetShortcut(self, self.onEnterShortcut, "Return", "Enter", context=withChildren)
        makeWidgetShortcut(self, self.onShiftEnterShortcut, "Shift+Return", "Shift+Enter", context=withChildren)
        makeWidgetShortcut(self, self.bail, "Escape", context=withChildren)

        if SearchBar.MacToolTipQuirks:
            self.trapNextToolTip = False
            self.trappedToolTip = ""

        assert providers, "SearchBar needs at least one SearchProvider"
        self.provider = None
        self.providers = providers
        for provider in providers:
            self._installProvider(provider)
        self.ui.providerChooser.setVisible(len(providers) >= 2)
        self._setProvider(self.providers[0])

    def _installProvider(self, provider: SearchProvider):
        provider.statusChanged.connect(self.onProviderStatusChanged)
        provider.freeze(True)  # Freeze until in active use

        def makeCurrent():
            self._setProvider(provider)

        action = QAction(f"{provider.shortTitle()} \u2013 {provider.longTitle()}", parent=self)
        action.setActionGroup(self._providerChooserActionGroup)
        action.setCheckable(True)
        action.setData(provider)
        action.triggered.connect(makeCurrent)

        keys = provider.keyboardShortcut()
        if keys:
            action.setShortcut(keys)

            # Prevent action from being invoked by shortcut application-wide,
            # and duplicate the shortcut so it works throughout the SearchBar
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            makeWidgetShortcut(self, makeCurrent, keys, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

        self._providerChooserMenu.addAction(action)

    def onEnterShortcut(self):
        if SearchBar.MacToolTipQuirks:
            self.trapNextToolTip = True

        self.lineEdit.selectAll()
        self.runSearchForward()

    def onShiftEnterShortcut(self):
        if SearchBar.MacToolTipQuirks:
            self.trapNextToolTip = True

        self.lineEdit.selectAll()
        self.runSearchBackward()

    def runSearchForward(self):
        self.runSearch(True)

    def runSearchBackward(self):
        self.runSearch(False)

    def runSearch(self, forward: bool):
        wasAwaitingDebounce = self.debounceTimer.isActive()

        self.debounceTimer.stop()
        self.hideToolTip()

        # We're here because the user has hit the return key, and...
        # ...the query is still running, so tell user to chill
        if self.provider.status() == SearchProvider.TermStatus.Loading:
            self.showToolTip(_("Please wait…"))

        # ...user is in a hurry, expedite debounce
        elif wasAwaitingDebounce:
            self.onDebounce(forward)

        # ...we know there are matches, so jump to next match
        elif self.provider.isGoodAndNonEmpty():
            self.provider.jump(forward)

        # ...the search term is empty, so quack at user
        elif self.provider.isEmpty():
            QApplication.beep()

        # ...there are no results, so tell user about it explicitly
        elif self.provider.isBad():
            self.showToolTip(self.provider.notFoundMessage())

    def onDebounce(self, forwardHint: bool = True):
        assert self.isVisible(), "don't debounce while invisible"
        assert self.provider.status() != SearchProvider.TermStatus.Loading
        if self.provider.isEmpty() or self.provider.isBad():
            return

        self.hideToolTip()

        # Prime the search. This may emit provider.statusChanged, which is bound
        # to onProviderStatusChanged.
        self.provider.prime(forwardHint)

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

        # Set text in provider
        self.provider.setTerm(text)

        # Schedule a debounce
        if self.provider.term():
            self.autoJumpWhenResultsComeIn = True
            self.debounceTimer.start()

    def _setProvider(self, provider: SearchProvider):
        self.lineEdit.clear()

        providerIndex = self.providers.index(provider)
        assert providerIndex >= 0, "unregistered provider"
        oldProvider = self.provider

        if provider is oldProvider:
            return

        action = next(a for a in self._providerChooserMenu.actions()
                      if a.data() is provider)
        action.setChecked(True)

        if oldProvider is not None:
            # Freeze it when not in use
            with QSignalBlockerContext(oldProvider):
                oldProvider.freeze(True)

        logger.debug(f"Swapping provider to {provider.shortTitle()}")

        self.provider = provider
        self.ui.filterCheckBox.setVisible(provider.canFilter())

        self.ui.providerChooser.setText(provider.shortTitle())
        self.ui.lineEdit.setPlaceholderText(provider.longTitle())

        provider.freeze(False)

        # Update styling
        self.autoJumpWhenResultsComeIn = False
        self.onProviderStatusChanged(provider.status())

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
        self.autoJumpWhenResultsComeIn = False

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

        # If good search results just came in, jump to the next match
        # ...unless current selection already matches
        # ...unless an old search term is being reevaluated "passively"
        if (status == SearchProvider.TermStatus.Good
                and not self.provider.isCurrentMatch()
                and self.autoJumpWhenResultsComeIn):
            self.provider.jump(True)

    def showToolTip(self, text: str):
        # On macOS, Qt kills tooltips on keyup.
        # So, if enter key is down, stash tooltip until keyup.
        if SearchBar.MacToolTipQuirks:
            if self.trapNextToolTip:
                self.trappedToolTip = text
                return
            self.trappedToolTip = ""

        pos = QPoint(0, 0)

        # Hack: when the cursor is "above" the tooltip, then Qt makes the
        # tooltip vanish quickly. So try to avoid spawning the tooltip on top
        # of the cursor.
        if self.geometry().adjusted(0, 0, 0, 32).contains(self.mapFromGlobal(QCursor.pos())):
            pos.setY(-int(self.height() * 2.2))

        pos = self.mapToGlobal(pos)
        QToolTip.showText(pos, f"<p style='white-space: pre;'>{text}{self._ToolTipTag}", self)

    def hideToolTip(self):
        if SearchBar.MacToolTipQuirks:
            self.trappedToolTip = ""

        if QToolTip.isVisible() and QToolTip.text().endswith(self._ToolTipTag):
            QToolTip.hideText()

    if MacToolTipQuirks:
        # Schedule a tooltip that was trapped while the enter key was down.
        def keyReleaseEvent(self, event: QKeyEvent):
            super().keyReleaseEvent(event)
            self.trapNextToolTip = False
            if self.trappedToolTip:
                QTimer.singleShot(0, lambda t=self.trappedToolTip: self.showToolTip(t))

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
