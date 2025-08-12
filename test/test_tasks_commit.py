# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os.path

import pytest

from gitfourchette.forms.checkoutcommitdialog import CheckoutCommitDialog
from gitfourchette.forms.commitdialog import CommitDialog
from gitfourchette.forms.identitydialog import IdentityDialog
from gitfourchette.forms.newtagdialog import NewTagDialog
from gitfourchette.forms.signatureform import SignatureOverride
from gitfourchette.graphview.commitlogmodel import CommitLogModel, SpecialRow
from gitfourchette.nav import NavLocator
from gitfourchette.sidebar.sidebarmodel import SidebarNode, SidebarItem
from . import reposcenario
from .util import *


def testCommit(tempDir, mainWindow, gitBackend):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/a/a1.txt", "a1\nPENDING CHANGE\n")  # unstaged change
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)
    QTest.keyPress(rw.dirtyFiles, Qt.Key.Key_Return)
    assert qlvGetRowData(rw.dirtyFiles) == []
    assert qlvGetRowData(rw.stagedFiles) == ["a/a1.txt"]
    rw.diffArea.commitButton.click()

    dialog: CommitDialog = findQDialog(rw, "commit")
    QTest.keyClicks(dialog.ui.summaryEditor, "Some New Commit")
    assert dialog.acceptButton.isEnabled()

    dialog.ui.revealSignature.click()

    enteredDate = QDateTime.fromString("1999-12-31 23:59:00", "yyyy-MM-dd HH:mm:ss")
    sigUI = dialog.ui.signature.ui
    qcbSetIndex(sigUI.replaceComboBox, "author")
    sigUI.nameEdit.clear()
    assert not dialog.acceptButton.isEnabled()
    sigUI.nameEdit.setText("Custom Author")
    sigUI.emailEdit.setText("custom.author@example.com")
    sigUI.timeEdit.setDateTime(enteredDate)

    assert dialog.acceptButton.isEnabled()
    dialog.accept()

    headCommit = rw.repo.head_commit
    assert headCommit.message == "Some New Commit\n"
    assert headCommit.author.name == "Custom Author"
    assert headCommit.author.email == "custom.author@example.com"
    assert headCommit.author.time == enteredDate.toSecsSinceEpoch()
    assert headCommit.committer.name == TEST_SIGNATURE.name

    assert len(headCommit.parents) == 1
    diff = rw.repo.diff(headCommit.parents[0], headCommit)
    patches: list[Patch] = list(diff)
    assert len(patches) == 1
    assert patches[0].delta.new_file.path == "a/a1.txt"


def testCommitUntrackedFileInEmptyRepo(tempDir, mainWindow, gitBackend):
    wd = unpackRepo(tempDir, "TestEmptyRepository")
    touchFile(F"{wd}/SomeNewFile.txt")
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)
    QTest.keyPress(rw.dirtyFiles, Qt.Key.Key_Return)

    assert qlvGetRowData(rw.dirtyFiles) == []
    assert qlvGetRowData(rw.stagedFiles) == ["SomeNewFile.txt"]

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    QTest.keyClicks(dialog.ui.summaryEditor, "Initial commit")
    dialog.accept()

    rows = qlvGetRowData(rw.graphView, CommitLogModel.Role.Commit)
    commit: Commit = rows[-1].peel(Commit)
    assert commit.message == "Initial commit\n"


def testCommitMessageDraftSavedOnCancel(tempDir, mainWindow, gitBackend):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    assert dialog.ui.summaryEditor.text() == ""
    assert dialog.getOverriddenSignatureKind() == SignatureOverride.Nothing
    QTest.keyClicks(dialog.ui.summaryEditor, "hoping to save this message")
    dialog.reject()
    assert rw.repoModel.prefs.hasDraftCommit()
    assert rw.repoModel.prefs.draftCommitMessage == "hoping to save this message\n"
    assert rw.repoModel.prefs.draftCommitSignatureOverride == SignatureOverride.Nothing

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    assert dialog.ui.summaryEditor.text() == "hoping to save this message"
    assert dialog.ui.descriptionEditor.toPlainText() == ""
    dialog.ui.revealSignature.click()
    dialog.ui.signature.ui.replaceComboBox.setCurrentIndex(2)
    dialog.reject()
    assert rw.repoModel.prefs.hasDraftCommit()
    assert rw.repoModel.prefs.draftCommitMessage == "hoping to save this message\n"
    assert rw.repoModel.prefs.draftCommitSignatureOverride == SignatureOverride.Both
    assert rw.repoModel.prefs.draftCommitSignature is not None

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    assert rw.repoModel.prefs.hasDraftCommit()
    assert dialog.ui.summaryEditor.text() == "hoping to save this message"
    assert dialog.getOverriddenSignatureKind() == SignatureOverride.Both
    dialog.accept()  # Go through with the commit this time

    # Ensure nothing remains of the draft after a successful commit
    rw.diffArea.commitButton.click()
    acceptQMessageBox(rw, "empty commit")
    dialog: CommitDialog = findQDialog(rw, "commit")
    assert not rw.repoModel.prefs.hasDraftCommit()
    assert dialog.ui.summaryEditor.text() == ""
    assert dialog.getOverriddenSignatureKind() == SignatureOverride.Nothing
    dialog.reject()


