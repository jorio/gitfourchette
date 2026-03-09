# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses

from pygit2.enums import AttrCheck

from gitfourchette.appconsts import APP_DEBUG
from gitfourchette.gitdriver.gitconflict import GitConflict
from gitfourchette.gitdriver.gitdeltafile import GitDeltaFile, FileMode, NavContext
from gitfourchette.gitdriver.lfspointer import LfsPointer, LfsPointerState
from gitfourchette.porcelain import Repo, Oid, NULL_OID


@dataclasses.dataclass
class GitDelta:
    status: str = ""
    old: GitDeltaFile = dataclasses.field(default_factory=GitDeltaFile)
    new: GitDeltaFile = dataclasses.field(default_factory=GitDeltaFile)
    similarity: int = 0
    submoduleStatus: str = ""  # Only in UNSTAGED contexts
    conflict: GitConflict | None = None  # Only in UNSTAGED contexts

    if APP_DEBUG:
        def __post_init__(self):
            assert not self.old.source.isDirty(), "old source cannot be unstaged/untracked"

    @property
    def context(self) -> NavContext:
        return self.new.source

    @property
    def submoduleWorkdirDirty(self) -> bool:
        sub = self.submoduleStatus
        return "M" in sub or "U" in sub

    def isSubtreeCommitPatch(self) -> bool:
        return FileMode.COMMIT in (self.old.mode, self.new.mode)

    def cacheLfsPointers(self, repo: Repo, newCommitId: Oid):
        old = self.old
        new = self.new

        # Cache "old" LFS pointer
        if old.lfs.state:
            # Already cached
            pass
        elif self.status in "?A":
            # Untracked/unstaged: No pointer yet
            old.lfs = LfsPointer(LfsPointerState.NoPointer)
        else:
            try:
                oldCommitId = repo[newCommitId].parent_ids[0]
            except (KeyError, IndexError):
                oldCommitId = newCommitId

            if oldCommitId != NULL_OID:
                oldCheck = AttrCheck.INCLUDE_COMMIT
            else:
                assert not old.source.isDirty(), "old source cannot be dirty"
                oldCheck = AttrCheck.INDEX_THEN_FILE

            if oldCommitId == NULL_OID and not repo.head_is_unborn:
                oldCheck |= AttrCheck.INCLUDE_HEAD

            old.cacheLfsPointer(repo, oldCommitId, oldCheck)

        # Cache "new" LFS pointer
        if new.lfs.state:
            # Already cached
            pass
        elif self.status == "D":
            # Deletion: No pointer
            new.lfs = LfsPointer(LfsPointerState.NoPointer)
        else:
            if newCommitId != NULL_OID:
                newCheck = AttrCheck.INCLUDE_COMMIT
            elif new.source.isDirty():
                # Note: If .gitattributes itself contains unstaged changes, then
                # this check is unreliable with libgit2 alone (we'd need an
                # AttrCheck.FILE_ONLY flag). For that specific case,
                # `loadWorkdir` should already have cached the 'new' lfs pointer
                # state via `git check-attr`.
                newCheck = AttrCheck.FILE_THEN_INDEX
            else:
                newCheck = AttrCheck.INDEX_ONLY

            new.cacheLfsPointer(repo, newCommitId, newCheck)
