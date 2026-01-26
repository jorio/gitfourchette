# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Submodule management tasks.
"""

from contextlib import suppress
from pathlib import Path

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.registersubmoduledialog import RegisterSubmoduleDialog
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskPrereqs, TaskEffects
from gitfourchette.toolbox import *


class RegisterSubmodule(RepoTask):
    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoUnborn | TaskPrereqs.NoConflicts

    def flow(self, path: str):
        yield from self._flow(path, absorb=False)

    def _flow(self, path: str, absorb: bool):
        thisWD = Path(self.repo.workdir)
        thisName = thisWD.name
        subWD = Path(thisWD / path)
        subName = subWD.name
        subRemotes = {}

        preferredRemote = ""
        with RepoContext(thisWD / subWD) as subRepo:
            assert not subRepo.is_bare
            for remote in subRepo.remotes:
                subRemotes[remote.name] = remote.url
            with suppress(Exception):
                localBranch = subRepo.branches.local[subRepo.head_branch_shorthand]
                upstreamRemoteName = localBranch.upstream.remote_name
                preferredRemote = subRemotes[upstreamRemoteName]

        if not subRemotes:
            message = paragraphs(
                _("{0} has no remotes.", bquo(subName)),
                _("Please open {0} and add a remote to it before absorbing it as a submodule.", bquo(subName)))
            raise AbortTask(message)

        reservedNames = set(self.repo.listall_submodules_dict().keys())
        dlg = RegisterSubmoduleDialog(
            workdirPath=path,
            superprojectName=thisName,
            remotes=subRemotes,
            absorb=absorb,
            reservedNames=reservedNames,
            parent=self.parentWidget())

        if preferredRemote:
            i = dlg.ui.remoteComboBox.findData(preferredRemote)
            if i >= 0:
                dlg.ui.remoteComboBox.setCurrentIndex(i)

        subtitle = _("Settings will be saved in {0}", tquo(".gitmodules"))
        convertToBrandedDialog(dlg, subtitleText=subtitle)
        yield from self.flowDialog(dlg)

        remoteUrl = dlg.remoteUrl
        customName = dlg.customName
        dlg.deleteLater()

        self.effects |= TaskEffects.Workdir | TaskEffects.Refs  # we don't have TaskEffects.Submodules so .Refs is the next best thing

        innerWD = str(subWD.relative_to(thisWD))
        yield from self.flowCallGit("submodule", "add", "--force", "--name", customName, "--", remoteUrl, innerWD)

        if absorb:
            yield from self.flowCallGit("submodule", "absorbgitdirs", "--", innerWD)


class AbsorbSubmodule(RegisterSubmodule):
    def flow(self, path: str):
        yield from self._flow(path, absorb=True)


class RemoveSubmodule(RepoTask):
    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoUnborn | TaskPrereqs.NoConflicts

    def flow(self, submoduleName: str):
        submodule = self.repo.submodules[submoduleName]
        path = submodule.path

        yield from self.flowConfirm(
            text=paragraphs(
                _("Really remove submodule {0}?", bquo(submoduleName)),
                _("The submodule will be removed from {0} and its working copy will be deleted.", hquo(".gitmodules")),
                _("Any changes in the submodule that haven’t been pushed will be lost."),
                _("This cannot be undone!")),
            buttonIcon="SP_DialogDiscardButton",
            verb="Remove")

        self.effects |= TaskEffects.Workdir | TaskEffects.Refs  # we don't have TaskEffects.Submodules so .Refs is the next best thing
        self.effects |= TaskEffects.Head  # also force refresh libgit2 index TODO: better naming

        # 1. Unregister from .git/config & remove worktree
        yield from self.flowCallGit("submodule", "deinit", "--", path)

        # 2. Unregister from .gitmodules (& remove worktree again)
        yield from self.flowCallGit("rm", "--", path)

        self._postStatus = _("Submodule {0} removed.", tquo(submoduleName))
