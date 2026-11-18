# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Remote management tasks.
"""

from gitfourchette.forms.remotedialog import RemoteDialog
from gitfourchette.gitdriver import GitDriver, argsIf
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.tasks.repotask import RepoTask, TaskEffects
from gitfourchette.toolbox import *


class NewRemote(RepoTask):
    def flow(self):
        existingRemotes = [r.name for r in self.repo.remotes]

        dlg = RemoteDialog(
            editExistingRemote=False,
            name="",
            url="",
            existingRemotes=existingRemotes,
            skipFetchAll=False,
            parent=self.parentWidget())

        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.show()
        dlg.setMaximumHeight(dlg.height())
        yield from self.flowDialog(dlg)

        newRemoteName = dlg.ui.nameEdit.text()
        newRemoteUrl = dlg.ui.urlEdit.text()
        fetchAfterAdd = dlg.ui.fetchAfterAddCheckBox.isChecked()
        newSkipFetchAll = dlg.ui.skipFetchAllCheckBox.isChecked()
        dlg.deleteLater()

        self.epilog.effects |= TaskEffects.Refs | TaskEffects.Remotes
        yield from self.flowCallGit("remote", "add", "--", newRemoteName, newRemoteUrl)
        if newSkipFetchAll:
            yield from self.flowSetGitConfig(f"remote.{newRemoteName}.skipFetchAll", "true")

        self.epilog.status = _("Remote {0} added.", tquo(newRemoteName))

        if fetchAfterAdd:
            from gitfourchette.tasks import FetchRemotes
            yield from self.flowSubtask(FetchRemotes, newRemoteName)


class EditRemote(RepoTask):
    def flow(self, oldRemoteName: str):
        oldRemoteUrl = self.repo.remotes[oldRemoteName].url

        existingRemotes = [r.name for r in self.repo.remotes]
        existingRemotes.remove(oldRemoteName)

        skipFetchAll = self.repo.get_remote_skipfetchall(oldRemoteName)

        dlg = RemoteDialog(
            editExistingRemote=True,
            name=oldRemoteName,
            url=oldRemoteUrl,
            existingRemotes=existingRemotes,
            skipFetchAll=skipFetchAll,
            parent=self.parentWidget())

        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.show()
        yield from self.flowDialog(dlg)

        newRemoteName = dlg.ui.nameEdit.text()
        newRemoteUrl = dlg.ui.urlEdit.text().strip()
        newSkipFetchAll = dlg.ui.skipFetchAllCheckBox.isChecked()
        dlg.deleteLater()

        self.epilog.effects |= TaskEffects.Refs | TaskEffects.Remotes

        if oldRemoteName != newRemoteName:
            yield from self.flowCallGit(
                "remote",
                "rename",
                *argsIf(GitDriver.supportsDashDashBeforePositionalArgs(), "--progress", "--"),
                oldRemoteName,
                newRemoteName)

        if oldRemoteUrl != newRemoteUrl:
            yield from self.flowCallGit(
                "remote",
                "set-url",
                "--",
                newRemoteName,
                newRemoteUrl)

        # Always write it: "git remote rename" doesn't carry over a value from the global config
        yield from self.flowSetGitConfig(f"remote.{newRemoteName}.skipFetchAll", "true" if newSkipFetchAll else None)

        self.epilog.status = _("Remote {0} modified.", tquo(newRemoteName))


class DeleteRemote(RepoTask):
    def flow(self, remoteName: str):
        yield from self.flowConfirm(
            text=paragraphs(
                _("Really remove remote {0}?", bquo(remoteName)),
                _("This will merely detach the remote from your local repository. "
                  "The remote server itself will not be affected.")),
            verb=_("Remove remote"),
            buttonIcon="SP_DialogDiscardButton")

        self.epilog.effects |= TaskEffects.Refs | TaskEffects.Remotes

        yield from self.flowCallGit(
            "remote",
            "remove",
            *argsIf(GitDriver.supportsDashDashBeforePositionalArgs(), "--"),
            remoteName)

        self.epilog.status = _("Remote {0} removed.", tquo(remoteName))
