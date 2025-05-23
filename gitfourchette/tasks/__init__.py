# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.tasks.repotask import RepoTask, RepoTaskRunner, TaskPrereqs, TaskEffects
from gitfourchette.tasks.repotask import RepoGoneError
from gitfourchette.tasks.repotask import TaskInvoker

from gitfourchette.tasks.blametasks import (
    OpenBlame,
)
from gitfourchette.tasks.branchtasks import (
    DeleteBranch,
    DeleteBranchFolder,
    EditUpstreamBranch,
    FastForwardBranch,
    MergeBranch,
    NewBranchFromCommit,
    NewBranchFromHead,
    NewBranchFromRef,
    RecallCommit,
    RenameBranch,
    RenameBranchFolder,
    ResetHead,
    SwitchBranch,
)
from gitfourchette.tasks.committasks import (
    AmendCommit,
    CheckoutCommit,
    CherrypickCommit,
    DeleteTag,
    NewCommit,
    NewTag,
    RevertCommit,
    SetUpGitIdentity,
)
from gitfourchette.tasks.exporttasks import (
    ExportCommitAsPatch,
    ExportPatchCollection,
    ExportStashAsPatch,
    ExportWorkdirAsPatch,
)
from gitfourchette.tasks.misctasks import (
    EditRepoSettings,
    GetCommitInfo,
    NewIgnorePattern,
)
from gitfourchette.tasks.jumptasks import (
    Jump,
    JumpBack,
    JumpBackOrForward,
    JumpForward,
    JumpToHEAD,
    JumpToUncommittedChanges,
    RefreshRepo,
)
from gitfourchette.tasks.nettasks import (
    DeleteRemoteBranch,
    RenameRemoteBranch,
    FetchRemotes,
    FetchRemoteBranch,
    PullBranch,
    PushBranch,
    PushRefspecs,
    UpdateSubmodule,
    UpdateSubmodulesRecursive,
)
from gitfourchette.tasks.remotetasks import NewRemote, EditRemote, DeleteRemote

from gitfourchette.tasks.indextasks import (
    AbortMerge,
    AcceptMergeConflictResolution,
    ApplyPatch,
    ApplyPatchFile,
    ApplyPatchFileReverse,
    DiscardFiles,
    DiscardModeChanges,
    HardSolveConflicts,
    MarkConflictSolved,
    RevertPatch,
    ApplyPatchData,
    StageFiles,
    UnstageFiles,
    UnstageModeChanges,
    RestoreRevisionToWorkdir,
)

from gitfourchette.tasks.stashtasks import (
    ApplyStash,
    DropStash,
    NewStash,
)

from gitfourchette.tasks.submoduletasks import (
    AbsorbSubmodule,
    RegisterSubmodule,
    RemoveSubmodule,
)

from gitfourchette.tasks.taskbook import TaskBook
