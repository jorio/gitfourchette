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

        self.currentLocator = NavLocator()
        self.isDetachedWindow = False

        # Highlighter for search terms
        self.highlighter = highlighterClass(self)
        self.highlighter.setDocument(self.document())
        self.visibilityChanged.connect(self.highlighter.onParentVisibilityChanged)

        self.gutter = gutterClass(self)
        self.gutter.customContextMenuRequested.connect(lambda p: self.execContextMenu(self.gutter.mapToGlobal(p)))
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

    def contextMenuEvent(self, event: QContextMenuEvent):
        self.execContextMenu(event.globalPos())

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
        if delta == 0:
            return
        font = self.font()
        newSize = font.pointSizeF() + delta
        if newSize <= 0:
            return
        font.setPointSizeF(newSize)
        self.setFont(font)
        self.gutter.setFont(font)
        self.resizeGutter()
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
        pos = locator.diffCursor
        lineNo = locator.diffLineNo

        # Get position at start of line
        try:
            sol = self.lineCursorStartCache[lineNo]
        except IndexError:
            sol = self.lineCursorStartCache[-1]

        # Get position at end of line
        try:
            eol = self.lineCursorStartCache[lineNo+1]
        except IndexError:
            eol = self.getMaxPosition()

        # If cursor position still falls within the same line, keep that position.
        # Otherwise, snap cursor position to start of line.
        if not (sol <= pos < eol):
            pos = sol

        # Unholy kludge to stabilize scrollbar position when QPlainTextEdit has wrapped lines
        vsb = self.verticalScrollBar()
        scrollTo = locator.diffScroll
        if self.lineWrapMode() != QPlainTextEdit.LineWrapMode.NoWrap and locator.diffScroll != 0:
            topCursor = self.textCursor()
            topCursor.setPosition(locator.diffScrollTop)
            self.setTextCursor(topCursor)
            self.centerCursor()
            scrolls = 0
            corner = self.getStableTopLeftCorner()
            while scrolls < 500 and self.cursorForPosition(corner).position() < locator.diffScrollTop:
                scrolls += 1
                scrollTo = vsb.value() + 1
                vsb.setValue(scrollTo)
            # logger.debug(f"Stabilized in {scrolls} iterations - final scroll {scrollTo} vs {locator.diffScroll})"
            #              f" - char pos {self.cursorForPosition(corner).position()} vs {locator.diffScrollTop}")

        # Move text cursor
        newTextCursor = self.textCursor()
        newTextCursor.setPosition(pos)
        self.setTextCursor(newTextCursor)

        # Finally, restore the scrollbar
        vsb.setValue(scrollTo)

    def getStableTopLeftCorner(self):
        return QPoint(0, self.fontMetrics().height() // 2)

    def getPreciseLocator(self):
        corner = self.getStableTopLeftCorner()
        cfp: QTextCursor = self.cursorForPosition(corner)

        diffCursor = self.textCursor().position()
        diffLineNo = self.findLineDataIndexAt(diffCursor)
        diffScroll = self.verticalScrollBar().value()
        diffScrollTop = cfp.position()
        locator = self.currentLocator.coarse().replace(
            diffCursor=diffCursor,
            diffLineNo=diffLineNo,
            diffScroll=diffScroll,
            diffScrollTop=diffScrollTop)

        # log.info("DiffView", f"getPreciseLocator: {diffScrollTop} - {cfp.positionInBlock()}"
        #                      f" - {cfp.block().text()[cfp.positionInBlock():]}")
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

        self.gutter.setFont(monoFont)
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
        self.setLineWrapMode(wrapMode)

    def toggleWordWrap(self):
        settings.prefs.wordWrap = not settings.prefs.wordWrap
        settings.prefs.write()
        self.refreshWordWrap()

    # ---------------------------------------------
    # Context menu

    def contextMenuActions(self, clickedCursor: QTextCursor) -> list[ActionDef]:
        return []

    def contextMenu(self, globalPos: QPoint):
        # Don't show the context menu if we're empty
        if self.document().isEmpty():
            return None

        # Get position of click in document
        clickedCursor = self.cursorForPosition(self.mapFromGlobal(globalPos))

        actions = self.contextMenuActions(clickedCursor)

        actions += [
            ActionDef.SEPARATOR,
            ActionDef(_("&Word Wrap"), self.toggleWordWrap, checkState=1 if settings.prefs.wordWrap else -1),
            ActionDef(_("Configure Appearance…"), lambda: GFApplication.instance().openPrefsDialog("font"), icon="configure"),
        ]

        bottom: QMenu = self.createStandardContextMenu()
        menu = ActionDef.makeQMenu(self, actions, bottom)
        bottom.deleteLater()  # don't need this menu anymore
        menu.setObjectName("CodeViewContextMenu")
        return menu

    def execContextMenu(self, globalPos: QPoint):  # pragma: no cover
        try:
            menu = self.contextMenu(globalPos)
            if not menu:
                return
            menu.exec(globalPos)
            menu.deleteLater()
        except Exception as exc:
            # Avoid exceptions in contextMenuEvent at all costs to prevent a crash
            excMessageBox(exc, message="Failed to create CodeView context menu")

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
