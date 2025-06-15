# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging as _logging
from collections.abc import Generator

from gitfourchette.appconsts import *
from gitfourchette.blame.annotatedfile import AnnotatedFile
from gitfourchette.blame.trace import TraceNode, Trace
from gitfourchette.porcelain import *

_logger = _logging.getLogger(__name__)

BLAME_PROGRESS_INTERVAL = 10 if not APP_TESTMODE else 1


def blameFile(
        repo: Repo,
        topNode: TraceNode,
        topCommitId: Oid = NULL_OID,
        progressCallback=Trace.dummyProgressCallback
):
    nodeSequence = list(topNode.walkGraph())

    blobIdA = nodeSequence[-1].blobId
    blobA = repo[blobIdA]
    assert isinstance(blobA, Blob)

    for i, node in enumerate(reversed(nodeSequence)):
        if i % BLAME_PROGRESS_INTERVAL == 0:
            progressCallback(i)

        assert node.sealed
        assert node.annotatedFile is None, ("node already has an annotated file "
                                            "(safe to ignore this if benchmarking; just run python -OO)")

        blobIdA = node.ancestorBlobId  # blob id in first parent
        blobIdB = node.blobId

        # Skip nodes that don't contribute a new blob
        if blobIdA == blobIdB:
            assert node.status == DeltaStatus.RENAMED, f"{node} isn't 'R'?"
            continue

        # Assign informal revision number
        node.revisionNumber = i + 1

        blobB = repo[blobIdB]
        assert isinstance(blobB, Blob)

        if blobIdA == NULL_OID:
            assert node.status == DeltaStatus.ADDED
            node.annotatedFile = _makeInitialBlame(node, blobB)
            continue
        elif blobA.id == blobIdA:
            # Reuse previous blob (speedup, common case)
            pass
        else:
            blobA = repo[blobIdA]

        assert isinstance(blobA, Blob)
        assert node.parents[0].annotatedFile is not None, "node parent 0 is not annotated yet"
        patch = blobA.diff(blobB)
        blameA = node.parents[0].annotatedFile
        blameB = _blamePatch(patch, blameA, node)

        if APP_DEBUG and not blameB.binary:
            def countLines(data: bytes):
                return data.count(b'\n') + (0 if data.endswith(b'\n') else 1)
            assert len(blameB.lines) - 1 == countLines(blobB.data)

        # Enrich blame with more precise information from a merged branch
        if (not blameB.binary
                and len(node.parents) >= 2
                and node.parents[1].blobId != blobIdA):
            extraParent = node.parents[1]
            if APP_DEBUG:  # Very expensive assertion that will slow down the blame significantly
                assert repo.descendant_of(node.commitId, extraParent.commitId)
            olderBlob = repo[extraParent.blobId]
            olderBlame = extraParent.annotatedFile
            olderPatch = olderBlob.diff(blobB)
            _overrideBlame(olderPatch, olderBlame, blameB)

        # Save this blame
        node.annotatedFile = blameB

        # Save new blob for next iteration, might save us a lookup if it's the next blob's ancestor
        blobA = blobB

        # See if stop
        if topCommitId == node.commitId:
            break


def _makeInitialBlame(node: TraceNode, blob: Blob) -> AnnotatedFile:
    blame = AnnotatedFile(node)

    data = blob.data
    if b'\0' in data:
        blobText = "$$$BINARY_PLACEHOLDER_LINE$$$"
        blame.binary = True
    else:
        blobText = data.decode("utf-8", errors="replace")

    blame.lines.extend(AnnotatedFile.Line(node, line) for line in blobText.splitlines(keepends=True))
    return blame


def _blamePatch(patch: Patch, blameA: AnnotatedFile, nodeB: TraceNode) -> AnnotatedFile:
    blameB = AnnotatedFile(nodeB)
    blameB.binary = patch.delta.is_binary

    for lineA, lineB, diffLine in _traversePatch(patch, len(blameA.lines)):
        assert lineB == len(blameB.lines)
        if lineA:  # context line
            blameB.lines.append(blameA.lines[lineA])
        else:  # new line originating in B
            blameB.lines.append(AnnotatedFile.Line(nodeB, diffLine.content))

    return blameB


def _overrideBlame(patch: Patch, blameA: AnnotatedFile, blameB: AnnotatedFile):
    for lineA, lineB, _dummy in _traversePatch(patch, len(blameA.lines)):
        if lineA:  # context line
            assert blameB.lines[lineB].text == blameA.lines[lineA].text
            blameB.lines[lineB] = blameA.lines[lineA]


def _traversePatch(patch: Patch, numLinesA: int) -> Generator[tuple[int, int, DiffLine | None], None, None]:
    cursorA = 1
    cursorB = 1

    for hunk in patch.hunks:
        for diffLine in hunk.lines:
            lineA = diffLine.old_lineno
            lineB = diffLine.new_lineno
            origin = diffLine.origin

            if origin == '-':
                # Skip deleted line
                assert lineA >= 1
                cursorA = lineA + 1
            elif origin == '+':
                # This commit is to blame for this line
                assert lineB >= 1
                yield 0, cursorB, diffLine
                cursorB += 1
            elif origin == ' ':
                # Catch up to lineA
                assert lineA >= 1
                while cursorA <= lineA:
                    yield cursorA, cursorB, None
                    cursorA += 1
                    cursorB += 1
                assert cursorB == lineB + 1
            else:
                # GIT_DIFF_LINE_CONTEXT_EOFNL, ...ADD_EOFNL, ...DEL_EOFNL
                assert origin in "=><"

    # Copy rest of file
    while cursorA < numLinesA:
        yield cursorA, cursorB, None
        cursorA += 1
        cursorB += 1
