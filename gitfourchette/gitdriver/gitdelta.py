# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import enum

from pygit2.enums import AttrCheck

from gitfourchette.gitdriver.gitconflict import GitConflict
from gitfourchette.gitdriver.gitdeltafile import GitDeltaFile, FileMode, GitDeltaSource
from gitfourchette.gitdriver.lfspointer import LfsPointer, LfsPointerState
from gitfourchette.porcelain import Repo


class GitStatus(enum.StrEnum):
    """Status of a file in a GitDelta."""

    # git: diff.h "diff-raw status letters"
    Added = "A"
    Copied = "C"
    Deleted = "D"
    Modified = "M"
    Renamed = "R"
    TypeChanged = "T"
    Unmerged = "U"  # aka merge conflict
    Unknown = "X"  # aka Unreadable in libgit2

    # Additional statuses
    Untracked = "?"
    Ignored = "!"  # note: "I" in libgit2 (git_diff_status_char())

    @property
    def isAddedOrUntracked(self) -> bool:
        return self in "?A"


@dataclasses.dataclass
class GitDelta:
    status: GitStatus = GitStatus.Unknown
    old: GitDeltaFile = dataclasses.field(default_factory=GitDeltaFile)
    new: GitDeltaFile = dataclasses.field(default_factory=GitDeltaFile)
    similarity: int = 0
    submoduleStatus: str = ""  # Only in UNSTAGED contexts
    conflict: GitConflict | None = None  # Only in UNSTAGED contexts

    def __post_init__(self):
        assert isinstance(self.status, GitStatus)
        assert self.old.source != GitDeltaSource.Dirty, "old source cannot be dirty"

        # Clear empty submodule status so it's falsy
        if self.submoduleStatus == "N...":
            self.submoduleStatus = ""

    @property
    def source(self) -> GitDeltaSource:
        return self.new.source

    @property
    def submoduleWorkdirDirty(self) -> bool:
        sub = self.submoduleStatus
        return "M" in sub or "U" in sub

    def isSubtreeCommitPatch(self) -> bool:
        return (self.old.mode | self.new.mode) & FileMode.COMMIT == FileMode.COMMIT

    def isTreeOrSubmodule(self) -> bool:
        assert (FileMode.COMMIT & FileMode.TREE) == FileMode.TREE  # commit must contain tree bit
        return (self.old.mode | self.new.mode) & FileMode.TREE == FileMode.TREE

    def cacheLfsPointers(self, repo: Repo):
        old = self.old
        new = self.new

        # Cache "old" LFS pointer
        if old.lfs.state:
            # Already cached
            pass
        elif self.status.isAddedOrUntracked:
            # Untracked/unstaged: No pointer yet
            old.lfs = LfsPointer(LfsPointerState.NoPointer)
        else:
            if old.source == GitDeltaSource.Commit:
                oldCheck = AttrCheck.INCLUDE_COMMIT
            else:
                assert old.source != GitDeltaSource.Dirty, "old source cannot be dirty"
                oldCheck = AttrCheck.INDEX_THEN_FILE
                if not repo.head_is_unborn:
                    oldCheck |= AttrCheck.INCLUDE_HEAD

            old.cacheLfsPointer(repo, oldCheck)

        # Cache "new" LFS pointer
        if new.lfs.state:
            # Already cached
            pass
        elif self.status == GitStatus.Deleted:
            # Deletion: No pointer
            new.lfs = LfsPointer(LfsPointerState.NoPointer)
        else:
            if new.source == GitDeltaSource.Commit:
                newCheck = AttrCheck.INCLUDE_COMMIT
            elif new.source == GitDeltaSource.Dirty:
                # Note: If .gitattributes itself contains unstaged changes, then
                # this check is unreliable with libgit2 alone (we'd need an
                # AttrCheck.FILE_ONLY flag). For that specific case,
                # `loadWorkdir` should already have cached the 'new' lfs pointer
                # state via `git check-attr`.
                newCheck = AttrCheck.FILE_THEN_INDEX
            else:
                newCheck = AttrCheck.INDEX_ONLY

            new.cacheLfsPointer(repo, newCheck)
