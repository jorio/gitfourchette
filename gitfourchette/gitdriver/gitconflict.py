# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
from enum import StrEnum

from gitfourchette.gitdriver.gitdeltafile import GitDeltaFile


class GitConflictSides(StrEnum):
    BothDeleted   = "DD"
    AddedByUs     = "AU"
    DeletedByThem = "UD"
    AddedByThem   = "UA"
    DeletedByUs   = "DU"
    BothAdded     = "AA"
    BothModified  = "UU"


@dataclasses.dataclass
class GitConflict:
    sides: GitConflictSides
    ancestor: GitDeltaFile
    ours: GitDeltaFile
    theirs: GitDeltaFile
