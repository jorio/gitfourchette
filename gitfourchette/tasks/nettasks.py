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

from gitfourchette import settings
from gitfourchette.forms.pushdialog import PushDialog
from gitfourchette.forms.remotelinkdialog import RemoteLinkDialog
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.gitdriver import GitDriver, VanillaFetchStatusFlag, argsIf
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
    aborting: bool

    def __init__(self, parent):
        super().__init__(parent)
        self.remoteLinkDialog = None
        self.aborting = False

    def _showRemoteLinkDialog(self, title: str = ""):
        assert not self.remoteLinkDialog
        assert onAppThread()
        self.remoteLinkDialog = RemoteLinkDialog(title, self.parentWidget())
        self.remoteLinkDialog.abortButtonClicked.connect(self.abortCurrentProcess)

    def cleanup(self):
        assert onAppThread()
        if self.remoteLinkDialog:
            self.remoteLinkDialog.close()
            self.remoteLinkDialog.deleteLater()
            self.remoteLinkDialog = None

    @property
    def remoteLink(self) -> RemoteLink:
        assert not settings.prefs.vanillaGit, "can't get RemoteLink with vanilla git backend"
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

    def onGitProgressMessage(self, message: str):
        if not self.aborting and self.remoteLinkDialog:
            self.remoteLinkDialog.setStatusText(message)

    def onGitProgressFraction(self, num: int, denom: int):
        if not self.aborting and self.remoteLinkDialog:
            self.remoteLinkDialog.onRemoteLinkProgress(num, denom)

    def abortCurrentProcess(self):
        self.aborting = True
        if self.currentProcess:
            self.currentProcess.terminate()


class DeleteRemoteBranch(_BaseNetTask):
    def flow(self, remoteBranchShorthand: str):
        assert not remoteBranchShorthand.startswith(RefPrefix.REMOTES)

        remoteName, branchNameOnRemote = split_remote_branch_shorthand(remoteBranchShorthand)

        text = paragraphs(
            _("Really delete branch {0} from the remote repository?", bquo(remoteBranchShorthand)),
            _("The remote branch will disappear for all users of remote {0}.", bquo(remoteName))
            + " " + _("This cannot be undone!"))
        verb = _("Delete on remote")
        yield from self.flowConfirm(text=text, verb=verb, buttonIcon="SP_DialogDiscardButton")

        self._showRemoteLinkDialog()

        impl = self._withGit if settings.prefs.vanillaGit else self._withLibgit2
        yield from impl(remoteBranchShorthand, remoteName, branchNameOnRemote)

        self.postStatus = _("Remote branch {0} deleted.", tquo(remoteBranchShorthand))

    def _withLibgit2(self, remoteBranchShorthand: str, remoteName: str, branchNameOnRemote: str):
        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Remotes | TaskEffects.Refs

        remote = self.repo.remotes[remoteName]
        with self.remoteLink.remoteContext(remote):
            self.repo.delete_remote_branch(remoteBranchShorthand, self.remoteLink)

    def _withGit(self, remoteBranchShorthand: str, remoteName: str, branchNameOnRemote: str):
        self.effects |= TaskEffects.Remotes | TaskEffects.Refs
        yield from self.flowCallGit(
            "push",
            "--porcelain",
            "--progress",
            remoteName,
            "--delete",
            branchNameOnRemote,
            remote=remoteName,
        )


