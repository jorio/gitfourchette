# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import dataclasses

from gitfourchette.porcelain import *

PLACEHOLDER_OID = Oid(hex='E' * 40)


@dataclasses.dataclass
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
