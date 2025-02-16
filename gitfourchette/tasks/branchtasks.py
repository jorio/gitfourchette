# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging

from gitfourchette.forms.newbranchdialog import NewBranchDialog
from gitfourchette.forms.resetheaddialog import ResetHeadDialog
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskPrereqs, TaskEffects
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)


class SwitchBranch(RepoTask):
    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoConflicts

    def flow(self, newBranch: str, askForConfirmation: bool = True, recurseSubmodules: bool = False):
        assert not newBranch.startswith(RefPrefix.HEADS)

        branchObj: Branch = self.repo.branches.local[newBranch]

        if branchObj.is_checked_out():
            message = _("Branch {0} is already checked out.", bquo(newBranch))
            raise AbortTask(message, 'information')

        if askForConfirmation:
            text = _("Do you want to switch to branch {0}?", bquo(newBranch))
            verb = _("Switch")

            recurseCheckbox = None
            anySubmodules = bool(self.repo.listall_submodules_fast())
            anySubmodules &= pygit2_version_at_least("1.15.1", False)  # TODO: Nuke this once we can drop support for old versions of pygit2
            if anySubmodules:
                recurseCheckbox = QCheckBox(_("Update submodules recursively"))
                recurseCheckbox.setChecked(True)

            yield from self.flowConfirm(text=text, verb=verb, checkbox=recurseCheckbox)
            recurseSubmodules = recurseCheckbox is not None and recurseCheckbox.isChecked()

        headId = self.repoModel.headCommitId
        if self.repoModel.dangerouslyDetachedHead() and branchObj.target != headId:
            text = paragraphs(
                _("You are in <b>Detached HEAD</b> mode at commit {0}.", btag(shortHash(headId))),
                _("You might lose track of this commit if you carry on switching to {0}.", hquo(newBranch)))
            yield from self.flowConfirm(text=text, icon='warning')

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs | TaskEffects.Head

        self.repo.checkout_local_branch(newBranch)

        self.postStatus = _("Switched to branch {0}.", tquo(newBranch))

        if recurseSubmodules:
            from gitfourchette.tasks import UpdateSubmodulesRecursive
            yield from self.flowEnterUiThread()
            yield from self.flowSubtask(UpdateSubmodulesRecursive)


class RenameBranch(RepoTask):
    def flow(self, oldBranchName: str):
        assert not oldBranchName.startswith(RefPrefix.HEADS)

        forbiddenBranchNames = self.repo.listall_branches(BranchType.LOCAL)
        forbiddenBranchNames.remove(oldBranchName)

        nameTaken = _("This name is already taken by another local branch.")

        dlg = TextInputDialog(
            self.parentWidget(),
            _("Rename local branch"),
            _("Enter new name:"),
            subtitle=_("Current name: {0}", oldBranchName))
        dlg.setText(oldBranchName)
        dlg.setValidator(lambda name: nameValidationMessage(name, forbiddenBranchNames, nameTaken))
        dlg.okButton.setText(_("Rename"))

        yield from self.flowDialog(dlg)
        dlg.deleteLater()
        newBranchName = dlg.lineEdit.text()

        # Bail if identical to dodge AlreadyExistsError
        if newBranchName == oldBranchName:
            raise AbortTask()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs

        self.repo.rename_local_branch(oldBranchName, newBranchName)

        self.postStatus = _("Branch {0} renamed to {1}.", tquo(oldBranchName), tquo(newBranchName))


