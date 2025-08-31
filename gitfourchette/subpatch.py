# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import io
from collections.abc import Iterable
from dataclasses import dataclass

from gitfourchette.porcelain import *

REVERSE_ORIGIN_MAP = {
    ' ': ' ',
    '=': '=',
    '+': '-',
    '-': '+',
    '>': '<',
    '<': '>',
}


@dataclass
class DiffLinePos:
    hunkID: int
    hunkLineNum: int


def quotePath(path: bytes):
    surround = False

    safePath = ""

    escapes = {
        ord(' '): ' ',
        ord('"'): '\\"',
        ord('\a'): '\\a',
        ord('\b'): '\\b',
        ord('\t'): '\\t',
        ord('\n'): '\\n',
        ord('\v'): '\\v',
        ord('\f'): '\\f',
        ord('\r'): '\\r',
        ord('\\'): '\\\\',
    }

    for c in path:
        if c in escapes:
            safePath += escapes[c]
            surround = True
        elif c < ord('!') or c > ord('~'):
            safePath += F"\\{c:03o}"
            surround = True
        else:
            safePath += chr(c)

    if surround:
        return F'"{safePath}"'
    else:
        return safePath


def getPatchPreamble(delta: DiffDelta, reverse=False):
    if not reverse:
        of = delta.old_file
        nf = delta.new_file
    else:
        # When reversing some lines within a patch, stick to new_file to avoid
        # changing the file's name or mode.
        of = delta.new_file
        nf = delta.new_file
        # ...Unless we're reversing lines within a deletion.
        if nf.id == NULL_OID:
            nf = delta.old_file

    aQuoted = quotePath(b"a/" + of.raw_path)
    bQuoted = quotePath(b"b/" + nf.raw_path)
    preamble = F"diff --git {aQuoted} {bQuoted}\n"

    ofExists = of.id != NULL_OID
    nfExists = nf.id != NULL_OID

    if not ofExists:
        preamble += F"new file mode {nf.mode:06o}\n"
    elif of.mode != nf.mode or nf.mode != FileMode.BLOB:
        preamble += F"old mode {of.mode:06o}\n"
        preamble += F"new mode {nf.mode:06o}\n"

    # Work around libgit2 bug: if a patch lacks the "index" line,
    # libgit2 will fail to parse it if there are "old mode"/"new mode" lines.
    # Also, even if the patch is successfully parsed as a Diff, and we need to
    # regenerate it (from the Diff), libgit2 may fail to re-create the
    # "---"/"+++" lines and it'll therefore fail to parse its own output.
    preamble += f"index {of.id}..{'f'*40}\n"

    if ofExists:
        preamble += F"--- a/{of.path}\n"
    else:
        preamble += "--- /dev/null\n"

    if nfExists:
        preamble += F"+++ b/{nf.path}\n"
    else:
        preamble += "+++ /dev/null\n"

    return preamble


def originToDelta(origin):
    if origin == '+':
        return 1
    elif origin == '-':
        return -1
    else:
        return 0


def reverseOrigin(origin):
    return REVERSE_ORIGIN_MAP.get(origin, origin)


def writeContext(subpatch: io.BytesIO, reverse: bool, lines: Iterable[DiffLine]):
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
            subpatch.write(b" ")
        else:
            raise NotImplementedError(f"unknown origin char {line.origin}")
        subpatch.write(line.raw_content)


