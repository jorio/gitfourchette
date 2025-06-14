# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations as _annotations

import dataclasses as _dataclasses
import logging as _logging
import time
from collections.abc import Generator, Iterator
from contextlib import suppress
from pathlib import Path

from gitfourchette.appconsts import *
from gitfourchette.graph import MockCommit
from gitfourchette.porcelain import *
from gitfourchette.repomodel import UC_FAKEID
from gitfourchette.toolbox.benchmark import BENCHMARK_LOGGING_LEVEL, Benchmark

_logger = _logging.getLogger(__name__)

PLACEHOLDER_OID = Oid(hex='E' * 40)
TRACE_PROGRESS_INTERVAL = 200 if not APP_TESTMODE else 1
BLAME_PROGRESS_INTERVAL = 10 if not APP_TESTMODE else 1


@_dataclasses.dataclass
class TraceNode:
    DefaultStatus = DeltaStatus.UNMODIFIED

    # "Constant" fields known at constructor time
    path: str
    commitId: Oid  # earliest commit in the branch where this blob shows up
    blobId: Oid
    level: int  # branch ancestry level (breadth distance from root branch)

    # Fields that are modified as the trace is refined
    status: DeltaStatus = DefaultStatus
    llPrev: TraceNode | None = None
    llNext: TraceNode | None = None
    sealed: bool = False
    ancestorBlobId: Oid = PLACEHOLDER_OID
    revisionNumber: int = 0

    def __str__(self):
        status_char = self.status.name[0]
        indent = ' ' * 4 * self.level
        return f"({self.level},{id7(self.commitId)},{id7(self.blobId)},{status_char}) {indent}{self.path}"

    def __repr__(self):
        status_char = self.status.name[0]
        return f"(level={self.level}, commit={id7(self.commitId)}, blob={id7(self.ancestorBlobId)}→{id7(self.blobId)}, status={status_char}, path={self.path})"

    def seal(
            self,
            commit: Commit,
            frontier: list[tuple[TraceNode, Commit]],
            ancestorBlobId: Oid
    ) -> bool:
        assert not self.sealed, "node already sealed"
        assert commit
        assert commit.id == self.commitId
        assert self.blobId != NULL_OID

        # Update status, unless we've set it manually (i.e. RENAMED)
        if self.status != TraceNode.DefaultStatus:
            assert self.status == DeltaStatus.RENAMED
        elif ancestorBlobId == self.blobId:
            self.status = DeltaStatus.UNMODIFIED
        elif ancestorBlobId == NULL_OID:
            self.status = DeltaStatus.ADDED
        else:
            self.status = DeltaStatus.MODIFIED

        # A significant node contributes a difference to the blob or path
        significant = self.status != DeltaStatus.UNMODIFIED

        self.sealed = True
        self.ancestorBlobId = ancestorBlobId

        if significant:
            # Look at parents if we're significant
            parents = commit.parents
            if len(parents) > 1:
                if len(parents) > 2:
                    raise NotImplementedError(f"Octopus merge unsupported ({id7(commit)})")
                parent1 = parents[1]
                frontier.insert(0, (self, parent1))

        return significant


@_dataclasses.dataclass
class BlameLine:
    traceNode: TraceNode
    text: str


class Blame:
    binary: bool
    lines: list[BlameLine]

    def __init__(self, node: TraceNode):
        sentinel = BlameLine(node, "$$$BOGUS$$$")
        self.lines = [sentinel]
        self.binary = False

    @property
    def traceNode(self):
        return self.lines[0].traceNode

    def toPlainText(self, repo: Repo):  # pragma: no cover (for debugging)
        from datetime import datetime

        dateNow = datetime.now()
        result = ""

        for i, blameLine in enumerate(self.lines):
            node = blameLine.traceNode

            if node.commitId == UC_FAKEID:
                date = dateNow
                author = "Not Committed Yet"
            else:
                commit = repo[node.commitId].peel(Commit)
                author = commit.author.name
                date = datetime.fromtimestamp(commit.author.time)

            strDate = date.strftime("%Y-%m-%d")
            result += f"{id7(node.commitId)} {node.path:20} ({author:20} {strDate} {i}) {blameLine.text.rstrip()}\n"

        return result


BlameCollection = dict[Oid, Blame]