class RenameBranchFolder(RepoTask):
    def flow(self, oldFolderRefName: str):
        prefix, oldFolderName = RefPrefix.split(oldFolderRefName)
        assert prefix == RefPrefix.HEADS
        assert not oldFolderName.endswith("/")
        oldFolderNameSlash = oldFolderName + "/"

        forbiddenBranches = set()
        folderBranches = []
        for oldBranchName in self.repo.listall_branches(BranchType.LOCAL):
            if oldBranchName.startswith(oldFolderNameSlash):
                folderBranches.append(oldBranchName)
            else:
                forbiddenBranches.add(oldBranchName)

        def transformBranchName(branchName: str, newFolderName: str) -> str:
            assert branchName.startswith(oldFolderName)
            newBranchName = newFolderName + branchName.removeprefix(oldFolderName)
            newBranchName = newBranchName.removeprefix("/")
            return newBranchName

        def validate(newFolderName: str) -> str:
            for oldBranchName in folderBranches:
                newBranchName = transformBranchName(oldBranchName, newFolderName)
                if newBranchName in forbiddenBranches:
                    return _("This name clashes with existing branch {0}.", tquo(newBranchName))
            # Finally validate the folder name itself as if it were a branch,
            # but don't test against existing refs (which we just did above),
            # and allow an empty name.
            if not newFolderName:
                return ""
            return nameValidationMessage(newFolderName, [])

        subtitle = _n("Folder {name} contains {n} branch.",
                      "Folder {name} contains {n} branches.",
                      len(folderBranches), name=lquoe(oldFolderName))

        dlg = TextInputDialog(
            self.parentWidget(),
            _("Rename branch folder"),
            _("Enter new name:"),
            subtitle=subtitle)
        dlg.setText(oldFolderName)
        dlg.setValidator(validate)
        dlg.okButton.setText(_("Rename"))
        dlg.lineEdit.setPlaceholderText(_("Leave blank to move the branches to the root folder."))

        yield from self.flowDialog(dlg)
        dlg.deleteLater()

        newFolderName = dlg.lineEdit.text()

        # Bail if identical to dodge AlreadyExistsError
        if newFolderName == oldFolderName:
            raise AbortTask()

        # Perform rename
        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs

        for oldBranchName in folderBranches:
            newBranchName = transformBranchName(oldBranchName, newFolderName)
            self.repo.rename_local_branch(oldBranchName, newBranchName)

        self.postStatus = (
                _("Branch folder {0} renamed to {1}.", tquo(oldFolderName), tquo(newFolderName))
                + " "
                + _n("{n} branch affected.", "{n} branches affected.", len(folderBranches))
        )

class DeleteBranch(RepoTask):
    def flow(self, localBranchName: str):
        assert not localBranchName.startswith(RefPrefix.HEADS)

        if localBranchName == self.repo.head_branch_shorthand:
            text = paragraphs(
                _("Cannot delete {0} because it is the current branch.", bquo(localBranchName)),
                _("Before you try again, switch to another branch."))
            raise AbortTask(text)

        text = paragraphs(_("Really delete local branch {0}?", bquo(localBranchName)),
                          _("This cannot be undone!"))

        yield from self.flowConfirm(
            text=text,
            verb=_("Delete branch"),
            buttonIcon="SP_DialogDiscardButton")

        yield from self.flowEnterWorkerThread()
        target = self.repo.branches[localBranchName].target
        self.effects |= TaskEffects.Refs
        self.repo.delete_local_branch(localBranchName)

        self.postStatus = _("Branch {0} deleted (commit at tip was {1}).",
                            tquo(localBranchName), tquo(shortHash(target)))


class DeleteBranchFolder(RepoTask):
    def flow(self, folderRefName: str):
        prefix, folderName = RefPrefix.split(folderRefName)
        assert prefix == RefPrefix.HEADS
        assert not folderName.endswith("/")
        folderNameSlash = folderName + "/"

        currentBranch = self.repo.head_branch_shorthand
        if currentBranch.startswith(folderNameSlash):
            text = paragraphs(
                _("Cannot delete folder {0} because it contains the current branch {1}.", bquo(folderName), bquo(currentBranch)),
                _("Before you try again, switch to another branch."))
            raise AbortTask(text)

        folderBranches = [b for b in self.repo.listall_branches(BranchType.LOCAL)
                          if b.startswith(folderNameSlash)]

        text = paragraphs(
            _("Really delete local branch folder {0}?", bquo(folderName)),
            _n("<b>{n}</b> branch will be deleted.", "<b>{n}</b> branches will be deleted.", n=len(folderBranches)
               ) + " " + _("This cannot be undone!"))

        yield from self.flowConfirm(
            _("Delete branch folder"),
            text,
            detailList=folderBranches,
            verb=_("Delete folder"),
            buttonIcon="SP_DialogDiscardButton")

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs

        for b in folderBranches:
            self.repo.delete_local_branch(b)

        self.postStatus = _n("{n} branch deleted in folder {name}.",
                             "{n} branches deleted in folder {name}.",
                             n=len(folderBranches), name=tquo(folderName))


