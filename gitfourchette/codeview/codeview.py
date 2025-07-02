# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.codeview.codehighlighter import CodeHighlighter
from gitfourchette.codeview.coderubberband import CodeRubberBand
from gitfourchette.forms.searchbar import SearchBar
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.qt import *
from gitfourchette.toolbox import *

if TYPE_CHECKING:
    from gitfourchette.codeview.codegutter import CodeGutter

logger = logging.getLogger(__name__)


class CodeView(QPlainTextEdit):
    contextualHelp = Signal(str)
    selectionActionable = Signal(bool)
    visibilityChanged = Signal(bool)

    highlighter: CodeHighlighter
    gutter: CodeGutter
    currentLocator: NavLocator
    isDetachedWindow: bool

    def __init__(self, gutterClass, highlighterClass=CodeHighlighter, parent=None):
        super().__init__(parent)

        self.setReadOnly(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.onContextMenuRequested)

        self.currentLocator = NavLocator()
        self.isDetachedWindow = False

        # Highlighter for search terms
        self.highlighter = highlighterClass(self)
        self.highlighter.setDocument(self.document())
        self.visibilityChanged.connect(self.highlighter.onParentVisibilityChanged)

        self.gutter = gutterClass(self)
        self.gutter.customContextMenuRequested.connect(self.onContextMenuRequestedFromGutter)
        self.updateRequest.connect(self.gutter.onParentUpdateRequest)
        # self.blockCountChanged.connect(self.updateGutterWidth)
        self.syncViewportMarginsWithGutter()

        self.cursorPositionChanged.connect(self.updateRubberBand)
        self.selectionChanged.connect(self.updateRubberBand)

        self.searchBar = SearchBar(self, _("Find text"))
        self.searchBar.searchNext.connect(lambda: self.search(SearchBar.Op.Next))
        self.searchBar.searchPrevious.connect(lambda: self.search(SearchBar.Op.Previous))
        self.searchBar.searchTermChanged.connect(self.onSearchTermChanged)
        self.searchBar.visibilityChanged.connect(self.onToggleSearch)
        self.searchBar.hide()

        self.rubberBand = CodeRubberBand(self.viewport())
        self.rubberBand.hide()

        self.rubberBandButtonGroup = QWidget(parent=self.viewport())
        rubberBandButtonLayout = QHBoxLayout(self.rubberBandButtonGroup)
        rubberBandButtonLayout.setSpacing(0)
        rubberBandButtonLayout.setContentsMargins(0, 0, 0, 0)
        self.rubberBandButtonGroup.hide()

        self.verticalScrollBar().valueChanged.connect(self.updateRubberBand)
        self.horizontalScrollBar().valueChanged.connect(self.updateRubberBand)

        # Initialize font & styling
        GFApplication.instance().restyle.connect(self.refreshPrefs)
        GFApplication.instance().prefsChanged.connect(self.refreshPrefs)
        self.refreshPrefs()

        makeWidgetShortcut(self, self.searchBar.hideOrBeep, "Escape")

    def setUpAsDetachedWindow(self):
        # In a detached window, we can't rely on the main window's menu bar to
        # dispatch shortcuts to us (except on macOS, which has a global main menu).

        self.isDetachedWindow = True

        makeWidgetShortcut(self, lambda: self.search(SearchBar.Op.Start), *GlobalShortcuts.find)
        makeWidgetShortcut(self, lambda: self.search(SearchBar.Op.Next), *GlobalShortcuts.findNext)
        makeWidgetShortcut(self, lambda: self.search(SearchBar.Op.Previous), *GlobalShortcuts.findPrevious)

        makeWidgetShortcut(self, lambda: self.window().close(), QKeySequence.StandardKey.Close,
                           context=Qt.ShortcutContext.WindowShortcut)

    # ---------------------------------------------
    # Qt events

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self.resizeGutter()
        self.updateRubberBand()

    def wheelEvent(self, event: QWheelEvent):
        # Drop-in replacement for QPlainTextEdit::wheelEvent which scales text
        # on ctrl+wheel. The vanilla version doesn't emit a signal, but we need
        # to percolate the new font to the gutter & rubberband.
        # See https://github.com/qt/qtbase/blob/6.7.2/src/widgets/widgets/qplaintextedit.cpp#L2327
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.wheelZoom(event.angleDelta().y())
            return

        super().wheelEvent(event)

    def wheelZoom(self, delta: int):
        delta //= 120
        font = self.font()
        oldSize = font.pointSizeF()
        newSize = oldSize + delta
        newSize = max(4, newSize)
        if newSize == oldSize:
            return
        font.setPointSizeF(newSize)
        self.setFont(font)
        self.gutter.syncFont(font)
        self.syncViewportMarginsWithGutter()
        self.updateRubberBand()

    def focusInEvent(self, event: QFocusEvent):
        self.rubberBand.repaint()
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent):
        self.rubberBand.repaint()
        super().focusOutEvent(event)

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        self.visibilityChanged.emit(True)

    def hideEvent(self, event: QHideEvent):
        super().hideEvent(event)
        self.visibilityChanged.emit(False)

    # ---------------------------------------------
    # Document replacement

    def clear(self):  # override
        # Clear info about the current patch - necessary for document reuse detection to be correct when the user
        # clears the selection in a FileList and then reselects the last-displayed document.
        self.currentLocator = NavLocator()

        # Clear the actual contents
        super().clear()

    # ---------------------------------------------
    # Restore position

    def restorePosition(self, locator: NavLocator):
        # Get position at start/end of line
        block: QTextBlock = self.document().findBlockByNumber(locator.cursorLine)
        sol = block.position()
        eol = block.position() + block.length()

        # If cursor position still falls within the same line, keep that position.
        # Otherwise, snap cursor position to start of line.
        pos = locator.cursorChar
        if not (sol <= pos < eol):
            pos = sol

        # Move text cursor
        newTextCursor = self.textCursor()
        newTextCursor.setPosition(pos)
        self.setTextCursor(newTextCursor)

        # Restore the scrollbar
        self.restoreScrollPosition(locator.scrollChar)

    def restoreScrollPosition(self, topCharacter: int) -> int:
        scrollValue = self._findScrollPosition(topCharacter)
        self.verticalScrollBar().setValue(scrollValue)
        return scrollValue

    def _findScrollPosition(self, topCharacter: int) -> int:
        """
        Return a value to be set on the vertical scrollbar so that `topCharacter`
        is part of the first visible line in the viewport.
        """
        if topCharacter == 0:
            return 0

        topCursor = self.textCursor()
        topCursor.setPosition(topCharacter)

        scrollBar = self.verticalScrollBar()

        # If line wrapping is OFF, QScrollBar.value() perfectly matches up with
        # line numbers.
        if self.lineWrapMode() == QPlainTextEdit.LineWrapMode.NoWrap:
            return topCursor.blockNumber()

        # If line wrapping is ON, we can't simply cache and restore QScrollBar.value().
        # It seems that QPlainTextEdit doesn't wrap lines that aren't visible yet,
        # so the scrollbar's range isn't reliable until the desired line is in view.

        # First, center the viewport on the desired top character.
        backupCursor = self.textCursor()
        self.setTextCursor(topCursor)
        self.centerCursor()

        # Scroll down one notch at a time until topCharacter becomes part of
        # the top visible line in the viewport.
        cornerPixel = self.topLeftCornerPixel()
        scrollValue = 0
        i = 0
        while i < 500 and self.cursorForPosition(cornerPixel).position() < topCharacter:
            i += 1
            scrollValue = scrollBar.value() + 1
            scrollBar.setValue(scrollValue)
            if scrollBar.value() < scrollValue:  # Can't scroll past end of document
                break

        # logger.debug(f"Stabilized in {i} iterations - final scroll {scrollValue} - "
        #              f"char pos {self.cursorForPosition(cornerPixel).position()} vs {topCharacter}")

        # Restore backup cursor
        self.setTextCursor(backupCursor)

        return scrollValue

    def topLeftCornerPixel(self) -> QPoint:
        return QPoint(0, self.fontMetrics().height() // 2)

    def topLeftCornerCursor(self) -> QTextCursor:
        cornerPixel = self.topLeftCornerPixel()
        cornerCursor = self.cursorForPosition(cornerPixel)
        return cornerCursor

    def topLeftCornerCharacter(self) -> int:
        cornerCursor = self.topLeftCornerCursor()
        return cornerCursor.position()

    def preciseLocator(self) -> NavLocator:
        scrollChar = self.topLeftCornerCharacter()
        textCursor = self.textCursor()

        locator = self.currentLocator.coarse()
        locator = locator.replace(
            cursorChar=textCursor.position(),
            cursorLine=textCursor.blockNumber(),
            scrollChar=scrollChar)

        return locator

    # ---------------------------------------------
    # Prefs

    def refreshPrefs(self, changeColorScheme=True):
        monoFont = settings.prefs.monoFont()
        self.setFont(monoFont)

        currentDocument = self.document()
        if currentDocument:
            currentDocument.setDefaultFont(monoFont)

        tabWidth = settings.prefs.tabSpaces
        self.setTabStopDistance(QFontMetricsF(monoFont).horizontalAdvance(' ' * tabWidth))
        self.refreshWordWrap()
        self.setCursorWidth(2)

        self.gutter.syncFont(monoFont)
        self.syncViewportMarginsWithGutter()

        if changeColorScheme:
            scheme = settings.prefs.syntaxHighlightingScheme()
            self.highlighter.setColorScheme(scheme)
            self.highlighter.rehighlight()

            # See selection-background-color in .qss asset.
            dark = scheme.isDark() if scheme else isDarkTheme()
            self.setProperty("dark", "true" if dark else "false")

            # Had better luck setting colors with a stylesheet than via setPalette().
            styleSheet = scheme.basicQss(self)
            self.setStyleSheet(styleSheet)

    def refreshWordWrap(self):
        if settings.prefs.wordWrap:
            wrapMode = QPlainTextEdit.LineWrapMode.WidgetWidth
        else:
            wrapMode = QPlainTextEdit.LineWrapMode.NoWrap

        # Bail if no-op
        if self.lineWrapMode() == wrapMode:
            return

        # Changing the wrap mode will trash our scroll position, so remember where we are.
        topCharacter = self.topLeftCornerCharacter()

        self.setLineWrapMode(wrapMode)
        self.restoreScrollPosition(topCharacter)

    def toggleWordWrap(self):
        settings.prefs.wordWrap = not settings.prefs.wordWrap
        settings.prefs.write()
        self.refreshWordWrap()

    # ---------------------------------------------
    # Context menu

    def contextMenuActions(self, clickedCursor: QTextCursor) -> list[ActionDef]:
        raise NotImplementedError("subclasses of CodeView must override this!")

    def onContextMenuRequested(self, point: QPoint):
        # Don't show the context menu if we're empty
        if self.document().isEmpty():
            return None

        # Get standard context menu (copy, select all, etc.)
        bottomMenu: QMenu = self.createStandardContextMenu()

        # Get position of click in document
        clickedCursor = self.cursorForPosition(point)

        # Get actions from concrete class
        actions = self.contextMenuActions(clickedCursor)

        # Append common CodeView actions
        actions += [
            ActionDef.SEPARATOR,
            ActionDef(_("&Word Wrap"), self.toggleWordWrap, checkState=1 if settings.prefs.wordWrap else -1),
            ActionDef(_("Configure Appearance…"), lambda: GFApplication.instance().openPrefsDialog("font"), icon="configure"),
            ActionDef.SEPARATOR,
            *bottomMenu.actions(),
        ]

        # Create QMenu
        menu = ActionDef.makeQMenu(self, actions)
        menu.setObjectName("CodeViewContextMenu")
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        # The master menu doesn't take ownership of bottomMenu's actions,
        # so bottomMenu must be kept alive until the master menu is closed.
        menu.destroyed.connect(bottomMenu.deleteLater)

        # Show QMenu
        menu.popup(self.viewport().mapToGlobal(point))

    def onContextMenuRequestedFromGutter(self, point: QPoint):
        point = self.gutter.mapToGlobal(point)
        point = self.viewport().mapFromGlobal(point)
        self.onContextMenuRequested(point)

    # ---------------------------------------------
    # Gutter

    def resizeGutter(self):
        cr: QRect = self.contentsRect()
        cr.setWidth(self.gutter.calcWidth())
        self.gutter.setGeometry(cr)

    def syncViewportMarginsWithGutter(self):
        self.gutter.refreshMetrics()
        gutterWidth = self.gutter.calcWidth()

        # Prevent Qt freeze if margin width exceeds widget width, e.g. when window is very narrow
        # (especially prevalent with word wrap?)
        self.setMinimumWidth(gutterWidth * 2)

        self.setViewportMargins(gutterWidth, 0, 0, 0)

    # ---------------------------------------------
    # Rubberband

    def updateRubberBand(self):
        pass

    # ---------------------------------------------
    # Cursor/selection

    def getSelectedLineExtents(self):
        """ Return block numbers of the first and last blocks encompassing the current selection """

        cursor: QTextCursor = self.textCursor()
        posStart = cursor.selectionStart()
        posEnd = cursor.selectionEnd()

        assert posStart >= 0
        assert posEnd >= 0

        document: QTextDocument = self.document()
        startBlock = document.findBlock(posStart).blockNumber()
        endBlock = document.findBlock(posEnd).blockNumber()

        return startBlock, endBlock

    def getMaxPosition(self):
        lastBlock = self.document().lastBlock()
        return lastBlock.position() + max(0, lastBlock.length() - 1)

    def getAnchorHomeLinePosition(self):
        cursor: QTextCursor = self.textCursor()

        # Snap anchor to start of home line
        cursor.setPosition(cursor.anchor(), QTextCursor.MoveMode.MoveAnchor)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.MoveAnchor)

        return cursor.anchor()

    def getStartOfLineAt(self, point: QPoint):
        clickedCursor: QTextCursor = self.cursorForPosition(point)
        clickedCursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        return clickedCursor.position()

    def replaceCursor(self, cursor: QTextCursor):
        """Replace the cursor without moving the horizontal scroll bar"""
        with QScrollBackupContext(self.horizontalScrollBar()):
            self.setTextCursor(cursor)

    def selectWholeLineAt(self, point: QPoint):
        clickedPosition = self.getStartOfLineAt(point)

        cursor: QTextCursor = self.textCursor()
        cursor.setPosition(clickedPosition)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)

        self.replaceCursor(cursor)

    def selectWholeLinesTo(self, point: QPoint):
        homeLinePosition = self.getAnchorHomeLinePosition()
        clickedPosition = self.getStartOfLineAt(point)

        cursor: QTextCursor = self.textCursor()

        if homeLinePosition <= clickedPosition:
            # Move anchor to START of home line
            cursor.setPosition(homeLinePosition, QTextCursor.MoveMode.MoveAnchor)
            # Move cursor to END of clicked line
            cursor.setPosition(clickedPosition, QTextCursor.MoveMode.KeepAnchor)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        else:
            # Move anchor to END of home line
            cursor.setPosition(homeLinePosition, QTextCursor.MoveMode.MoveAnchor)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.MoveAnchor)
            # Move cursor to START of clicked line
            cursor.setPosition(clickedPosition, QTextCursor.MoveMode.KeepAnchor)
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)

        self.replaceCursor(cursor)

    # ---------------------------------------------
    # Search

    def onSearchTermChanged(self, term: str):
        numOccurrences = self.highlighter.setSearchTerm(term)
        self.searchBar.setRed(bool(term) and numOccurrences == 0)

    def onToggleSearch(self, searching: bool):
        if not searching:
            self.highlighter.setSearchTerm("")
        else:
            self.onSearchTermChanged(self.searchBar.searchTerm)

    def search(self, op: SearchBar.Op):
        assert isinstance(op, SearchBar.Op)
        self.searchBar.popUp(forceSelectAll=op == SearchBar.Op.Start)

        if op == SearchBar.Op.Start:
            return

        message = self.searchBar.searchTerm
        if not message:
            QApplication.beep()
            return

        doc: QTextDocument = self.document()

        if op == SearchBar.Op.Next:
            newCursor = doc.find(message, self.textCursor())
        else:
            newCursor = doc.find(message, self.textCursor(), QTextDocument.FindFlag.FindBackward)

        if newCursor and not newCursor.isNull():  # extra isNull check needed for PyQt5 & PyQt6
            self.setTextCursor(newCursor)
            return

        def wrapAround():
            tc = self.textCursor()
            if op == SearchBar.Op.Next:
                tc.movePosition(QTextCursor.MoveOperation.Start)
            else:
                tc.movePosition(QTextCursor.MoveOperation.End)
            self.setTextCursor(tc)
            self.search(op)

        prompt = [
            _("End of document reached.") if op == SearchBar.Op.Next
            else _("Top of document reached."),
            _("No more occurrences of {0} found.", bquo(message))
        ]
        askConfirmation(
            self,
            self.searchBar.lineEdit.placeholderText().split('\x9C', 1)[0],
            paragraphs(prompt),
            okButtonText=_("Wrap Around"),
            messageBoxIcon="information",
            callback=wrapAround)

    @staticmethod
    def currentDetachedCodeView() -> CodeView:
        activeWindow = QApplication.activeWindow()
        detachedCodeView: CodeView = activeWindow.findChild(CodeView)
        if detachedCodeView is None:
            raise KeyError("no detached code view")
        assert detachedCodeView.isDetachedWindow
        return detachedCodeView
