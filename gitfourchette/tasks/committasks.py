# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
from contextlib import suppress

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.commitdialog import CommitDialog
from gitfourchette.forms.deletetagdialog import DeleteTagDialog
from gitfourchette.forms.identitydialog import IdentityDialog
from gitfourchette.forms.newtagdialog import NewTagDialog
from gitfourchette.forms.signatureform import SignatureOverride
from gitfourchette.forms.ui_checkoutcommitdialog import Ui_CheckoutCommitDialog
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
            yield from self.flowConfirm(
                title=self.tr("Create empty commit"),
                verb=self.tr("Empty commit"),
                text=paragraphs(
                    self.tr("No files are staged for commit."),
                    self.tr("Do you want to create an empty commit anyway?")))

        yield from self.flowSubtask(SetUpGitIdentity, self.tr("Proceed to Commit"))

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
        self.repo.create_commit_on_head(message, author, committer)

        yield from self.flowEnterUiThread()
        uiPrefs.clearDraftCommit()


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

        yield from self.flowSubtask(SetUpGitIdentity, self.tr("Proceed to Amend Commit"))

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

        self.repo.amend_commit_on_head(message, author, committer)

        yield from self.flowEnterUiThread()
        self.repoModel.prefs.clearDraftAmend()


class SetUpGitIdentity(RepoTask):
    def flow(self, okButtonText="", firstRun=True):
        if firstRun:
            # Getting the default signature will fail if the user's identity is missing or incorrectly set
            try:
                _ = self.repo.default_signature
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
    def flow(self, oid: Oid):
        refs = self.repo.listall_refs_pointing_at(oid)
        refs = [r.removeprefix(RefPrefix.HEADS) for r in refs if r.startswith(RefPrefix.HEADS)]

        commitMessage = self.repo.get_commit_message(oid)
        commitMessage, junk = messageSummary(commitMessage)
        anySubmodules = bool(self.repo.listall_submodules_fast())
        anySubmodules &= pygit2_version_at_least("1.15.1", False)  # TODO: Nuke this once we can drop support for old versions of pygit2

        dlg = QDialog(self.parentWidget())

        ui = Ui_CheckoutCommitDialog()
        ui.setupUi(dlg)
        dlg.ui = ui  # for unit tests
        ok = ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        ui.detachedHeadRadioButton.clicked.connect(lambda: ok.setText(self.tr("Detach HEAD")))
        ui.detachedHeadRadioButton.clicked.connect(lambda: ok.setIcon(stockIcon("git-head-detached")))
        ui.switchToLocalBranchRadioButton.clicked.connect(lambda: ok.setText(self.tr("Switch Branch")))
        ui.switchToLocalBranchRadioButton.clicked.connect(lambda: ok.setIcon(stockIcon("git-branch")))
        ui.createBranchRadioButton.clicked.connect(lambda: ok.setText(self.tr("Create Branch...")))
        ui.createBranchRadioButton.clicked.connect(lambda: ok.setIcon(stockIcon("vcs-branch-new")))
        if refs:
            ui.switchToLocalBranchComboBox.addItems(refs)
            ui.switchToLocalBranchRadioButton.click()
        else:
            ui.detachedHeadRadioButton.click()
            ui.switchToLocalBranchComboBox.setVisible(False)
            ui.switchToLocalBranchRadioButton.setVisible(False)

        if not anySubmodules:
            ui.recurseSubmodulesSpacer.setVisible(False)
            ui.recurseSubmodulesGroupBox.setVisible(False)

        ui.createBranchRadioButton.toggled.connect(lambda t: ui.recurseSubmodulesGroupBox.setEnabled(not t))

        dlg.setWindowTitle(self.tr("Check out commit {0}").format(shortHash(oid)))
        convertToBrandedDialog(dlg, subtitleText=tquo(commitMessage))
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        yield from self.flowDialog(dlg)

        # Make sure to copy user input from dialog UI *before* starting worker thread
        dlg.deleteLater()

        wantSubmodules = anySubmodules and ui.recurseSubmodulesCheckBox.isChecked()

        self.effects |= TaskEffects.Refs | TaskEffects.Head

        if ui.detachedHeadRadioButton.isChecked():
            if self.repoModel.dangerouslyDetachedHead() and oid != self.repoModel.headCommitId:
                text = paragraphs(
                    self.tr("You are in <b>Detached HEAD</b> mode at commit {0}."),
                    self.tr("You might lose track of this commit if you carry on checking out another commit ({1})."),
                ).format(btag(shortHash(self.repoModel.headCommitId)), shortHash(oid))
                yield from self.flowConfirm(text=text, icon='warning')

            yield from self.flowEnterWorkerThread()
            self.repo.checkout_commit(oid)

            # Force sidebar to select detached HEAD
            self.jumpTo = NavLocator.inRef("HEAD")

            if wantSubmodules:
                from gitfourchette.tasks import UpdateSubmodulesRecursive
                yield from self.flowEnterUiThread()
                yield from self.flowSubtask(UpdateSubmodulesRecursive)

        elif ui.switchToLocalBranchRadioButton.isChecked():
            branchName = ui.switchToLocalBranchComboBox.currentText()
            from gitfourchette.tasks import SwitchBranch
            yield from self.flowSubtask(SwitchBranch, branchName, askForConfirmation=False, recurseSubmodules=wantSubmodules)

        elif ui.createBranchRadioButton.isChecked():
            from gitfourchette.tasks.branchtasks import NewBranchFromCommit
            yield from self.flowSubtask(NewBranchFromCommit, oid)

        else:
            raise NotImplementedError("Unsupported CheckoutCommitDialog outcome")