class _NewBranchBaseTask(RepoTask):
    TRACK_ANY_UPSTREAM = ".ANY"

    def _internalFlow(self, tip: Oid, localName: str = "", trackUpstream: str = TRACK_ANY_UPSTREAM):
        repo = self.repo

        tipHashText = shortHash(tip)

        # Are we creating a branch at the tip of the current branch?
        if not repo.head_is_unborn and not repo.head_is_detached and repo.head.target == tip:
            # Let user know that's the HEAD
            tipHashText = f"HEAD ({tipHashText})"

            # Default to the current branch's name (if no name given)
            if not localName:
                localName = repo.head.shorthand

        # Collect upstream names and set initial localName (if we haven't been able to set it above).
        refsPointingHere = repo.listall_refs_pointing_at(tip)
        upstreams = []
        for r in refsPointingHere:
            prefix, shorthand = RefPrefix.split(r)
            if prefix == RefPrefix.HEADS:
                if not localName:
                    localName = shorthand
                branch = repo.branches[shorthand]
                if branch.upstream:
                    upstreams.append(branch.upstream.shorthand)
            elif prefix == RefPrefix.REMOTES:
                if not localName:
                    _prefix, localName = split_remote_branch_shorthand(shorthand)
                upstreams.append(shorthand)

        # Start with a unique name so the branch validator doesn't shout at us
        forbiddenBranchNames = repo.listall_branches(BranchType.LOCAL)
        localName = withUniqueSuffix(localName, forbiddenBranchNames)

        # Ensure no duplicate upstreams (stable order since Python 3.7+)
        upstreams = list(dict.fromkeys(upstreams))

        forbiddenBranchNames = repo.listall_branches(BranchType.LOCAL)

        commitMessage = repo.get_commit_message(tip)
        commitMessage, junk = messageSummary(commitMessage)

        dlg = NewBranchDialog(
            initialName=localName,
            target=tipHashText,
            targetSubtitle=commitMessage,
            upstreams=upstreams,
            reservedNames=forbiddenBranchNames,
            allowSwitching=not self.repo.any_conflicts,
            parent=self.parentWidget())

        if not repo.listall_submodules_fast():
            dlg.ui.recurseSubmodulesCheckBox.setChecked(False)
            dlg.ui.recurseSubmodulesCheckBox.setVisible(False)

        if trackUpstream == self.TRACK_ANY_UPSTREAM:
            trackUpstream = ""
        elif trackUpstream:
            i = dlg.ui.upstreamComboBox.findText(trackUpstream)
            found = i >= 0
            if found:
                dlg.ui.upstreamComboBox.setCurrentIndex(i)

        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setFixedHeight(dlg.sizeHint().height())
        dlg.show()
        yield from self.flowDialog(dlg)
        dlg.deleteLater()

        localName = dlg.ui.nameEdit.text()
        trackUpstream = ""
        switchTo = dlg.ui.switchToBranchCheckBox.isChecked()
        recurseSubmodules = dlg.ui.recurseSubmodulesCheckBox.isChecked()
        if dlg.ui.upstreamCheckBox.isChecked():
            trackUpstream = dlg.ui.upstreamComboBox.currentText()

        yield from self.flowEnterWorkerThread()

        # Create local branch
        repo.create_branch_from_commit(localName, tip)
        self.effects |= TaskEffects.Refs | TaskEffects.Head | TaskEffects.Upstreams
        self.postStatus = _("Branch {0} created on commit {1}.", tquo(localName), tquo(shortHash(tip)))

        # Optionally make it track a remote branch
        if trackUpstream:
            repo.edit_upstream_branch(localName, trackUpstream)

        # Switch to it last (if user wants to)
        if switchTo:
            headId = self.repoModel.headCommitId
            if self.repoModel.dangerouslyDetachedHead() and tip != headId:
                yield from self.flowEnterUiThread()

                # Refresh GraphView underneath dialog
                from gitfourchette.tasks import RefreshRepo
                yield from self.flowSubtask(RefreshRepo)

                text = paragraphs(
                    _("You are in <b>Detached HEAD</b> mode at commit {0}.", btag(shortHash(headId))),
                    _("You might lose track of this commit if you switch to the new branch."))
                yield from self.flowConfirm(text=text, icon='warning', verb=_("Switch to {0}", lquoe(localName)), cancelText=_("Don’t Switch"))

            repo.checkout_local_branch(localName)

            if recurseSubmodules:
                from gitfourchette.tasks.nettasks import UpdateSubmodulesRecursive
                yield from self.flowEnterUiThread()
                yield from self.flowSubtask(UpdateSubmodulesRecursive)


