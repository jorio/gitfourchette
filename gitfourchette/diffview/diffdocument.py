# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import difflib
import re
from bisect import bisect_left
from collections.abc import Generator
from dataclasses import dataclass

from gitfourchette import colors
from gitfourchette import settings
from gitfourchette.gitdriver import GitDelta
from gitfourchette.gitdriver.parsers import iterateLines
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.syntax import LexJob
from gitfourchette.toolbox import *


_indexLinePattern = re.compile(r"index ([\da-f]+)\.\.([\da-f]+)")
_hunkHeaderPattern = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parseHunkHeader(text: str) -> tuple[int, int, int, int, str]:
    match = _hunkHeaderPattern.match(text)
    oldStartStr, oldLinesStr, newStartStr, newLinesStr = match.groups()
    oldStart = int(oldStartStr)
    newStart = int(newStartStr)
    oldLines = int(oldLinesStr) if oldLinesStr else 1
    newLines = int(newLinesStr) if newLinesStr else 1
    comment = text[match.end():]
    return oldStart, oldLines, newStart, newLines, comment


@dataclass
class DiffLinePos:
    hunkID: int
    hunkLineNum: int


@dataclass
class LineData:
    text: str
    "Line text for visual representation."

    hunkPos: DiffLinePos
    "Which hunk this line pertains to, and its position in the hunk."

    origin: str = ""
    oldLineNo: int = -1
    newLineNo: int = -1

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

    hiddenSuffix: str = ""
    """
    Suffix that follows `text` in a patch file but should be hidden in the UI,
    e.g. newline + backslash + ' No newline at end of file'.
    """

    @classmethod
    def getHunkExtents(cls, array: list[LineData], hunkID: int) -> tuple[int, int]:
        """
        Find indices of first and last LineData objects given the current hunk.
        """

        first = bisect_left(array, hunkID, 0, key=LineData._hunkIDKey)
        last = bisect_left(array, hunkID + 1, first, key=LineData._hunkIDKey) - 1
        return first, last

    def _hunkIDKey(self) -> int:
        return self.hunkPos.hunkID

    def parseHunkHeader(self) -> tuple[int, int, int, int, str]:
        assert self.hunkPos.hunkLineNum == -1
        return _parseHunkHeader(self.text)


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
    maxLine: int

    # Syntax highlighting
    oldLexJob: LexJob | None = None
    newLexJob: LexJob | None = None

    class VeryLongLinesError(ValueError):
        pass

    class NoChangeError(ValueError):
        pass

    class BinaryError(ValueError):
        pass

    @staticmethod
    def fromPatch(delta: GitDelta, patch: str, maxLineLength=0) -> DiffDocument:
        lineData: list[LineData] = []

        clumpID = 0
        numLinesInClump = 0
        perfectClumpTally = 0
        pluses = 0
        minuses = 0

        hunkID = -1
        oldLine = -1
        newLine = -1
        hunkLineNum = -1
        isBinary = False

        for pos, endPos in iterateLines(patch):
            if maxLineLength and endPos - pos > maxLineLength:
                raise DiffDocument.VeryLongLinesError()

            firstChar = patch[pos]

            # Keep looking for first hunk
            if firstChar != "@" and hunkID < 0:
                if patch.startswith(("Binary files", "GIT binary patch"), pos, endPos):
                    isBinary = True
                elif patch.startswith("index ", pos, endPos):
                    # Complete existing delta with actual hashes
                    indexLineMatch = _indexLinePattern.match(patch, pos, endPos)
                    oldHash, newHash = indexLineMatch.groups()
                    assert oldHash == delta.old.id
                    if not delta.new.isIdValid():
                        delta.new.id = newHash
                continue

            # Start new hunk
            if firstChar == "@":
                rawLine = patch[pos:endPos]
                oldLine, _dummy, newLine, _dummy, _dummy = _parseHunkHeader(rawLine)

                hunkID += 1
                hunkLineNum = -1
                hunkHeaderLD = LineData(text=rawLine, hunkPos=DiffLinePos(hunkID, -1),
                                        oldLineNo=oldLine, newLineNo=newLine)
                lineData.append(hunkHeaderLD)
                continue

            origin = firstChar

            # "No newline at end of file" (message might be localized)
            if origin == '\\':
                # Fix up the last LineData and don't create a new one.
                ld = lineData[-1]
                ld.text = ld.text.removesuffix("\n")
                ld.hiddenSuffix = "\n" + patch[pos:endPos]
                continue

            hunkLineNum += 1

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

            ld = LineData(text=patch[pos+1:endPos],
                          hunkPos=DiffLinePos(hunkID, hunkLineNum),
                          origin=origin,
                          oldLineNo=-1 if origin == "+" else oldLine,
                          newLineNo=-1 if origin == "-" else newLine)

            if origin == '+':
                assert ld.newLineNo == newLine
                assert ld.oldLineNo == -1
                newLine += 1
                ld.clumpID = clumpID
                numLinesInClump += 1
                perfectClumpTally += 1
                pluses += 1
            elif origin == '-':
                assert ld.newLineNo == -1
                assert ld.oldLineNo == oldLine
                oldLine += 1
                ld.clumpID = clumpID
                numLinesInClump += 1
                perfectClumpTally -= 1
                minuses += 1
            else:
                assert origin == " ", f"unknown origin: '{origin.encode('unicode_escape')}'"
                assert ld.newLineNo == newLine
                assert ld.oldLineNo == oldLine
                newLine += 1
                oldLine += 1

            lineData.append(ld)

        if not lineData:
            if isBinary:
                raise DiffDocument.BinaryError()
            raise DiffDocument.NoChangeError()

        # Recreating a QTextDocument is faster than clearing any existing one.
        textDocument = QTextDocument()
        textDocument.setObjectName("DiffDocument")
        textDocument.setDocumentLayout(QPlainTextDocumentLayout(textDocument))

        diffDocument = DiffDocument(document=textDocument, lineData=lineData, style=DiffStyle(),
                                    pluses=pluses, minuses=minuses,
                                    maxLine=max(newLine, oldLine))

        # Begin batching text insertions for performance.
        # This prevents Qt from recomputing the document's layout after every line insertion.
        cursor = QTextCursor(textDocument)
        cursor.beginEditBlock()

        # Build up document from the lineData array.
        diffDocument.buildTextDocument(cursor)

        # Emphasize doppelganger differences.
        diffDocument.formatDoppelgangerDiffs(cursor)

        # Done batching text insertions.
        cursor.endEditBlock()

        return diffDocument

    @benchmark
    def buildTextDocument(self, cursor: QTextCursor):
        assert self.document.isEmpty()

        style = self.style
        defaultBF = cursor.blockFormat()
        defaultCF = cursor.charFormat()
        showStrayCRs = settings.prefs.showStrayCRs
        isEmpty = True

        for ld in self.lineData:
            # Decide block format & character format
            origin = ld.origin
            if not origin:
                bf = style.hunkBF
                cf = style.hunkCF
            elif origin == '+':
                bf = style.addBF1
                cf = defaultCF
            elif origin == '-':
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

            if isEmpty:
                ld.cursorStart = 0
            else:
                cursor.insertBlock()
                ld.cursorStart = cursor.position()

            cursor.setBlockFormat(bf)
            cursor.setBlockCharFormat(cf)
            cursor.insertText(ld.text[:trimBack])

            if trailer:
                ld.trailerLength = len(trailer)
                cursor.setCharFormat(style.warningCF)
                cursor.insertText(trailer)

            ld.cursorEnd = cursor.position()
            isEmpty = False

    @benchmark
    def formatDoppelgangerDiffs(self, cursor: QTextCursor):
        if self.pluses == 0 or self.minuses == 0:  # Don't bother if there can't be any doppelgangers
            return

        doppelgangerBlocksQueue = []
        delFormat = self.style.delCF2
        addFormat = self.style.addCF2

        for lineNumber, line in enumerate(self.lineData):
            if line.doppelganger < 0:  # Skip lines without doppelgangers
                continue

            assert lineNumber != line.doppelganger, "line cannot be its own doppelganger"
            assert line.origin in "+-", "line with doppelganger must have origin"
            aheadOfDoppelganger = lineNumber < line.doppelganger

            if aheadOfDoppelganger:
                textA = line.text
                textB = self.lineData[line.doppelganger].text
                sm = difflib.SequenceMatcher(a=textA, b=textB)
                blocks = sm.get_matching_blocks()
                doppelgangerBlocksQueue.append(blocks)  # Set blocks aside for my doppelganger
            else:
                blocks = doppelgangerBlocksQueue.pop(0)  # Consume blocks set aside by my doppelganger

            charFormat = delFormat if line.origin == "-" else addFormat

            cursorPos = line.cursorStart
            oldBlockEnd = 0
            for blockStart, blockEnd in _invertMatchingBlocks(blocks, useA=aheadOfDoppelganger):
                assert blockStart >= oldBlockEnd

                # Advance Qt cursor (UTF-16!) to new doppelganger block
                cursorPos += qstringLength(line.text[oldBlockEnd: blockStart])
                cursor.setPosition(cursorPos, QTextCursor.MoveMode.MoveAnchor)

                # Move to end of doppelganger block and apply formatting
                cursorPos += qstringLength(line.text[blockStart: blockEnd])
                cursor.setPosition(cursorPos, QTextCursor.MoveMode.KeepAnchor)
                cursor.setCharFormat(charFormat)

                oldBlockEnd = blockEnd

        assert not doppelgangerBlocksQueue, "should've consumed all doppelganger matching blocks!"


def _invertMatchingBlocks(blockList: list[difflib.Match], useA: bool) -> Generator[tuple[int, int], None, None]:
    px = 0

    for block in blockList:
        x1 = block.a if useA else block.b
        x2 = x1 + block.size

        if px != x1:
            yield px, x1

        px = x2