class Trace:
    head: TraceNode
    tail: TraceNode
    count: int

    def __init__(self, path: str):
        self.head = TraceNode(path, NULL_OID, NULL_OID, level=-1, sealed=True)
        self.tail = self.head
        self.count = 0

    def __len__(self):
        return self.count

    def __bool__(self):
        return self.count != 0

    def __contains__(self, node: TraceNode) -> bool:
        if node is self.head:
            return True
        for candidate in self:
            if node is candidate:
                return True
        return False

    @property
    def first(self):
        if self.head is self.tail:
            raise IndexError("empty trace")
        return self.head.llNext

    def insert(self, after: TraceNode, node: TraceNode):
        assert after
        assert after is not node
        assert not node.llPrev
        assert not node.llNext

        if APP_DEBUG:  # expensive!
            assert after in self, "inserting after a node that's not in the LL"
            assert node not in self, "node to insert is already in the LL"

        afterNext = after.llNext

        node.llNext = after.llNext
        node.llPrev = after
        after.llNext = node

        if after is self.tail:
            assert not afterNext
            self.tail = node
        else:
            afterNext.llPrev = node

        self.count += 1
        assert self.count >= 0

        if APP_DEBUG:  # expensive!
            assert self.allCommitsUnique(), "duplicate commits in LL"

    def unlink(self, node: TraceNode):
        if APP_DEBUG:  # expensive!
            assert node in self, "unlinking a node that's not in the LL"

        assert node is not self.head, "can't remove head sentinel"
        if node is self.tail:
            self.tail = node.llPrev

        assert node.llPrev, "only head may have null llPrev"
        node.llPrev.llNext = node.llNext

        if node.llNext:
            node.llNext.llPrev = node.llPrev

        self.count -= 1
        assert self.count >= 0

        node.llNext = None
        node.llPrev = None

    def allCommitsUnique(self):
        return len(set(n.commitId for n in self)) == len(self)

    class TraceNodeIterator:
        def __init__(self, ll: Trace, reverse=False):
            self.reverse = reverse
            if reverse:
                self.next = ll.tail
                self.end = ll.head
            else:
                self.next = ll.head.llNext
                self.end = None

        def __iter__(self) -> Iterator[TraceNode]:
            return self

        def __next__(self) -> TraceNode:
            node = self.next
            if node is self.end:
                raise StopIteration()
            self.next = node.llPrev if self.reverse else node.llNext
            return node

    def __iter__(self) -> Iterator[TraceNode]:
        return Trace.TraceNodeIterator(self)

    def reverseIter(self):
        return Trace.TraceNodeIterator(self, reverse=True)

    def nodeForCommit(self, oid: Oid):
        for node in self:
            if node.commitId == oid:
                return node
        raise KeyError("commit is not in trace")

    def dump(self):
        for node in self:
            print(str(node))


def _getBlob(path: str, tree: Tree, treeAbove: Tree | None, knownBlobId: Oid) -> tuple[str, Oid]:
    try:
        # Most common case: the path is in the commit's tree.
        return path, tree[path].id
    except KeyError:
        # Path missing from this commit's tree.
        pass

    # No treeAbove in the case of a new branch that we just popped off the frontier.
    # If we get here in this case, then the new branch is useless.
    if treeAbove is None:
        return "", NULL_OID

    # Did the commit above rename the file?
    diff = tree.diff_to_tree(treeAbove, DiffOption.NORMAL, 0, 0)

    # If we're lucky, the commit has renamed the file without modifying it.
    # (This lets us bypass find_similar and save a ton of time.)
    adds, dels = 0, 0
    for delta in diff.deltas:
        if delta.status == DeltaStatus.DELETED:
            dels += 1
            if delta.old_file.id == knownBlobId:
                # Perfect match for the blob we're looking for
                path = delta.old_file.path
                return path, knownBlobId
        elif delta.status == DeltaStatus.ADDED:
            adds += 1

    # For a rename to occur, we need at least an add and a del.
    if adds == 0 or dels == 0:
        if APP_DEBUG:  # Make sure we haven't missed a rename (expensive check!)
            diff.find_similar()  # slow!
            assert DeltaStatus.RENAMED not in (d.status for d in diff.deltas)
        return "", NULL_OID

    # Fall back to find_similar. Slow!
    diff.find_similar()
    for delta in diff.deltas:
        if delta.new_file.path == path and delta.status == DeltaStatus.RENAMED:
            # It's a rename
            path = delta.old_file.path
            return path, tree[path].id

    # We're past the commit that created this file. Bail from the branch.
    return "", NULL_OID


