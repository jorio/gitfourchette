# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses

from pygit2.enums import AttrCheck

from gitfourchette.gitdriver.gitconflict import GitConflict
from gitfourchette.gitdriver.gitdeltafile import GitDeltaFile, FileMode, NavContext
from gitfourchette.porcelain import Repo, Oid, NULL_OID


@dataclasses.dataclass
class GitDelta:
    status: str = ""
    old: GitDeltaFile = dataclasses.field(default_factory=GitDeltaFile)
    new: GitDeltaFile = dataclasses.field(default_factory=GitDeltaFile)
    similarity: int = 0
    submoduleStatus: str = ""  # Only in UNSTAGED contexts
    conflict: GitConflict | None = None  # Only in UNSTAGED contexts

    @property
    def context(self) -> NavContext:
        return self.new.source

    @property
    def submoduleWorkdirDirty(self) -> bool:
        sub = self.submoduleStatus
        return "M" in sub or "U" in sub

    def isSubtreeCommitPatch(self) -> bool:
        return FileMode.COMMIT in (self.old.mode, self.new.mode)

    def cacheLfsPointers(self, repo: Repo, commitId: Oid):
        if not (self.old.lfs.state and self.new.lfs.state):
            self._cacheLfsPointers(repo, commitId)
        return self.old.lfs or self.new.lfs

    def _cacheLfsPointers(self, repo: Repo, newCommitId: Oid):
        old = self.old
        new = self.new

        try:
            oldCommitId = repo[newCommitId].parent_ids[0]
        except (KeyError, IndexError):
            oldCommitId = newCommitId

        if oldCommitId != NULL_OID:
            oldCheck = AttrCheck.INCLUDE_COMMIT
        elif old.source.isDirty():
            # TODO: Not 100% sure about this - we need tests!
            oldCheck = AttrCheck.INDEX_ONLY
        else:
            oldCheck = AttrCheck.INDEX_THEN_FILE

        if oldCommitId == NULL_OID and not repo.head_is_unborn:
            oldCheck |= AttrCheck.INCLUDE_HEAD

        if newCommitId != NULL_OID:
            newCheck = AttrCheck.INCLUDE_COMMIT
        elif new.source.isDirty():
            newCheck = AttrCheck.FILE_THEN_INDEX
        else:
            # TODO: Not 100% sure about this - we need tests!
            newCheck = AttrCheck.INDEX_ONLY

        self.old.cacheLfsPointer(repo, oldCommitId, oldCheck)
        self.new.cacheLfsPointer(repo, newCommitId, newCheck)
