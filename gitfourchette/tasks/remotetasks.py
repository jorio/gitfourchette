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
from gitfourchette.porcelain import GitConfigHelper
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

        self.effects |= TaskEffects.Refs | TaskEffects.Remotes
        yield from self.flowCallGit("remote", "add", "--", newRemoteName, newRemoteUrl)
        self.repo.set_remote_skipfetchall(newRemoteName, newSkipFetchAll)

        self.postStatus = _("Remote {0} added.", tquo(newRemoteName))

        if fetchAfterAdd:
            from gitfourchette.tasks import FetchRemotes
            yield from self.flowSubtask(FetchRemotes, newRemoteName)


class EditRemote(RepoTask):
    def flow(self, oldRemoteName: str):
        oldRemoteUrl = self.repo.remotes[oldRemoteName].url

        existingRemotes = [r.name for r in self.repo.remotes]
        existingRemotes.remove(oldRemoteName)

        skipFetchAllConfigKey = GitConfigHelper.sanitize_key(("remote", oldRemoteName, "skipFetchAll"))
        try:
            skipFetchAll = self.repo.config.get_bool(skipFetchAllConfigKey)
        except KeyError:
            skipFetchAll = False

        dlg = RemoteDialog(
            editExistingRemote=True,
            name=oldRemoteName,
            url=oldRemoteUrl,
            existingRemotes=existingRemotes,
            skipFetchAll=skipFetchAll,
            parent=self.parentWidget())

        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setFixedHeight(dlg.sizeHint().height())
        dlg.show()
        yield from self.flowDialog(dlg)

        newRemoteName = dlg.ui.nameEdit.text()
        newRemoteUrl = dlg.ui.urlEdit.text().strip()
        newSkipFetchAll = dlg.ui.skipFetchAllCheckBox.isChecked()
        dlg.deleteLater()

        self.effects |= TaskEffects.Refs | TaskEffects.Remotes

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

        self.repo.set_remote_skipfetchall(newRemoteName, newSkipFetchAll)

        self.postStatus = _("Remote {0} modified.", tquo(newRemoteName))


class DeleteRemote(RepoTask):
    def flow(self, remoteName: str):
        yield from self.flowConfirm(
            text=paragraphs(
                _("Really remove remote {0}?", bquo(remoteName)),
                _("This will merely detach the remote from your local repository. "
                  "The remote server itself will not be affected.")),
            verb=_("Remove remote"),
            buttonIcon="SP_DialogDiscardButton")

        self.effects |= TaskEffects.Refs | TaskEffects.Remotes

        yield from self.flowCallGit(
            "remote",
            "remove",
            *argsIf(GitDriver.supportsDashDashBeforePositionalArgs(), "--"),
            remoteName)

        self.postStatus = _("Remote {0} removed.", tquo(remoteName))