def testClearCommitMessageDraft(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    rw.diffArea.commitButton.click()
    acceptQMessageBox(rw, "empty commit")
    dialog: CommitDialog = findQDialog(rw, "commit")
    assert dialog.ui.summaryEditor.text() == ""
    assert dialog.getOverriddenSignatureKind() == SignatureOverride.Nothing
    QTest.keyClicks(dialog.ui.summaryEditor, "hoping to save this message")
    dialog.reject()

    assert rw.repoModel.prefs.hasDraftCommit()
    assert rw.repoModel.prefs.draftCommitMessage == "hoping to save this message\n"
    assert rw.repoModel.prefs.draftCommitSignatureOverride == SignatureOverride.Nothing

    assert rw.navLocator.context.isWorkdir()
    triggerContextMenuAction(rw.graphView.viewport(), "clear draft")

    assert not rw.repoModel.prefs.hasDraftCommit()
    assert not rw.repoModel.prefs.draftCommitMessage


def testCommitMessageDraftWithInvalidSignatureSavedOnCancel(tempDir, mainWindow, gitBackend):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    dialog.ui.summaryEditor.setText("hoping to save this message")
    dialog.ui.revealSignature.click()
    dialog.ui.signature.ui.replaceComboBox.setCurrentIndex(2)
    dialog.ui.signature.ui.nameEdit.setText("")
    dialog.ui.signature.ui.emailEdit.setText("")
    assert not dialog.acceptButton.isEnabled()
    dialog.reject()
    assert rw.repoModel.prefs.draftCommitMessage == "hoping to save this message\n"
    assert rw.repoModel.prefs.draftCommitSignatureOverride == SignatureOverride.Nothing
    assert rw.repoModel.prefs.draftCommitSignature is None
    assert rw.repoModel.prefs.hasDraftCommit()

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    assert dialog.ui.summaryEditor.text() == "hoping to save this message"
    assert dialog.getOverriddenSignatureKind() == SignatureOverride.Nothing
    dialog.accept()  # Go through with the commit this time


def testPasteMultilineCommitMessage(tempDir, mainWindow):
    """
    WARNING: THIS TEST MODIFIES THE SYSTEM'S CLIPBOARD.
    (No worries if you're running the tests offscreen.)
    """

    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)

    rw.diffArea.commitButton.click()
    dialog: CommitDialog = findQDialog(rw, "commit")
    QTest.keyClicks(dialog.ui.summaryEditor, "aaa")
    QTest.keyClicks(dialog.ui.descriptionEditor, "bbb")

    QApplication.clipboard().setText("summary\ndetails1\ndetails2")

    dialog.ui.summaryEditor.setFocus()
    QTest.keySequence(dialog.ui.summaryEditor, "Ctrl+V")
    assert dialog.ui.summaryEditor.text() == "aaasummary"
    assert dialog.ui.counterLabel.text() == str(len("aaasummary"))
    assert dialog.ui.descriptionEditor.toPlainText() == "details1\ndetails2"

    # TODO: Ctrl+Zing in both fields isn't ideal
    QTest.keySequence(dialog.ui.summaryEditor, "Ctrl+Z")
    assert dialog.ui.summaryEditor.text() == "aaa"
    QTest.keySequence(dialog.ui.descriptionEditor, "Ctrl+Z")
    assert dialog.ui.descriptionEditor.toPlainText() == "bbb"

    dialog.reject()