class RenameRemoteBranch(_BaseNetTask):
    def flow(self, remoteBranchShorthand: str):
        assert not remoteBranchShorthand.startswith(RefPrefix.REMOTES)
        remoteName, branchName = split_remote_branch_shorthand(remoteBranchShorthand)
        newBranchName = branchName  # naked name, NOT prefixed with the name of the remote

        reservedNames = self.repo.listall_remote_branches().get(remoteName, [])
        with suppress(ValueError):
            reservedNames.remove(branchName)
        nameTaken = _("This name is already taken by another branch on this remote.")

        dlg = TextInputDialog(
            self.parentWidget(),
            _("Rename remote branch {0}", tquoe(remoteBranchShorthand)),
            _("WARNING: This will rename the branch for all users of the remote!") + "<br>" + _("Enter new name:"))
        dlg.setText(newBranchName)
        dlg.setValidator(lambda name: nameValidationMessage(name, reservedNames, nameTaken))
        dlg.okButton.setText(_("Rename on remote"))

        yield from self.flowDialog(dlg)
        dlg.deleteLater()

        # Naked name, NOT prefixed with the name of the remote
        newBranchName = dlg.lineEdit.text()

        self._showRemoteLinkDialog(self.name())

        impl = self._withGit if settings.prefs.vanillaGit else self._withLibgit2
        yield from impl(remoteName, remoteBranchShorthand, newBranchName)

        self.postStatus = _("Remote branch {0} renamed to {1}.", tquo(remoteBranchShorthand), tquo(newBranchName))

    def _withLibgit2(self, remoteName: str, remoteBranchShorthand: str, newBranchName: str):
        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Remotes | TaskEffects.Refs

        remote: Remote = self.repo.remotes[remoteName]

        # Fetch remote branch first to avoid data loss if we're out of date
        with self.remoteLink.remoteContext(remote):
            self.repo.fetch_remote_branch(remoteBranchShorthand, self.remoteLink)

        # Rename the remote branch
        # TODO: Can we reuse the connection in a single remoteContext?
        with self.remoteLink.remoteContext(remote):
            self.repo.rename_remote_branch(remoteBranchShorthand, newBranchName, self.remoteLink)

    def _withGit(self, remoteName: str, oldShorthand: str, newBranchName: str):
        repo = self.repo
        _remoteName, oldBranchName = split_remote_branch_shorthand(oldShorthand)
        oldRemoteRef = RefPrefix.REMOTES + oldShorthand

        # Find local branches using this upstream
        adjustUpstreams: list[str] = []
        for lb in repo.branches.local:
            with suppress(KeyError):  # KeyError if upstream branch doesn't exist
                if repo.branches.local[lb].upstream_name == oldRemoteRef:
                    adjustUpstreams.append(lb)

        self.effects |= TaskEffects.Remotes | TaskEffects.Refs

        # First, make a new branch pointing to the same ref as the old one
        refspec1 = f"{RefPrefix.REMOTES}{oldShorthand}:{RefPrefix.HEADS}{newBranchName}"

        # Next, delete the old branch
        refspec2 = f":{RefPrefix.HEADS}{oldBranchName}"

        logger.info(f"Rename remote branch: remote: {remoteName}; refspec: {[refspec1, refspec2]}; "
                    f"adjust upstreams: {adjustUpstreams}")

        # For safety, make sure we're up to date on this branch
        yield from self.flowSubtask(FetchRemoteBranch, oldShorthand)

        # Then go ahead with the push
        yield from self.flowCallGit(
            "push",
            "--porcelain",
            "--progress",
            "--atomic",
            remoteName,
            refspec1,
            refspec2,
            remote=remoteName,
        )

        new_remote_branch = repo.branches.remote[remoteName + "/" + newBranchName]
        for lb in adjustUpstreams:
            repo.branches.local[lb].upstream = new_remote_branch


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

        if settings.prefs.vanillaGit:
            yield from self._withGit(title, singleRemoteName)
        else:
            yield from self._withLibgit2(title, remotes)

    def _withLibgit2(self, title: str, remotes: list[Remote]):
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

    def _withGit(self, title: str, singleRemoteName: str = ""):
        # TODO: postStatus?
        self.effects |= TaskEffects.Remotes | TaskEffects.Refs
        yield from self.flowCallGit(
            "fetch",
            "--prune",
            "--progress",
            *argsIf(GitDriver.supportsFetchPorcelain(), "--porcelain", "--verbose"),
            *argsIf(singleRemoteName, "--no-all", singleRemoteName),
            *argsIf(not singleRemoteName, "--all"),
            remote=singleRemoteName)


