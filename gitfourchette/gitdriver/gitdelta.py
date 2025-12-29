# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses

from gitfourchette.gitdriver.gitconflict import GitConflict
from gitfourchette.gitdriver.gitdeltafile import GitDeltaFile, FileMode, NavContext


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
