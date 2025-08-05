# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Remote access tasks.
"""

import logging
import traceback
from contextlib import suppress

from gitfourchette.forms.pushdialog import PushDialog
from gitfourchette.forms.remotelinkdialog import RemoteLinkDialog
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.remotelink import RemoteLink
from gitfourchette.tasks import TaskPrereqs, RefreshRepo
from gitfourchette.tasks.branchtasks import MergeBranch
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskEffects
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables

logger = logging.getLogger(__name__)


class _BaseNetTask(RepoTask):
    remoteLinkDialog: RemoteLinkDialog | None

    def __init__(self, parent):
        super().__init__(parent)
        self.remoteLinkDialog = None

    def _showRemoteLinkDialog(self, title: str = ""):
        assert not self.remoteLinkDialog
        assert onAppThread()
        self.remoteLinkDialog = RemoteLinkDialog(title, self.parentWidget())

    def cleanup(self):
        assert onAppThread()
        if self.remoteLinkDialog:
            self.remoteLinkDialog.close()
            self.remoteLinkDialog.deleteLater()
            self.remoteLinkDialog = None

    @property
    def remoteLink(self) -> RemoteLink:
        assert self.remoteLinkDialog is not None, "can't get RemoteLink without a RemoteLinkDialog"
        return self.remoteLinkDialog.remoteLink

    def _autoDetectUpstream(self, noUpstreamMessage: str = ""):
        branchName = self.repo.head_branch_shorthand
        branch = self.repo.branches.local[branchName]

        if not branch.upstream:
            message = noUpstreamMessage or _("Can’t fetch new commits on {0} because this branch isn’t tracking an upstream branch.")
            message = message.format(bquoe(branch.shorthand))
            raise AbortTask(message)

        return branch.upstream


class DeleteRemoteBranch(_BaseNetTask):
    def flow(self, remoteBranchShorthand: str):
        assert not remoteBranchShorthand.startswith(RefPrefix.REMOTES)

        remoteName, _remoteBranchName = split_remote_branch_shorthand(remoteBranchShorthand)

        text = paragraphs(
            _("Really delete branch {0} from the remote repository?", bquo(remoteBranchShorthand)),
            _("The remote branch will disappear for all users of remote {0}.", bquo(remoteName))
            + " " + _("This cannot be undone!"))
        verb = _("Delete on remote")
        yield from self.flowConfirm(text=text, verb=verb, buttonIcon="SP_DialogDiscardButton")

        self._showRemoteLinkDialog()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Remotes | TaskEffects.Refs

        remote = self.repo.remotes[remoteName]
        with self.remoteLink.remoteContext(remote):
            self.repo.delete_remote_branch(remoteBranchShorthand, self.remoteLink)

        self.postStatus = _("Remote branch {0} deleted.", tquo(remoteBranchShorthand))


class RenameRemoteBranch(_BaseNetTask):
    def flow(self, remoteBranchName: str):
        assert not remoteBranchName.startswith(RefPrefix.REMOTES)
        remoteName, branchName = split_remote_branch_shorthand(remoteBranchName)
        newBranchName = branchName  # naked name, NOT prefixed with the name of the remote

        reservedNames = self.repo.listall_remote_branches().get(remoteName, [])
        with suppress(ValueError):
            reservedNames.remove(branchName)
        nameTaken = _("This name is already taken by another branch on this remote.")

        dlg = TextInputDialog(
            self.parentWidget(),
            _("Rename remote branch {0}", tquoe(remoteBranchName)),
            _("WARNING: This will rename the branch for all users of the remote!") + "<br>" + _("Enter new name:"))
        dlg.setText(newBranchName)
        dlg.setValidator(lambda name: nameValidationMessage(name, reservedNames, nameTaken))
        dlg.okButton.setText(_("Rename on remote"))

        yield from self.flowDialog(dlg)
        dlg.deleteLater()

        # Naked name, NOT prefixed with the name of the remote
        newBranchName = dlg.lineEdit.text()

        self._showRemoteLinkDialog(self.name())

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Remotes | TaskEffects.Refs

        remote: Remote = self.repo.remotes[remoteName]

        # Fetch remote branch first to avoid data loss if we're out of date
        with self.remoteLink.remoteContext(remote):
            self.repo.fetch_remote_branch(remoteBranchName, self.remoteLink)

        # Rename the remote branch
        # TODO: Can we reuse the connection in a single remoteContext?
        with self.remoteLink.remoteContext(remote):
            self.repo.rename_remote_branch(remoteBranchName, newBranchName, self.remoteLink)

        self.postStatus = _("Remote branch {0} renamed to {1}.", tquo(remoteBranchName), tquo(newBranchName))


class FetchRemotes(_BaseNetTask):
    def flow(self, singleRemoteName: str = ""):
        remotes: list[Remote] = list(self.repo.remotes)

        if len(remotes) == 0:
            text = paragraphs(
                _("To fetch remote branches, you must first add a remote to your repo."),
                _("You can do so via <i>“Repo &rarr; Add Remote”</i>."))
            raise AbortTask(text)

        if singleRemoteName:
            remotes = [next(r for r in remotes if r.name == singleRemoteName)]

        if len(remotes) == 1:
            title = _("Fetch remote {0}", lquo(remotes[0].name))
        else:
            title = _("Fetch {n} remotes", n=len(remotes))

        self._showRemoteLinkDialog(title)

        errors = []
        for remote in remotes:
            # Bail if user clicked Abort button
            yield from self.flowEnterUiThread()
            assert onAppThread()
            if self.remoteLink.isAborting():
                break

            remoteName = remote.name

            self.effects |= TaskEffects.Remotes | TaskEffects.Refs
            yield from self.flowEnterWorkerThread()
            try:
                with self.remoteLink.remoteContext(remote):
                    self.repo.fetch_remote(remoteName, self.remoteLink)
            except Exception as e:
                errors.append(f"<p><b>{escape(remoteName)}</b> — {TrTables.exceptionName(e)}.<br>{escape(str(e))}</p>")

        yield from self.flowEnterUiThread()
        self.postStatus = self.remoteLink.formatUpdatedTipsMessage(_("Fetch complete."))

        # Clean up RemoteLinkDialog before showing any error text
        self.cleanup()

        if errors:
            errorMessage = _n("Couldn’t fetch remote:", "Couldn’t fetch {n} remotes:", len(errors))
            yield from self.flowConfirm(title, errorMessage, detailList=errors, canCancel=False, icon='warning')


class FetchRemoteBranch(_BaseNetTask):
    def flow(self, remoteBranchName: str = "", debrief: bool = True):
        if not remoteBranchName:
            upstream = self._autoDetectUpstream()
            remoteBranchName = upstream.shorthand

        title = _("Fetch remote branch {0}", tquoe(remoteBranchName))
        self._showRemoteLinkDialog(title)

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Remotes | TaskEffects.Refs

        remoteName, _remoteBranchName = split_remote_branch_shorthand(remoteBranchName)
        remote = self.repo.remotes[remoteName]

        oldTarget = NULL_OID
        newTarget = NULL_OID
        with suppress(KeyError):
            oldTarget = self.repo.branches.remote[remoteBranchName].target

        with self.remoteLink.remoteContext(remote):
            self.repo.fetch_remote_branch(remoteBranchName, self.remoteLink)

        with suppress(KeyError):
            newTarget = self.repo.branches.remote[remoteBranchName].target

        yield from self.flowEnterUiThread()
        self.postStatus = self.remoteLink.formatUpdatedTipsMessage(
            _("Fetch complete."), noNewCommits=_("No new commits on {0}.", lquo(remoteBranchName)))

        # Jump to new commit (if branch didn't vanish)
        if oldTarget != newTarget and newTarget != NULL_OID:
            self.jumpTo = NavLocator.inCommit(newTarget)

        # Clean up RemoteLinkDialog before showing any error text
        self.cleanup()

        if newTarget == NULL_OID:
            # Raise exception to prevent PullBranch from continuing
            raise AbortTask(_("{0} has disappeared from the remote server.", bquoe(remoteBranchName)))


class PullBranch(_BaseNetTask):
    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoUnborn | TaskPrereqs.NoDetached

    def flow(self):
        # Auto-detect the upstream now so we can bail early
        # with a helpful message if there's no upstream.
        noUpstreamMessage = _("Can’t pull new commits into {0} because this branch isn’t tracking an upstream branch.")
        self._autoDetectUpstream(noUpstreamMessage)

        # First, fetch the remote branch.
        # By default, FetchRemoteBranch will fetch the upstream for the current branch.
        yield from self.flowSubtask(FetchRemoteBranch, debrief=False)

        # If we're already up to date, bail now.
        # Note that we're re-resolving the upstream branch after fetching so we have a fresh target.
        upstreamBranch = self._autoDetectUpstream(noUpstreamMessage)
        newUpstreamTarget = upstreamBranch.target
        if self.repo.head_commit_id == newUpstreamTarget:
            self.postStatus = (
                    _p("toolbar", "Pull") + _(":") + " " +
                    _("Your local branch {0} is already up to date with {1}.",
                      tquo(self.repo.head_branch_shorthand),
                      tquo(upstreamBranch.shorthand)))
            return

        # Let user look at the new state of the graph beneath any dialog boxes.
        yield from self.flowSubtask(RefreshRepo, effectFlags=TaskEffects.Refs, jumpTo=self.jumpTo)

        # Consume jumpTo (which bubbled up from fetchSubtask) so the next subtask can override it
        self.jumpTo = NavLocator.Empty

        # Fast-forward, or merge.
        try:
            silentFastForward = self.repo.config.get_bool("pull.ff")
        except (KeyError, GitError):
            silentFastForward = True
        yield from self.flowSubtask(MergeBranch, upstreamBranch.name,
                                    silentFastForward=silentFastForward, autoFastForwardOptionName="pull.ff")


class UpdateSubmodule(_BaseNetTask):
    def flow(self, submoduleName: str, init=True):
        self._showRemoteLinkDialog()
        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        repo = self.repo
        submodule = repo.submodules[submoduleName]
        submodulePath = submodule.path

        if repo.restore_submodule_gitlink(submodulePath):
            with RepoContext(repo.in_workdir(submodulePath)) as subrepo:
                tree = subrepo[submodule.head_id].peel(Tree)
                subrepo.checkout_tree(tree)

        # Wrap update operation with RemoteLinkKeyFileContext: we need the keys
        # if the submodule uses an SSH connection.
        with self.remoteLink.remoteContext(submodule.url or ""):
            submodule.update(init=init, callbacks=self.remoteLink)

        # The weird construct (n=1) is to stop xgettext from complaining about duplicate singular strings.
        self.postStatus = _n("Submodule updated.", "{n} submodules updated.", 1)


class UpdateSubmodulesRecursive(_BaseNetTask):
    def flow(self):
        count = 0

        for submodule in self.repo.recurse_submodules():
            count += 1
            yield from self.flowSubtask(UpdateSubmodule, submodule.name)

        self.postStatus = _n("Submodule updated.", "{n} submodules updated.", count)


class PushRefspecs(_BaseNetTask):
    def flow(self, remoteName: str, refspecs: list[str]):
        assert remoteName
        assert type(remoteName) is str
        assert type(refspecs) is list

        if remoteName == "*":
            remotes = list(self.repo.remotes)
        else:
            remotes = [self.repo.remotes[remoteName]]

        self._showRemoteLinkDialog()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs

        for remote in remotes:
            with self.remoteLink.remoteContext(remote):
                remote.push(refspecs, callbacks=self.remoteLink)


class PushBranch(RepoTask):
    def flow(self, branchName: str = ""):
        if len(self.repo.remotes) == 0:
            text = paragraphs(
                _("To push a local branch to a remote, you must first add a remote to your repo."),
                _("You can do so via <i>“Repo &rarr; Add Remote”</i>."))
            raise AbortTask(text)

        try:
            if not branchName:
                branchName = self.repo.head_branch_shorthand
            branch = self.repo.branches.local[branchName]
        except (GitError, KeyError) as exc:
            raise AbortTask(_("Please switch to a local branch before performing this action.")) from exc

        dialog = PushDialog(self.repoModel, branch, self.parentWidget())
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        tryAgain = True
        while tryAgain:
            tryAgain = yield from self.attempt(dialog)

        dialog.accept()

    def attempt(self, dialog: PushDialog):
        yield from self.flowDialog(dialog, proceedSignal=dialog.startOperationButton.clicked)

        # ---------------
        # Push clicked

        if dialog.willForcePush and RemoteLink.supportsLease():
            lease = dialog.currentRemoteBranchName
        else:
            lease = None

        remote = self.repo.remotes[dialog.currentRemoteName]
        logger.info(f"Will push to: {dialog.refspec} ({remote.name})")
        link = RemoteLink(self)

        dialog.ui.statusForm.initProgress(_("Contacting remote host…"))
        link.message.connect(dialog.ui.statusForm.setProgressMessage)
        link.progress.connect(dialog.ui.statusForm.setProgressValue)

        if dialog.ui.trackCheckBox.isEnabled() and dialog.ui.trackCheckBox.isChecked():
            resetTrackingReference = dialog.currentRemoteBranchFullName
        else:
            resetTrackingReference = None

        # Look at the state of the checkboxes BEFORE calling this --  it'll disable the checkboxes!
        dialog.setRemoteLink(link)

        # ----------------
        # Task meat

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs
        if resetTrackingReference:
            self.effects |= TaskEffects.Upstreams

        error = None
        try:
            with link.remoteContext(remote):
                if lease:
                    link.setLease(remote, lease)

                remote.push([dialog.refspec], callbacks=link)

                link.clearLease()

            if resetTrackingReference:
                self.repo.edit_upstream_branch(dialog.currentLocalBranchName, resetTrackingReference)
        except Exception as exc:
            error = exc

        # ---------------
        # Debrief

        yield from self.flowEnterUiThread()
        dialog.setRemoteLink(None)
        dialog.saveShadowUpstream()
        link.deleteLater()

        if error:
            traceback.print_exception(error)
            QApplication.beep()
            QApplication.alert(dialog, 500)
            dialog.ui.statusForm.setBlurb(F"<b>{TrTables.exceptionName(error)}:</b> {escape(str(error))}")
        else:
            self.postStatus = link.formatUpdatedTipsMessage(_("Push complete."))

        return bool(error)