class NewBranchFromHead(_NewBranchBaseTask):
    def prereqs(self):
        return TaskPrereqs.NoUnborn

    def flow(self):
        tip = self.repo.head_commit.id

        # Initialize upstream to the current branch's upstream, if any
        try:
            headBranchName = self.repo.head.shorthand
            branch = self.repo.branches.local[headBranchName]
            upstream = branch.upstream.shorthand if branch.upstream else ""
            yield from self._internalFlow(tip, trackUpstream=upstream)
        except KeyError:  # e.g. detached HEAD
            # Pick any upstream
            yield from self._internalFlow(tip)


class NewBranchFromCommit(_NewBranchBaseTask):
    def flow(self, tip: Oid):
        yield from self._internalFlow(tip)


class NewBranchFromRef(_NewBranchBaseTask):
    def flow(self, refname: str):
        prefix, name = RefPrefix.split(refname)

        if prefix == RefPrefix.HEADS:
            branch = self.repo.branches.local[name]
            upstream = branch.upstream.shorthand if branch.upstream else ""

        elif prefix == RefPrefix.REMOTES:
            branch = self.repo.branches.remote[name]
            upstream = branch.shorthand
            name = name.removeprefix(branch.remote_name + "/")

        else:
            raise NotImplementedError(f"Unsupported prefix for refname '{refname}'")

        yield from self._internalFlow(branch.target, name, trackUpstream=upstream)


class EditUpstreamBranch(RepoTask):
    def flow(self, localBranchName: str, remoteBranchName: str):
        # Bail if no-op
        currentUpstream = self.repo.branches.local[localBranchName].upstream
        currentUpstreamName = "" if not currentUpstream else currentUpstream.branch_name
        if remoteBranchName == currentUpstreamName:
            raise AbortTask()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Upstreams
        self.repo.edit_upstream_branch(localBranchName, remoteBranchName)
        self.repoModel.prefs.setShadowUpstream(localBranchName, "")  # Clear any shadow upstream

        if remoteBranchName:
            self.postStatus = _("Branch {0} now tracks {1}.", tquo(localBranchName), tquo(remoteBranchName))
        else:
            self.postStatus = _("Branch {0} now tracks no upstream.", tquo(localBranchName))


class ResetHead(RepoTask):
    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoUnborn | TaskPrereqs.NoDetached

    def flow(self, onto: Oid):
        branchName = self.repo.head_branch_shorthand
        commitMessage = self.repo.get_commit_message(onto)
        submoduleDict = self.repo.listall_submodules_dict(absolute_paths=True)
        hasSubmodules = bool(submoduleDict)

        dlg = ResetHeadDialog(onto, branchName, commitMessage, hasSubmodules, parent=self.parentWidget())

        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)  # don't leak dialog
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.resize(600, 128)
        yield from self.flowDialog(dlg)
        resetMode = dlg.activeMode
        recurseSubmodules = dlg.recurseSubmodules()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs | TaskEffects.Workdir

        self.repo.reset(onto, resetMode)
        self.postStatus = _("Branch {0} was reset to {1} ({mode}).",
                            tquo(branchName), tquo(shortHash(onto)), mode=resetMode.name.lower())

        if hasSubmodules and recurseSubmodules:
            for submodule in self.repo.recurse_submodules():
                subOnto = submodule.head_id
                logger.info(f"Reset {repr(resetMode)}: Submodule '{submodule.name}' --> {shortHash(subOnto)}")
                with RepoContext(submodule.open()) as subRepo:
                    subRepo.reset(subOnto, resetMode)


