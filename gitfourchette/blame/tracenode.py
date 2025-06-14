# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import dataclasses
from collections.abc import Generator

from gitfourchette.appconsts import *
from gitfourchette.porcelain import *


@dataclasses.dataclass
class TraceNode:
    DefaultStatus = DeltaStatus.UNMODIFIED
    GarbageStatus = DeltaStatus.UNREADABLE
    ValidStatuses = [DeltaStatus.ADDED, DeltaStatus.DELETED, DeltaStatus.MODIFIED, DeltaStatus.RENAMED]

    path: str
    commit: Commit
    blobId: Oid
    level: int = -1
    revisionNumber: int = -1

    sealed: bool = False
    status: DeltaStatus = DefaultStatus
    parents: list[TraceNode] = dataclasses.field(default_factory=list)
    children: list[TraceNode] = dataclasses.field(default_factory=list)

    subbingInForCommits: list[Oid] = dataclasses.field(default_factory=list)
    # Irrelevant commits that this node is subbing in for.

    def __repr__(self):
        return f"({self.status.name[0]},{id7(self.commit)})"

    @property
    def commitId(self) -> Oid:
        return self.commit.id

    @property
    def ancestorBlobId(self):
        try:
            assert self.parents[0].status in TraceNode.ValidStatuses
            assert self.parents[0].sealed
            return self.parents[0].blobId
        except IndexError:
            assert self.status == DeltaStatus.ADDED
            return NULL_OID

    def compare(self, path: str, blobId: Oid) -> DeltaStatus:
        if blobId == NULL_OID:
            return DeltaStatus.ADDED
        if path != self.path:
            return DeltaStatus.RENAMED
        if blobId != self.blobId:
            return DeltaStatus.MODIFIED
        return DeltaStatus.UNMODIFIED

    def addParent(self, node: TraceNode):
        assert node not in self.parents
        assert self not in node.children
        self.parents.append(node)
        node.children.append(self)

    def unlinkPassthrough(self, replaceWith: TraceNode):
        assert not self.parents, "passthrough nodes aren't supposed to have any parents"
        assert self.status != TraceNode.GarbageStatus, "this node has already been unlinked"
        assert replaceWith.status != TraceNode.GarbageStatus, "don't chain passthrough nodes"
        assert replaceWith.sealed

        for child in self.children:
            assert child.status != TraceNode.GarbageStatus
            oldIndex = child.parents.index(self)
            try:
                existingIndex = child.parents.index(replaceWith)
            except ValueError:
                child.parents[oldIndex] = replaceWith
                assert child not in replaceWith.children
                replaceWith.children.append(child)
            else:
                assert existingIndex < oldIndex
                del child.parents[oldIndex]
                assert child in replaceWith.children

        assert all(oid not in replaceWith.subbingInForCommits for oid in self.subbingInForCommits)
        replaceWith.subbingInForCommits.extend(self.subbingInForCommits)

        self.sealed = True
        self.status = TraceNode.GarbageStatus  # this node should never be used anymore
        self.parents.clear()
        self.children.clear()
        self.subbingInForCommits.clear()

    def walkGraph(self) -> Generator[TraceNode, None, None]:
        frontierNodes = [self]
        frontierPendingChildren = [0]

        if APP_DEBUG:
            debugSeen: set[Oid] = set()

        while frontierNodes:
            # Find rightmost frontier node with no pending children.
            for i in range(len(frontierPendingChildren) - 1, -1, -1):
                if frontierPendingChildren[i] == 0:
                    break
            else:
                raise NotImplementedError("frontier deadlock")

            # Pop the node off the frontier.
            node = frontierNodes[i]
            del frontierNodes[i]
            del frontierPendingChildren[i]

            # Push this node's parents to the frontier.
            for parent in node.parents:
                if APP_DEBUG:
                    assert node in parent.children

                # Figure out how many pending children this parent still has.
                # If the parent was already in the frontier, some of its children have already been seen.
                try:
                    i = frontierNodes.index(parent)
                except ValueError:
                    # Parent isn't in frontier yet, so none of its children have been seen yet.
                    parentPendingChildren = len(parent.children)
                else:
                    # Parent is already in frontier, meaning some of its children have already been seen.
                    # Pop parent from frontier so we can add it back at the tail.
                    parentPendingChildren = frontierPendingChildren[i]
                    del frontierNodes[i]
                    del frontierPendingChildren[i]
                assert 1 <= parentPendingChildren <= len(parent.children)

                # Deduct current node from parent's pending children.
                parentPendingChildren -= 1

                # Push parent to frontier tail.
                frontierNodes.append(parent)
                frontierPendingChildren.append(parentPendingChildren)

            if APP_DEBUG:
                assert len(frontierNodes) == len(frontierPendingChildren)
                assert node.status in TraceNode.ValidStatuses
                assert node.commitId not in debugSeen, f"commit {id7(node.commitId)} visited twice"
                debugSeen.add(node.commitId)

            # Yield the current node to the caller.
            yield node
