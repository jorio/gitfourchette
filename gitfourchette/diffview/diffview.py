# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
import re
from bisect import bisect_left, bisect_right

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.diffview.diffdocument import DiffDocument, LineData
from gitfourchette.diffview.diffgutter import DiffGutter
from gitfourchette.diffview.diffrubberband import DiffRubberBand
from gitfourchette.diffview.diffsyntaxhighlighter import DiffSyntaxHighlighter
from gitfourchette.forms.searchbar import SearchBar
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.nav import NavContext, NavFlags, NavLocator
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.subpatch import extractSubpatch
from gitfourchette.tasks import ApplyPatch, RevertPatch
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)


class DiffView(QPlainTextEdit):
    DetachedWindowObjectName = "DiffViewDetachedWindow"

    contextualHelp = Signal(str)
    selectionActionable = Signal(bool)
    visibilityChanged = Signal(bool)

    lineData: list[LineData]
    lineCursorStartCache: list[int]
    lineHunkIDCache: list[int]
    currentLocator: NavLocator
    currentPatch: Patch | None
    currentWorkdirFileStat: os.stat_result | None
    repo: Repo | None
    isDetachedWindow: bool

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setReadOnly(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)

        # First-time init so callbacks don't crash looking for missing attributes
        self.lineData = []
        self.lineCursorStartCache = []
        self.lineHunkIDCache = []
        self.currentLocator = NavLocator()
        self.currentPatch = None
        self.repo = None
        self.isDetachedWindow = False

        # Highlighter for search terms
        self.highlighter = DiffSyntaxHighlighter(self)
        self.visibilityChanged.connect(self.highlighter.onParentVisibilityChanged)

        self.gutter = DiffGutter(self)
        self.gutter.customContextMenuRequested.connect(lambda p: self.execContextMenu(self.gutter.mapToGlobal(p)))
        self.updateRequest.connect(self.gutter.onParentUpdateRequest)
        # self.blockCountChanged.connect(self.updateGutterWidth)
        self.syncViewportMarginsWithGutter()

        # Emit contextual help with non-empty selection
        self.cursorPositionChanged.connect(self.emitSelectionHelp)
        self.selectionChanged.connect(self.emitSelectionHelp)
        self.cursorPositionChanged.connect(self.updateRubberBand)
        self.selectionChanged.connect(self.updateRubberBand)

        self.searchBar = SearchBar(self, toLengthVariants(_("Find text in diff|Find in diff")))
        self.searchBar.searchNext.connect(lambda: self.search(SearchBar.Op.Next))
        self.searchBar.searchPrevious.connect(lambda: self.search(SearchBar.Op.Previous))
        self.searchBar.searchTermChanged.connect(self.highlighter.setSearchTerm)
        self.searchBar.visibilityChanged.connect(self.highlighter.setSearching)
        self.searchBar.hide()

        self.rubberBand = DiffRubberBand(self.viewport())
        self.rubberBand.hide()

        self._initRubberBandButtons()
        self.rubberBandButtonGroup.hide()

        self.verticalScrollBar().valueChanged.connect(self.updateRubberBand)
        self.horizontalScrollBar().valueChanged.connect(self.updateRubberBand)

        # Initialize font & styling
        self.refreshPrefs()
        GFApplication.instance().restyle.connect(self.refreshPrefs)

    def _initRubberBandButtons(self):
        self.rubberBandButtonGroup = QWidget(parent=self.viewport())
        rubberBandButtonLayout = QHBoxLayout(self.rubberBandButtonGroup)
        rubberBandButtonLayout.setSpacing(0)
        rubberBandButtonLayout.setContentsMargins(0, 0, 0, 0)

        self.stageButton = QToolButton()
        self.stageButton.setText(_("Stage Selection"))
        self.stageButton.setIcon(stockIcon("git-stage-lines"))
        self.stageButton.setToolTip(appendShortcutToToolTipText(_("Stage selected lines"), GlobalShortcuts.stageHotkeys[0]))
        self.stageButton.clicked.connect(self.stageSelection)

        self.unstageButton = QToolButton()
        self.unstageButton.setText(_("Unstage Selection"))
        self.unstageButton.setIcon(stockIcon("git-unstage-lines"))
        self.unstageButton.clicked.connect(self.unstageSelection)
        self.unstageButton.setToolTip(appendShortcutToToolTipText(_("Unstage selected lines"), GlobalShortcuts.discardHotkeys[0]))

        self.discardButton = QToolButton()
        self.discardButton.setText(_("Discard"))
        self.discardButton.setIcon(stockIcon("git-discard-lines"))
        self.discardButton.clicked.connect(self.discardSelection)
        self.discardButton.setToolTip(appendShortcutToToolTipText(_("Discard selected lines"), GlobalShortcuts.discardHotkeys[0]))

        for button in self.stageButton, self.discardButton, self.unstageButton:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            rubberBandButtonLayout.addWidget(button)

        makeWidgetShortcut(self, self.onStageShortcut, *GlobalShortcuts.stageHotkeys)
        makeWidgetShortcut(self, self.onDiscardShortcut, *GlobalShortcuts.discardHotkeys)
        makeWidgetShortcut(self, self.searchBar.hideOrBeep, "Escape")

    # ---------------------------------------------
    # Qt events

    def contextMenuEvent(self, event: QContextMenuEvent):
        self.execContextMenu(event.globalPos())

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self.resizeGutter()
        self.updateRubberBand()

    def onStageShortcut(self):
        navContext = self.currentLocator.context
        if navContext == NavContext.UNSTAGED:
            self.stageSelection()
        else:
            QApplication.beep()

    def onDiscardShortcut(self):
        navContext = self.currentLocator.context
        if navContext == NavContext.STAGED:
            self.unstageSelection()
        elif navContext == NavContext.UNSTAGED:
            self.discardSelection()
        else:
            QApplication.beep()

    def addSearchShortcuts(self):
        # In a detached window, we can't rely on the main window's menu bar to
        # dispatch shortcuts to us (except on macOS, which has a global main menu).
        makeWidgetShortcut(self, lambda: self.search(SearchBar.Op.Start), *GlobalShortcuts.find)
        makeWidgetShortcut(self, lambda: self.search(SearchBar.Op.Previous), *GlobalShortcuts.findPrevious)
        makeWidgetShortcut(self, lambda: self.search(SearchBar.Op.Next), *GlobalShortcuts.findNext)

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

    def mouseReleaseEvent(self, event: QMouseEvent):
        super().mouseReleaseEvent(event)
        if settings.prefs.middleClickToStage and event.button() == Qt.MouseButton.MiddleButton:
            self.doPrimaryApplyLinesAction()

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
        self.currentPatch = None

        # Clear the actual contents
        super().clear()

    @benchmark
    def replaceDocument(self, repo: Repo, patch: Patch, locator: NavLocator, newDoc: DiffDocument):
        assert newDoc.document is not None

        oldDocument = self.document()

        # Detect if we're trying to load exactly the same patch - common occurrence when moving the app back to the
        # foreground. In that case, don't change the document to prevent losing any selected text.
        if self.canReuseCurrentDocument(locator, patch, newDoc):
            if settings.DEVDEBUG:  # this check can be pretty expensive!
                assert self.currentPatch is not None
                assert patch.data == self.currentPatch.data

            # Delete new document
            assert newDoc.document is not oldDocument  # make sure it's not in use before deleting
            newDoc.document.deleteLater()
            newDoc.document = None  # prevent any callers from using a stale object

            # Bail now - don't change the document
            logger.debug("Don't need to regenerate diff document.")
            return

        if oldDocument:
            oldDocument.deleteLater()  # avoid leaking memory/objects, even though we do set QTextDocument's parent to this QTextEdit

        self.repo = repo
        self.currentPatch = patch
        self.currentLocator = locator

        newDoc.document.setParent(self)
        self.setDocument(newDoc.document)
        self.highlighter.setDiffDocument(newDoc)

        self.lineData = newDoc.lineData
        self.lineCursorStartCache = [ld.cursorStart for ld in self.lineData]
        self.lineHunkIDCache = [ld.hunkPos.hunkID for ld in self.lineData]

        # now reset defaults that are lost when changing documents
        self.refreshPrefs(changeColorScheme=False)

        if self.currentPatch and len(self.currentPatch.hunks) > 0:
            lastHunk = self.currentPatch.hunks[-1]
            maxNewLine = lastHunk.new_start + lastHunk.new_lines
            maxOldLine = lastHunk.old_start + lastHunk.old_lines
            maxLine = max(maxNewLine, maxOldLine)
        else:
            maxLine = 0
        self.gutter.setMaxLineNumber(maxLine)
        self.syncViewportMarginsWithGutter()

        buttonMask = 0
        if locator.context == NavContext.UNSTAGED:
            buttonMask = PatchPurpose.Stage | PatchPurpose.Discard
        elif locator.context == NavContext.STAGED:
            buttonMask = PatchPurpose.Unstage
        self.stageButton.setVisible(bool(buttonMask & PatchPurpose.Stage))
        self.discardButton.setVisible(bool(buttonMask & PatchPurpose.Discard))
        self.unstageButton.setVisible(bool(buttonMask & PatchPurpose.Unstage))

        # Now restore cursor/scrollbar positions
        self.restorePosition(locator)

    @benchmark
    def canReuseCurrentDocument(self, newLocator: NavLocator, newPatch: Patch, newDocument: DiffDocument
                                ) -> bool:
        """Detect if we're trying to reload the same patch that's already being displayed"""

        if newLocator.hasFlags(NavFlags.ForceRecreateDocument):
            return False

        if not self.currentLocator.isSimilarEnoughTo(newLocator):
            return False

        assert self.currentPatch is not None

        of1: DiffFile = self.currentPatch.delta.old_file
        nf1: DiffFile = self.currentPatch.delta.new_file
        of2: DiffFile = newPatch.delta.old_file
        nf2: DiffFile = newPatch.delta.new_file

        if not DiffFile_compare(of1, of2):
            return False

        if not DiffFile_compare(nf1, nf2):
            return False

        # Changing amount of context lines?
        if len(newDocument.lineData) != len(self.lineData):
            return False

        # All IDs must be valid
        assert of1.flags & DiffFlag.VALID_ID
        assert nf1.flags & DiffFlag.VALID_ID
        assert of2.flags & DiffFlag.VALID_ID
        assert nf2.flags & DiffFlag.VALID_ID

        return True

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
            # logger.info(f"Stabilized in {scrolls} iterations - final scroll {scrollTo} vs {locator.diffScroll})"
            #               f" - char pos {self.cursorForPosition(corner).position()} vs {locator.diffScrollTop}")

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

    def contextMenu(self, globalPos: QPoint):
        # Don't show the context menu if we're empty
        if self.document().isEmpty():
            return None

        # If we have a document, we should have a patch
        assert self.currentPatch is not None

        # Get position of click in document
        clickedPosition = self.cursorForPosition(self.mapFromGlobal(globalPos)).position()

        cursor: QTextCursor = self.textCursor()
        hasSelection = cursor.hasSelection()

        # Find hunk at click position
        clickedHunkID = self.findHunkIDAt(clickedPosition)
        shortHunkHeader = ""
        if clickedHunkID >= 0:
            hunk: DiffHunk = self.currentPatch.hunks[clickedHunkID]
            headerMatch = re.match(r"@@ ([^@]+) @@.*", hunk.header)
            shortHunkHeader = headerMatch.group(1) if headerMatch else f"#{clickedHunkID}"

        actions = []

        navContext = self.currentLocator.context

        if navContext == NavContext.COMMITTED:
            if hasSelection:
                actions = [
                    ActionDef(_("Export Lines as Patch…"), self.exportSelection),
                    ActionDef(_("Revert Lines…"), self.revertSelection),
                ]
            else:
                actions = [
                    ActionDef(_("Export Hunk {0} as Patch…", shortHunkHeader), lambda: self.exportHunk(clickedHunkID)),
                    ActionDef(_("Revert Hunk…"), lambda: self.revertHunk(clickedHunkID)),
                ]

        elif navContext == NavContext.UNTRACKED:
            if hasSelection:
                actions = [
                    ActionDef(_("Export Lines as Patch…"), self.exportSelection),
                ]
            else:
                actions = [
                    ActionDef(_("Export Hunk as Patch…"), lambda: self.exportHunk(clickedHunkID)),
                ]

        elif navContext == NavContext.UNSTAGED:
            if hasSelection:
                actions = [
                    ActionDef(
                        _("Stage Lines"),
                        self.stageSelection,
                        "git-stage-lines",
                        shortcuts=GlobalShortcuts.stageHotkeys[0],
                    ),
                    ActionDef(
                        _("Discard Lines"),
                        self.discardSelection,
                        "git-discard-lines",
                        shortcuts=GlobalShortcuts.discardHotkeys[0],
                    ),
                    ActionDef(
                        _("Export Lines as Patch…"),
                        self.exportSelection
                    ),
                ]
            else:
                actions = [
                    ActionDef(
                        _("Stage Hunk {0}", shortHunkHeader),
                        lambda: self.stageHunk(clickedHunkID),
                        "git-stage-lines",
                    ),
                    ActionDef(
                        _("Discard Hunk"),
                        lambda: self.discardHunk(clickedHunkID),
                        "git-discard-lines",
                    ),
                    ActionDef(_("Export Hunk as Patch…"), lambda: self.exportHunk(clickedHunkID)),
                ]

        elif navContext == NavContext.STAGED:
            if hasSelection:
                actions = [
                    ActionDef(
                        _("Unstage Lines"),
                        self.unstageSelection,
                        "git-unstage-lines",
                        shortcuts=GlobalShortcuts.discardHotkeys[0],
                    ),
                    ActionDef(
                        _("Export Lines as Patch…"),
                        self.exportSelection,
                    ),
                ]
            else:
                actions = [
                    ActionDef(
                        _("Unstage Hunk {0}", shortHunkHeader),
                        lambda: self.unstageHunk(clickedHunkID),
                        "git-unstage-lines",
                    ),
                    ActionDef(
                        _("Export Hunk as Patch…"),
                        lambda: self.exportHunk(clickedHunkID),
                    ),
                ]

        actions += [
            ActionDef.SEPARATOR,
            ActionDef(_("&Word Wrap"), self.toggleWordWrap, checkState=1 if settings.prefs.wordWrap else -1),
            ActionDef(_("Configure Appearance…"), lambda: GFApplication.instance().openPrefsDialog("font"), icon="configure"),
        ]

        bottom: QMenu = self.createStandardContextMenu()
        menu = ActionDef.makeQMenu(self, actions, bottom)
        bottom.deleteLater()  # don't need this menu anymore
        menu.setObjectName("DiffViewContextMenu")
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
            excMessageBox(exc, message="Failed to create DiffView context menu")

    # ---------------------------------------------
    # Patch

    def findLineDataIndexAt(self, cursorPosition: int, firstLineDataIndex: int = 0):
        if not self.lineData:
            return -1
        index = bisect_right(self.lineCursorStartCache, cursorPosition, firstLineDataIndex)
        return index - 1

    def findHunkIDAt(self, cursorPosition: int):
        clickLineDataIndex = self.findLineDataIndexAt(cursorPosition)
        try:
            return self.lineData[clickLineDataIndex].hunkPos.hunkID
        except IndexError:
            return -1

    def getSelectedLineExtents(self):
        cursor: QTextCursor = self.textCursor()
        posStart = cursor.selectionStart()
        posEnd = cursor.selectionEnd()

        if posStart < 0 or posEnd < 0:
            return -1, -1

        # Find indices of first and last LineData objects given the current selection
        biStart = self.findLineDataIndexAt(posStart)
        biEnd = self.findLineDataIndexAt(posEnd, biStart)

        return biStart, biEnd

    def isSelectionActionable(self):
        start, end = self.getSelectedLineExtents()
        numAdds = 0
        numDels = 0
        if start >= 0:
            for i in range(start, end+1):
                ld = self.lineData[i]
                if not ld.diffLine:
                    pass
                elif ld.diffLine.origin == "+":
                    numAdds += 1
                elif ld.diffLine.origin == "-":
                    numDels += 1
        return numAdds, numDels

    def extractSelection(self, reverse=False) -> bytes:
        assert self.currentPatch is not None

        start, end = self.getSelectedLineExtents()

        return extractSubpatch(
            self.currentPatch,
            self.lineData[start].hunkPos,
            self.lineData[end].hunkPos,
            reverse)

    def extractHunk(self, hunkID: int, reverse=False) -> bytes:
        assert self.currentPatch is not None

        # Find indices of first and last LineData objects given the current hunk
        hunkFirstLineIndex = bisect_left(self.lineHunkIDCache, hunkID, 0)
        hunkLastLineIndex = bisect_left(self.lineHunkIDCache, hunkID+1, hunkFirstLineIndex) - 1

        return extractSubpatch(
            self.currentPatch,
            self.lineData[hunkFirstLineIndex].hunkPos,
            self.lineData[hunkLastLineIndex].hunkPos,
            reverse)

    def exportPatch(self, patchData: bytes):
        if not patchData:
            QApplication.beep()
            return

        def dump(path: str):
            with open(path, "wb") as file:
                file.write(patchData)

        name = os.path.basename(self.currentLocator.path) + "[partial].patch"
        qfd = PersistentFileDialog.saveFile(self, "SaveFile", _("Export selected lines"), name)
        qfd.fileSelected.connect(dump)
        qfd.show()

    def fireRevert(self, patchData: bytes):
        RevertPatch.invoke(self, self.currentPatch, patchData)

    def fireApplyLines(self, purpose: PatchPurpose):
        purpose |= PatchPurpose.Lines
        reverse = not (purpose & PatchPurpose.Stage)
        patchData = self.extractSelection(reverse)
        ApplyPatch.invoke(self, self.currentPatch, patchData, purpose)

    def fireApplyHunk(self, hunkID: int, purpose: PatchPurpose):
        purpose |= PatchPurpose.Hunk
        reverse = not (purpose & PatchPurpose.Stage)
        patchData = self.extractHunk(hunkID, reverse)
        ApplyPatch.invoke(self, self.currentPatch, patchData, purpose)

    def doPrimaryApplyLinesAction(self):
        navContext = self.currentLocator.context
        if navContext == NavContext.UNSTAGED:
            self.stageSelection()
        elif navContext == NavContext.STAGED:
            self.unstageSelection()
        else:
            QApplication.beep()

    def stageSelection(self):
        self.fireApplyLines(PatchPurpose.Stage)

    def unstageSelection(self):
        self.fireApplyLines(PatchPurpose.Unstage)

    def discardSelection(self):
        self.fireApplyLines(PatchPurpose.Discard)

    def exportSelection(self):
        patchData = self.extractSelection()
        self.exportPatch(patchData)

    def revertSelection(self):
        patchData = self.extractSelection(reverse=True)
        self.fireRevert(patchData)

    def stageHunk(self, hunkID: int):
        self.fireApplyHunk(hunkID, PatchPurpose.Stage)

    def unstageHunk(self, hunkID: int):
        self.fireApplyHunk(hunkID, PatchPurpose.Unstage)

    def discardHunk(self, hunkID: int):
        self.fireApplyHunk(hunkID, PatchPurpose.Discard)

    def exportHunk(self, hunkID: int):
        patchData = self.extractHunk(hunkID)
        self.exportPatch(patchData)

    def revertHunk(self, hunkID: int):
        patchData = self.extractHunk(hunkID, reverse=True)
        self.fireRevert(patchData)

    # ---------------------------------------------
    # Gutter

    def resizeGutter(self):
        cr: QRect = self.contentsRect()
        cr.setWidth(self.gutter.calcWidth())
        self.gutter.setGeometry(cr)

    def syncViewportMarginsWithGutter(self):
        gutterWidth = self.gutter.calcWidth()

        # Prevent Qt freeze if margin width exceeds widget width, e.g. when window is very narrow
        # (especially prevalent with word wrap?)
        self.setMinimumWidth(gutterWidth * 2)

        self.setViewportMargins(gutterWidth, 0, 0, 0)

    # ---------------------------------------------
    # Rubberband

    def updateRubberBand(self):
        textCursor: QTextCursor = self.textCursor()
        start = textCursor.selectionStart()
        end = textCursor.selectionEnd()
        assert start <= end

        startLine, endLine = self.getSelectedLineExtents()
        numAdds, numDels = self.isSelectionActionable()
        actionable = numAdds + numDels > 0

        if startLine < 0 or endLine < 0 or (not actionable and start == end):
            self.rubberBand.hide()
            self.rubberBandButtonGroup.hide()
            return

        start = self.lineData[startLine].cursorStart
        end = self.lineData[endLine].cursorEnd

        textCursor.setPosition(start)
        top = self.cursorRect(textCursor).top()

        textCursor.setPosition(end)
        bottom = self.cursorRect(textCursor).bottom()

        viewportWidth = self.viewport().width()
        viewportHeight = self.viewport().height()

        pad = 4
        self.rubberBand.setGeometry(0, top-pad, viewportWidth, bottom-top+1+pad*2)
        self.rubberBand.show()

        # Move rubberBandButton to edge of rubberBand
        if not self.currentLocator.context.isWorkdir():
            # No rubberBandButton in this context
            assert self.rubberBandButtonGroup.isHidden()
        elif top >= viewportHeight-4 or bottom < 4:
            # Scrolled past rubberband, no point in showing button
            self.rubberBandButtonGroup.hide()
        else:
            # Show button before moving so that width/height are correct
            self.rubberBandButtonGroup.show()
            self.rubberBandButtonGroup.ensurePolished()
            rbbWidth = self.rubberBandButtonGroup.width()
            rbbHeight = self.rubberBandButtonGroup.height()

            # Place button above rubberband
            rbbTop = top - rbbHeight
            rbbTop = max(rbbTop, 0)  # keep it visible
            self.rubberBandButtonGroup.move(viewportWidth - rbbWidth, rbbTop)
            self.rubberBandButtonGroup.setEnabled(actionable)

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

    def selectClumpOfLinesAt(self, clickPoint: QPoint | None = None, textCursorPosition: int = -1):
        assert (textCursorPosition >= 0) ^ (clickPoint is not None)
        if textCursorPosition < 0:
            assert clickPoint is not None
            textCursorPosition = self.getStartOfLineAt(clickPoint)

        ldList = self.lineData
        i = self.findLineDataIndexAt(textCursorPosition)
        ld = ldList[i]

        if ld.hunkPos.hunkLineNum < 0:
            # Hunk header line, select whole hunk
            start = i
            end = i
            while end < len(ldList)-1 and ldList[end+1].hunkPos.hunkID == ld.hunkPos.hunkID:
                end += 1
        elif ld.clumpID < 0:
            # Context line
            QApplication.beep()
            return
        else:
            # Get clump boundaries
            start = i
            end = i
            while start > 0 and ldList[start-1].clumpID == ld.clumpID:
                start -= 1
            while end < len(ldList)-1 and ldList[end+1].clumpID == ld.clumpID:
                end += 1

        startPosition = ldList[start].cursorStart
        endPosition = min(self.getMaxPosition(), ldList[end].cursorEnd)

        cursor: QTextCursor = self.textCursor()
        cursor.setPosition(startPosition, QTextCursor.MoveMode.MoveAnchor)
        cursor.setPosition(endPosition, QTextCursor.MoveMode.KeepAnchor)
        self.replaceCursor(cursor)

    # ---------------------------------------------
    # Selection help

    def emitSelectionHelp(self):
        if self.currentLocator.context in [NavContext.COMMITTED, NavContext.EMPTY]:
            return

        numAdds, numDels = self.isSelectionActionable()

        if numAdds + numDels == 0:
            self.contextualHelp.emit("")
            self.selectionActionable.emit(False)
            return

        stageKey = QKeySequence(GlobalShortcuts.stageHotkeys[0]).toString(QKeySequence.SequenceFormat.NativeText)
        discardKey = QKeySequence(GlobalShortcuts.discardHotkeys[0]).toString(QKeySequence.SequenceFormat.NativeText)
        unstageKey = discardKey
        if settings.prefs.middleClickToStage:
            stageKey += " " + _("or Middle-Click")
            unstageKey += " " + _("or Middle-Click")

        if numAdds and numDels:
            nl = f"+{numAdds} -{numDels}"
        else:
            nl = f"+{numAdds}" if numAdds else f"-{numDels}"
        if self.currentLocator.context == NavContext.UNSTAGED:
            help = _n("Hit {sk} to stage {nl} line. Hit {dk} to discard it.",
                      "Hit {sk} to stage {nl} lines. Hit {dk} to discard them.",
                      n=numAdds+numDels, nl=nl, sk=stageKey, dk=discardKey)
        elif self.currentLocator.context == NavContext.STAGED:
            help = _n("Hit {uk} to unstage {nl} line.",
                      "Hit {uk} to unstage {nl} lines.",
                      n=numAdds+numDels, nl=nl, uk=unstageKey)

        self.contextualHelp.emit(help)
        self.selectionActionable.emit(True)

    # ---------------------------------------------
    # Search

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
            _("End of diff reached.") if op == SearchBar.Op.Next
            else _("Top of diff reached."),
            _("No more occurrences of {0} found.", bquo(message))
        ]
        askConfirmation(self, _("Find in Diff"), paragraphs(prompt), okButtonText=_("Wrap Around"),
                        messageBoxIcon="information", callback=wrapAround)
