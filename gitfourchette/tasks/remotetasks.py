# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Remote management tasks.
"""

from gitfourchette.forms.remotedialog import RemoteDialog
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
            customKeyFile="",
            existingRemotes=existingRemotes,
            parent=self.parentWidget())

        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.show()
        dlg.setMaximumHeight(dlg.height())
        yield from self.flowDialog(dlg)

        newRemoteName = dlg.ui.nameEdit.text()
        newRemoteUrl = dlg.ui.urlEdit.text()
        fetchAfterAdd = dlg.ui.fetchAfterAddCheckBox.isChecked()
        dlg.deleteLater()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs | TaskEffects.Remotes
        self.repo.create_remote(newRemoteName, newRemoteUrl)

        self.postStatus = _("Remote {0} added.", tquo(newRemoteName))

        if fetchAfterAdd:
            yield from self.flowEnterUiThread()

            from gitfourchette.tasks import FetchRemotes
            yield from self.flowSubtask(FetchRemotes, newRemoteName)


class EditRemote(RepoTask):
    def flow(self, oldRemoteName: str):
        oldRemoteUrl = self.repo.remotes[oldRemoteName].url

        existingRemotes = [r.name for r in self.repo.remotes]
        existingRemotes.remove(oldRemoteName)

        dlg = RemoteDialog(
            editExistingRemote=True,
            name=oldRemoteName,
            url=oldRemoteUrl,
            customKeyFile=self.repoModel.prefs.getRemoteKeyFile(oldRemoteName),
            existingRemotes=existingRemotes,
            parent=self.parentWidget())

        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setFixedHeight(dlg.sizeHint().height())
        dlg.show()
        yield from self.flowDialog(dlg)

        newRemoteName = dlg.ui.nameEdit.text()
        newRemoteUrl = dlg.ui.urlEdit.text().strip()
        newRemoteKeyfile = dlg.privateKeyFilePath
        dlg.deleteLater()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs | TaskEffects.Remotes
        self.repo.edit_remote(oldRemoteName, newRemoteName, newRemoteUrl)
        self.repoModel.prefs.setRemoteKeyFile(newRemoteName, newRemoteKeyfile)


class DeleteRemote(RepoTask):
    def flow(self, remoteName: str):
        yield from self.flowConfirm(
            text=paragraphs(
                _("Really remove remote {0}?", bquo(remoteName)),
                _("This will merely detach the remote from your local repository. "
                  "The remote server itself will not be affected.")),
            verb=_("Remove remote"),
            buttonIcon="SP_DialogDiscardButton")

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs | TaskEffects.Remotes
        self.repo.delete_remote(remoteName)

        self.postStatus = _("Remote {0} removed.", tquo(remoteName))
