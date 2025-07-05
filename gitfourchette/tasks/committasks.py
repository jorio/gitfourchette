# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
from contextlib import suppress

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.checkoutcommitdialog import CheckoutCommitDialog
from gitfourchette.forms.commitdialog import CommitDialog
from gitfourchette.forms.deletetagdialog import DeleteTagDialog
from gitfourchette.forms.identitydialog import IdentityDialog
from gitfourchette.forms.newtagdialog import NewTagDialog
from gitfourchette.forms.signatureform import SignatureOverride
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks.jumptasks import RefreshRepo
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskPrereqs, TaskEffects
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)


class NewCommit(RepoTask):
    def prereqs(self):
        return TaskPrereqs.NoConflicts

    def flow(self):
        from gitfourchette.tasks import Jump

        uiPrefs = self.repoModel.prefs

        # Jump to workdir
        yield from self.flowSubtask(Jump, NavLocator.inWorkdir())

        emptyCommit = not self.repo.any_staged_changes
        if emptyCommit:
            text = [_("No files are staged for commit."), _("Do you want to create an empty commit anyway?")]

            if self.repoModel.numUncommittedChanges != 0:
                text.append("<small>" + _n(
                    "Note: Your working directory contains {n} unstaged file. "
                    "If you want to commit it, you should <b>stage</b> it first.",
                    "Note: Your working directory contains {n} unstaged files. "
                    "If you want to commit them, you should <b>stage</b> them first.",
                    self.repoModel.numUncommittedChanges) + "</small>")

            yield from self.flowConfirm(
                title=_("Create empty commit"),
                verb=_("Empty commit"),
                text=paragraphs(text))

        yield from self.flowSubtask(SetUpGitIdentity, _("Proceed to Commit"))

        fallbackSignature = self.repo.default_signature
        initialMessage = uiPrefs.draftCommitMessage

        cd = CommitDialog(
            initialText=initialMessage,
            authorSignature=fallbackSignature,
            committerSignature=fallbackSignature,
            amendingCommitHash="",
            detachedHead=self.repo.head_is_detached,
            repositoryState=self.repo.state(),
            emptyCommit=emptyCommit,
            parent=self.parentWidget())

        if uiPrefs.draftCommitSignatureOverride == SignatureOverride.Nothing:
            cd.ui.revealSignature.setChecked(False)
        else:
            assert uiPrefs.draftCommitSignature is not None, "overridden Signature can't be None"
            cd.ui.revealSignature.setChecked(True)
            cd.ui.signature.setSignature(uiPrefs.draftCommitSignature)
            cd.ui.signature.ui.replaceComboBox.setCurrentIndex(int(uiPrefs.draftCommitSignatureOverride) - 1)

        cd.setWindowModality(Qt.WindowModality.WindowModal)

        # Reenter task even if dialog rejected, because we want to save the commit message as a draft
        yield from self.flowDialog(cd, abortTaskIfRejected=False)

        message = cd.getFullMessage()
        author = cd.getOverriddenAuthorSignature() or fallbackSignature
        committer = cd.getOverriddenCommitterSignature() or fallbackSignature
        overriddenSignatureKind = cd.getOverriddenSignatureKind()
        signatureIsOverridden = overriddenSignatureKind != SignatureOverride.Nothing

        # Save commit message/signature as draft now,
        # so we don't lose it if the commit operation fails or is rejected.
        if message != initialMessage or signatureIsOverridden:
            uiPrefs.draftCommitMessage = message
            uiPrefs.draftCommitSignature = cd.ui.signature.getSignature() if signatureIsOverridden else None
            uiPrefs.draftCommitSignatureOverride = overriddenSignatureKind
            uiPrefs.setDirty()

        if cd.result() == QDialog.DialogCode.Rejected:
            cd.deleteLater()
            raise AbortTask()

        cd.deleteLater()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir | TaskEffects.Refs | TaskEffects.Head
        newOid = self.repo.create_commit_on_head(message, author, committer)

        yield from self.flowEnterUiThread()
        uiPrefs.clearDraftCommit()

        self.postStatus = _("Commit {0} created.", tquo(shortHash(newOid)))


