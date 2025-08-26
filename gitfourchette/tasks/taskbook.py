# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import warnings
from typing import Any

from gitfourchette import tasks
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.tasks import RepoTask
from gitfourchette.toolbox import MultiShortcut, makeMultiShortcut, ActionDef, englishTitleCase


class TaskBook:
    """ Registry of metadata about task commands """

    names: dict[type[RepoTask], str] = {}
    toolbarNames: dict[type[RepoTask], str] = {}
    tips: dict[type[RepoTask], str] = {}
    shortcuts: dict[type[RepoTask], MultiShortcut] = {}
    icons: dict[type[RepoTask], str] = {}
    noEllipsis: set[type[RepoTask]]

    @classmethod
    def retranslate(cls):
        cls.names = {
            tasks.AbortMerge: _("Abort merge"),
            tasks.AbsorbSubmodule: _("Absorb submodule"),
            tasks.AcceptMergeConflictResolution: _("Accept merge conflict resolution"),
            tasks.AmendCommit: _("Amend last commit"),
            tasks.ApplyPatch: _("Apply selected text"),
            tasks.ApplyPatchData: _("Apply patch file"),
            tasks.ApplyPatchFile: _("Apply patch file"),
            tasks.ApplyPatchFileReverse: _("Revert patch file"),
            tasks.ApplyStash: _("Apply stash"),
            tasks.CheckoutCommit: _("Check out commit"),
            tasks.CherrypickCommit: _("Cherry-pick"),
            tasks.DeleteBranch: _("Delete local branch"),
            tasks.DeleteBranchFolder: _("Delete local branch folder"),
            tasks.DeleteRemote: _("Remove remote"),
            tasks.DeleteRemoteBranch: _("Delete branch on remote"),
            tasks.DeleteTag: _("Delete tag"),
            tasks.DiscardFiles: _("Discard changes"),
            tasks.DiscardModeChanges: _("Discard mode changes"),
            tasks.DropStash: _("Delete stash"),
            tasks.EditRemote: _("Edit remote"),
            tasks.EditUpstreamBranch: _("Edit upstream branch"),
            tasks.ExportCommitAsPatch: _("Export commit as patch file"),
            tasks.ExportPatchCollection: _("Export patch file"),
            tasks.ExportStashAsPatch: _("Export stash as patch file"),
            tasks.ExportWorkdirAsPatch: _("Export changes as patch file"),
            tasks.FastForwardBranch: _("Fast-forward branch"),
            tasks.FetchRemotes: _("Fetch remote branches"),
            tasks.FetchRemoteBranch: _("Fetch remote branch"),
            tasks.GetCommitInfo: _("Get commit information"),
            tasks.HardSolveConflicts: _("Accept/reject incoming changes"),
            tasks.Jump: _("Navigate in repo"),
            tasks.JumpBack: _("Navigate back"),
            tasks.JumpBackOrForward: _("Navigate forward"),
            tasks.JumpForward: _("Navigate forward"),
            tasks.JumpToHEAD: _("Go to HEAD commit"),
            tasks.JumpToUncommittedChanges: _("Go to Working Directory"),
            tasks.MarkConflictSolved: _("Mark conflict solved"),
            tasks.MergeBranch: _("Merge branch"),
            tasks.NewBranchFromCommit: _("New local branch"),
            tasks.NewBranchFromHead: _("New local branch"),
            tasks.NewBranchFromRef: _("New local branch"),
            tasks.NewCommit: _("New commit"),
            tasks.NewIgnorePattern: _("Ignore a new file name pattern"),
            tasks.NewRemote: _("Add remote"),
            tasks.NewStash: _("Stash changes"),
            tasks.NewTag: _("New tag"),
            tasks.OpenBlame: _("Blame file"),
            tasks.PullBranch: _("Pull remote branch"),
            tasks.PushBranch: _("Push branch"),
            tasks.PushRefspecs: _("Push refspecs"),
            tasks.RecallCommit: _("Recall lost commit"),
            tasks.RefreshRepo: _("Refresh repo"),
            tasks.RegisterSubmodule: _("Register submodule"),
            tasks.RemoveSubmodule: _("Remove submodule"),
            tasks.RenameBranch: _("Rename local branch"),
            tasks.RenameBranchFolder: _("Rename local branch folder"),
            tasks.RenameRemoteBranch: _("Rename branch on remote"),
            tasks.ResetHead: _("Reset HEAD"),
            tasks.RestoreRevisionToWorkdir: _("Restore file revision"),
            tasks.RevertCommit: _("Revert commit"),
            tasks.RevertPatch: _("Revert selected text"),
            tasks.SetUpGitIdentity: _("Git identity"),
            tasks.EditRepoSettings: _("Repository settings"),
            tasks.StageFiles: _("Stage files"),
            tasks.SwitchBranch: _("Switch to branch"),
            tasks.UpdateSubmodule: _("Update submodule"),
            tasks.UpdateSubmodulesRecursive: _("Update submodules recursively"),
            tasks.UnstageFiles: _("Unstage files"),
            tasks.UnstageModeChanges: _("Unstage mode changes"),
            tasks.VerifyGpgSignature: _("Verify signature"),
            tasks.VerifyGpgQueue: _("Verifying signatures"),
        }

        cls.toolbarNames = {
            tasks.AmendCommit: _p("toolbar", "Amend"),
            tasks.FetchRemotes: _p("toolbar", "Fetch"),
            tasks.JumpBack: _p("toolbar", "Back"),
            tasks.JumpForward: _p("toolbar", "Forward"),
            tasks.JumpToHEAD: _p("toolbar", "HEAD"),
            tasks.JumpToUncommittedChanges: _p("toolbar", "Workdir"),
            tasks.NewBranchFromHead: _p("toolbar", "Branch"),
            tasks.NewStash: _p("toolbar", "Stash"),
            tasks.PullBranch: _p("toolbar", "Pull"),
            tasks.PushBranch: _p("toolbar", "Push"),
        }

        cls.tips = {
            tasks.AmendCommit: _("Amend the last commit on the current branch with the staged changes in the working directory"),
            tasks.ApplyPatchFile: _("Apply a patch file to the working directory"),
            tasks.ApplyPatchFileReverse: _("Apply a patch file to the working directory (reverse patch before applying)"),
            tasks.ApplyStash: _("Restore backed up changes to the working directory"),
            tasks.CherrypickCommit: _("Bring the changes introduced by this commit to the current branch"),
            tasks.DeleteBranch: _("Delete this branch locally"),
            tasks.EditUpstreamBranch: _("Choose the remote branch to be tracked by this local branch"),
            tasks.ExportStashAsPatch: _("Create a patch file from this stash"),
            tasks.FastForwardBranch: _("Advance this local branch to the tip of the remote-tracking branch"),
            tasks.FetchRemotes: _("Get the latest commits on all remote branches"),
            tasks.FetchRemoteBranch: _("Get the latest commits from the remote server"),
            tasks.NewBranchFromCommit: _("Start a new branch from this commit"),
            tasks.NewBranchFromHead: _("Start a new branch from the current HEAD"),
            tasks.NewBranchFromRef: _("Start a new branch from the tip of this branch"),
            tasks.NewCommit: _("Create a commit of the staged changes in the working directory"),
            tasks.NewRemote: _("Add a remote server to this repo"),
            tasks.NewStash: _("Back up uncommitted changes and clean up the working directory"),
            tasks.NewTag: _("Tag this commit with a name"),
            tasks.PullBranch: _("Fetch the latest commits from the remote, then integrate them into your local branch"),
            tasks.PushBranch: _("Upload your commits on the current branch to the remote server"),
            tasks.RemoveSubmodule: _("Remove this submodule from .gitmodules and delete its working copy from this repo"),
            tasks.RenameBranch: _("Rename this branch locally"),
            tasks.ResetHead: _("Make HEAD point to another commit"),
            tasks.RevertCommit: _("Revert the changes introduced by this commit"),
            tasks.SetUpGitIdentity: _("Set up the identity under which you create commits"),
            tasks.EditRepoSettings: _("Set up the identity under which you create commits"),
            tasks.SwitchBranch: _("Switch to this branch and update the working directory to match it"),
        }

    @classmethod
    def initialize(cls):
        cls.names = {}
        cls.toolbarNames = {}
        cls.tips = {}

        cls.shortcuts = {
            tasks.AmendCommit: makeMultiShortcut(QKeySequence.StandardKey.SaveAs, "Ctrl+Shift+S"),
            tasks.ApplyPatchFile: makeMultiShortcut("Ctrl+I"),
            tasks.FetchRemotes: makeMultiShortcut("Ctrl+Shift+R"),
            tasks.JumpBack: makeMultiShortcut("Ctrl+Left" if MACOS else "Alt+Left"),
            tasks.JumpForward: makeMultiShortcut("Ctrl+Right" if MACOS else "Alt+Right"),
            tasks.JumpToHEAD: makeMultiShortcut("Meta+H" if MACOS else "Ctrl+H"),
            tasks.JumpToUncommittedChanges: makeMultiShortcut("Meta+G" if MACOS else "Ctrl+G"),
            tasks.NewBranchFromHead: makeMultiShortcut("Ctrl+B"),
            tasks.NewCommit: makeMultiShortcut(QKeySequence.StandardKey.Save),
            tasks.NewStash: makeMultiShortcut("Ctrl+Alt+S"),
            tasks.OpenBlame: makeMultiShortcut("Ctrl+L"),
            tasks.PullBranch: makeMultiShortcut("Ctrl+Shift+P"),
            tasks.PushBranch: makeMultiShortcut("Ctrl+P"),
        }

        cls.icons = {
            tasks.AmendCommit: "git-commit-amend",
            tasks.CheckoutCommit: "git-checkout",
            tasks.CherrypickCommit: "git-cherrypick",
            tasks.DeleteBranch: "vcs-branch-delete",
            tasks.DeleteRemote: "SP_TrashIcon",
            tasks.DeleteRemoteBranch: "SP_TrashIcon",
            tasks.DeleteTag: "SP_TrashIcon",
            tasks.DropStash: "SP_TrashIcon",
            tasks.EditRemote: "document-edit",
            tasks.EditRepoSettings: "configure",
            tasks.FetchRemoteBranch: "git-fetch",
            tasks.FetchRemotes: "git-fetch",
            tasks.JumpBack: "back",
            tasks.JumpForward: "forward",
            tasks.JumpToHEAD: "git-head",
            tasks.JumpToUncommittedChanges: "git-workdir",
            tasks.MergeBranch: "git-merge",
            tasks.NewBranchFromCommit: "git-branch",
            tasks.NewBranchFromHead: "git-branch",
            tasks.NewBranchFromRef: "git-branch",
            tasks.NewCommit: "git-commit",
            tasks.NewRemote: "git-remote",
            tasks.NewStash: "git-stash-black",
            tasks.NewTag: "git-tag",
            tasks.OpenBlame: "git-blame",
            tasks.PullBranch: "git-pull",
            tasks.PushBranch: "git-push",
            tasks.SetUpGitIdentity: "user-identity",
            tasks.SwitchBranch: "git-checkout",
        }

        cls.noEllipsis = {
            tasks.FastForwardBranch,
            tasks.FetchRemotes,
            tasks.FetchRemoteBranch,
            tasks.JumpBack,
            tasks.JumpForward,
            tasks.JumpToHEAD,
            tasks.JumpToUncommittedChanges,
            tasks.UnstageModeChanges,
            tasks.UpdateSubmodule,
            tasks.UpdateSubmodulesRecursive,
        }

        cls.retranslate()

    @classmethod
    def autoActionName(cls, t: type[RepoTask]):
        assert cls.names
        try:
            name = cls.names[t]
        except KeyError:
            name = t.__name__
            cls.names[t] = name
            warnings.warn(f"Missing name for task '{name}'")

        name = englishTitleCase(name)

        if t not in cls.noEllipsis:
            name += "…"

        return name

    @classmethod
    def action(
            cls,
            invoker: QObject,
            taskClass: type[RepoTask],
            name="",
            accel="",
            taskArgs: Any = None,
            **kwargs
    ) -> ActionDef:
        if not name:
            name = cls.autoActionName(taskClass)

        if accel:
            name = cls.autoActionName(taskClass)
            i = name.lower().find(accel.lower())
            if i >= 0:
                name = name[:i] + "&" + name[i:]

        if taskArgs is None:
            taskArgs = ()
        elif not isinstance(taskArgs, tuple | list):
            taskArgs = (taskArgs,)

        icon = cls.icons.get(taskClass, "")
        shortcuts = cls.shortcuts.get(taskClass, [])
        tip = cls.tips.get(taskClass, "")

        def callback():
            taskClass.invoke(invoker, *taskArgs)

        actionDef = ActionDef(name, callback=callback, icon=icon, shortcuts=shortcuts, tip=tip)

        if kwargs:
            actionDef = actionDef.replace(**kwargs)

        return actionDef

    @classmethod
    def toolbarAction(cls, invoker: QObject, taskClass: type[RepoTask]):
        name = cls.toolbarNames.get(taskClass, "")
        tip = cls.autoActionName(taskClass)
        return cls.action(invoker, taskClass, name).replace(tip=tip)
