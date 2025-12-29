# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from collections.abc import Iterable
from io import StringIO

from pygit2.enums import FileMode

from gitfourchette.diffview.diffdocument import LineData
from gitfourchette.gitdriver import GitDelta

REVERSE_ORIGIN_MAP = {
    ' ': ' ',
    '+': '-',
    '-': '+',
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


def getPatchPreamble(delta: GitDelta, reverse=False) -> str:
    old = delta.old
    new = delta.new

    if not reverse:
        # Not reversing. Old/new sides are correct.
        pass
    elif delta.status == "D":
        # Reversing lines within a deleted file. Swap old/new sides.
        new, old = old, new
        assert old.isId0()  # 'old' side is now the deleted file
    else:
        # When reversing lines within a patch, stick to the new file
        # to avoid changing the file's name or mode.
        old = new

    oldPathQuoted = quotePath(f"a/{old.path}")
    newPathQuoted = quotePath(f"b/{new.path}")
    preamble = [f"diff --git {oldPathQuoted} {newPathQuoted}\n"]

    oldExists = not old.isId0()
    newExists = not new.isId0()

    if not oldExists:
        preamble.append(f"new file mode {new.mode:06o}\n")
    elif old.mode != new.mode or new.mode != FileMode.BLOB:
        preamble.append(f"old mode {old.mode:06o}\n")
        preamble.append(f"new mode {new.mode:06o}\n")

    # Work around libgit2 bug: if a patch lacks the "index" line,
    # libgit2 will fail to parse it if there are "old mode"/"new mode" lines.
    # Also, even if the patch is successfully parsed as a Diff, and we need to
    # regenerate it (from the Diff), libgit2 may fail to re-create the
    # "---"/"+++" lines and it'll therefore fail to parse its own output.
    preamble.append(f"index {old.id}..{'f' * 40}\n")

    if oldExists:
        # TODO: Should we quote this?
        preamble.append(f"--- a/{old.path}\n")
    else:
        preamble.append("--- /dev/null\n")

    if newExists:
        # TODO: Should we quote this?
        preamble.append(f"+++ b/{old.path}\n")
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
        assert line.origin in " +-", f"unknown origin {line.origin}"

        if line.origin == skipOrigin:
            # Skip that line entirely
            continue

        # Make it a context line
        subpatch.write(" ")
        subpatch.write(line.text)
        subpatch.write(line.hiddenSuffix)


def extractSubpatch(
        masterDelta: GitDelta,
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

    preamble = getPatchPreamble(masterDelta, reverse)
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
            if origin == "+":
                # Save this line for the end of the clump - write to plusLines for now
                buffer = plusLines
            elif origin == " " and plusLines.tell() != 0:
                # A context line breaks up the clump of non-context lines - flush plusLines
                patch.write(plusLines.getvalue())
                plusLines = StringIO()

            buffer.write(origin)
            buffer.write(line.text)
            buffer.write(line.hiddenSuffix)

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
