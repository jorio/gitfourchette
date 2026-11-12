# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import difflib
import itertools
import re
from bisect import bisect_left
from collections.abc import Iterator
from dataclasses import dataclass

from gitfourchette import colors
from gitfourchette import settings
from gitfourchette.gitdriver.parsers import iterateLines
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.syntax import LexJob, ColorScheme
from gitfourchette.toolbox import *


STRAY_LINE_ENDINGS = "\r\u2029"
TRANSLATE_STRAY_LINE_ENDINGS = {ord(c): 0x2028 for c in STRAY_LINE_ENDINGS}
"""
Qt treats LF, CR, and U+2029 (PARAGRAPH SEPARATOR) as newlines, and QTextCursor
creates a new QTextBlock when inserting text that contains one of these. But Git
only recognizes LF as a newline. We want QTextBlocks to match up exactly with
what Git sees as a line, so translate the offending chars to U+2028 (LINE
SEPARATOR) to show a newline visually without creating a QTextBlock.

(Note: Only call str.translate with this table on a string that has had CRLF
replaced with LF! This table is only intended to translate stray newline chars.)
"""


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
    """
    0-indexed line number within the hunk.
    -1 means the hunk header line itself ("@@ ... @@").
    """

    def isHunkHeaderLine(self) -> bool:
        return self.hunkLineNum == -1


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

    @property
    def originDelta(self) -> int:
        if self.origin == "+":
            return 1
        if self.origin == "-":
            return -1
        return 0

    @property
    def reverseOrigin(self) -> str:
        if self.origin == "+":
            return "-"
        if self.origin == "-":
            return "+"
        return self.origin


class DiffTextFormats:
    addBF = QTextBlockFormat()
    delBF = QTextBlockFormat()
    doppelgangerAddCF = QTextCharFormat()
    doppelgangerDelCF = QTextCharFormat()
    hunkBF = QTextBlockFormat()
    hunkCF = QTextCharFormat()
    warningCF = QTextCharFormat()

    @classmethod
    def refresh(cls, scheme: ColorScheme, colorblind: bool):
        bgColor = scheme.backgroundColor

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
        elif scheme.isDark():
            delColor2 = mixColors(delColor1, QColor(0x993333), .6)
            addColor2 = mixColors(addColor1, QColor(0x339933), .6)
        else:
            delColor2 = mixColors(delColor1, QColor(0x993333), .25)
            addColor2 = mixColors(addColor1, QColor(0x339933), .25)

        if scheme.isDark():
            warningColor = colors.red
            hunkColor = colors.blue.lighter(125)
        else:
            warningColor = colors.red.darker(125)
            hunkColor = QColor(0x0050f0)

        cls.addBF.setBackground(addColor1)
        cls.delBF.setBackground(delColor1)

        cls.doppelgangerAddCF.setBackground(addColor2)
        cls.doppelgangerDelCF.setBackground(delColor2)

        cls.hunkCF.setFontItalic(True)
        cls.hunkCF.setForeground(hunkColor)

        cls.warningCF.setFontUnderline(True)
        cls.warningCF.setFontWeight(QFont.Weight.Bold)
        cls.warningCF.setBackground(scheme.backgroundColor)
        cls.warningCF.setForeground(warningColor)


