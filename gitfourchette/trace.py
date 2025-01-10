# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations as _annotations

import dataclasses as _dataclasses
import logging as _logging

from gitfourchette.porcelain import *
from gitfourchette.settings import DEVDEBUG

_logger = _logging.getLogger(__name__)


@_dataclasses.dataclass
class TraceNode:
    path: str
    commitId: Oid
    blobId: Oid
    level: int  # branch ancestry level (breadth distance from root branch)
    status: DeltaStatus = DeltaStatus.MODIFIED
    llPrev: TraceNode | None = None
    llNext: TraceNode | None = None
    sealed: bool = False

    def __str__(self):
        status_char = self.status.name[0]
        indent = ' ' * 4 * self.level
        return f"({self.level},{id7(self.commitId)},{id7(self.blobId)},{status_char}) {indent}{self.path}"

    def seal(self, commit, stop, frontier):
        assert not self.sealed
        assert commit
        assert commit.id == self.commitId

        if len(commit.parents) > 1:
            if len(commit.parents) > 2:
                raise NotImplementedError(f"Octopus merge unsupported ({id7(commit)})")
            parent1 = commit.parents[1]
            if parent1.id not in stop:
                stop.add(parent1.id)
                frontier.append((self, parent1))

        if not self.llNext:
            assert self.status == DeltaStatus.MODIFIED  # should not be changed from default
            self.status = DeltaStatus.ADDED

        self.sealed = True


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
            else:
                self.next = ll.head.llNext

        def __iter__(self):
            return self

        def __next__(self):
            node = self.next
            if not node:
                raise StopIteration()
            self.next = node.llPrev if self.reverse else node.llNext
            return node

    def __iter__(self):
        return Trace.Iterator(self)

    def reverseIter(self):
        return Trace.Iterator(self, reverse=True)

    def indexOfCommit(self, oid: Oid):
        for i, item in enumerate(self):
            if item.commitId == oid:
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


def traceFile(topPath: str, topCommit: Commit) -> Trace:
    ll = Trace(topPath)
    frontier = [(ll.head, topCommit)]
    stop = set()
    numCommits = 0

    # Outer loop: Pop branch off frontier
    while frontier:
        node, commit = frontier.pop(0)
        path = node.path
        level = node.level + 1

        # TODO: Deleted file in seed
        treeAbove = None
        commitAbove = None
        newBranch = True

        # Inner loop: Walk branch
        while True:
            assert (not newBranch) == (node.level == level)
            assert newBranch == node.sealed

            numCommits += 1
            tree = commit.tree
            stop.add(commit.id)

            path, blobId = _getBlob(path, tree, treeAbove, node.blobId)
            if blobId == NULL_OID:
                break  # bail from the branch
            if not newBranch and path != node.path:
                node.status = DeltaStatus.RENAMED

            if newBranch and level > 0 and blobId != node.blobId:
                # Branch doesn't contribute the blob
                assert node is not ll.head
                break  # bail from the branch

            if newBranch or blobId != node.blobId or node.status == DeltaStatus.RENAMED:
                nodeAbove = node
                node = TraceNode(path=path, commitId=commit.id, blobId=blobId, level=level)
                ll.insert(nodeAbove, node)
                if not newBranch:  # Seal node above
                    nodeAbove.seal(commit=commitAbove, stop=stop, frontier=frontier)
                newBranch = False
            else:
                assert node.level == level
                node.commitId = commit.id

            # We own the node past this point
            assert not newBranch

            commitAbove = commit
            treeAbove = tree

            try:
                commit = commit.parents[0]
            except IndexError:
                break  # bail from the branch

            if commit.id in stop:
                break  # bail from the branch

        # Seal last node in branch
        if not newBranch:
            node.seal(commit=commitAbove, stop=stop, frontier=frontier)

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
        if knownLevels.get(node.blobId, 0x3FFFFFFF) > node.level:
            knownLevels[node.blobId] = node.level
        elif node.status == DeltaStatus.MODIFIED:
            # print("Scrapping", str(node))
            ll.unlink(node)

    _logger.debug(f"{numCommits} commits traced; {len(ll)} were relevant.")
    # ll.dump()
    return ll
