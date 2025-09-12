# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from collections.abc import Iterable
from io import StringIO

from pygit2.enums import FileMode

from gitfourchette.diffview.diffdocument import LineData
from gitfourchette.gitdriver import VanillaDelta
from gitfourchette.nav import NavContext

REVERSE_ORIGIN_MAP = {
    ' ': ' ',
    '=': '=',
    '+': '-',
    '-': '+',
    '>': '<',
    '<': '>',
}

QUOTE_PATH_ESCAPES = {
    ' ': ' ',
    '"': '\\"',
    '\a': '\\a',
    '\b': '\\b',
    '\t': '\\t',
    '\n': '\\n',
    '\v': '\\v',
    '\f': '\\f',
    '\r': '\\r',
    '\\': '\\\\',
}


def quotePath(path: str) -> str:
    quote = False
    safePath = []

    for c in path:
        codepoint = ord(c)
        if 0x21 <= codepoint <= 0x7e:  # copy ASCII characters '!' through '~' verbatim
            safePath.append(c)
            continue

        if not quote:
            safePath.insert(0, '"')
            quote = True

        try:
            safePath.append(QUOTE_PATH_ESCAPES[c])
        except KeyError:
            safePath.append(f"\\{codepoint:03o}")

    if quote:
        safePath.append('"')

    return "".join(safePath)


def getPatchPreamble(delta: VanillaDelta, context: NavContext, reverse=False) -> str:
    oldPath, newPath = delta.origPath or delta.path, delta.path
    oldMode, newMode = delta.modesPerContext(context)
    oldHash, newHash = delta.hashesPerContext(context)

    oldHash = oldHash or "0" * 40
    newHash = newHash or "0" * 40

    if not reverse:
        pass
    elif delta.statusPerContext(context) != "D":
        # When reversing some lines within a patch, stick to the new file
        # to avoid changing the file's name or mode.
        oldPath, oldMode, oldHash = newPath, newMode, newHash
    else:
        # ...Unless we're reversing lines within a deletion.
        newPath, newMode, newHash = oldPath, oldMode, oldHash

    oldPathQuoted = quotePath(f"a/{oldPath}")
    newPathQuoted = quotePath(f"b/{newPath}")
    preamble = [f"diff --git {oldPathQuoted} {newPathQuoted}\n"]

    oldExists = not all(c == "0" for c in oldHash)
    newExists = not all(c == "0" for c in newHash)

    if not oldExists:
        preamble.append(f"new file mode {newMode:06o}\n")
    elif oldMode != newMode or newMode != FileMode.BLOB:
        preamble.append(f"old mode {oldMode:06o}\n")
        preamble.append(f"new mode {newMode:06o}\n")

    # Work around libgit2 bug: if a patch lacks the "index" line,
    # libgit2 will fail to parse it if there are "old mode"/"new mode" lines.
    # Also, even if the patch is successfully parsed as a Diff, and we need to
    # regenerate it (from the Diff), libgit2 may fail to re-create the
    # "---"/"+++" lines and it'll therefore fail to parse its own output.
    preamble += f"index {oldHash}..{'f'*40}\n"

    if oldExists:
        # TODO: Should we quote this?
        preamble.append(f"--- a/{oldPath}\n")
    else:
        preamble.append("--- /dev/null\n")

    if newExists:
        # TODO: Should we quote this?
        preamble.append(f"+++ b/{newPath}\n")
    else:
        preamble.append("+++ /dev/null\n")

    return "".join(preamble)


def originToDelta(origin):
    if origin == '+':
        return 1
    elif origin == '-':
        return -1
    else:
        return 0


def reverseOrigin(origin):
    return REVERSE_ORIGIN_MAP.get(origin, origin)


def writeContext(subpatch: StringIO, reverse: bool, lines: Iterable[LineData]):
    skipOrigin = '-' if reverse else '+'
    for line in lines:
        if line.origin == skipOrigin:
            # Skip that line entirely
            continue
        elif line.origin in "=><":
            # GIT_DIFF_LINE_CONTEXT_EOFNL, ...ADD_EOFNL, ...DEL_EOFNL
            # Just copy "\ No newline at end of file" verbatim without an origin character
            pass
        elif line.origin in " -+":
            # Make it a context line
            subpatch.write(" ")
        else:
            raise NotImplementedError(f"unknown origin char {line.origin}")
        subpatch.write(line.text)