@dataclass
class DiffDocument:
    document: QTextDocument
    lineData: list[LineData]
    pluses: int
    minuses: int
    maxLine: int
    oldHash: str
    newHash: str

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
    def fromPatch(patch: str, maxLineLength=0) -> DiffDocument:
        lineData: list[LineData] = []

        pluses = 0
        minuses = 0

        hunkID = -1
        oldLine = -1
        newLine = -1
        hunkLineNum = -1
        isBinary = False
        oldHash = ""
        newHash = ""

        for pos, endPos in iterateLines(patch):
            if maxLineLength and endPos - pos > maxLineLength:
                raise DiffDocument.VeryLongLinesError()

            firstChar = patch[pos]

            # Keep looking for first hunk
            if firstChar != "@" and hunkID < 0:
                if patch.startswith(("Binary files", "GIT binary patch"), pos, endPos):
                    isBinary = True
                elif patch.startswith("index ", pos, endPos):
                    # The 'index' line can be used to complete an existing delta with actual blob hashes
                    indexLineMatch = _indexLinePattern.match(patch, pos, endPos)
                    oldHash, newHash = indexLineMatch.groups()
                continue

            # Start new hunk
            if firstChar == "@":
                rawLine = patch[pos:endPos]
                oldLine, _dummy1, newLine, _dummy2, _dummy3 = _parseHunkHeader(rawLine)

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

            ld = LineData(text=patch[pos+1:endPos],
                          hunkPos=DiffLinePos(hunkID, hunkLineNum),
                          origin=origin,
                          oldLineNo=-1 if origin == "+" else oldLine,
                          newLineNo=-1 if origin == "-" else newLine)

            if origin == '+':
                assert ld.newLineNo == newLine
                assert ld.oldLineNo == -1
                newLine += 1
                pluses += 1
            elif origin == '-':
                assert ld.newLineNo == -1
                assert ld.oldLineNo == oldLine
                oldLine += 1
                minuses += 1
            else:
                assert origin == " ", f"unknown origin: {origin.encode('unicode_escape')!r}"
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

        diffDocument = DiffDocument(document=textDocument, lineData=lineData,
                                    pluses=pluses, minuses=minuses,
                                    maxLine=max(newLine, oldLine),
                                    oldHash=oldHash, newHash=newHash)

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

        defaultBF = cursor.blockFormat()
        defaultCF = cursor.charFormat()
        showStrayCRs = settings.prefs.showStrayCRs
        isEmpty = True

        for ld in self.lineData:
            # Decide block format & character format
            origin = ld.origin
            if not origin:
                bf = DiffTextFormats.hunkBF
                cf = DiffTextFormats.hunkCF
            elif origin == '+':
                bf = DiffTextFormats.addBF
                cf = defaultCF
            elif origin == '-':
                bf = DiffTextFormats.delBF
                cf = defaultCF
            else:
                bf = defaultBF
                cf = defaultCF

            # Process line ending
            text = _withoutLineEnding(ld.text)
            lineEnding = ld.text[len(text):]
            if not lineEnding:
                trailer = _("<no newline at end of file>")
            elif showStrayCRs and lineEnding != "\n":
                trailer = "<CRLF>" if lineEnding == "\r\n" else "<CR>"
            else:
                trailer = ""

            # The code assumes there's exactly one QTextBlock for each LineData.
            # Don't let Qt split the line into multiple blocks if it contains
            # stray line terminators (CR or PARAGRAPH SEPARATOR).
            if "\r" in text or "\u2029" in text:
                strayChar = next((c for c in text if c in STRAY_LINE_ENDINGS), "")
                strayName = "CR" if strayChar == "\r" else "PS"
                trailer += _("<stray {0} in this line>", strayName)
                text = text.translate(TRANSLATE_STRAY_LINE_ENDINGS)

            # Insert the text
            if isEmpty:
                ld.cursorStart = 0
            else:
                cursor.insertBlock()
                ld.cursorStart = cursor.position()
            blockStart = cursor.blockNumber()
            cursor.setBlockFormat(bf)
            cursor.setBlockCharFormat(cf)
            cursor.insertText(text)

            # Insert the trailer
            if trailer:
                # Replace spaces in trailer so whitespace formatting skips it
                trailer = trailer.replace(" ", "\u2009")

                ld.trailerLength = len(trailer)
                cursor.setCharFormat(DiffTextFormats.warningCF)
                cursor.insertText(trailer)

            numBlocks = 1 + cursor.blockNumber() - blockStart
            assert numBlocks, f"Qt inserted {numBlocks} blocks for line {ld.text:!r}"

            ld.cursorEnd = cursor.position()
            isEmpty = False

    @benchmark
    def formatDoppelgangerDiffs(self, cursor: QTextCursor):
        if self.pluses == 0 or self.minuses == 0:  # Don't bother if there can't be any doppelgangers
            return

        for minus, plus in _doppelgangers(self.lineData):
            # Compare the text shown in the document (the last line may gain or lose its newline)
            minusSpans, plusSpans = _changedSpans(_withoutLineEnding(minus.text), _withoutLineEnding(plus.text))
            _highlightSpans(cursor, minus, minusSpans, DiffTextFormats.doppelgangerDelCF)
            _highlightSpans(cursor, plus, plusSpans, DiffTextFormats.doppelgangerAddCF)


def _invertMatchingBlocks(blockList: list[difflib.Match], useA: bool) -> Iterator[tuple[int, int]]:
    px = 0

    for block in blockList:
        x1 = block.a if useA else block.b
        x2 = x1 + block.size

        if px != x1:
            yield px, x1

        px = x2


def _withoutLineEnding(text: str) -> str:
    """The part of a diff line that the document shows: no LF, CRLF or CR at the end."""
    return text.removesuffix("\n").removesuffix("\r")


def _doppelgangers(lineData: list[LineData]) -> Iterator[tuple[LineData, LineData]]:
    """
    Pair up the - and + lines of each clump (run of adjacent -/+ lines) that has as
    many - lines as + lines. The n-th - line pairs with the n-th + line.
    """
    clumps = itertools.groupby(lineData, key=lambda ld: ld.origin in ("-", "+"))
    for isClump, lines in clumps:
        if not isClump:
            continue
        clump = list(lines)
        minusLines = [ld for ld in clump if ld.origin == "-"]
        plusLines = [ld for ld in clump if ld.origin == "+"]
        if len(minusLines) == len(plusLines):
            yield from zip(minusLines, plusLines, strict=True)


def _changedSpans(a: str, b: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """
    The parts of a and b that differ, as (start, end) offsets in UTF-16 units,
    which is what QTextCursor counts in.
    """
    blocks = difflib.SequenceMatcher(a=a, b=b).get_matching_blocks()

    def utf16Spans(text: str, useA: bool) -> list[tuple[int, int]]:
        return [(qstringLength(text[:start]), qstringLength(text[:end]))
                for start, end in _invertMatchingBlocks(blocks, useA)]

    return utf16Spans(a, True), utf16Spans(b, False)


def _highlightSpans(cursor: QTextCursor, line: LineData, spans: list[tuple[int, int]], charFormat: QTextCharFormat):
    for start, end in spans:
        cursor.setPosition(line.cursorStart + start, QTextCursor.MoveMode.MoveAnchor)
        cursor.setPosition(line.cursorStart + end, QTextCursor.MoveMode.KeepAnchor)
        cursor.setCharFormat(charFormat)