class AmendCommit(RepoTask):
    def prereqs(self):
        return TaskPrereqs.NoUnborn | TaskPrereqs.NoConflicts | TaskPrereqs.NoCherrypick

    def getDraftMessage(self):
        return self.repoModel.prefs.draftAmendMessage

    def setDraftMessage(self, newMessage):
        self.repoModel.prefs.draftAmendMessage = newMessage
        self.repoModel.prefs.setDirty()

    def flow(self):
        from gitfourchette.tasks import Jump

        # Jump to workdir
        yield from self.flowSubtask(Jump, NavLocator.inWorkdir())

        yield from self.flowSubtask(SetUpGitIdentity, _("Proceed to Amend Commit"))

        headCommit = self.repo.head_commit
        fallbackSignature = self.repo.default_signature

        # TODO: Retrieve draft message
        cd = CommitDialog(
            initialText=headCommit.message,
            authorSignature=headCommit.author,
            committerSignature=fallbackSignature,
            amendingCommitHash=shortHash(headCommit.id),
            detachedHead=self.repo.head_is_detached,
            repositoryState=self.repo.state(),
            emptyCommit=False,
            parent=self.parentWidget())

        cd.setWindowModality(Qt.WindowModality.WindowModal)

        # Reenter task even if dialog rejected, because we want to save the commit message as a draft
        yield from self.flowDialog(cd, abortTaskIfRejected=False)
        cd.deleteLater()

        message = cd.getFullMessage()

        # Save amend message as draft now, so we don't lose it if the commit operation fails or is rejected.
        self.setDraftMessage(message)

        if cd.result() == QDialog.DialogCode.Rejected:
            raise AbortTask()

        author = cd.getOverriddenAuthorSignature()  # no "or fallback" here - leave author intact for amending
        committer = cd.getOverriddenCommitterSignature() or fallbackSignature

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir | TaskEffects.Refs | TaskEffects.Head

        newOid = self.repo.amend_commit_on_head(message, author, committer)

        yield from self.flowEnterUiThread()
        self.repoModel.prefs.clearDraftAmend()

        self.postStatus = _("Commit {0} amended. New hash: {1}.",
                            tquo(shortHash(headCommit.id)), tquo(shortHash(newOid)))


class SetUpGitIdentity(RepoTask):
    def flow(self, okButtonText="", firstRun=True):
        if firstRun:
            # Getting the default signature will fail if the user's identity is missing or incorrectly set
            try:
                _dummy = self.repo.default_signature
                return
            except (KeyError, ValueError):
                pass

        initialName, initialEmail, editLevel = GitConfigHelper.global_identity()

        # Fall back to a sensible path if the identity comes from /etc/gitconfig or some other systemwide file
        if editLevel not in [GitConfigLevel.XDG, GitConfigLevel.GLOBAL]:
            # Favor XDG path if we can, otherwise use ~/.gitconfig
            if FREEDESKTOP and GitSettings.search_path[GitConfigLevel.XDG]:
                editLevel = GitConfigLevel.XDG
            else:
                editLevel = GitConfigLevel.GLOBAL

        editPath = GitConfigHelper.path_for_level(editLevel, missing_dir_ok=True)

        dlg = IdentityDialog(firstRun, initialName, initialEmail, editPath,
                             self.repo.has_local_identity(), self.parentWidget())

        if okButtonText:
            dlg.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setText(okButtonText)

        dlg.resize(512, 0)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        yield from self.flowDialog(dlg)

        name, email = dlg.identity()
        dlg.deleteLater()

        configObject = GitConfigHelper.ensure_file(editLevel)
        configObject['user.name'] = name
        configObject['user.email'] = email

        # An existing repo will automatically pick up the new GLOBAL config file,
        # but apparently not the XDG config file... So add it to be sure.
        with suppress(ValueError):
            self.repo.config.add_file(editPath, editLevel, force=False)


