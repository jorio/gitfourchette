# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import time
from collections.abc import Callable
import logging

from gitfourchette.appconsts import *
from gitfourchette.blame.tracenode import TraceNode
from gitfourchette.graph import MockCommit
from gitfourchette.porcelain import *
from gitfourchette.repomodel import UC_FAKEID

_logger = logging.getLogger(__name__)

TRACE_PROGRESS_INTERVAL = 200 if not APP_TESTMODE else 1


class Trace:
    """
    Trace relevant commits in a file's history.
    """

    first: TraceNode
    numRelevantNodes: int
    visitedCommits: dict[Oid, TraceNode]

    @staticmethod
    def dummyProgressCallback(n: int):
        pass

    def __init__(
            self,
            topPath: str,
            topCommit: Commit,
            skimInterval: int = 0,
            maxLevel: int = 0x3FFFFFF,
            progressCallback: Callable[[int], None] = dummyProgressCallback,
    ):
        self._branchFrontier = []
        self.visitedCommits = {}
        self.numRelevantNodes = -1  # deduct 1 for mock starter

        mockStarter = MockCommit(NULL_OID, [topCommit.id])
        mockStarter.parents = [topCommit]
        mockStarter.tree = None
        nodeStarter = TraceNode(topPath, mockStarter, NULL_OID, level=0)
        self._branchFrontier.append((nodeStarter, 0))

        progressCallback(0)
        progressTicks = 0
        timeStart = time.perf_counter()

        while self._branchFrontier:
            # Pop a branch off the frontier
            node, pNum = self._branchFrontier.pop(0)

            # Skip this branch if it's beyond the breadth limit
            if node.level + min(1, pNum) > maxLevel:
                continue

            # Walk commits on the branch, top to bottom (newest to oldest), until one of these dead-ends:
            # - the file was created in the current commit (no need to explore any older commits)
            # - reached the branching point off a branch that we've already explored
            # - the current commit has no parents (initial commit)
            while node is not None:
                if progressTicks % TRACE_PROGRESS_INTERVAL == 0:
                    progressCallback(self.numRelevantNodes)
                progressTicks += 1

                node = self._walkBranch(node, pNum)
                pNum = 0

        del self._branchFrontier

        assert len(nodeStarter.parents) == 1
        self.first = nodeStarter.parents[0]

        timeTaken = int(1000 * (time.perf_counter() - timeStart))
        _logger.debug(f"{len(self.visitedCommits)} commits visited, {len(self)} were relevant ({timeTaken} ms)")

    def _walkBranch(self, nodeAbove: TraceNode, parentNum: int = 0):
        assert parentNum >= 0

        # Optional: Skim over irrelevant portions of the branch
        # if skipSkimming > 0:
        #     # Don't skim yet
        #     skipSkimming -= 1
        # elif level == 0 and skimInterval:
        #     # Try to skim this branch (see docstring in the function for more info)
        #     commit, skipSkimming = _skimBranch(node, commit, knownBlobs, skimInterval)
        #     if skipSkimming == 0:
        #         commitAbove = commit
        #         treeAbove = commit.tree

        # Get next commit in branch
        try:
            commitBelow = nodeAbove.commit.parents[parentNum]
        except IndexError:  # Initial commit
            assert parentNum == 0
            assert not nodeAbove.sealed
            nodeAbove.status = DeltaStatus.ADDED
            nodeAbove.sealed = True
            self.numRelevantNodes += 1
            return None  # bail from branch

        # Compare
        treeAbove = nodeAbove.commit.tree
        treeBelow = commitBelow.tree
        pathBelow, blobIdBelow = _getBlob(nodeAbove.path, treeBelow, treeAbove, nodeAbove.blobId)
        cmpStatus = nodeAbove.compare(pathBelow, blobIdBelow)
        commitIsRelevant = cmpStatus != DeltaStatus.UNMODIFIED

        # Look up branching point on parent branch (if any)
        # (if found, we're here:)   │ ┿  <-- nodeAbove
        #                           ┿─╯  <-- nodeBelow
        nodeBelow = self.visitedCommits.get(commitBelow.id, None)

        # See if this commit is relevant
        if not commitIsRelevant and not nodeAbove.sealed:
            # If known parent on visited branch: don't revisit
            if nodeBelow is not None:
                # Scrub passthrough node from visitedCommits
                for oid in nodeAbove.subbingInForCommits:
                    assert self.visitedCommits[oid] is nodeAbove
                    self.visitedCommits[oid] = nodeBelow
                # This node is useless now
                nodeAbove.unlinkPassthrough(replaceWith=nodeBelow)
                return None

            # Commit is not relevant.
            # Move this node to the next commit on the branch.
            assert not nodeAbove.sealed, "can't change the commit in a sealed node!"
            assert pathBelow == nodeAbove.path
            assert blobIdBelow == nodeAbove.blobId
            nodeBelow = nodeAbove
            nodeBelow.commit = commitBelow
        else:
            if not commitIsRelevant:
                assert nodeAbove.sealed
                assert parentNum != 0

            # Commit is relevant
            if parentNum == 0:
                assert not nodeAbove.sealed
                nodeAbove.status = cmpStatus
                nodeAbove.sealed = True
                self.numRelevantNodes += 1
            assert nodeAbove.sealed

            # Push extra parents onto frontier
            if parentNum == 0:
                numParents = len(nodeAbove.commit.parents)
                if numParents == 2:
                    self._branchFrontier.insert(0, (nodeAbove, 1))
                elif numParents >= 3:
                    raise NotImplementedError("Octopus merge unsupported")

            # Bail from the branch if we added the file here
            if blobIdBelow == NULL_OID:
                assert nodeAbove.sealed
                # assert nodeAbove.status == DeltaStatus.ADDED, f"{nodeAbove} isn't 'A'? (above {id7(commitBelow.id)})"
                return None

            # If known parent on visited branch: don't revisit
            if nodeBelow is not None:
                assert nodeBelow.status != TraceNode.GarbageStatus
                assert nodeBelow.sealed
                if nodeBelow.blobId != blobIdBelow:
                    _logger.warning(f"{nodeAbove} disagrees with parent branch {nodeBelow} on a renamed file")
                nodeAbove.addParent(nodeBelow)  # merge into it
                return None  # bail from the branch

            # Create new transient node below to keep exploring this branch linearly
            levelBelow = nodeAbove.level + min(1, parentNum)
            nodeBelow = TraceNode(path=pathBelow, commit=commitBelow, blobId=blobIdBelow, level=levelBelow)
            nodeAbove.addParent(nodeBelow)

        if commitBelow.id in self.visitedCommits:
            assert commitBelow.id not in self.visitedCommits, f"commit {id7(commitBelow)} visited twice"
        self.visitedCommits[commitBelow.id] = nodeBelow
        nodeBelow.subbingInForCommits.append(commitBelow.id)

        return nodeBelow

    def __len__(self):
        return self.numRelevantNodes

    def nodeForCommit(self, commitId: Oid) -> TraceNode:
        return self.visitedCommits[commitId]

    def dump(self):
        from gitfourchette.graph import GraphWeaver, GraphDiagram
        _graph, graphWeaver = GraphWeaver.newGraph()
        diagram = GraphDiagram()
        for node in self.first.walkGraph():
            parentIds = [parent.commitId for parent in node.parents]
            graphWeaver.newCommit(node.commitId, parentIds)
            y = len(diagram.scanlines)
            diagram.newFrame(graphWeaver.sealCopy(), set(), False)
            diagram.margins[y] = [f"{id7(node.ancestorBlobId)}\u2192{id7(node.blobId)} {str(node)}", node.path]
        print(diagram.bake())

    @staticmethod
    def makeWorkdirMockCommit(repo: Repo, path: str) -> MockCommit:
        headCommit = repo.head.peel(Commit)
        workdirBlobId = repo.create_blob_fromworkdir(path)
        workdirBlob = repo[workdirBlobId]
        workdirMock = MockCommit(UC_FAKEID, [headCommit.id])
        workdirMock.parents = [headCommit]
        workdirMock.tree = {path: workdirBlob}
        return workdirMock


def _getBlob(path: str, tree: Tree, treeAbove: Tree, knownBlobId: Oid) -> tuple[str, Oid]:
    try:
        # Most common case: the path is in the commit's tree.
        return path, tree[path].id
    except KeyError:
        # Path missing from this commit's tree.
        pass

    assert treeAbove is not None

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


