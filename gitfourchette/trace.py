# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Trace the relevant commits in a file's history and annotate (blame) it.

This can be faster than libgit2's blame (as of libgit2 1.8), especially if you
need annotations at all points of the file's history.

CAVEAT: Octopus merges not supported yet.
"""

from __future__ import annotations as _annotations

import bisect
import dataclasses as _dataclasses
import logging as _logging
from collections.abc import Generator
from contextlib import suppress
from pathlib import Path

from gitfourchette.porcelain import *
from gitfourchette.settings import DEVDEBUG
from gitfourchette.toolbox.benchmark import BENCHMARK_LOGGING_LEVEL, Benchmark

_logger = _logging.getLogger(__name__)

PLACEHOLDER_OID = Oid(hex='E' * 40)


@_dataclasses.dataclass
class TraceNode:
    path: str
    commitId: Oid  # earliest commit in the branch where this blob shows up
    blobId: Oid
    level: int  # branch ancestry level (breadth distance from root branch)
    status: DeltaStatus = DeltaStatus.MODIFIED
    llPrev: TraceNode | None = None
    llNext: TraceNode | None = None
    sealed: bool = False
    ancestorBlobId: Oid = PLACEHOLDER_OID
    likelyMerge: bool = False

    def __str__(self):
        status_char = self.status.name[0]
        indent = ' ' * 4 * self.level
        return f"({self.level},{id7(self.commitId)},{id7(self.blobId)},{status_char}) {indent}{self.path}"

    def __repr__(self):
        status_char = self.status.name[0]
        return f"(level={self.level}, commit={id7(self.commitId)}, blob={id7(self.ancestorBlobId)}→{id7(self.blobId)}, status={status_char}, path={self.path})"

    def seal(self, commit, frontier, ancestorBlobId):
        assert not self.sealed
        assert commit
        assert commit.id == self.commitId

        parents = commit.parents
        if len(parents) > 1:
            if len(parents) > 2:
                raise NotImplementedError(f"Octopus merge unsupported ({id7(commit)})")
            parent1 = parents[1]
            # Push to frontier as a stack (grouped by levels)
            # so that the commit closest to the tail gets popped first.
            insPoint = bisect.bisect_left(frontier, self.level, key=lambda item: item[0].level)
            frontier.insert(insPoint, (self, parent1))
            self.likelyMerge = True

        if ancestorBlobId == NULL_OID:
            assert self.status == DeltaStatus.MODIFIED  # should not be changed from default
            self.status = DeltaStatus.ADDED

        self.sealed = True
        self.ancestorBlobId = ancestorBlobId


@_dataclasses.dataclass
class BlameLine:
    traceNode: TraceNode
    text: str


Blame = list[BlameLine]
BlameCollection = dict[Oid, Blame]


class Trace:
    head: TraceNode
    tail: TraceNode
    count: int

    def __init__(self, path: str):
        self.head = TraceNode(path, NULL_OID, NULL_OID, level=-1, status=DeltaStatus.CONFLICTED, sealed=True)
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

        if DEVDEBUG:  # expensive!
            assert after in self
            assert node not in self

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

    def unlink(self, node: TraceNode):
        if DEVDEBUG:  # expensive!
            assert node in self

        assert node is not self.head, "can't remove head sentinel"
        if node is self.tail:
            self.tail = node.llPrev

        assert node.llPrev, "only head may have null llPrev"
        node.llPrev.llNext = node.llNext

        if node.llNext:
            node.llNext.llPrev = node.llPrev

        self.count -= 1
        assert self.count >= 0

    class Iterator:
        def __init__(self, ll: Trace, reverse=False):
            self.reverse = reverse
            if reverse:
                self.next = ll.tail
                self.end = ll.head
            else:
                self.next = ll.head.llNext
                self.end = None

        def __iter__(self):
            return self

        def __next__(self) -> TraceNode:
            node = self.next
            if node is self.end:
                raise StopIteration()
            self.next = node.llPrev if self.reverse else node.llNext
            return node

    def __iter__(self):
        return Trace.Iterator(self)

    def reverseIter(self):
        return Trace.Iterator(self, reverse=True)

    def indexOfCommit(self, oid: Oid):
        for i, node in enumerate(self):
            if node.commitId == oid:
                return i
        raise ValueError("commit is not in trace")

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

    if not treeAbove:
        # Bail from useless branch.
        return path, NULL_OID

    # Did the commit above rename the file?
    diff = tree.diff_to_tree(treeAbove, DiffOption.NORMAL, 0, 0)

    # If we're lucky, the commit has renamed the file without modifying it.
    # (This lets us bypass find_similar and save a ton of time.)
    for delta in diff.deltas:
        if delta.old_file.id == knownBlobId:
            path = delta.old_file.path
            return path, knownBlobId

    # Fall back to find_similar. Slow!
    diff.find_similar()
    for delta in diff.deltas:
        if delta.new_file.path == path and delta.status == DeltaStatus.RENAMED:
            # It's a rename
            path = delta.old_file.path
            return path, tree[path].id

    # We're past the commit that created this file. Bail from the branch.
    return path, NULL_OID


def traceFile(topPath: str, topCommit: Commit, skimInterval=0, maxLevel=0x3FFFFFFF) -> Trace:
    ll = Trace(topPath)
    frontier = [(ll.head, topCommit)]
    visited: dict[Oid, TraceNode] = {}
    knownBlobIds = set()
    numCommits = 0

    # Outer loop: Pop branch off frontier
    while frontier:
        node, commit = frontier.pop(0)
        path = node.path
        level = node.level + 1

        if commit.id in visited:
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
            assert commit.id not in visited, "commit already visited!"

            numCommits += 1
            tree = commit.tree
            visited[commit.id] = node

            path, blobId = _getBlob(path, tree, treeAbove, node.blobId)
            if blobId == NULL_OID:
                # Blob added here
                break  # bail from the branch
            if not newBranch and path != node.path:
                node.status = DeltaStatus.RENAMED

            if newBranch and blobId != node.blobId and blobId in knownBlobIds:
                # Branch doesn't contribute the blob: prune it.
                # Required for proper blaming of cpython/Lib/test/test_urllib.py
                assert level > 0
                assert node.likelyMerge
                # Allow re-visiting this commit further down the graph.
                # We might need it if this branch is merged by another earlier commit,
                # at a "wider" level.
                del visited[commit.id]
                break

            if newBranch or blobId != node.blobId or node.status == DeltaStatus.RENAMED:
                nodeAbove = node
                node = TraceNode(path=path, commitId=commit.id, blobId=blobId, level=level)
                ll.insert(nodeAbove, node)
                if not newBranch:  # Seal node above
                    nodeAbove.seal(commit=commitAbove, frontier=frontier, ancestorBlobId=blobId)
                newBranch = False
                knownBlobIds.add(blobId)
                visited[commit.id] = node
            else:
                assert node.level == level
                node.commitId = commit.id

            # We own the node past this point
            assert not newBranch

            commitAbove = commit
            treeAbove = tree

            if skipSkimming > 0:
                # Don't skim yet
                skipSkimming -= 1
            elif level == 0 and skimInterval:
                # Try to skim this branch (see docstring in the function for more info)
                commit, skipSkimming = _skimBranch(node, commit, visited, skimInterval)
                if skipSkimming == 0:
                    commitAbove = commit
                    treeAbove = commit.tree

            try:
                # Get next commit in branch
                commit = commit.parents[0]
            except IndexError:
                # Initial commit
                blobId = NULL_OID
                break  # bail from the branch

            if commit.id in visited:
                # Don't revisit
                visitedNode = visited[commit.id]
                assert visitedNode.blobId != NULL_OID
                assert visitedNode.level <= node.level
                blobId = visitedNode.blobId
                break  # bail from the branch

        # Seal last node in branch
        if not newBranch:
            assert commitAbove.id in visited
            node.seal(commit=commitAbove, frontier=frontier, ancestorBlobId=blobId)

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
        if knownLevels.get(node.blobId, 0x3FFFFFFF) > node.level:
            knownLevels[node.blobId] = node.level
        elif node.status == DeltaStatus.MODIFIED:
            ll.unlink(node)
        else:
            assert not (node.status == DeltaStatus.MODIFIED and node.blobId == node.ancestorBlobId)

    _logger.debug(f"{numCommits} commits traced; {len(ll)} were relevant.")
    return ll


def _skimBranch(node: TraceNode, topCommit: Commit, visited: dict[Oid, TraceNode], interval: int):
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

    skimmed = {node.commitId: node}
    try:
        for _step in range(interval):
            parents = commit.parents
            if len(parents) > 1:
                raise LookupError()
            commit = parents[0]
            skimmed[commit.id] = node
        tree = commit.tree
        blobId = tree[node.path].id
        if blobId == node.blobId:
            node.commitId = commit.id  # Important! Bring current node to this commit
            visited.update(skimmed)  # Mark all skimmed commits as visited
            return commit, 0
    except LookupError:
        pass

    return topCommit, len(skimmed)


def blameFile(repo: Repo, ll: Trace, topCommitId: Oid = NULL_OID) -> BlameCollection:
    def countLines(data: bytes):
        return data.count(b'\n') + (0 if data.endswith(b'\n') else 1)

    # Prime the iterator: Skip the tail
    llIter = ll.reverseIter()
    tail = next(llIter)
    assert tail is ll.tail

    # Get tail blob
    blobIdA = tail.blobId
    blobA = repo[blobIdA].peel(Blob)

    # Prep blame
    blameCollection: BlameCollection = {blobIdA: _makeInitialBlame(tail, blobA)}

    # Traverse trace from tail up
    for node in llIter:
        assert node.sealed

        # Stop at head sentinel
        if node is ll.head:
            assert node.commitId == NULL_OID  # assume head sentinel isn't a real commit
            break
        assert node is not ll.tail

        blobIdA = node.ancestorBlobId
        blobIdB = node.blobId

        # Skip nodes that don't contribute a new blob
        if blobIdA == blobIdB:
            assert node.likelyMerge or node.status == DeltaStatus.RENAMED
            _logger.debug(f"Not blaming node (no-op): {node}")
            continue
        if blobIdB in blameCollection:
            _logger.debug(f"Not blaming node (same blob contributed earlier): {node}")
            continue

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

        if DEVDEBUG:
            assert len(blameB) - 1 == countLines(blobB.data)

        if node.llNext and node.llNext.level == node.level + 1 and node.llNext.blobId != blobIdA:
            if DEVDEBUG:  # Very expensive assertion that will slow down the blame significantly
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


def _makeInitialBlame(node: TraceNode, blob: Blob) -> list[BlameLine]:
    line0 = BlameLine(node, "$$$BOGUS$$$")
    blobText: str = blob.data.decode("utf-8", errors="replace")
    blame = [line0]
    blame.extend(BlameLine(node, line) for line in blobText.splitlines(keepends=True))
    return blame


def _blamePatch(patch: Patch, blameA: list[BlameLine], nodeB: TraceNode) -> Blame:
    blameB = [blameA[0]]  # copy sentinel

    for lineA, lineB, diffLine in _traversePatch(patch, len(blameA)):
        assert lineB == len(blameB)
        if lineA:  # context line
            blameB.append(blameA[lineA])
        else:  # new line originating in B
            blameB.append(BlameLine(nodeB, diffLine.content))

    return blameB


def _overrideBlame(patch: Patch, blameA: list[BlameLine], blameB: list[BlameLine]):
    for lineA, lineB, _dummy in _traversePatch(patch, len(blameA)):
        if lineA:  # context line
            assert blameB[lineB].text == blameA[lineA].text
            blameB[lineB] = blameA[lineA]


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


def traceCommandLineTool():  # pragma: no cover
    from argparse import ArgumentParser
    from datetime import datetime, timezone
    from timeit import timeit

    parser = ArgumentParser(description="GitFourchette trace/blame tool")
    parser.add_argument("path", help="File path")
    parser.add_argument("-d", "--debug", action="store_true", help="Enable expensive assertions")
    parser.add_argument("-t", "--trace", action="store_true", help="Print trace (file history)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Don't print annotations")
    parser.add_argument("-s", "--skim", action="store", type=int, default=0, help="Skimming interval")
    parser.add_argument("-m", "--max-level", action="store", type=int, default=0x3FFFFFFF, help="Max breadth level")
    parser.add_argument("-b", "--benchmark", action="store_true", help="Benchmark mode")
    args = parser.parse_args()

    _logging.basicConfig(level=BENCHMARK_LOGGING_LEVEL)
    _logging.captureWarnings(True)

    global DEVDEBUG
    DEVDEBUG = args.debug

    repo = Repo(args.path)
    relPath = Path(args.path)
    with suppress(ValueError):
        relPath = relPath.relative_to(repo.workdir)

    topCommit = repo.head.peel(Commit)

    with Benchmark("Trace"):
        trace = traceFile(str(relPath), topCommit, skimInterval=args.skim, maxLevel=args.max_level)

    if args.trace:
        trace.dump()

    with Benchmark("Blame"):
        blame = blameFile(repo, trace, topCommit.id)

    if not args.quiet:
        for i, blameLine in enumerate(blame[trace.first.blobId]):
            traceNode = blameLine.traceNode
            commit = repo[traceNode.commitId].peel(Commit)
            date = datetime.fromtimestamp(commit.author.time, timezone.utc).strftime("%Y-%m-%d")
            print(f"{id7(traceNode.commitId)} {traceNode.path:20} ({commit.author.name:20} {date} {i}) {blameLine.text.rstrip()}")

    if args.benchmark:
        DEVDEBUG = False
        N = 10
        print("Benchmarking...")
        elapsed = timeit(lambda: traceFile(str(relPath), topCommit, skimInterval=args.skim, maxLevel=args.max_level), number=N)
        print(f"Trace: {elapsed*1000/N:.0f} ms avg")
        elapsed = timeit(lambda: blameFile(repo, trace, topCommit.id), number=N)
        print(f"Blame: {elapsed*1000/N:.0f} ms avg")


if __name__ == '__main__':
    traceCommandLineTool()