def testAmendCommit(tempDir, mainWindow, gitBackend):
    oldMessage = "Delete c/c2-2.txt"
    newMessage = "amended commit message"
    newAuthorName = "Jean-Michel Tartempion"
    newAuthorEmail = "jmtartempion@example.com"

    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)

    oldHeadCommit = rw.repo.head_commit

    # Kick off amend dialog
    triggerMenuAction(rw.diffArea.commitButton.menu(), "amend")

    dialog: CommitDialog = findQDialog(rw, "amend")
    assert dialog.ui.summaryEditor.text() == oldMessage
    dialog.ui.summaryEditor.setText(newMessage)
    dialog.ui.revealSignature.setChecked(True)
    dialog.ui.signature.ui.nameEdit.setText(newAuthorName)
    dialog.ui.signature.ui.emailEdit.setText(newAuthorEmail)
    dialog.accept()

    headCommit = rw.repo.head_commit
    assert headCommit.id != oldHeadCommit.id
    assert headCommit.message == newMessage + "\n"
    assert headCommit.author.name == newAuthorName
    assert headCommit.author.email == newAuthorEmail
    assert headCommit.committer.name == TEST_SIGNATURE.name
    assert headCommit.committer.email == TEST_SIGNATURE.email

    assert rw.graphView.currentRowKind == SpecialRow.UncommittedChanges  # uncommitted changes should still be selected
    assert rw.stagedFiles.isVisibleTo(rw)
    assert rw.dirtyFiles.isVisibleTo(rw)
    assert not rw.committedFiles.isVisibleTo(rw)


def testAmendCommitDontBreakRefresh(tempDir, mainWindow, gitBackend):
    wd = unpackRepo(tempDir)
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)

    # Kick off amend dialog
    rw.jump(NavLocator.inWorkdir())
    triggerContextMenuAction(rw.graphView.viewport(), "amend")

    # Amend HEAD commit without any changes, i.e. just change the timestamp.
    dialog: CommitDialog = findQDialog(rw, "amend")
    dialog.accept()


def testEmptyCommitRaisesWarning(tempDir, mainWindow, gitBackend):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.diffArea.commitButton.click()
    acceptQMessageBox(rw, "create.+empty commit")

    commitDialog = findQDialog(rw, "commit")
    assert isinstance(commitDialog, CommitDialog)
    assert commitDialog.ui.infoText.isVisible()
    assert "empty commit" in commitDialog.ui.infoText.text().lower()
    commitDialog.reject()

    # Look for additional hint text when there are unstaged changes
    writeFile(f"{wd}/toto.txt", "toto")
    writeFile(f"{wd}/titi.txt", "titi")
    rw.refreshRepo()
    rw.diffArea.commitButton.click()
    qmb = findQMessageBox(rw, "create.+empty commit")
    assert re.search("2 unstaged files.+you should.+stage.+them first", qmb.text(), re.I)
    qmb.reject()


def testCommitWithoutUserIdentity(tempDir, mainWindow, gitBackend):
    clearSessionwideIdentity()

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    assert "user.name" not in rw.repo.config
    assert "user.email" not in rw.repo.config

    rw.diffArea.commitButton.click()
    acceptQMessageBox(rw, "create.+empty commit")

    identityDialog = findQDialog(rw, "identity")
    assert isinstance(identityDialog, IdentityDialog)
    identityOK = identityDialog.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
    assert not identityOK.isEnabled()
    identityDialog.ui.nameEdit.setText("Archibald Haddock")
    identityDialog.ui.emailEdit.setText("1e15sabords@example.com")
    assert identityOK.isEnabled()
    identityDialog.accept()

    commitDialog = findQDialog(rw, "commit")
    assert isinstance(commitDialog, CommitDialog)
    commitDialog.ui.summaryEditor.setText("ca geht's mol?")
    commitDialog.accept()

    headCommit = rw.repo.head_commit
    assert headCommit.message == "ca geht's mol?\n"
    assert headCommit.author.name == "Archibald Haddock"
    assert headCommit.author.email == "1e15sabords@example.com"


def testCommitStableDate(tempDir, mainWindow, gitBackend):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/a/a1.txt", "a1\nPENDING CHANGE\n")  # unstaged change
    rw = mainWindow.openRepo(wd)

    rw.diffArea.commitButton.click()
    acceptQMessageBox(rw, "empty commit")

    dialog: CommitDialog = findQDialog(rw, "commit")
    dialog.ui.summaryEditor.setText("hold on a sec...")

    # Wait for next second before confirming.
    # Commit time should not depend on when the dialog is accepted.
    QTest.qWait(1001)
    dialog.accept()

    headCommit = rw.repo.head_commit
    assert headCommit.message == "hold on a sec...\n"
    assert signatures_equalish(headCommit.author, headCommit.committer)


