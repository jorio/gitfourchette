# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import difflib
from collections.abc import Generator
from dataclasses import dataclass

from gitfourchette import colors
from gitfourchette import settings
from gitfourchette.diffview.specialdiff import SpecialDiffError
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavFlags
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.subpatch import DiffLinePos
from gitfourchette.syntax import LexJob
from gitfourchette.toolbox import *

MAX_LINE_LENGTH = 10_000


@dataclass
class LineData:
    text: str
    "Line text for visual representation."

    hunkPos: DiffLinePos
    "Which hunk this line pertains to, and its position in the hunk."

    diffLine: DiffLine | None = None
    "pygit2 diff line data."

    cursorStart: int = -1
    "Cursor position at start of line in QDocument."

    cursorEnd: int = -1
    "Cursor position at end of line in QDocument."

    clumpID: int = -1
    "Which clump this line pertains to. 'Clumps' are groups of adjacent +/- lines."

    doppelganger: int = -1
    "Index of the doppelganger LineData in a perfectly even clump."

    trailerLength: int = 0
    "Stop highlighting the syntax past this column in the line."


class DiffStyle:
    def __init__(self):
        colorblind = settings.prefs.colorblind
        syntaxScheme = settings.prefs.syntaxHighlightingScheme()
        bgColor = syntaxScheme.backgroundColor

        # Base del/add backgrounds.
        # Instead of using an alpha value, blend with the background color.
        # This way, we avoid overlapping alpha artifacts at the edges of QCharFormat runs.
        if colorblind:
            delColor1 = mixColors(bgColor, colors.orange, .35)
            addColor1 = mixColors(bgColor, colors.teal, .35)
        else:
            delColor1 = mixColors(bgColor, QColor(0xff5555), .35)
            addColor1 = mixColors(bgColor, QColor(0x55ff55), .35)

        # Starker contrast for per-character highlights
        if colorblind:
            delColor2 = mixColors(delColor1, colors.orange, .6)
            addColor2 = mixColors(addColor1, colors.teal, .6)
        elif settings.prefs.syntaxHighlightingScheme().isDark():
            delColor2 = mixColors(delColor1, QColor(0x993333), .6)
            addColor2 = mixColors(addColor1, QColor(0x339933), .6)
        else:
            delColor2 = mixColors(delColor1, QColor(0x993333), .25)
            addColor2 = mixColors(addColor1, QColor(0x339933), .25)

        if syntaxScheme.isDark():
            warningColor = colors.red
            hunkColor = colors.blue.lighter(125)
        else:
            warningColor = colors.red.darker(125)
            hunkColor = QColor(0x0050f0)

        self.addBF1 = QTextBlockFormat()
        self.delBF1 = QTextBlockFormat()
        self.addBF1.setBackground(addColor1)
        self.delBF1.setBackground(delColor1)

        self.addCF2 = QTextCharFormat()
        self.delCF2 = QTextCharFormat()
        self.addCF2.setBackground(addColor2)
        self.delCF2.setBackground(delColor2)

        self.hunkBF = QTextBlockFormat()
        self.hunkCF = QTextCharFormat()
        self.hunkCF.setFontItalic(True)
        self.hunkCF.setForeground(hunkColor)

        self.warningCF = QTextCharFormat()
        self.warningCF.setFontUnderline(True)
        self.warningCF.setFontWeight(QFont.Weight.Bold)
        self.warningCF.setBackground(syntaxScheme.backgroundColor)
        self.warningCF.setForeground(warningColor)