class FastForwardBranch(RepoTask):
    def flow(self, localBranchName: str = ""):
        if not localBranchName:
            self.checkPrereqs(TaskPrereqs.NoUnborn | TaskPrereqs.NoDetached)
            localBranchName = self.repo.head_branch_shorthand

        branch = self.repo.branches.local[localBranchName]
        upstream: Branch = branch.upstream
        if not upstream:
            raise AbortTask(_("Can’t fast-forward {0} because it isn’t tracking an upstream branch.",
                              bquo(branch.shorthand)))

        remoteBranchName = upstream.shorthand

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs | TaskEffects.Head

        upToDate = self.repo.fast_forward_branch(localBranchName, remoteBranchName)

        ahead = False
        if upToDate:
            ahead = upstream.target != branch.target

        self.jumpTo = NavLocator.inRef(RefPrefix.HEADS + localBranchName)

        yield from self.flowEnterUiThread()

        if upToDate:
            lines = [_("No fast-forwarding necessary.")]
            if ahead:
                lines.append(_("Your local branch {0} is ahead of {1}."))
            else:
                lines.append(_("Your local branch {0} is already up to date with {1}."))
            message = paragraphs(lines).format(bquo(localBranchName), bquo(remoteBranchName))
            self.postStatus = stripHtml(message)
            yield from self.flowConfirm(text=message, canCancel=False, dontShowAgainKey="NoFastForwardingNecessary")

    def onError(self, exc):
        if isinstance(exc, DivergentBranchesError):
            parentWidget = self.parentWidget()

            lb = exc.local_branch
            rb = exc.remote_branch
            text = paragraphs(
                _("Can’t fast-forward {0} to {1}.", bquo(lb.shorthand), bquo(rb.shorthand)),
                _("The branches are divergent."))
            qmb = showWarning(parentWidget, self.name(), text)

            # If it's the checked-out branch, suggest merging
            if lb.is_checked_out():
                mergeCaption = _("Merge into {0}", lquoe(lb.shorthand))
                mergeButton = qmb.addButton(mergeCaption, QMessageBox.ButtonRole.ActionRole)
                mergeButton.clicked.connect(lambda: MergeBranch.invoke(parentWidget, rb.name))
        else:
            super().onError(exc)