class CheckoutCommit(RepoTask):
    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoConflicts

    def flow(self, oid: Oid):
        from gitfourchette.tasks.nettasks import UpdateSubmodulesRecursive
        from gitfourchette.tasks.branchtasks import SwitchBranch, NewBranchFromCommit, ResetHead, MergeBranch

        refs = self.repo.listall_refs_pointing_at(oid)
        refs = [r for r in refs if r.startswith((RefPrefix.HEADS, RefPrefix.REMOTES))]

        commitMessage = self.repo.get_commit_message(oid)
        commitMessage, junk = messageSummary(commitMessage)
        anySubmodules = bool(self.repo.listall_submodules_fast())
        anySubmodules &= pygit2_version_at_least("1.15.1", False)  # TODO: Nuke this once we can drop support for old versions of pygit2

        dlg = CheckoutCommitDialog(
            oid=oid,
            refs=refs,
            currentBranch=self.repo.head_branch_shorthand,
            anySubmodules=anySubmodules,
            parent=self.parentWidget())

        convertToBrandedDialog(dlg, subtitleText=tquo(commitMessage))
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        yield from self.flowDialog(dlg)

        # Make sure to copy user input from dialog UI *before* starting worker thread
        dlg.deleteLater()

        wantSubmodules = anySubmodules and dlg.ui.recurseSubmodulesCheckBox.isChecked()

        self.effects |= TaskEffects.Refs | TaskEffects.Head

        if dlg.ui.detachHeadRadioButton.isChecked():
            headId = self.repoModel.headCommitId
            if self.repoModel.dangerouslyDetachedHead() and oid != headId:
                text = paragraphs(
                    _("You are in <b>Detached HEAD</b> mode at commit {0}.", btag(shortHash(headId))),
                    _("You might lose track of this commit "
                      "if you carry on checking out another commit ({0}).", shortHash(oid)))
                yield from self.flowConfirm(text=text, icon='warning')

            yield from self.flowEnterWorkerThread()
            self.repo.checkout_commit(oid)

            self.postStatus = _("Entered detached HEAD on {0}.", lquo(shortHash(oid)))

            # Force sidebar to select detached HEAD
            self.jumpTo = NavLocator.inRef("HEAD")

            if wantSubmodules:
                yield from self.flowEnterUiThread()
                yield from self.flowSubtask(UpdateSubmodulesRecursive)

        elif dlg.ui.switchRadioButton.isChecked():
            branchName = dlg.ui.switchComboBox.currentText()
            yield from self.flowSubtask(SwitchBranch, branchName, askForConfirmation=False, recurseSubmodules=wantSubmodules)

        elif dlg.ui.createBranchRadioButton.isChecked():
            yield from self.flowSubtask(NewBranchFromCommit, oid)

        elif dlg.ui.resetHeadRadioButton.isChecked():
            yield from self.flowSubtask(ResetHead, oid)

        elif dlg.ui.mergeRadioButton.isChecked():
            yield from self.flowSubtask(MergeBranch, refs[0])

        else:
            raise NotImplementedError("Unsupported CheckoutCommitDialog outcome")


class NewTag(RepoTask):
    def prereqs(self):
        return TaskPrereqs.NoUnborn

    def flow(self, oid: Oid = NULL_OID, signIt: bool = False):
        if signIt:
            yield from self.flowSubtask(SetUpGitIdentity, _("Proceed to New Tag"))

        repo = self.repo
        if oid is None or oid == NULL_OID:
            oid = repo.head_commit_id

        reservedNames = repo.listall_tags()
        commitMessage = repo.get_commit_message(oid)
        commitMessage, _dummy = messageSummary(commitMessage)

        dlg = NewTagDialog(shortHash(oid), commitMessage, reservedNames,
                           remotes=self.repoModel.remotes,
                           parent=self.parentWidget())

        dlg.setFixedHeight(dlg.sizeHint().height())
        yield from self.flowDialog(dlg)

        tagName = dlg.ui.nameEdit.text()
        pushIt = dlg.ui.pushCheckBox.isChecked()
        pushTo = dlg.ui.remoteComboBox.currentData()
        dlg.deleteLater()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs

        refName = RefPrefix.TAGS + tagName

        if signIt:
            repo.create_tag(tagName, oid, ObjectType.COMMIT, self.repo.default_signature, "")
        else:
            repo.create_reference(refName, oid)

        self.postStatus = _("Tag {0} created on commit {1}.", tquo(tagName), tquo(shortHash(oid)))

        if pushIt:
            from gitfourchette.tasks import PushRefspecs
            yield from self.flowEnterUiThread()
            yield from self.flowSubtask(PushRefspecs, pushTo, [refName])


