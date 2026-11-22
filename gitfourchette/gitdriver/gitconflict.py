# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
from enum import StrEnum, IntEnum

from gitfourchette.gitdriver.gitdeltafile import GitDeltaFile


class GitConflictStage(IntEnum):
    Unknown = 0
    Ancestor = 1
    Ours = 2
    Theirs = 3


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

    def oneSidedStage(self, fallback=GitConflictStage.Unknown) -> GitConflictStage:
        """
        In a one-sided conflict, return the stage that still contains the file.
        In a two-sided conflict (i.e. file exists in both or neither sides),
        return fallback, by default GitConflictStage.Unknown.
        """
        hasOurs = self.hasOurs()
        return (fallback if hasOurs == self.hasTheirs()  # two-sided
                else GitConflictStage.Ours if hasOurs
                else GitConflictStage.Theirs)


@dataclasses.dataclass
class GitConflict:
    sides: GitConflictSides
    ancestor: GitDeltaFile
    ours: GitDeltaFile
    theirs: GitDeltaFile

    def fileFromStageNumber(self, stage: GitConflictStage) -> GitDeltaFile:
        return {
            GitConflictStage.Ancestor: self.ancestor,
            GitConflictStage.Ours: self.ours,
            GitConflictStage.Theirs: self.theirs,
        }[stage]