def extractSubpatch(
        masterDelta: VanillaDelta,
        masterContext: NavContext,
        masterLineDatas: list[LineData],
        spanStart: int,
        spanEnd: int,
        reverse: bool
) -> str:
    """
    Create a patch (in unified diff format) from a range of selected lines in a diff.
    """

    spanStartPos = masterLineDatas[spanStart].hunkPos
    spanEndPos = masterLineDatas[spanEnd].hunkPos

    # Edge case: a single hunk header line is selected
    if (spanStartPos.hunkID == spanEndPos.hunkID
            and spanStartPos.hunkLineNum < 0
            and spanEndPos.hunkLineNum < 0):
        return ""

    patch = StringIO()

    preamble = getPatchPreamble(masterDelta, masterContext, reverse)
    patch.write(preamble)

    newHunkStartOffset = 0
    subpatchIsEmpty = True

    for hunkID in range(spanStartPos.hunkID, spanEndPos.hunkID + 1):
        assert hunkID >= 0

        hunkStart, hunkEnd = LineData.getHunkExtents(masterLineDatas, hunkID)
        hunkHeader = masterLineDatas[hunkStart]
        hunkContents = masterLineDatas[hunkStart + 1 : hunkEnd + 1]  # Skip header line
        numHunkLines = len(hunkContents)

        # ---------------------------------------------------------------------
        # Compute selection bounds within the hunk

        # Compute start line boundary for this hunk
        if hunkID == spanStartPos.hunkID:  # First hunk in selection?
            boundStart = spanStartPos.hunkLineNum
            if boundStart < 0:  # The hunk header's hunkLineNum is -1
                boundStart = 0
        else:  # Middle hunk: take all lines in hunk
            boundStart = 0

        # Compute end line boundary for this hunk
        if hunkID == spanEndPos.hunkID:  # Last hunk in selection?
            boundEnd = spanEndPos.hunkLineNum
            if boundEnd < 0:  # The hunk header's relative line number is -1
                boundEnd = 0
        else:  # Middle hunk: take all lines in hunk
            boundEnd = numHunkLines-1

        # Expand selection to any lines saying "\ No newline at end of file"
        # that are adjacent to the selection. This will let us properly reorder
        # -/+ lines without an LF character later on (see plusLines below).
        while boundEnd < numHunkLines-1 and hunkContents[boundEnd+1].origin in "=><":
            boundEnd += 1

        # Compute line count delta in this hunk
        lineCountDelta = sum(originToDelta(hunkContents[ln].origin)
                             for ln in range(boundStart, boundEnd + 1))
        if reverse:
            lineCountDelta = -lineCountDelta

        # Skip this hunk if all selected lines are context
        if lineCountDelta == 0 and \
                all(originToDelta(hunkContents[ln].origin) == 0 for ln in range(boundStart, boundEnd + 1)):
            continue

        subpatchIsEmpty = False

        # ---------------------------------------------------------------------
        # Adapt hunk header

        # Parse hunk info
        hunkOldStart, hunkOldLines, hunkNewStart, hunkNewLines, hunkComment = hunkHeader.parseHunkHeader()

        # Get coordinates of old hunk
        if reverse:  # flip old<=>new if reversing
            oldStart, oldLines = hunkNewStart, hunkNewLines
        else:
            oldStart, oldLines = hunkOldStart, hunkOldLines

        # Compute coordinates of new hunk
        newStart = oldStart + newHunkStartOffset
        newLines = oldLines + lineCountDelta

        # Assemble doctored hunk header
        assert hunkComment.endswith("\n")
        patch.write(f"@@ -{oldStart},{oldLines} +{newStart},{newLines} @@")
        patch.write(hunkComment)

        # Account for line count delta in next new hunk's start offset
        newHunkStartOffset += lineCountDelta

        # ---------------------------------------------------------------------
        # Write hunk contents

        # Write non-selected lines at beginning of hunk as context
        writeContext(patch, reverse,
                     (hunkContents[ln] for ln in range(0, boundStart)))

        # We'll reorder all non-context lines so that "-" lines always appear above "+" lines.
        # This buffer will hold "+" lines while we're processing a clump of non-context lines.
        # This is to work around a libgit2 bug where it fails to parse "+" lines without LF
        # that appear above "-" lines. (Vanilla git doesn't have this issue.)
        # libgit2 fails to parse this:          But this parses fine:
        #   +hello                                -hallo
        #   \ No newline at end of file           +hello
        #   -hallo                                \ No newline at end of file
        plusLines = StringIO()

        # Write selected lines within the hunk
        for ln in range(boundStart, boundEnd + 1):
            line = hunkContents[ln]

            if not reverse:
                origin = line.origin
            else:
                origin = reverseOrigin(line.origin)

            buffer = patch
            if origin in "+<":
                # Save those lines for the end of the clump - write to plusLines for now
                buffer = plusLines
            elif origin == " " and plusLines.tell() != 0:
                # A context line breaks up the clump of non-context lines - flush plusLines
                patch.write(plusLines.getvalue())
                plusLines = StringIO()

            if origin in "=><":
                # GIT_DIFF_LINE_CONTEXT_EOFNL, ...ADD_EOFNL, ...DEL_EOFNL
                # Just write raw content (b"\n\\ No newline at end of file") without an origin char
                assert line.text == ord('\n')
                buffer.write(line.text)
            else:
                buffer.write(origin)
                buffer.write(line.text)

        # End of selected lines.
        # All remaining lines in the hunk are context from now on.

        # Flush plusLines
        if plusLines.tell() != 0:
            patch.write(plusLines.getvalue())

        # Write non-selected lines at end of hunk as context
        writeContext(patch, reverse,
                     (hunkContents[ln] for ln in range(boundEnd + 1, len(hunkContents))))

    if subpatchIsEmpty:
        return ""

    return patch.getvalue()