class FetchRemoteBranch(_BaseNetTask):
    def flow(self, remoteBranchName: str = "", debrief: bool = True):
        impl = self._withGit if settings.prefs.vanillaGit else self._withLibgit2
        yield from impl(remoteBranchName, debrief)

    def _withLibgit2(self, remoteBranchName: str = "", debrief: bool = True):
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

    def _withGit(self, shorthand: str = "", debrief: bool = True):
        if not shorthand:
            upstream = self._autoDetectUpstream()
            shorthand = upstream.shorthand

        title = _("Fetch remote branch {0}", tquoe(shorthand))
        self._showRemoteLinkDialog(title)

        remoteName, remoteBranch = split_remote_branch_shorthand(shorthand)
        fullRemoteRef = RefPrefix.REMOTES + shorthand

        self.effects |= TaskEffects.Remotes | TaskEffects.Refs

        driver = yield from self.flowCallGit(
            "fetch",
            "--progress",
            "--no-tags",
            *argsIf(GitDriver.supportsFetchPorcelain(), "--porcelain", "--verbose"),
            remoteName,
            remoteBranch,
            remote=remoteName)

        # Old git: don't attempt to parse the result
        if not GitDriver.supportsFetchPorcelain():
            self.cleanup()
            return

        stdout = driver.readAll().data()
        table = GitDriver.parseTable(r"^(.) ([0-9a-f]+) ([0-9a-f]+) (.+)$", stdout)

        updatedTips = {
            localRef: (flag, Oid(hex=oldHex), Oid(hex=newHex))
            for flag, oldHex, newHex, localRef in table
        }

        flag, oldTarget, newTarget = updatedTips[fullRemoteRef]

        self.postStatus = RemoteLink.formatUpdatedTipsMessageFromGitOutput(
            updatedTips,
            _("Fetch complete."),
            noNewCommits=_("No new commits on {0}.", lquo(shorthand)),
            skipUpToDate=True)

        # Jump to new commit if there was an update and the branch didn't vanish
        if flag not in [VanillaFetchStatusFlag.UpToDate, VanillaFetchStatusFlag.PrunedRef]:
            self.jumpTo = NavLocator.inCommit(newTarget)

        # Clean up RemoteLinkDialog before showing any error text
        self.cleanup()

        if flag == VanillaFetchStatusFlag.PrunedRef:
            # Raise exception to prevent PullBranch from continuing
            # TODO: This does not actually occur when fetching a single branch!
            raise AbortTask(_("{0} has disappeared from the remote server.", bquoe(shorthand)))


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

        if settings.prefs.vanillaGit:
            yield from self.flowEnterUiThread()
            yield from self.flowCallGit(
                "submodule",
                "update",
                *argsIf(init, "--init"),
                "--",
                submodulePath)
        else:
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

        impl = self._withGit if settings.prefs.vanillaGit else self._withLibgit2
        yield from impl(remotes, refspecs)

    def _withLibgit2(self, remotes: list[Remote], refspecs: list[str]):
        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs

        for remote in remotes:
            with self.remoteLink.remoteContext(remote):
                remote.push(refspecs, callbacks=self.remoteLink)

    def _withGit(self, remotes: list[Remote], refspecs: list[str]):
        self.effects |= TaskEffects.Refs

        for remote in remotes:
            yield from self.flowCallGit("push", "--porcelain", "--progress", "--atomic", remote.name, *refspecs, remote=remote.name)


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

        impl = self.attemptWithGit if settings.prefs.vanillaGit else self.attemptWithLibgit2

        tryAgain = True
        while tryAgain:
            tryAgain = yield from impl(dialog)

        dialog.accept()

    def attemptWithGit(self, dialog: PushDialog):
        yield from self.flowDialog(dialog, proceedSignal=dialog.startOperationButton.clicked)

        # ---------------
        # Push clicked

        remote = self.repo.remotes[dialog.currentRemoteName]
        refspec = dialog.refspec(withForcePrefix=False)  # no '+' prefix -- we control force via arguments to git
        logger.info(f"Will push to: {refspec} ({remote.name})")
        link = RemoteLink(self)

        dialog.ui.statusForm.initProgress(_("Contacting remote host…"))
        link.message.connect(dialog.ui.statusForm.setProgressMessage)
        link.progress.connect(dialog.ui.statusForm.setProgressValue)

        resetTrackingReference = dialog.ui.trackCheckBox.isEnabled() and dialog.ui.trackCheckBox.isChecked()

        # Look at the state of the checkboxes BEFORE calling this --  it'll disable the checkboxes!
        dialog.setRemoteLink(link)

        # ----------------
        # Task meat

        self.effects |= TaskEffects.Refs
        if resetTrackingReference:
            self.effects |= TaskEffects.Upstreams

        driver = yield from self.flowCallGit(
            "push",
            "--porcelain",
            "--progress",
            *argsIf(dialog.willForcePush, "--force-with-lease"),
            *argsIf(resetTrackingReference, "--set-upstream"),
            remote.name,
            refspec,
            autoFail=False,
            remote=remote.name)
        stdout = driver.readAll().data().decode(errors="replace")

        # ---------------
        # Debrief

        # Output format: "<flag> \t <from(local)>:<to(remote)> \t <summary> (<reason>)"
        # But the first and last lines may contain other junk,
        # so skip lines that don't match the pattern (strict=False).
        table = GitDriver.parseTable("(.)\t(.+):(.+)\t(.+)", stdout, strict=False)

        # Capture summary for the last pushed branch.
        try:
            summary = table[-1][-1]
        except IndexError:
            summary = ""

        errorText = "<p style='white-space: pre-wrap'>"
        if "[rejected]" in summary:
            reason = summary.removeprefix("[rejected]").strip()
            errorText += btag(_("The push was rejected: {0}.", reason)) + "<br>"
        if "(stale info)" in summary:  # Git doesn't provide a hint about this, so add our own
            errorText += _(
                "Your repository’s knowledge of remote branch {branch} is out of date. "
                "The force-push was rejected to prevent data loss. "
                "Please fetch remote {remote} before pushing again.",
                branch=hquo(dialog.currentRemoteBranchFullName),
                remote=hquo(remote.name))
        errorText += GitDriver.reformatHintText(driver.stderrScrollback())

        dialog.setRemoteLink(None)
        dialog.saveShadowUpstream()
        link.deleteLater()

        if driver.exitCode() != 0:
            QApplication.beep()
            QApplication.alert(dialog, 500)
            dialog.ui.statusForm.setBlurb(errorText)
        else:
            # self.postStatus = RemoteLink.formatUpdatedTipsMessageFromGitOutput(_("Push complete."))
            self.postStatus = _("Push complete.") + " " + summary

        return driver.exitCode() != 0

    def attemptWithLibgit2(self, dialog: PushDialog):
        yield from self.flowDialog(dialog, proceedSignal=dialog.startOperationButton.clicked)

        # ---------------
        # Push clicked

        if dialog.willForcePush and RemoteLink.supportsLease():
            lease = dialog.currentRemoteBranchName
        else:
            lease = None

        remote = self.repo.remotes[dialog.currentRemoteName]
        refspec = dialog.refspec(withForcePrefix=True)
        logger.info(f"Will push to: {refspec} ({remote.name})")
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

                remote.push([refspec], callbacks=link)

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
