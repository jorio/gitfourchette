# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from collections.abc import Iterable

from gitfourchette.diffview.diffdocument import LineData
from gitfourchette.gitdriver import GitDelta, GitStatus
from gitfourchette.porcelain import FileMode

QUOTE_PATH_ESCAPES = {
    '"': '\\"',
    '\a': '\\a',
    '\b': '\\b',
    '\t': '\\t',
    '\n': '\\n',
    '\v': '\\v',
    '\f': '\\f',
    '\r': '\\r',
    '\\': '\\\\',
    # Although we're not technically escaping the space character, it's
    # included in this dict to force any paths containing spaces to be quoted.
    ' ': ' ',
}
""" Predefined character escapes for `quotePath`. """


def quotePath(path: str) -> str:
    # If no escaping is needed, we can spit back the input path verbatim.
    verbatim = True

    # Build a safe (quoted + escaped) path.
    safePath = ['"']

    for char in path:
        # See if we should escape this character
        try:
            char = QUOTE_PATH_ESCAPES[char]
            verbatim = False
        except KeyError:
            # This character has no predefined escape.
            # If it's a printable ASCII char, we can copy it verbatim,
            # otherwise it should be encoded as octal-escaped UTF-8.
            isPrintableAscii = 0x21 <= ord(char) <= 0x7e
            if not isPrintableAscii:
                char = "".join(f"\\{byte:03o}" for byte in char.encode("utf-8"))
                verbatim = False

        safePath.append(char)

    if verbatim:
        # None of the characters had to be escaped
        assert path == "".join(safePath).removeprefix('"')
        return path

    safePath.append('"')
    return "".join(safePath)


def getPatchPreamble(delta: GitDelta, reverse=False) -> list[str]:
    old = delta.old
    new = delta.new

    if not reverse:
        # Not reversing. Old/new sides are correct.
        pass
    elif delta.status == GitStatus.Deleted:
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

    preamble.append(f"--- {oldPathQuoted if oldExists else '/dev/null'}\n")
    preamble.append(f"+++ {newPathQuoted if newExists else '/dev/null'}\n")

    return preamble


def writeContext(subpatch: list[str], reverse: bool, lines: Iterable[LineData]):
    skipOrigin = '-' if reverse else '+'
    for line in lines:
        assert line.origin in " +-", f"unknown origin {line.origin}"

        if line.origin == skipOrigin:
            # Skip that line entirely
            continue

        # Make it a context line
        subpatch.append(" ")
        subpatch.append(line.text)
        subpatch.append(line.hiddenSuffix)


def extractSubpatch(
        masterDelta: GitDelta,
        lines: list[LineData],
        spanStart: int,
        spanEnd: int,
        reverse: bool
) -> str:
    """
    Create a patch (in unified diff format) from a range of selected lines in a diff.
    """

    patch = getPatchPreamble(masterDelta, reverse)
    preamblePartCount = len(patch)

    newHunkStartOffset = 0

    firstLinePos = lines[spanStart].hunkPos
    lastLinePos = lines[spanEnd].hunkPos

    for hunkID in range(firstLinePos.hunkID, lastLinePos.hunkID + 1):
        assert hunkID >= 0

        hunkStart, hunkLast = LineData.getHunkExtents(lines, hunkID)
        hunkHeader = lines[hunkStart]
        assert hunkHeader.hunkPos.isHunkHeaderLine()
        hunkStart += 1  # Skip header line
        hunkStop = hunkLast + 1

        # ---------------------------------------------------------------------
        # Compute selection bounds within the hunk

        if hunkID == firstLinePos.hunkID and not firstLinePos.isHunkHeaderLine():
            # Start of selection falls inside this hunk: Adjust slice start
            sliceStart = hunkStart + firstLinePos.hunkLineNum
        else:
            # Start of selection was before this hunk: Take entire hunk
            sliceStart = hunkStart

        if hunkID == lastLinePos.hunkID:
            if lastLinePos.isHunkHeaderLine():
                # End of selection falls inside hunk header: ignore this hunk
                break

            # End of selection falls inside current hunk: adjust slice end
            sliceStop = hunkStart + lastLinePos.hunkLineNum + 1
        else:
            # End of selection is beyond this hunk: Take entire hunk
            sliceStop = hunkStop

        # Selected line numbers in this hunk
        sliceRange = range(sliceStart, sliceStop)
        # Context line numbers above/below selection in this hunk
        headContextRange = range(hunkStart, sliceStart)
        tailContextRange = range(sliceStop, hunkStop)

        # Compute line count delta in this hunk
        lineCountDelta = sum(lines[ln].originDelta for ln in sliceRange)
        if reverse:
            lineCountDelta = -lineCountDelta

        # Skip this hunk if all selected lines are context
        if lineCountDelta == 0 and all(lines[ln].originDelta == 0 for ln in sliceRange):
            continue

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
        patch.append(f"@@ -{oldStart},{oldLines} +{newStart},{newLines} @@")
        patch.append(hunkComment)

        # Account for line count delta in next new hunk's start offset
        newHunkStartOffset += lineCountDelta

        # ---------------------------------------------------------------------
        # Write hunk contents

        # Write non-selected lines at beginning of hunk as context
        writeContext(patch, reverse, (lines[ln] for ln in headContextRange))

        # We'll reorder all non-context lines so that "-" lines always appear above "+" lines.
        # This buffer will hold "+" lines while we're processing a clump of non-context lines.
        # This is to work around a libgit2 bug where it fails to parse "+" lines without LF
        # that appear above "-" lines. (Vanilla git doesn't have this issue.)
        # libgit2 fails to parse this:          But this parses fine:
        #   +hello                                -hallo
        #   \ No newline at end of file           +hello
        #   -hallo                                \ No newline at end of file
        buffer: list[str] = []

        # Write selected lines within the hunk
        for ln in sliceRange:
            line = lines[ln]
            origin = line.reverseOrigin if reverse else line.origin

            if origin == " " and buffer:
                # A context line breaks up the clump of non-context lines - flush buffer
                patch.extend(buffer)
                buffer.clear()

            if origin == "+":
                # Save "+" line for the end of the clump
                writeTo = buffer
            else:
                # Write "-" and " " lines to final patch now
                writeTo = patch
            writeTo.append(origin)
            writeTo.append(line.text)
            writeTo.append(line.hiddenSuffix)

        # Flush any remaining buffered "+" lines
        patch.extend(buffer)

        # End of selected lines.
        # All remaining lines in the hunk are context from now on.
        # Write non-selected lines at end of hunk as context
        writeContext(patch, reverse, (lines[ln] for ln in tailContextRange))

    # Bail if the patch comes out empty
    if len(patch) <= preamblePartCount:
        return ""

    return "".join(patch)