def testAmendAltersCommitterDate(tempDir, mainWindow, gitBackend):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/a/a1.txt", "a1\nPENDING CHANGE\n")  # unstaged change
    rw = mainWindow.openRepo(wd)

    headCommit = rw.repo.head_commit
    triggerMenuAction(rw.diffArea.commitButton.menu(), "amend")

    dialog: CommitDialog = findQDialog(rw, "amend")
    dialog.ui.summaryEditor.setText("hold on a sec...")
    dialog.accept()

    amendedHeadCommit = rw.repo.head_commit
    assert amendedHeadCommit.message == "hold on a sec...\n"
    assert signatures_equalish(amendedHeadCommit.author, headCommit.author)
    assert not signatures_equalish(amendedHeadCommit.committer, headCommit.committer)
    assert not signatures_equalish(amendedHeadCommit.author, amendedHeadCommit.committer)
    assert amendedHeadCommit.author.name != TEST_SIGNATURE.name
    assert amendedHeadCommit.committer.name == TEST_SIGNATURE.name
    assert amendedHeadCommit.committer.time > amendedHeadCommit.author.time


def testCommitDialogJumpsToWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.fileWithStagedAndUnstagedChanges(wd)
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="0966a434eb1a025db6b71485ab63a3bfbea520b6")
    rw.jump(NavLocator.inCommit(oid1))

    triggerMenuAction(mainWindow.menuBar(), r"repo/commit")
    findQDialog(rw, r"commit").reject()
    assert NavLocator.inUnstaged("a/a1.txt").isSimilarEnoughTo(rw.navLocator)

    rw.jump(NavLocator.inStaged("a/a1.txt"))
    triggerMenuAction(mainWindow.menuBar(), r"repo/commit")
    findQDialog(rw, r"commit").reject()
    assert NavLocator.inStaged("a/a1.txt").isSimilarEnoughTo(rw.navLocator)


@pytest.mark.skipif(QT5, reason="Qt 5 (deprecated) is flaky here")
def testCommitDialogCtrlReturn(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), r"repo/commit")
    acceptQMessageBox(rw, "create an empty commit anyway")

    commitDialog: CommitDialog = findQDialog(rw, r"commit")

    # Widget focus is finicky in offscreen tests unless we force the dialog to be active first
    commitDialog.activateWindow()
    waitUntilTrue(commitDialog.isActiveWindow)

    commitDialog.ui.summaryEditor.setText("hello from ctrl+return")

    # Make sure the shortcut works even when a QPlainTextEdit (multiline editor) has focus
    commitDialog.ui.descriptionEditor.setFocus()
    assert commitDialog.ui.descriptionEditor.hasFocus()
    QTest.keySequence(commitDialog.focusWidget(), "Ctrl+Return")

    assert rw.repo.head_commit_message.strip() == "hello from ctrl+return"


@pytest.mark.parametrize("method", ["graphkey", "graphcm"])
def testCheckoutCommitDetachHead(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    for loc in [NavLocator.inCommit(Oid(hex="0966a434eb1a025db6b71485ab63a3bfbea520b6"), "master.txt"),
                NavLocator.inCommit(Oid(hex="6db9c2ebf75590eef973081736730a9ea169a0c4"), "a/a2.txt"),
                ]:
        rw.jump(loc, check=True)
        rw.activateWindow()

        if method == "graphcm":
            triggerContextMenuAction(rw.graphView.viewport(), r"check.?out")
        elif method == "graphkey":
            QTest.keyPress(rw.graphView.viewport(), Qt.Key.Key_Return)
        else:
            raise NotImplementedError(f"unknown method {method}")

        checkoutDialog: CheckoutCommitDialog = findQDialog(rw, "check.?out commit")
        checkoutDialog.ui.detachHeadRadioButton.setChecked(True)
        checkoutDialog.accept()

        assert repo.head_is_detached
        assert repo.head_commit_id == loc.commit

        assert rw.graphView.currentCommitId == loc.commit, "graphview's selected commit has jumped around"


def testCheckoutCommitBlockedByConflicts(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.statelessConflictingChange(wd)

    rw = mainWindow.openRepo(wd)

    oid = Oid(hex="0966a434eb1a025db6b71485ab63a3bfbea520b6")
    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), r"check.?out")

    acceptQMessageBox(rw, "fix merge conflicts before performing this action")


