"""
Remote access tasks.
"""

from contextlib import suppress
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskEffects
from gitfourchette.toolbox import *
from gitfourchette.forms.brandeddialog import showTextInputDialog
from gitfourchette.forms.remotelinkprogressdialog import RemoteLinkProgressDialog


class _BaseNetTask(RepoTask):
    remoteLinkDialog: RemoteLinkProgressDialog | None

    def __init__(self, parent):
        super().__init__(parent)
        self.remoteLinkDialog = None

    def effects(self) -> TaskEffects:
        return TaskEffects.Remotes

    def _showRemoteLinkDialog(self, title: str = ""):
        assert not self.remoteLinkDialog
        assert onAppThread()
        self.remoteLinkDialog = RemoteLinkProgressDialog(title, self.parentWidget())

    def cleanup(self):
        assert onAppThread()
        if self.remoteLinkDialog:
            self.remoteLinkDialog.close()
            self.remoteLinkDialog.deleteLater()
            self.remoteLinkDialog = None

    @property
    def remoteLink(self):
        return self.remoteLinkDialog.remoteLink

    def _autoDetectUpstream(self):
        branchName = self.repo.head_branch_shorthand

        try:
            branch = self.repo.branches.local[branchName]
        except KeyError:
            message = tr("Please switch to a local branch before performing this action.")
            raise AbortTask(message)

        if not branch.upstream:
            message = self.tr("Can’t fetch remote changes on {0} because this branch "
                              "isn’t tracking a remote branch.").format(bquoe(branch.shorthand))
            raise AbortTask(message)

        return branch.upstream


class DeleteRemoteBranch(_BaseNetTask):
    def flow(self, remoteBranchShorthand: str):
        assert not remoteBranchShorthand.startswith(RefPrefix.REMOTES)

        remoteName, _ = split_remote_branch_shorthand(remoteBranchShorthand)

        text = paragraphs(
            self.tr("Really delete branch {0} from the remote repository?"),
            self.tr("The remote branch will disappear for all users of remote {1}.")
            + " " + tr("This cannot be undone!")
        ).format(bquo(remoteBranchShorthand), bquo(remoteName))
        verb = self.tr("Delete on remote")
        yield from self.flowConfirm(text=text, verb=verb, buttonIcon=QStyle.StandardPixmap.SP_DialogDiscardButton)

        self._showRemoteLinkDialog()

        yield from self.flowEnterWorkerThread()
        remote = self.repo.remotes[remoteName]
        self.remoteLink.discoverKeyFiles(remote)
        self.repo.delete_remote_branch(remoteBranchShorthand, self.remoteLink)
        self.remoteLink.rememberSuccessfulKeyFile()


class RenameRemoteBranch(_BaseNetTask):
    def flow(self, remoteBranchName: str):
        assert not remoteBranchName.startswith(RefPrefix.REMOTES)
        remoteName, branchName = split_remote_branch_shorthand(remoteBranchName)
        newBranchName = branchName  # naked name, NOT prefixed with the name of the remote

        reservedNames = self.repo.listall_remote_branches().get(remoteName, [])
        with suppress(ValueError):
            reservedNames.remove(branchName)
        nameTaken = self.tr("This name is already taken by another branch on this remote.")

        dlg = showTextInputDialog(
            self.parentWidget(),
            self.tr("Rename remote branch {0}").format(tquoe(remoteBranchName)),
            self.tr("Enter new name:"),
            newBranchName,
            okButtonText=self.tr("Rename on remote"),
            validate=lambda name: nameValidationMessage(name, reservedNames, nameTaken),
            deleteOnClose=False)

        yield from self.flowDialog(dlg)
        dlg.deleteLater()

        # Naked name, NOT prefixed with the name of the remote
        newBranchName = dlg.lineEdit.text()

        self._showRemoteLinkDialog()

        yield from self.flowEnterWorkerThread()
        remote = self.repo.remotes[remoteName]
        self.remoteLink.discoverKeyFiles(remote)
        self.repo.rename_remote_branch(remoteBranchName, newBranchName, self.remoteLink)
        self.remoteLink.rememberSuccessfulKeyFile()


class FetchRemote(_BaseNetTask):
    def flow(self, remoteName: str = ""):
        if not remoteName:
            upstream = self._autoDetectUpstream()
            remoteName = upstream.remote_name

        remote = self.repo.remotes[remoteName]

        title = self.tr("Fetch remote {0}").format(lquo(remoteName))
        connectingMessage = self.tr("Connecting to remote {0}...").format(lquo(remoteName)) + "\n" + remote.url
        self._showRemoteLinkDialog(title)
        self.remoteLinkDialog.setLabelText(connectingMessage)

        yield from self.flowEnterWorkerThread()
        self.remoteLink.discoverKeyFiles(remote)
        self.repo.fetch_remote(remoteName, self.remoteLink)
        self.remoteLink.rememberSuccessfulKeyFile()


class FetchRemoteBranch(_BaseNetTask):
    def flow(self, remoteBranchName: str = ""):
        if not remoteBranchName:
            upstream = self._autoDetectUpstream()
            remoteBranchName = upstream.shorthand

        title = self.tr("Fetch remote branch {0}").format(tquoe(remoteBranchName))
        self._showRemoteLinkDialog(title)

        yield from self.flowEnterWorkerThread()

        remoteName, _ = split_remote_branch_shorthand(remoteBranchName)
        remote = self.repo.remotes[remoteName]

        self.remoteLink.discoverKeyFiles(remote)
        self.repo.fetch_remote_branch(remoteBranchName, self.remoteLink)
        self.remoteLink.rememberSuccessfulKeyFile()


class UpdateSubmodule(_BaseNetTask):
    def flow(self, submodulePath: str, init=False):
        self._showRemoteLinkDialog()
        yield from self.flowEnterWorkerThread()

        repo = self.repo
        submo = repo.submodules[submodulePath]
        subHeadOid = submo.head_id

        if repo.restore_submodule_gitlink(submodulePath):
            with RepoContext(repo.in_workdir(submodulePath)) as subrepo:
                tree = subrepo[subHeadOid].peel(Tree)
                subrepo.checkout_tree(tree)

        # TODO: Should we call discoverKeyFiles for each submodule?
        self.repo.submodules.update([submodulePath], init=init, callbacks=self.remoteLink)