def _dummyProgressCallback(n: int):
    pass


def traceFile(
        topPath: str,
        topCommit: Commit,
        skimInterval=0,
        maxLevel=0x3FFFFFFF,
        progressCallback=_dummyProgressCallback,
) -> Trace:
    ll = Trace(topPath)
    frontier: list[tuple[TraceNode, Commit]] = [(ll.head, topCommit)]
    knownBlobs: dict[Oid, Oid] = {}
    numCommits = 0

    progressCallback(0)
    timeStart = time.perf_counter()

    # Outer loop: Pop branch off frontier
    while frontier:
        node, commit = frontier.pop(0)
        path = node.path
        level = node.level + 1

        assert node is ll.head or node.llPrev, "dangling node in frontier!"

        if commit.id in knownBlobs:
            continue

        if level > maxLevel:
            continue

        # TODO: Deleted file in seed
        treeAbove = None
        commitAbove = None
        newBranch = True
        skipSkimming = 0

        # Inner loop: Walk branch
        while True:
            assert (not newBranch) == (node.level == level)
            assert newBranch == node.sealed
            assert commit.id not in knownBlobs, "commit already visited!"

            numCommits += 1
            tree = commit.tree

            if numCommits % TRACE_PROGRESS_INTERVAL == 0:
                progressCallback(len(ll))

            path, blobId = _getBlob(path, tree, treeAbove, node.blobId)
            useful = blobId != node.blobId
            knownBlobs[commit.id] = blobId

            if blobId == NULL_OID:
                # Blob added here
                assert newBranch or treeAbove is not None
                break  # bail from the branch
            if not newBranch and path != node.path:
                node.status = DeltaStatus.RENAMED
                useful = True

            if newBranch or useful:
                nodeAbove = node
                node = TraceNode(path=path, commitId=commit.id, blobId=blobId, level=level)
                ll.insert(nodeAbove, node)
                if not newBranch:  # Seal node above
                    significant = nodeAbove.seal(commit=commitAbove, frontier=frontier, ancestorBlobId=blobId)
                    assert significant
                newBranch = False
                knownBlobs[commit.id] = node.blobId
            else:
                assert node.level == level
                node.commitId = commit.id

            # We own the node past this point
            assert not newBranch

            commitAbove = commit
            treeAbove = tree

            # Optional: Skim over irrelevant portions of the branch
            if skipSkimming > 0:
                # Don't skim yet
                skipSkimming -= 1
            elif level == 0 and skimInterval:
                # Try to skim this branch (see docstring in the function for more info)
                commit, skipSkimming = _skimBranch(node, commit, knownBlobs, skimInterval)
                if skipSkimming == 0:
                    commitAbove = commit
                    treeAbove = commit.tree

            # Get next commit in branch
            try:
                commit = commit.parents[0]
            except IndexError:
                # Initial commit
                blobId = NULL_OID
                break  # bail from the branch

            # Don't revisit a commit
            try:
                blobId = knownBlobs[commit.id]  # will be used as ancestor blob for sealing the node
                break  # this commit has already been seen, bail from the branch
            except KeyError:
                # Commit hasn't been visited yet
                pass

        # Seal last node in branch
        if not newBranch:
            assert commitAbove.id in knownBlobs
            significant = node.seal(commit=commitAbove, frontier=frontier, ancestorBlobId=blobId)
            if not significant:
                ll.unlink(node)

    # Scrap useless revisions: Traverse LL from the tail up;
    # Cull nodes with blobs that are known to show up at a smaller ancestry level
    # closer to the tail. For example:
    # (level=3) │ │ ┿   blob2 - Keep
    # (level=2) │ │ ┿   blob1 - Cull
    # (level=1) │ ┿─╯   blob1 - Cull
    # (level=0) ┿─╯     blob1 - Keep
    #           ├─╮
    # (level=1) │ ┷     blob1 - Keep - Earliest appearance of blob1
    knownLevels = {}
    for node in ll.reverseIter():
        assert node.sealed
        assert node.status != TraceNode.DefaultStatus
        if knownLevels.get(node.blobId, 0x3FFFFFFF) > node.level:
            knownLevels[node.blobId] = node.level
        elif node.status == DeltaStatus.MODIFIED:
            ll.unlink(node)
        else:
            assert not (node.status == DeltaStatus.MODIFIED and node.blobId == node.ancestorBlobId)

    if APP_DEBUG:
        assert ll.allCommitsUnique(), "some duplicates!!"

    if progressCallback:
        progressCallback(len(ll))

    timeTaken = int(1000 * (time.perf_counter() - timeStart))
    _logger.debug(f"{numCommits} commits traced; {len(ll)} were relevant. ({timeTaken} ms)")
    return ll


