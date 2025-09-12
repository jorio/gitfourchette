# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from gitfourchette import settings
from gitfourchette.codeview.codeview import CodeView
from gitfourchette.diffview.diffdocument import DiffDocument, LineData
from gitfourchette.diffview.diffgutter import DiffGutter
from gitfourchette.diffview.diffhighlighter import DiffHighlighter
from gitfourchette.gitdriver import FatDelta, ABDelta
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.nav import NavContext, NavFlags, NavLocator
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.subpatch import extractSubpatch
from gitfourchette.tasks import ApplyPatch, ApplyPatchData
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)


class DiffView(CodeView):
    contextualHelp = Signal(str)
    selectionActionable = Signal(bool)
    visibilityChanged = Signal(bool)

    lineData: list[LineData]
    currentLocator: NavLocator
    # TODO: Rename this to currentDelta?
    currentPatch: FatDelta | None
    currentWorkdirFileStat: os.stat_result | None
    repo: Repo | None

    def __init__(self, parent=None):
        super().__init__(gutterClass=DiffGutter, highlighterClass=DiffHighlighter, parent=parent)

        self.lineData = []
        self.lineHunkIDCache = []
        self.repo = None

        # Emit contextual help with non-empty selection
        self.cursorPositionChanged.connect(self.emitSelectionHelp)
        self.selectionChanged.connect(self.emitSelectionHelp)

        self.searchBar.lineEdit.setPlaceholderText(toLengthVariants(_("Find text in diff|Find in diff")))

        self._initRubberBandButtons()

        self.gutter.lineClicked.connect(self.selectWholeLineAt)
        self.gutter.lineShiftClicked.connect(self.selectWholeLinesTo)
        self.gutter.lineDoubleClicked.connect(self.selectClumpOfLinesAt)
        self.gutter.selectionMiddleClicked.connect(self.onMiddleClick)

    def _initRubberBandButtons(self):
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
            self.rubberBandButtonGroup.layout().addWidget(button)

        makeWidgetShortcut(self, self.onStageShortcut, *GlobalShortcuts.stageHotkeys)
        makeWidgetShortcut(self, self.onDiscardShortcut, *GlobalShortcuts.discardHotkeys)

    @property
    def currentABDelta(self) -> ABDelta:
        return self.currentPatch.distillOldNew(self.currentLocator.context)

    # ---------------------------------------------
    # Callbacks for Qt events/shortcuts

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

    def mouseReleaseEvent(self, event: QMouseEvent):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.MiddleButton:
            self.onMiddleClick()

    # ---------------------------------------------
    # Document replacement

    def clear(self):  # override
        # Clear info about the current patch - necessary for document reuse detection to be correct when the user
        # clears the selection in a FileList and then reselects the last-displayed document.
        self.currentPatch = None

        # Clear the actual contents
        super().clear()

    @benchmark
    def replaceDocument(self, repo: Repo, delta: FatDelta, locator: NavLocator, newDoc: DiffDocument):
        assert newDoc.document is not None

        oldDocument = self.document()

        # Detect if we're trying to load exactly the same patch - common occurrence when moving the app back to the
        # foreground. In that case, don't change the document to prevent losing any selected text.
        if self.canReuseCurrentDocument(locator, delta, newDoc):
            """ TODO
            if APP_DEBUG:  # this check can be pretty expensive!
                assert self.currentPatch is not None
                assert patch.data == self.currentPatch.data
            """

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
        self.currentPatch = delta
        self.currentLocator = locator

        newDoc.document.setParent(self)
        self.setDocument(newDoc.document)
        self.highlighter.setDiffDocument(newDoc)

        self.lineData = newDoc.lineData

        # now reset defaults that are lost when changing documents
        self.refreshPrefs(changeColorScheme=False)

        self.gutter.maxLine = newDoc.maxLine
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

        if self.currentPatch != newPatch:
            return False

        if newLocator.context == NavContext.UNSTAGED:
            # TODO:
            print("TODO: More thorough check here!")

        return True

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
    # Context menu

    def contextMenuActions(self, clickedCursor: QTextCursor) -> list[ActionDef]:
        # If we have a document, we should have a patch
        assert self.currentPatch is not None

        cursor: QTextCursor = self.textCursor()
        hasSelection = cursor.hasSelection()

        # Find hunk at click position
        block = self.document().findBlock(clickedCursor.position())
        blockNumber = block.blockNumber()

        try:
            lineData = self.lineData[blockNumber]
        except IndexError:
            shortHunkHeader = "???"
        else:
            clickedHunkID = lineData.hunkPos.hunkID
            hunkFirstLine, _hunkLastLine = LineData.getHunkExtents(self.lineData, clickedHunkID)
            headerMatch = re.match(r"@@ ([^@]+) @@.*", self.lineData[hunkFirstLine].text)
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
                        _("Discard Lines…"),
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
                        _("Discard Hunk…"),
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

        return actions

    # ---------------------------------------------
    # Patch

    def findHunkIDAt(self, cursorPosition: int):
        block = self.document().findBlock(cursorPosition)
        blockNumber = block.blockNumber()
        try:
            return self.lineData[blockNumber].hunkPos.hunkID
        except IndexError:
            return -1

    def isSelectionActionable(self):
        start, end = self.getSelectedLineExtents()
        numAdds = 0
        numDels = 0
        for i in range(start, end+1):
            try:
                ld = self.lineData[i]
            except IndexError:
                assert (numAdds, numDels) == (0, 0)
                break
            if ld.origin == "+":
                numAdds += 1
            elif ld.origin == "-":
                numDels += 1
        return numAdds, numDels

    def extractSelection(self, reverse=False) -> str:
        i, j = self.getSelectedLineExtents()
        return extractSubpatch(self.currentABDelta, self.lineData, i, j, reverse)

    def extractHunk(self, hunkID: int, reverse=False) -> str:
        i, j = LineData.getHunkExtents(self.lineData, hunkID)
        return extractSubpatch(self.currentABDelta, self.lineData, i, j, reverse)

    def exportPatch(self, patchData: str):
        if not patchData:
            QApplication.beep()
            return

        def dump(path: str):
            Path(path).write_text(patchData, encoding="utf-8")

        name = os.path.basename(self.currentLocator.path) + "[partial].patch"
        qfd = PersistentFileDialog.saveFile(self, "SaveFile", _("Export selected lines"), name)
        qfd.fileSelected.connect(dump)
        qfd.show()

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

    def onMiddleClick(self):
        if not settings.prefs.middleClickToStage:
            return

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
        """ Revert selected lines (typically in an older commit). """

        # Prepare a pre-reverted patch for best results
        patchData = self.extractSelection(reverse=True)

        # Put a cap on how much context git will look at - this makes the patch
        # more likely to apply if the files have diverged.
        # (extractSelection keeps the entire hunk as context, some of which
        # may be obsolete in an older commit)
        ApplyPatchData.invoke(self, patchData, context=3,
                              title=_("Revert selected lines"),
                              question=_("Do you want to revert the selected lines?"))

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
        """ Revert a hunk (typically in an older commit). """

        # Prepare a pre-reverted patch for best results
        patchData = self.extractHunk(hunkID, reverse=True)

        # Put a cap on how much context git will look at - this makes the patch
        # more likely to apply if the files have diverged.
        ApplyPatchData.invoke(self, patchData, context=3,
                              title=_("Revert hunk"),
                              question=_("Do you want to revert this hunk?"))

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

    def selectClumpOfLinesAt(self, clickPoint: QPoint | None = None, textCursorPosition: int = -1):
        assert (textCursorPosition >= 0) ^ (clickPoint is not None)
        if textCursorPosition < 0:
            assert clickPoint is not None
            textCursorPosition = self.getStartOfLineAt(clickPoint)

        ldList = self.lineData
        i = self.document().findBlock(textCursorPosition).blockNumber()
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