@dataclass
class DiffDocument:
    document: QTextDocument
    lineData: list[LineData]
    style: DiffStyle
    pluses: int
    minuses: int

    # Syntax highlighting
    oldLexJob: LexJob | None = None
    newLexJob: LexJob | None = None

    @staticmethod
    def fromPatch(patch: Patch, locator: NavLocator):
        if patch.delta.similarity == 100:
            raise SpecialDiffError.noChange(patch.delta)

        # Don't show contents if file appears to be binary.
        if patch.delta.is_binary:
            raise SpecialDiffError.binaryDiff(patch.delta, locator)

        # Render SVG file if user wants to.
        if (settings.prefs.renderSvg
                and patch.delta.new_file.path.lower().endswith(".svg")
                and isImageFormatSupported("file.svg")):
            raise SpecialDiffError.binaryDiff(patch.delta, locator)

        # Special formatting for TYPECHANGE.
        if patch.delta.status == DeltaStatus.TYPECHANGE:
            raise SpecialDiffError.typeChange(patch.delta)

        # Don't load large diffs.
        threshold = settings.prefs.largeFileThresholdKB * 1024
        if threshold != 0 and len(patch.data) > threshold and not locator.hasFlags(NavFlags.AllowLargeFiles):
            raise SpecialDiffError.diffTooLarge(len(patch.data), threshold, locator)

        if len(patch.hunks) == 0:
            raise SpecialDiffError.noChange(patch.delta)

        lineData = []

        clumpID = 0
        numLinesInClump = 0
        perfectClumpTally = 0
        pluses = 0
        minuses = 0

        # For each line of the diff, create a LineData object.
        for hunkID, hunk in enumerate(patch.hunks):
            oldLine = hunk.old_start
            newLine = hunk.new_start

            hunkHeaderLD = LineData(text=hunk.header, hunkPos=DiffLinePos(hunkID, -1))
            lineData.append(hunkHeaderLD)

            for hunkLineNum, diffLine in enumerate(hunk.lines):
                origin = diffLine.origin
                content = diffLine.content

                # Any lines that aren't +/- break up the current clump
                if origin not in "+-" and numLinesInClump != 0:
                    # Process perfect clump (sum of + and - origins is 0)
                    if numLinesInClump > 0 and perfectClumpTally == 0:
                        assert (numLinesInClump % 2) == 0, "line count should be even in perfect clumps"
                        clumpStart = len(lineData) - numLinesInClump
                        halfClump = numLinesInClump // 2
                        for doppel1 in range(clumpStart, clumpStart + halfClump):
                            doppel2 = doppel1 + halfClump
                            lineData[doppel1].doppelganger = doppel2
                            lineData[doppel2].doppelganger = doppel1

                    # Start new clump
                    clumpID += 1
                    numLinesInClump = 0
                    perfectClumpTally = 0

                # Skip GIT_DIFF_LINE_CONTEXT_EOFNL, ...ADD_EOFNL, ...DEL_EOFNL
                if origin in "=><":
                    continue

                if len(content) > MAX_LINE_LENGTH and not locator.hasFlags(NavFlags.AllowLongLines):
                    loadAnywayLoc = locator.withExtraFlags(NavFlags.AllowLongLines)
                    raise SpecialDiffError(
                        _("This file contains very long lines."),
                        linkify(_("[Load diff anyway] (this may take a moment)"), loadAnywayLoc.url()),
                        "SP_MessageBoxWarning")

                ld = LineData(text=content, hunkPos=DiffLinePos(hunkID, hunkLineNum), diffLine=diffLine)

                assert origin in " -+", F"diffline origin: '{origin}'"
                if origin == '+':
                    assert diffLine.new_lineno == newLine
                    assert diffLine.old_lineno == -1
                    newLine += 1
                    ld.clumpID = clumpID
                    numLinesInClump += 1
                    perfectClumpTally += 1
                    pluses += 1
                elif origin == '-':
                    assert diffLine.new_lineno == -1
                    assert diffLine.old_lineno == oldLine
                    oldLine += 1
                    ld.clumpID = clumpID
                    numLinesInClump += 1
                    perfectClumpTally -= 1
                    minuses += 1
                else:
                    assert diffLine.new_lineno == newLine
                    assert diffLine.old_lineno == oldLine
                    newLine += 1
                    oldLine += 1

                lineData.append(ld)

        style = DiffStyle()

        document = QTextDocument()  # recreating a document is faster than clearing the existing one
        document.setObjectName("DiffPatchDocument")
        document.setDocumentLayout(QPlainTextDocumentLayout(document))

        cursor: QTextCursor = QTextCursor(document)

        # Begin batching text insertions for performance.
        # This prevents Qt from recomputing the document's layout after every line insertion.
        cursor.beginEditBlock()

        defaultBF = cursor.blockFormat()
        defaultCF = cursor.charFormat()
        showStrayCRs = settings.prefs.showStrayCRs

        assert document.isEmpty()

        # Build up document from the lineData array.
        for ld in lineData:
            # Decide block format & character format
            if ld.diffLine is None:
                bf = style.hunkBF
                cf = style.hunkCF
            elif ld.diffLine.origin == '+':
                bf = style.addBF1
                cf = defaultCF
            elif ld.diffLine.origin == '-':
                bf = style.delBF1
                cf = defaultCF
            else:
                bf = defaultBF
                cf = defaultCF

            # Process line ending
            trailer = ""
            if ld.text.endswith('\r\n'):
                trimBack = -2
                if showStrayCRs:
                    trailer = "<CRLF>"
            elif ld.text.endswith('\n'):
                trimBack = -1
            elif ld.text.endswith('\r'):
                trimBack = -1
                if showStrayCRs:
                    trailer = "<CR>"
            else:
                trailer = _("<no newline at end of file>")
                trimBack = None  # yes, None. This will cancel slicing.

            if not document.isEmpty():
                cursor.insertBlock()
                ld.cursorStart = cursor.position()
            else:
                ld.cursorStart = 0

            cursor.setBlockFormat(bf)
            cursor.setBlockCharFormat(cf)
            cursor.insertText(ld.text[:trimBack])

            if trailer:
                ld.trailerLength = len(trailer)
                cursor.setCharFormat(style.warningCF)
                cursor.insertText(trailer)

            ld.cursorEnd = cursor.position()

        # Emphasize doppelganger differences
        doppelgangerBlocksQueue = []
        for i, ld in enumerate(lineData):
            if ld.doppelganger < 0:  # Skip lines without doppelgangers
                continue

            assert i != ld.doppelganger, "line cannot be its own doppelganger"
            assert ld.diffLine is not None, "line with doppelganger must have a DiffLine"
            aheadOfDoppelganger = i < ld.doppelganger

            if aheadOfDoppelganger:
                sm = difflib.SequenceMatcher(a=ld.text, b=lineData[ld.doppelganger].text)
                blocks = sm.get_matching_blocks()
                doppelgangerBlocksQueue.append(blocks)  # Set blocks aside for my doppelganger
            else:
                blocks = doppelgangerBlocksQueue.pop(0)  # Consume blocks set aside by my doppelganger

            cf = style.delCF2 if ld.diffLine.origin == '-' else style.addCF2
            offset = ld.cursorStart

            for x1, x2 in _invertMatchingBlocks(blocks, useA=aheadOfDoppelganger):
                cursor.setPosition(offset + x1, QTextCursor.MoveMode.MoveAnchor)
                cursor.setPosition(offset + x2, QTextCursor.MoveMode.KeepAnchor)
                cursor.setCharFormat(cf)

        assert not doppelgangerBlocksQueue, "should've consumed all doppelganger matching blocks!"

        # Done batching text insertions.
        cursor.endEditBlock()

        return DiffDocument(document=document, lineData=lineData, style=style, pluses=pluses, minuses=minuses)


def _invertMatchingBlocks(blockList: list[difflib.Match], useA: bool) -> Generator[tuple[int, int], None, None]:
    px = 0

    for block in blockList:
        x1 = block.a if useA else block.b
        x2 = x1 + block.size

        if px != x1:
            yield px, x1

        px = x2