class MergeBranch(RepoTask):
    def flow(self, them: str, silentFastForward=False, autoFastForwardOptionName=""):
        assert them.startswith('refs/')

        theirBranch, theirBranchIsRemote = self.repo.get_branch_from_refname(them)
        assert isinstance(theirBranch, Branch)
        _theirPrefix, theirShorthand = RefPrefix.split(them)

        # Run merge analysis on background thread
        yield from self.flowEnterWorkerThread()
        self.repo.refresh_index()
        anyStagedFiles = self.repo.any_staged_changes
        anyConflicts = self.repo.any_conflicts
        myShorthand = self.repo.head_branch_shorthand
        target = theirBranch.target
        assert theirBranch.type == ReferenceType.DIRECT
        assert isinstance(target, Oid), "branch isn't a direct reference!"
        analysis, pref = self.repo.merge_analysis(target)
        wantMergeCommit = True

        yield from self.flowEnterUiThread()
        logger.info(f"Merge analysis: {repr(analysis)} {repr(pref)}")

        if anyConflicts:
            message = paragraphs(
                _("Merging is not possible right now because you have unresolved conflicts."),
                _("Fix the conflicts to proceed."))
            raise AbortTask(message)

        elif anyStagedFiles:
            message = paragraphs(
                _("Merging is not possible right now because you have staged changes."),
                _("Commit your changes or stash them to proceed."))
            raise AbortTask(message)

        elif analysis == MergeAnalysis.UP_TO_DATE:
            message = paragraphs(
                _("No merge is necessary."),
                _("Your branch {0} is already up to date with {1}.", bquo(myShorthand), bquo(theirShorthand)))
            raise AbortTask(message, icon="information")

        elif analysis == MergeAnalysis.UNBORN:
            message = _("Cannot merge into an unborn head.")
            raise AbortTask(message)

        elif analysis == MergeAnalysis.FASTFORWARD | MergeAnalysis.NORMAL:
            if silentFastForward:
                wantMergeCommit = False
            else:
                wantMergeCommit = yield from self.confirmFastForward(myShorthand, theirShorthand, target, autoFastForwardOptionName)

        elif analysis == MergeAnalysis.NORMAL:
            title = _("Merging may cause conflicts")
            message = paragraphs(
                _("Merging {0} into {1} may cause conflicts.", bquo(theirShorthand), bquo(myShorthand)),
                _("You will need to fix the conflicts, if any. Then, commit the result to conclude the merge."))
            yield from self.flowConfirm(title=title, text=message, verb=_("Merge"),
                                        dontShowAgainKey="MergeMayCauseConflicts")

        else:
            raise NotImplementedError(f"Unsupported MergeAnalysis! ma={repr(analysis)} mp={repr(pref)}")

        # -----------------------------------------------------------
        # Actually perform the fast-forward or the merge

        yield from self.flowEnterWorkerThread()

        self.effects |= TaskEffects.Refs
        if wantMergeCommit:
            # Create merge commit
            self.effects |= TaskEffects.Workdir
            self.jumpTo = NavLocator.inWorkdir()

            if pygit2_version_at_least("1.17.1", raise_error=False, feature_name="git_annotated_commit_from_ref"):
                self.repo.merge(theirBranch)
            else:  # pragma: no cover
                self.repo.merge(target)

            # Set a better message than libgit2 (it uses the longform ref name when merging remote branches)
            # TODO: If we ever add the ability to merge tags, add mergeWhat="tag"
            mergeWhat = "remote-tracking branch" if theirBranchIsRemote else "branch"
            self.repo.set_message(f"Merge {mergeWhat} '{theirBranch.shorthand}'")
            self.repoModel.prefs.draftCommitMessage = self.repo.message_without_conflict_comments

            self.postStatus = _("Merging {0} into {1}.", tquo(theirShorthand), tquo(myShorthand))
        else:
            # Fast-forward
            self.repo.fast_forward_branch(myShorthand, theirBranch.name)
            self.postStatus = _("Branch {0} fast-forwarded to {1}.", tquo(myShorthand), tquo(theirShorthand))

    def confirmFastForward(self, myShorthand: str, theirShorthand: str, target: Oid, autoFastForwardOptionName: str):
        title = _("Fast-forwarding possible")
        message = _("Your branch {0} can simply be fast-forwarded to {1}.", bquo(myShorthand), bquo(theirShorthand))

        if autoFastForwardOptionName:
            notice = _("Automatic fast-forwarding is blocked by the {0} option in your Git config.", tquo("pull.ff"))
            message += f"<p><small>{notice}</small></p>"

        hint = paragraphs(
            _("<b>Fast-forwarding</b> means that the tip of your branch will be moved to a more "
              "recent commit in a linear path, without the need to create a merge commit."),
            _("In this case, {0} will be fast-forwarded to {1}.", bquo(myShorthand), bquo(shortHash(target))))

        actionButton = QPushButton(_("Create Merge Commit"))
        result = yield from self.flowConfirm(title=title, text=message, verb=_("Fast-Forward"),
                                             actionButton=actionButton, helpText=hint)

        # OK button is Fast-Forward; Merge is the other one. (Cancel would have aborted early.)
        # Also checking for Accepted so that unit tests can do qmb.accept().
        wantMergeCommit = result not in [QMessageBox.StandardButton.Ok, QDialog.DialogCode.Accepted]
        return wantMergeCommit


class RecallCommit(RepoTask):
    def flow(self):
        dlg = TextInputDialog(
            self.parentWidget(),
            _("Recall lost commit"),
            _("If you know the hash of a commit that isn’t part of any branches anymore, "
              "{app} will try to recall it for you.", app=qAppName()))
        dlg.okButton.setText(_("Recall"))

        yield from self.flowDialog(dlg)
        dlg.deleteLater()
        needle = dlg.lineEdit.text()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs
        obj = self.repo[needle]
        commit: Commit = obj.peel(Commit)
        branchName = f"recall-{shortHash(commit.id)}"
        branchName = withUniqueSuffix(branchName, self.repo.listall_branches())
        self.repo.create_branch_from_commit(branchName, commit.id)
        self.jumpTo = NavLocator.inCommit(commit.id)
