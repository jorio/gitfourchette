# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses as _dataclasses

from gitfourchette.porcelain import *


@_dataclasses.dataclass
class TraceNode:
    path: str
    commitId: Oid
    blobId: Oid
    status: DeltaStatus = DeltaStatus.MODIFIED


def traceFile(repo: Repo, path: str, seed: Oid) -> list[TraceNode]:
    trace: list[TraceNode] = []
    oldestBlobId = NULL_OID
    commit = repo.peel_commit(seed)

    # TODO: Deleted file in seed
    while True:
        renamed = False

        try:
            blob = commit.tree[path]
        except KeyError:
            # Path missing from this commit's tree.
            # Did the subsequent commit rename the file?
            childCommit = repo.peel_commit(trace[-1].commitId)
            assert commit.id in childCommit.parent_ids
            diff = childCommit.tree.diff_to_tree(commit.tree, DiffOption.NORMAL, 0, 0, swap=True)
            diff.find_similar()
            for delta in diff.deltas:
                if delta.new_file.path == path and delta.status == DeltaStatus.RENAMED:
                    trace[-1].status = DeltaStatus.RENAMED
                    path = delta.old_file.path
                    blob = commit.tree[path]
                    renamed = True
                    break
            else:
                break

        blob_id = blob.id
        if renamed or blob_id != oldestBlobId:
            oldestBlobId = blob_id
            trace.append(TraceNode(path, commit.id, blob_id, DeltaStatus.MODIFIED))
        else:
            trace[-1].commitId = commit.id

        try:
            commit = commit.parents[0]
        except IndexError:
            break

    trace[-1].status = DeltaStatus.ADDED
    return trace
