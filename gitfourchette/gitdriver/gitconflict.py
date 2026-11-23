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
        """ Return True if the file exists on our side of the conflict. """
        return self[0] != "D" and self != GitConflictSides.AddedByThem

    def hasTheirs(self) -> bool:
        """ Return True if the file exists on their side of the conflict. """
        return self[1] != "D" and self != GitConflictSides.AddedByUs


@dataclasses.dataclass
class GitConflict:
    sides: GitConflictSides
    ancestor: GitDeltaFile
    ours: GitDeltaFile
    theirs: GitDeltaFile

    def oneSidedStage(self) -> GitDeltaFile | None:
        """
        In a one-sided conflict, return the GitDeltaFile that still exists among
        ours or theirs. Return None in a two-sided conflict, i.e. both ours and
        theirs have the file, or neither do.
        """
        hasOurs = self.sides.hasOurs()
        if hasOurs == self.sides.hasTheirs():  # not one-sided
            return None
        return self.ours if hasOurs else self.theirs