def _skimBranch(node: TraceNode, topCommit: Commit, knownBlobs: dict[Oid, Oid], interval: int):
    """
    Time spent tracing a file is dominated by looking up blobs by path in trees
    (in a lucky scenario where we never have to call Diff.find_similar()).

    In a long-lived repo, it's likely that the file we're tracing doesn't
    change blobs that often. This function attempts to skip irrelevant commits
    so we can space out blob lookups.

    We rewind the branch by `interval` commits (starting from `topCommit`)
    without looking at the trees that are skimmed over. We then look up the
    file's blob after rewinding.

    If we land on a blob that matches the one in `topCommit`, it's reasonable
    to assume that the file hasn't changed in the interval. Otherwise, we
    discard the rewind operation.

    Note that this technique may cause some revisions to be missing from the
    trace if the file changes contents within the interval, but reverts to
    identical blobs at both ends of the interval.
    """

    commit = topCommit
    assert commit.id == node.commitId
    assert node.level == 0

    skimmed = {node.commitId: node.blobId}
    try:
        for _step in range(interval):
            parents = commit.parents
            if len(parents) > 1:
                raise LookupError()
            commit = parents[0]
            skimmed[commit.id] = node.blobId
        tree = commit.tree
        blobId = tree[node.path].id
        if blobId == node.blobId:
            node.commitId = commit.id  # Important! Bring current node to this commit
            knownBlobs.update(skimmed)  # Mark all skimmed commits as visited
            return commit, 0
    except LookupError:
        pass

    return topCommit, len(skimmed)


def blameFile(
        repo: Repo,
        ll: Trace,
        topCommitId: Oid = NULL_OID,
        progressCallback=_dummyProgressCallback
) -> BlameCollection:
    # Get tail blob
    blobIdA = ll.tail.blobId
    blobA = repo[blobIdA].peel(Blob)

    # Prep blame
    blameCollection: BlameCollection = {}

    # Traverse trace from tail up
    i = 0
    revisionNumber = 1
    for node in ll.reverseIter():
        i += 1
        if i % BLAME_PROGRESS_INTERVAL == 0:
            progressCallback(i)

        assert node.sealed
        assert node is not ll.head, "head sentinel is fake"

        blobIdA = node.ancestorBlobId
        blobIdB = node.blobId

        # Skip nodes that don't contribute a new blob
        if blobIdA == blobIdB:
            assert node.status == DeltaStatus.RENAMED
            continue
        if blobIdB in blameCollection:
            _logger.debug(f"Not blaming node (same blob contributed earlier): {node}")
            continue

        # Assign informal revision number
        node.revisionNumber = revisionNumber
        revisionNumber += 1

        blobB = repo[blobIdB]
        assert isinstance(blobB, Blob)

        if blobIdA == NULL_OID:
            assert node.status == DeltaStatus.ADDED
            blameCollection[blobIdB] = _makeInitialBlame(node, blobB)
            continue
        elif blobA.id == blobIdA:
            # Reuse previous blob (speedup, common case)
            pass
        else:
            blobA = repo[blobIdA]

        assert isinstance(blobA, Blob)
        patch = blobA.diff(blobB)

        blameA = blameCollection[blobIdA]
        blameB = _blamePatch(patch, blameA, node)

        if APP_DEBUG and not blameB.binary:
            def countLines(data: bytes):
                return data.count(b'\n') + (0 if data.endswith(b'\n') else 1)
            assert len(blameB.lines) - 1 == countLines(blobB.data)

        # Enrich blame with more precise information from a merged branch
        if (not blameB.binary
                and node.llNext
                and node.llNext.level == node.level + 1
                and node.llNext.blobId != blobIdA):
            if APP_DEBUG:  # Very expensive assertion that will slow down the blame significantly
                assert repo.descendant_of(node.commitId, node.llNext.commitId)
            olderBlob = repo[node.llNext.blobId]
            olderBlame = blameCollection[node.llNext.blobId]
            olderPatch = olderBlob.diff(blobB)
            _overrideBlame(olderPatch, olderBlame, blameB)

        # Save this blame
        blameCollection[blobIdB] = blameB

        # Save new blob for next iteration, might save us a lookup if it's the next blob's ancestor
        blobA = blobB

        # See if stop
        if topCommitId == node.commitId:
            break

    return blameCollection