class NewTag(RepoTask):
    def prereqs(self):
        return TaskPrereqs.NoUnborn

    def flow(self, oid: Oid = None, signIt: bool = False):
        if signIt:
            yield from self.flowSubtask(SetUpGitIdentity, self.tr("Proceed to New Tag"))

        repo = self.repo
        if not oid:
            oid = repo.head_commit_id

        reservedNames = repo.listall_tags()
        commitMessage = repo.get_commit_message(oid)
        commitMessage, _ = messageSummary(commitMessage)

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

        if pushIt:
            from gitfourchette.tasks import PushRefspecs
            yield from self.flowEnterUiThread()
            yield from self.flowSubtask(PushRefspecs, pushTo, [refName])


class DeleteTag(RepoTask):
    def flow(self, tagName: str):
        assert not tagName.startswith("refs/")

        tagTarget = self.repo.commit_id_from_tag_name(tagName)
        commitMessage = self.repo.get_commit_message(tagTarget)
        commitMessage, _ = messageSummary(commitMessage)

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
            self.tr("Do you want to revert commit {0}?"),
            self.tr("You will have an opportunity to review the affected files in your working directory."),
        ).format(btag(shortHash(oid)))
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
            info = self.tr("There’s nothing to revert from {0} that the current branch hasn’t already undone."
                           ).format(bquo(shortHash(oid)))
            raise AbortTask(info, "information")

        yield from self.flowEnterUiThread()

        repoModel.prefs.draftCommitMessage = self.repo.message
        repoModel.prefs.setDirty()

        self.jumpTo = NavLocator.inWorkdir()

        if not anyConflicts:
            yield from self.flowSubtask(RefreshRepo, TaskEffects.Workdir, NavLocator.inStaged(""))
            text = self.tr("Reverting {0} was successful. Do you want to commit the result now?")
            text = text.format(bquo(shortHash(oid)))
            yield from self.flowConfirm(text=text, verb=self.tr("Commit"), cancelText=self.tr("Review changes"))
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
            info = self.tr("There’s nothing to cherry-pick from {0} that the current branch doesn’t already have."
                           ).format(bquo(shortHash(oid)))
            raise AbortTask(info, "information")

        self.repoModel.prefs.draftCommitMessage = self.repo.message
        self.repoModel.prefs.draftCommitSignature = commit.author
        self.repoModel.prefs.draftCommitSignatureOverride = SignatureOverride.Author
        self.repoModel.prefs.setDirty()

        self.jumpTo = NavLocator.inWorkdir()

        if not anyConflicts:
            yield from self.flowSubtask(RefreshRepo, TaskEffects.Workdir, NavLocator.inStaged(""))
            yield from self.flowConfirm(
                text=self.tr("Cherry-picking {0} was successful. "
                             "Do you want to commit the result now?").format(bquo(shortHash(oid))),
                verb=self.tr("Commit"),
                cancelText=self.tr("Review changes"))
            yield from self.flowSubtask(NewCommit)
