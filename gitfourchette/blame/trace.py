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
from gitfourchette.blame.blame import blameFile
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
        self.numRelevantNodes = 0

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
            numUnskimmables = 0
            while node is not None:
                if progressTicks % TRACE_PROGRESS_INTERVAL == 0:
                    progressCallback(self.numRelevantNodes)
                progressTicks += 1

                if pNum == 0 and skimInterval > 0:
                    numUnskimmables = self._skimBranch(node, skimInterval, numUnskimmables)

                node = self._walkBranch(node, pNum)
                pNum = 0

        del self._branchFrontier

        # Determine which node to use as the top of the graph.
        # The starter node is useless if it's not subbing in for any commits.
        # In the case of a deletion in the top commit, the starter node is useful
        # because it's been moved to a 'real' commit.
        assert len(nodeStarter.parents) == 1
        if nodeStarter.subbingInForCommits:
            self.first = nodeStarter
            assert self.first.status == DeltaStatus.DELETED
        else:
            self.first = nodeStarter.parents[0]
            assert self.first.children == [nodeStarter]
            self.first.children.clear()
            self.numRelevantNodes -= 1  # we're not using the starter
        assert not self.first.children
        if APP_DEBUG:
            nodeStarterInVisitedCommits = any(vNode is nodeStarter for vNode in self.visitedCommits.values())
            assert nodeStarterInVisitedCommits == (nodeStarter is self.first)

        timeTaken = int(1000 * (time.perf_counter() - timeStart))
        _logger.debug(f"{len(self.visitedCommits)} commits visited, {len(self)} were relevant ({timeTaken} ms)")

    def _walkBranch(self, nodeAbove: TraceNode, parentNum: int = 0):
        assert parentNum >= 0

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
        if nodeAbove.blobId != NULL_OID:
            statusBelow = nodeAbove.compare(pathBelow, blobIdBelow)
        elif blobIdBelow != NULL_OID:
            statusBelow = DeltaStatus.DELETED
            assert pathBelow == nodeAbove.path
        else:
            statusBelow = DeltaStatus.UNMODIFIED
            assert not pathBelow
            pathBelow = nodeAbove.path
        commitIsRelevant = statusBelow != DeltaStatus.UNMODIFIED

        # Look up branching point on parent branch (if any)
        # (if found, we're here:)   │ ┿  <-- nodeAbove
        #                           ┿─╯  <-- nodeBelow
        nodeBelow = self.visitedCommits.get(commitBelow.id, None)

        # See if this commit is relevant
        if not commitIsRelevant and not nodeAbove.sealed:
            # If known parent on visited branch: don't revisit
            if nodeBelow is not None:
                # We're at a branching point: a non-relevant branch (nodeAbove)
                # is branching off nodeBelow, which itself is relevant.
                # Replace nodeAbove with nodeBelow, then discard nodeAbove.
                for oid in nodeAbove.subbingInForCommits:
                    assert self.visitedCommits[oid] is nodeAbove
                    self.visitedCommits[oid] = nodeBelow
                if APP_DEBUG:
                    assert nodeAbove not in self.visitedCommits.values(), f"passthrough {nodeAbove} still appears in visitedCommits"
                # Replace any links to nodeAbove: redirect to nodeBelow instead.
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
                nodeAbove.status = statusBelow
                nodeAbove.sealed = True
                self.numRelevantNodes += 1
            assert nodeAbove.sealed

            # Push extra parents onto frontier
            if parentNum == 0:
                numParents = len(nodeAbove.commit.parents)
                for p in range(numParents - 1, 0, -1):
                    self._branchFrontier.insert(0, (nodeAbove, p))

            # Bail from the branch if we added the file here
            if blobIdBelow == NULL_OID:
                assert nodeAbove.sealed
                return None

            # If known parent on visited branch: don't revisit
            if nodeBelow is not None:
                assert nodeBelow.status != TraceNode.GarbageStatus, f"na={nodeAbove} nb={nodeBelow} (below is garbage)"
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

    def _skimBranch(self, node: TraceNode, interval: int, numUnskimmables: int):
        """
        Time spent tracing a file is dominated by looking up blobs by path in
        trees (in a lucky scenario where we never have to call
        Diff.find_similar()).

        In a long-lived repo, it's likely that the file we're tracing doesn't
        change blobs that often. This function attempts to skip irrelevant
        commits so we can space out blob lookups.

        We rewind the branch by `interval` commits (starting from the top
        commit) without looking at the trees that are skimmed over. We then look
        up the file's blob after rewinding.

        If we land on a blob that matches the one in the top commit, it's
        reasonable to assume that the file hasn't changed in the interval.
        Otherwise, we discard the rewind operation.

        Note that this technique may cause some revisions to be missing from
        the trace if the file changes contents within the interval, but reverts
        to identical blobs at both ends of the interval.
        """

        commit = node.commit
        assert not node.sealed
        assert not node.parents

        if numUnskimmables > 0:  # don't skim yet
            numUnskimmables -= 1
            return numUnskimmables

        skimmed: list[Oid] = []

        # Hop over `interval` commits.
        for _i in range(interval):
            # Get first parent, or stop here if it's a parentless commit.
            try:
                parent0 = commit.parents[0]
            except LookupError:
                break

            # Branching point: don't revisit known commits
            try:
                branchingPoint = self.visitedCommits[parent0.id]
                assert branchingPoint.sealed
                assert branchingPoint.status in TraceNode.ValidStatuses
                break
            except KeyError:
                pass

            commit = parent0
            skimmed.append(commit.id)

        # We've hopped over `len(skimmed)` commits.
        # `commit` is now the commit at the "bottom" of the hop.
        # Now see if the file is in the bottom commit's tree.
        tree = commit.tree
        try:
            blobId = tree[node.path].id
            sameBlob = blobId == node.blobId
        except LookupError:
            sameBlob = False

        # If it's not the same blob after skimming, the relevant commit must
        # be among those we've hopped over. Prevent hopping over these again
        # so that we examine each of them thoroughly.
        if not sameBlob:
            return len(skimmed)

        # It's the same blob at both ends of the hop.
        # Bring current node to the commit at the end of the hop.
        node.commit = commit

        # Mark all skimmed commits as visited by this node
        for oid in skimmed:
            assert oid not in self.visitedCommits
            assert oid not in node.subbingInForCommits
            self.visitedCommits[oid] = node
            node.subbingInForCommits.append(oid)
        assert commit.id in self.visitedCommits
        assert commit.id in node.subbingInForCommits

        # Skimming can resume immediately after this commit
        return 0

    def __len__(self):
        return self.numRelevantNodes

    def annotate(self, repo: Repo, progressCallback: Callable[[int], None] = dummyProgressCallback):
        blameFile(repo, self.first, progressCallback)

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

    # Support starting a trace from a commit that has deleted the file.
    if treeAbove is None:
        return "", NULL_OID

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