def _makeInitialBlame(node: TraceNode, blob: Blob) -> Blame:
    blame = Blame(node)

    data = blob.data
    if b'\0' in data:
        blobText = "$$$BINARY_PLACEHOLDER_LINE$$$"
        blame.binary = True
    else:
        blobText = data.decode("utf-8", errors="replace")

    blame.lines.extend(BlameLine(node, line) for line in blobText.splitlines(keepends=True))
    return blame


def _blamePatch(patch: Patch, blameA: Blame, nodeB: TraceNode) -> Blame:
    blameB = Blame(nodeB)
    blameB.binary = patch.delta.is_binary

    for lineA, lineB, diffLine in _traversePatch(patch, len(blameA.lines)):
        assert lineB == len(blameB.lines)
        if lineA:  # context line
            blameB.lines.append(blameA.lines[lineA])
        else:  # new line originating in B
            blameB.lines.append(BlameLine(nodeB, diffLine.content))

    return blameB


def _overrideBlame(patch: Patch, blameA: Blame, blameB: Blame):
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


def makeWorkdirMockCommit(repo: Repo, path: str) -> MockCommit:
    headCommit = repo.head.peel(Commit)
    workdirBlobId = repo.create_blob_fromworkdir(path)
    workdirBlob = repo[workdirBlobId]
    workdirMock = MockCommit(UC_FAKEID, [headCommit.id])
    workdirMock.parents = [headCommit]
    workdirMock.tree = {path: workdirBlob}
    return workdirMock


def traceCommandLineTool():  # pragma: no cover
    from argparse import ArgumentParser
    from timeit import timeit
    from sys import stderr

    parser = ArgumentParser(description="GitFourchette trace/blame tool")
    parser.add_argument("path", help="File path")
    parser.add_argument("-t", "--trace", action="store_true", help="Print trace (file history)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Don't print annotations")
    parser.add_argument("-s", "--skim", action="store", type=int, default=0, help="Skimming interval")
    parser.add_argument("-m", "--max-level", action="store", type=int, default=0x3FFFFFFF, help="Max breadth level")
    parser.add_argument("-b", "--benchmark", action="store_true", help="Benchmark mode")
    args = parser.parse_args()

    _logging.basicConfig(level=BENCHMARK_LOGGING_LEVEL)
    _logging.captureWarnings(True)

    repo = Repo(args.path)
    relPath = Path(args.path)
    with suppress(ValueError):
        relPath = relPath.relative_to(repo.workdir)

    topCommit = makeWorkdirMockCommit(repo, str(relPath))

    with Benchmark("Trace"):
        trace = traceFile(str(relPath), topCommit, skimInterval=args.skim, maxLevel=args.max_level,
                          progressCallback=lambda n: print(f"\rTrace {n}...", end="", file=stderr))

    if args.trace:
        trace.dump()

    with Benchmark("Blame"):
        blameCollection = blameFile(repo, trace, topCommit.id,
                                    progressCallback=lambda n: print(f"\rBlame {n}...", end="", file=stderr))

    if not args.quiet:
        rootBlame = blameCollection[trace.first.blobId]
        print(rootBlame.toPlainText(repo))

    if args.benchmark:
        global APP_DEBUG
        APP_DEBUG = False
        N = 10
        print("Benchmarking...")
        elapsed = timeit(lambda: traceFile(str(relPath), topCommit, skimInterval=args.skim, maxLevel=args.max_level), number=N)
        print(f"Trace: {elapsed*1000/N:.0f} ms avg")
        elapsed = timeit(lambda: blameFile(repo, trace, topCommit.id), number=N)
        print(f"Blame: {elapsed*1000/N:.0f} ms avg")


if __name__ == '__main__':
    traceCommandLineTool()
