# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging as _logging
import time
from collections.abc import Iterator

from gitfourchette.appconsts import *
from gitfourchette.blame.tracenode import TraceNode
from gitfourchette.graph import MockCommit
from gitfourchette.porcelain import *
from gitfourchette.repomodel import UC_FAKEID

_logger = _logging.getLogger(__name__)

TRACE_PROGRESS_INTERVAL = 200 if not APP_TESTMODE else 1


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
        return len({n.commitId for n in self}) == len(self)

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


def makeWorkdirMockCommit(repo: Repo, path: str) -> MockCommit:
    headCommit = repo.head.peel(Commit)
    workdirBlobId = repo.create_blob_fromworkdir(path)
    workdirBlob = repo[workdirBlobId]
    workdirMock = MockCommit(UC_FAKEID, [headCommit.id])
    workdirMock.parents = [headCommit]
    workdirMock.tree = {path: workdirBlob}
    return workdirMock
