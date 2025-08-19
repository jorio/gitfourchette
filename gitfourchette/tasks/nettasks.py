# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Remote access tasks.
"""

import logging
from contextlib import suppress

from gitfourchette.forms.pushdialog import PushDialog
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.gitdriver import GitDriver, VanillaFetchStatusFlag, argsIf
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks import TaskPrereqs, RefreshRepo
from gitfourchette.tasks.branchtasks import MergeBranch
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskEffects
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)


def autoDetectUpstream(repo: Repo, noUpstreamMessage: str = ""):
    branchName = repo.head_branch_shorthand
    branch = repo.branches.local[branchName]

    if not branch.upstream:
        message = noUpstreamMessage or _("Can’t fetch new commits on {0} because this branch isn’t tracking an upstream branch.")
        message = message.format(bquoe(branch.shorthand))
        raise AbortTask(message)

    return branch.upstream


def formatUpdatedTipsMessageFromGitOutput(
        updatedTips: dict[str, tuple[str, Oid, Oid]],
        header: str,
        noNewCommits="",
        skipUpToDate=False,
) -> str:
    messages = []
    for ref in updatedTips:
        rp, rb = RefPrefix.split(ref)
        if not rp:  # no "refs/" prefix, e.g. FETCH_HEAD, etc.
            continue
        flag, oldTip, newTip = updatedTips[ref]
        if flag == VanillaFetchStatusFlag.UpToDate:
            if skipUpToDate:
                continue
            ps = _("{0} is already up to date with {1}.", tquo(rb), tquo(shortHash(oldTip)))
        elif flag == VanillaFetchStatusFlag.NewRef:
            ps = _("{0} created: {1}.", tquo(rb), shortHash(newTip))
        elif flag == VanillaFetchStatusFlag.PrunedRef:
            ps = _("{0} deleted, was {1}.", tquo(rb), shortHash(oldTip))
        else:  # ' ' (fast forward), '+' (forced update), '!' (error)
            ps = _("{0}: {1} → {2}.", tquo(rb), shortHash(oldTip), shortHash(newTip))
        messages.append(ps)
    if not messages:
        messages.append(noNewCommits or _("No new commits."))
    return " ".join([header] + messages)


class DeleteRemoteBranch(RepoTask):
    def flow(self, remoteBranchShorthand: str):
        assert not remoteBranchShorthand.startswith(RefPrefix.REMOTES)

        remoteName, branchNameOnRemote = split_remote_branch_shorthand(remoteBranchShorthand)

        text = paragraphs(
            _("Really delete branch {0} from the remote repository?", bquo(remoteBranchShorthand)),
            _("The remote branch will disappear for all users of remote {0}.", bquo(remoteName))
            + " " + _("This cannot be undone!"))
        verb = _("Delete on remote")
        yield from self.flowConfirm(text=text, verb=verb, buttonIcon="SP_DialogDiscardButton")

        self.effects |= TaskEffects.Remotes | TaskEffects.Refs
        yield from self.flowCallGit(
            "push",
            "--porcelain",
            "--progress",
            remoteName,
            "--delete",
            branchNameOnRemote,
            remote=remoteName)

        self.postStatus = _("Remote branch {0} deleted.", tquo(remoteBranchShorthand))


class RenameRemoteBranch(RepoTask):
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

        oldShorthand = remoteBranchShorthand

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
            remote=remoteName)

        new_remote_branch = repo.branches.remote[remoteName + "/" + newBranchName]
        for lb in adjustUpstreams:
            repo.branches.local[lb].upstream = new_remote_branch

        self.postStatus = _("Remote branch {0} renamed to {1}.", tquo(remoteBranchShorthand), tquo(newBranchName))


class FetchRemotes(RepoTask):
    def flow(self, singleRemoteName: str = ""):
        remotes: list[Remote] = list(self.repo.remotes)

        if len(remotes) == 0:
            text = paragraphs(
                _("To fetch remote branches, you must first add a remote to your repo."),
                _("You can do so via <i>“Repo &rarr; Add Remote”</i>."))
            raise AbortTask(text)

        """
        if singleRemoteName:
            remotes = [next(r for r in remotes if r.name == singleRemoteName)]

        if len(remotes) == 1:
            title = _("Fetch remote {0}", lquo(remotes[0].name))
        else:
            title = _("Fetch {n} remotes", n=len(remotes))
        """

        # TODO: Use title?
        # TODO: postStatus?
        self.effects |= TaskEffects.Remotes | TaskEffects.Refs
        yield from self.flowCallGit(
            "fetch",
            "--prune",
            "--progress",
            *argsIf(GitDriver.supportsFetchPorcelain(), "--porcelain", "--verbose"),
            *argsIf(bool(singleRemoteName), "--no-all", singleRemoteName),
            *argsIf(not singleRemoteName, "--all"),
            remote=singleRemoteName)


class FetchRemoteBranch(RepoTask):
    def flow(self, remoteBranchName: str = "", debrief: bool = True):
        shorthand = remoteBranchName
        if not shorthand:
            upstream = autoDetectUpstream(self.repo)
            shorthand = upstream.shorthand

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

        stdout = driver.readAll().data().decode(errors="replace")
        table = GitDriver.parseTable(r"^(.) ([0-9a-f]+) ([0-9a-f]+) (.+)$", stdout)

        updatedTips = {
            localRef: (flag, Oid(hex=oldHex), Oid(hex=newHex))
            for flag, oldHex, newHex, localRef in table
        }

        flag, oldTarget, newTarget = updatedTips[fullRemoteRef]

        self.postStatus = formatUpdatedTipsMessageFromGitOutput(
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


class PullBranch(RepoTask):
    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoUnborn | TaskPrereqs.NoDetached

    def flow(self):
        # Auto-detect the upstream now so we can bail early
        # with a helpful message if there's no upstream.
        noUpstreamMessage = _("Can’t pull new commits into {0} because this branch isn’t tracking an upstream branch.")
        autoDetectUpstream(self.repo, noUpstreamMessage)

        # First, fetch the remote branch.
        # By default, FetchRemoteBranch will fetch the upstream for the current branch.
        yield from self.flowSubtask(FetchRemoteBranch, debrief=False)

        # If we're already up to date, bail now.
        # Note that we're re-resolving the upstream branch after fetching so we have a fresh target.
        upstreamBranch = autoDetectUpstream(self.repo, noUpstreamMessage)
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


class UpdateSubmodule(RepoTask):
    def flow(self, submoduleName: str, init=True):
        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        repo = self.repo
        submodule = repo.submodules[submoduleName]
        submodulePath = submodule.path

        if repo.restore_submodule_gitlink(submodulePath):
            with RepoContext(repo.in_workdir(submodulePath)) as subrepo:
                tree = subrepo[submodule.head_id].peel(Tree)
                subrepo.checkout_tree(tree)

        yield from self.flowEnterUiThread()
        yield from self.flowCallGit(
            "submodule",
            "update",
            *argsIf(init, "--init"),
            "--",
            submodulePath)

        # The weird construct (n=1) is to stop xgettext from complaining about duplicate singular strings.
        self.postStatus = _n("Submodule updated.", "{n} submodules updated.", 1)


class UpdateSubmodulesRecursive(RepoTask):
    def flow(self):
        count = 0

        for submodule in self.repo.recurse_submodules():
            count += 1
            yield from self.flowSubtask(UpdateSubmodule, submodule.name)

        self.postStatus = _n("Submodule updated.", "{n} submodules updated.", count)


class PushRefspecs(RepoTask):
    def flow(self, remoteName: str, refspecs: list[str]):
        assert remoteName
        assert type(remoteName) is str
        assert type(refspecs) is list

        if remoteName == "*":
            remotes = list(self.repo.remotes)
        else:
            remotes = [self.repo.remotes[remoteName]]

        self.effects |= TaskEffects.Refs

        for remote in remotes:
            yield from self.flowCallGit("push", "--porcelain", "--progress", "--atomic", remote.name, *refspecs, remote=remote.name)


class PushBranch(RepoTask):
    def broadcastProcesses(self) -> bool:
        return False

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
        dialog.abortRequested.connect(self.onAbortRequested)
        self.dialog = dialog

        tryAgain = True
        while tryAgain:
            tryAgain = yield from self.attempt(dialog)

        dialog.accept()

    def onGitProgressMessage(self, message: str):
        self.dialog.ui.statusForm.setProgressMessage(message)

    def onGitProgressFraction(self, num: int, denom: int):
        self.dialog.ui.statusForm.setProgressValue(num, denom)

    def attempt(self, dialog: PushDialog):
        # ---------------
        # Show dialog

        yield from self.flowDialog(dialog, proceedSignal=dialog.startOperationButton.clicked)

        # ---------------
        # Perform the push

        command = dialog.buildCommand()
        remoteName = dialog.currentRemoteName

        dialog.setBusy(True)  # Call setBusy *after* buildCommand

        self.effects |= TaskEffects.Refs
        if "--set-upstream" in command:
            self.effects |= TaskEffects.Upstreams
        driver = yield from self.flowCallGit(*command, autoFail=False, remote=remoteName)

        gitFailed = driver.exitCode() != 0
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
        if gitFailed:
            errorText += _("Git command exited with code {0}.", driver.formatExitCode()) + "<br>"
        if "[rejected]" in summary:
            reason = summary.removeprefix("[rejected]").strip()
            errorText += btag(_("The push was rejected: {0}.", reason)) + "<br>"
        if "(stale info)" in summary:  # Git doesn't provide a hint about this, so add our own
            errorText += _(
                "Your repository’s knowledge of remote branch {branch} is out of date. "
                "The force-push was rejected to prevent data loss. "
                "Please fetch remote {remote} before pushing again.",
                branch=hquo(dialog.currentRemoteBranchFullName),
                remote=hquo(remoteName))
        errorText += GitDriver.reformatHintText(driver.stderrScrollback())

        dialog.setBusy(False)
        dialog.saveShadowUpstream()

        if gitFailed:
            QApplication.beep()
            QApplication.alert(dialog, 500)
            dialog.ui.statusForm.setBlurb(errorText)
        else:
            # self.postStatus = RemoteLink.formatUpdatedTipsMessageFromGitOutput(_("Push complete."))
            self.postStatus = _("Push complete.") + " " + summary

        return gitFailed

    def onAbortRequested(self):
        process = self.currentProcess
        if process:
            process.terminate()