def testDetachHeadOnSameCommitAsCheckedOutBranch(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    headId = rw.repo.head_commit_id
    assert not rw.repo.head_is_detached
    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.DetachedHead)

    triggerMenuAction(mainWindow.menuBar(), "view/go to head commit")
    rw.graphView.setFocus()
    QTest.keyPress(rw.graphView, Qt.Key.Key_Return)

    checkoutDialog: CheckoutCommitDialog = findQDialog(rw, "check.?out commit")
    checkoutDialog.ui.detachHeadRadioButton.setChecked(True)
    checkoutDialog.accept()

    assert rw.repo.head_is_detached
    assert rw.repo.head_commit_id == headId

    # Sidebar must now reflect detached HEAD
    currentSidebarNode = SidebarNode.fromIndex(rw.sidebar.currentIndex())
    assert currentSidebarNode.kind == SidebarItem.DetachedHead


def testCommitOnDetachedHead(tempDir, mainWindow, gitBackend):
    wd = unpackRepo(tempDir)

    oid = Oid(hex='1203b03dc816ccbb67773f28b3c19318654b0bc8')

    with RepoContext(wd) as repo:
        repo.checkout_commit(oid)

    rw = mainWindow.openRepo(wd)

    assert rw.repo.head_is_detached
    assert rw.repo.head.target == oid

    displayedCommits = qlvGetRowData(rw.graphView, Qt.ItemDataRole.UserRole)
    assert rw.repo.head_commit in displayedCommits

    rw.diffArea.commitButton.click()
    acceptQMessageBox(rw, "create.+empty commit")
    commitDialog: CommitDialog = findQDialog(rw, "commit")
    commitDialog.ui.summaryEditor.setText("hello from detached HEAD")
    commitDialog.accept()

    assert rw.repo.head_is_detached
    assert rw.repo.head.target != oid  # detached HEAD should no longer point to initial commit

    newHeadCommit = rw.repo.head_commit
    assert newHeadCommit.message == "hello from detached HEAD\n"

    displayedCommits = qlvGetRowData(rw.graphView, Qt.ItemDataRole.UserRole)
    assert newHeadCommit in displayedCommits


@pytest.mark.skipif(pygit2OlderThan("1.15.1"), reason="old pygit2")
def testRevertCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "revert")
    acceptQMessageBox(rw, "do you want to revert")
    acceptQMessageBox(rw, "reverting.+c9ed7bf.+successful")

    commitDialog: CommitDialog = rw.findChild(CommitDialog)
    assert commitDialog.isVisible()
    assert re.search(r"revert.+delete c.c2-2.txt", commitDialog.ui.summaryEditor.text(), re.I)
    assert re.search(r"revert.+commit.+c9ed7bf", commitDialog.ui.descriptionEditor.toPlainText(), re.I)
    commitDialog.reject()

    assert rw.navLocator.context.isWorkdir()
    assert qlvGetRowData(rw.stagedFiles) == ["c/c2-2.txt"]
    assert rw.repo.status() == {"c/c2-2.txt": FileStatus.INDEX_NEW}


@pytest.mark.skipif(pygit2OlderThan("1.15.1"), reason="old pygit2")
def testAbortRevertCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "revert")
    acceptQMessageBox(rw, "do you want to revert")
    rejectQMessageBox(rw, "reverting.+c9ed7bf.+successful")

    assert rw.repo.state() == RepositoryState.REVERT
    assert rw.mergeBanner.isVisible()
    assert "revert" in rw.mergeBanner.label.text().lower()
    assert "abort" in rw.mergeBanner.buttons[-1].text().lower()

    rw.mergeBanner.buttons[-1].click()
    acceptQMessageBox(rw, "abort revert")
    assert rw.repo.state() == RepositoryState.NONE
    assert not os.path.exists(f"{wd}/c/c2-2.txt")


def testCherrypick(tempDir, mainWindow, gitBackend):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.checkout_local_branch("no-parent")

    oid = Oid(hex='ac7e7e44c1885efb472ad54a78327d66bfc4ecef')  # "First a/a1"

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "cherry")

    assert rw.diffArea.fileStackPage() == "workdir"
    assert rw.repo.status() == {"a/a1.txt": FileStatus.INDEX_NEW}

    acceptQMessageBox(rw, "cherry.+success.+commit")

    dialog: CommitDialog = findQDialog(rw, "commit")
    assert dialog.ui.summaryEditor.text() == "First a/a1"
    assert dialog.getOverriddenSignatureKind() == SignatureOverride.Author

    dialog.accept()

    headCommit = rw.repo.head_commit
    assert headCommit.message == "First a/a1\n"

    headCommitHash = str(headCommit.id)[:5]
    assert re.match(rf"commit.+{headCommitHash}.+created", mainWindow.statusBar().currentMessage(), re.I)

    rw.jump(NavLocator.inCommit(headCommit.id))
    assert qlvGetRowData(rw.committedFiles) == ["a/a1.txt"]


