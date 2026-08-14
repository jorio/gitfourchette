# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
from enum import StrEnum

from gitfourchette.gitdriver.gitdeltafile import GitDeltaFile


class GitConflictSides(StrEnum):
    BothDeleted   = "DD"
    AddedByUs     = "AU"
    AddedByThem   = "UA"
    DeletedByUs   = "DU"
    DeletedByThem = "UD"
    BothAdded     = "AA"
    BothModified  = "UU"

    def hasOurs(self) -> bool:
        return self[0] != "D" and self != GitConflictSides.AddedByThem

    def hasTheirs(self) -> bool:
        return self[1] != "D" and self != GitConflictSides.AddedByUs


@dataclasses.dataclass
class GitConflict:
    sides: GitConflictSides
    ancestor: GitDeltaFile
    ours: GitDeltaFile
    theirs: GitDeltaFile