class DeleteTag(RepoTask):
    def flow(self, tagName: str):
        assert not tagName.startswith("refs/")

        tagTarget = self.repo.commit_id_from_tag_name(tagName)
        commitMessage = self.repo.get_commit_message(tagTarget)
        commitMessage, _dummy = messageSummary(commitMessage)

        dlg = DeleteTagDialog(
            tagName,
            shortHash(tagTarget),
            commitMessage,
            self.repoModel.remotes,
            parent=self.parentWidget())

        dlg.setFixedHeight(dlg.sizeHint().height())
        yield from self.flowDialog(dlg)

        pushIt = dlg.ui.pushCheckBox.isChecked()
        pushTo = dlg.ui.remoteComboBox.currentData()
        dlg.deleteLater()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs

        # Stay on this commit after the operation
        if tagTarget:
            self.jumpTo = NavLocator.inCommit(tagTarget)

        self.repo.delete_tag(tagName)

        if pushIt:
            refspec = f":{RefPrefix.TAGS}{tagName}"
            from gitfourchette.tasks import PushRefspecs
            yield from self.flowEnterUiThread()
            yield from self.flowSubtask(PushRefspecs, pushTo, [refspec])


class RevertCommit(RepoTask):
    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoConflicts | TaskPrereqs.NoStagedChanges

    def flow(self, oid: Oid):
        # TODO: Remove this when we can stop supporting pygit2 <= 1.15.0
        pygit2_version_at_least("1.15.1")

        text = paragraphs(
            _("Do you want to revert commit {0}?", btag(shortHash(oid))),
            _("You will have an opportunity to review the affected files in your working directory."))
        yield from self.flowConfirm(text=text)

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir
        repoModel = self.repoModel
        repo = self.repo
        commit = repo.peel_commit(oid)
        repo.revert(commit)

        anyConflicts = repo.any_conflicts
        dud = not anyConflicts and not repo.any_staged_changes

        # If reverting didn't do anything, don't let the REVERT state linger.
        # (Otherwise, the state will be cleared when we commit)
        if dud:
            repo.state_cleanup()

        yield from self.flowEnterUiThread()

        if dud:
            info = _("There’s nothing to revert from {0} "
                     "that the current branch hasn’t already undone.", bquo(shortHash(oid)))
            raise AbortTask(info, "information")

        yield from self.flowEnterUiThread()

        repoModel.prefs.draftCommitMessage = self.repo.message_without_conflict_comments
        repoModel.prefs.setDirty()

        self.jumpTo = NavLocator.inWorkdir()

        if not anyConflicts:
            yield from self.flowSubtask(RefreshRepo, TaskEffects.Workdir, NavLocator.inStaged(""))
            text = _("Reverting {0} was successful. Do you want to commit the result now?", bquo(shortHash(oid)))
            yield from self.flowConfirm(text=text, verb=_p("verb", "Commit"), cancelText=_("Review changes"))
            yield from self.flowSubtask(NewCommit)


class CherrypickCommit(RepoTask):
    def prereqs(self):
        # Prevent cherry-picking with staged changes, like vanilla git (despite libgit2 allowing it)
        return TaskPrereqs.NoConflicts | TaskPrereqs.NoStagedChanges

    def flow(self, oid: Oid):
        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir
        commit = self.repo.peel_commit(oid)
        self.repo.cherrypick(oid)

        anyConflicts = self.repo.any_conflicts
        dud = not anyConflicts and not self.repo.any_staged_changes

        assert self.repo.state() == RepositoryState.CHERRYPICK

        # If cherrypicking didn't do anything, don't let the CHERRYPICK state linger.
        # (Otherwise, the state will be cleared when we commit)
        if dud:
            self.repo.state_cleanup()

        # Back to UI thread
        yield from self.flowEnterUiThread()

        if dud:
            info = _("There’s nothing to cherry-pick from {0} "
                     "that the current branch doesn’t already have.", bquo(shortHash(oid)))
            raise AbortTask(info, "information")

        self.repoModel.prefs.draftCommitMessage = self.repo.message_without_conflict_comments
        self.repoModel.prefs.draftCommitSignature = commit.author
        self.repoModel.prefs.draftCommitSignatureOverride = SignatureOverride.Author
        self.repoModel.prefs.setDirty()

        self.jumpTo = NavLocator.inWorkdir()

        if not anyConflicts:
            yield from self.flowSubtask(RefreshRepo, TaskEffects.Workdir, NavLocator.inStaged(""))
            yield from self.flowConfirm(
                text=_("Cherry-picking {0} was successful. "
                       "Do you want to commit the result now?", bquo(shortHash(oid))),
                verb=_p("verb", "Commit"),
                cancelText=_("Review changes"))
            yield from self.flowSubtask(NewCommit)