def extractSubpatch(
        masterPatch: Patch,
        startPos: DiffLinePos,  # index of first selected line in master patch
        endPos: DiffLinePos,  # index of last selected line in master patch
        reverse: bool
) -> bytes:
    """
    Creates a patch (in unified diff format) from the range of selected diff lines given as input.
    """

    # Edge case: a single hunk header line is selected
    if startPos.hunkID == endPos.hunkID and startPos.hunkLineNum < 0 and endPos.hunkLineNum < 0:
        return b""

    patch = io.BytesIO()

    preamble = getPatchPreamble(masterPatch.delta, reverse)
    patch.write(preamble.encode())

    newHunkStartOffset = 0
    subpatchIsEmpty = True

    for hunkID in range(startPos.hunkID, endPos.hunkID + 1):
        assert hunkID >= 0
        hunk = masterPatch.hunks[hunkID]
        numHunkLines = len(hunk.lines)

        # Compute start line boundary for this hunk
        if hunkID == startPos.hunkID:  # First hunk in selection?
            startLineNum = startPos.hunkLineNum
            if startLineNum < 0:  # The hunk header's hunkLineNum is -1
                startLineNum = 0
        else:  # Middle hunk: take all lines in hunk
            startLineNum = 0

        # Compute end line boundary for this hunk
        if hunkID == endPos.hunkID:  # Last hunk in selection?
            endLineNum = endPos.hunkLineNum
            if endLineNum < 0:  # The hunk header's relative line number is -1
                endLineNum = 0
        else:  # Middle hunk: take all lines in hunk
            endLineNum = numHunkLines-1

        # Expand selection to any lines saying "\ No newline at end of file"
        # that are adjacent to the selection. This will let us properly reorder
        # -/+ lines without an LF character later on (see plusLines below).
        while endLineNum < numHunkLines-1 and hunk.lines[endLineNum+1].origin in "=><":
            endLineNum += 1

        # Compute line count delta in this hunk
        lineCountDelta = sum(originToDelta(hunk.lines[ln].origin) for ln in range(startLineNum, endLineNum + 1))
        if reverse:
            lineCountDelta = -lineCountDelta

        # Skip this hunk if all selected lines are context
        if lineCountDelta == 0 and \
                all(originToDelta(hunk.lines[ln].origin) == 0 for ln in range(startLineNum, endLineNum + 1)):
            continue
        else:
            subpatchIsEmpty = False

        # Get coordinates of old hunk
        if reverse:  # flip old<=>new if reversing
            oldStart = hunk.new_start
            oldLines = hunk.new_lines
        else:
            oldStart = hunk.old_start
            oldLines = hunk.old_lines

        # Compute coordinates of new hunk
        newStart = oldStart + newHunkStartOffset
        newLines = oldLines + lineCountDelta

        # Assemble doctored hunk header
        headerComment = hunk.header[hunk.header.find(" @@") + 3 :]
        assert headerComment.endswith("\n")
        patch.write(F"@@ -{oldStart},{oldLines} +{newStart},{newLines} @@{headerComment}".encode())

        # Account for line count delta in next new hunk's start offset
        newHunkStartOffset += lineCountDelta

        # Write non-selected lines at beginning of hunk as context
        writeContext(patch, reverse,
                     (hunk.lines[ln] for ln in range(0, startLineNum)))

        # We'll reorder all non-context lines so that "-" lines always appear above "+" lines.
        # This buffer will hold "+" lines while we're processing a clump of non-context lines.
        # This is to work around a libgit2 bug where it fails to parse "+" lines without LF
        # that appear above "-" lines. (Vanilla git doesn't have this issue.)
        # libgit2 fails to parse this:          But this parses fine:
        #   +hello                                -hallo
        #   \ No newline at end of file           +hello
        #   -hallo                                \ No newline at end of file
        plusLines = io.BytesIO()

        # Write selected lines within the hunk
        for ln in range(startLineNum, endLineNum + 1):
            line = hunk.lines[ln]

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
                plusLines = io.BytesIO()

            if origin in "=><":
                # GIT_DIFF_LINE_CONTEXT_EOFNL, ...ADD_EOFNL, ...DEL_EOFNL
                # Just write raw content (b"\n\\ No newline at end of file") without an origin char
                assert line.raw_content[0] == ord('\n')
                buffer.write(line.raw_content)
            else:
                buffer.write(origin.encode())
                buffer.write(line.raw_content)

        # End of selected lines.
        # All remaining lines in the hunk are context from now on.

        # Flush plusLines
        if plusLines.tell() != 0:
            patch.write(plusLines.getvalue())

        # Write non-selected lines at end of hunk as context
        writeContext(patch, reverse,
                     (hunk.lines[ln] for ln in range(endLineNum + 1, len(hunk.lines))))

    if subpatchIsEmpty:
        return b""
    else:
        return patch.getvalue()