def testCherrypickDud(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex="f73b95671f326616d66b2afb3bdfcdbbce110b44")
    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "cherry")
    acceptQMessageBox(rw, "nothing to cherry.?pick.+already")


def testAbortCherrypick(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.checkout_local_branch("no-parent")

    oid = Oid(hex='ac7e7e44c1885efb472ad54a78327d66bfc4ecef')  # "First a/a1"

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "cherry")
    assert rw.diffArea.fileStackPage() == "workdir"
    assert rw.repo.status() == {"a/a1.txt": FileStatus.INDEX_NEW}
    rejectQMessageBox(rw, "cherry.+success.+commit")

    assert rw.repo.state() == RepositoryState.CHERRYPICK
    assert "First a/a1" in rw.repoModel.prefs.draftCommitMessage
    assert rw.mergeBanner.isVisibleTo(rw)
    assert re.search(r"cherry.+commit to conclude", rw.mergeBanner.label.text(), re.I | re.S)
    assert "abort" in rw.mergeBanner.buttons[-1].text().lower()

    # Abort cherrypick
    rw.mergeBanner.buttons[-1].click()
    acceptQMessageBox(rw, "abort.+cherry.+a/a1")

    assert rw.repo.state() == RepositoryState.NONE
    assert rw.repo.status() == {}
    assert rw.repoModel.prefs.draftCommitMessage == ""


def testNewTag(tempDir, mainWindow):
    newTag = "cool-tag"

    wd = unpackRepo(tempDir)

    # Nuke remotes for coverage of the no-remote code path.
    # (See also testPushTagOnCreate)
    with RepoContext(wd) as repo:
        repo.remotes.delete("origin")

    rw = mainWindow.openRepo(wd)
    assert newTag not in rw.repo.listall_tags()

    oid = Oid(hex='ac7e7e44c1885efb472ad54a78327d66bfc4ecef')  # "First a/a1"

    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), "tag this commit")

    dlg: NewTagDialog = findQDialog(rw, "new tag")
    QTest.keyClicks(dlg.ui.nameEdit, newTag)
    dlg.accept()

    assert newTag in rw.repo.listall_tags()


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey"])
def testDeleteTag(tempDir, mainWindow, method):
    tagToDelete = "annotated_tag"

    wd = unpackRepo(tempDir)

    # Nuke remotes for coverage of the no-remote code path.
    # (See also testPushDeleteTag)
    with RepoContext(wd) as repo:
        repo.remotes.delete("origin")

    rw = mainWindow.openRepo(wd)
    assert tagToDelete in rw.repo.listall_tags()
    node = rw.sidebar.findNodeByRef(f"refs/tags/{tagToDelete}")

    if method == "sidebarmenu":
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "delete")
    elif method == "sidebarkey":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Delete)
    else:
        raise NotImplementedError(f"unknown method {method}")

    findQDialog(rw, "delete tag").accept()
    assert tagToDelete not in rw.repo.listall_tags()


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey", "sidebardclick"])
def testCheckoutTag(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    repo = rw.repo

    node = sb.findNodeByRef("refs/tags/annotated_tag")
    if method == "sidebarmenu":
        menu = sb.makeNodeMenu(node)
        triggerMenuAction(menu, "check out")
    elif method == "sidebarkey":
        sb.setFocus()
        sb.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Return)
    elif method == "sidebardclick":
        rect = sb.visualRect(node.createIndex(sb.sidebarModel))
        QTest.mouseDClick(sb.viewport(), Qt.MouseButton.LeftButton, pos=rect.topLeft())
    else:
        raise NotImplementedError(f"unknown method {method}")

    checkoutDialog: CheckoutCommitDialog = findQDialog(rw, "check.?out commit")
    checkoutDialog.ui.detachHeadRadioButton.setChecked(True)
    checkoutDialog.accept()

    oid = Oid(hex="c070ad8c08840c8116da865b2d65593a6bb9cd2a")
    assert repo.head_is_detached
    assert repo.head_commit_id == oid
    assert rw.graphView.currentCommitId == oid
