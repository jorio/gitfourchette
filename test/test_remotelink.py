# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.clonedialog import CloneDialog
from gitfourchette.forms.passphrasedialog import PassphraseDialog
from gitfourchette.forms.remotedialog import RemoteDialog
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.nav import NavContext
from .util import *


NET_TIMEOUT = 30_000


@requiresNetwork
def testHttpsCloneRepo(tempDir, mainWindow, taskThread, gitBackend):
    triggerMenuAction(mainWindow.menuBar(), "file/clone")
    cloneDialog: CloneDialog = findQDialog(mainWindow, "clone")
    cloneDialog.ui.urlEdit.setEditText("  https://github.com/libgit2/TestGitRepository  ")  # whitespace should be stripped
    cloneDialog.ui.pathEdit.setText(tempDir.name + "/cloned")
    cloneDialog.cloneButton.click()
    waitForSignal(cloneDialog.finished, timeout=NET_TIMEOUT)

    rw = waitForRepoWidget(mainWindow)
    assert "master" in rw.repo.branches.local
    assert "origin/master" in rw.repo.branches.remote
    assert "origin/no-parent" in rw.repo.branches.remote


# TODO: Vanilla git backend
@requiresNetwork
def testSshCloneRepo(tempDir, mainWindow, taskThread):
    triggerMenuAction(mainWindow.menuBar(), "file/clone")
    cloneDialog: CloneDialog = findQDialog(mainWindow, "clone")
    cloneDialog.ui.urlEdit.setEditText("https://github.com/libgit2/TestGitRepository")
    cloneDialog.ui.pathEdit.setText(tempDir.name + "/cloned")

    # Set SSH URL via protocol swap button
    protocolButton = cloneDialog.ui.protocolButton
    assert protocolButton.isVisible()
    assert protocolButton.text() == "https"
    protocolButton.menu().actions()[0].trigger()
    assert protocolButton.text() == "ssh"
    assert cloneDialog.ui.urlEdit.lineEdit().text() == "git@github.com:libgit2/TestGitRepository"

    # Copy keyfile to non-default location to make sure we're not automatically picking up another key
    pubKeyCopy = tempDir.name + "/HelloTestKey.pub"
    privKeyCopy = tempDir.name + "/HelloTestKey"
    shutil.copyfile(getTestDataPath("keys/pygit2_empty.pub"), pubKeyCopy)
    shutil.copyfile(getTestDataPath("keys/pygit2_empty"), privKeyCopy)

    # Set custom passphrase-protected key
    cloneDialog.ui.keyFilePicker.setPath(pubKeyCopy)
    cloneDialog.cloneButton.click()

    passphraseDialog: TextInputDialog = waitForQDialog(mainWindow, "passphrase", timeout=NET_TIMEOUT)
    # Make sure we're prompted to enter the passphrase for the correct key
    assert any("HelloTestKey" in label.text() for label in passphraseDialog.findChildren(QLabel))
    # Enter passphrase and accept
    passphraseDialog.findChild(QLineEdit).setText("empty")
    passphraseDialog.accept()
    waitForSignal(cloneDialog.finished, timeout=NET_TIMEOUT)

    rw = waitForRepoWidget(mainWindow)
    assert "master" in rw.repo.branches.local
    assert "origin/master" in rw.repo.branches.remote
    assert "origin/no-parent" in rw.repo.branches.remote
    assert "HelloTestKey" in rw.repo.get_config_value(("remote", "origin", "gitfourchette-keyfile"))


@requiresNetwork
def testHttpsShallowClone(tempDir, mainWindow, taskThread, gitBackend):
    triggerMenuAction(mainWindow.menuBar(), "file/clone")
    cloneDialog: CloneDialog = findQDialog(mainWindow, "clone")
    cloneDialog.ui.urlEdit.setEditText("https://github.com/libgit2/TestGitRepository")
    cloneDialog.ui.pathEdit.setText(tempDir.name + "/cloned")
    cloneDialog.ui.shallowCloneCheckBox.setChecked(True)
    cloneDialog.cloneButton.click()
    waitForSignal(cloneDialog.finished, timeout=NET_TIMEOUT)

    rw = waitForRepoWidget(mainWindow)
    assert "master" in rw.repo.branches.local
    assert "origin/master" in rw.repo.branches.remote
    assert "origin/no-parent" in rw.repo.branches.remote

    # 5 rows: Uncommitted changes; 1 lone commit for each of the 3 branches; Shallow clone row
    assert rw.graphView.clModel.rowCount() == 5

    qlvClickNthRow(rw.graphView, 4)
    assert rw.navLocator.context == NavContext.SPECIAL
    assert rw.specialDiffView.isVisible()
    assert "shallow" in rw.specialDiffView.toPlainText().lower()


@requiresNetwork
def testHttpsAddRemoteAndFetch(tempDir, mainWindow, taskThread, gitBackend):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.remotes.delete("origin")
    mainWindow.openRepo(wd)
    rw = waitForRepoWidget(mainWindow)
    assert "origin/master" not in rw.repo.branches.remote

    triggerMenuAction(mainWindow.menuBar(), "repo/add remote")
    remoteDialog: RemoteDialog = findQDialog(rw, "add remote")
    remoteDialog.ui.urlEdit.setText("https://github.com/libgit2/TestGitRepository")
    remoteDialog.ui.nameEdit.setText("origin")
    remoteDialog.accept()

    waitForSignal(rw.taskRunner.ready, timeout=NET_TIMEOUT)
    assert "origin/master" in rw.repo.branches.remote


# TODO: Vanilla git backend
@requiresNetwork
def testSshAddRemoteAndFetchWithPassphrase(tempDir, mainWindow, taskThread):
    # Copy keyfile to non-default location to make sure we're not automatically picking up another key
    pubKeyCopy = tempDir.name + "/HelloTestKey.pub"
    privKeyCopy = tempDir.name + "/HelloTestKey"
    shutil.copyfile(getTestDataPath("keys/pygit2_empty.pub"), pubKeyCopy)
    shutil.copyfile(getTestDataPath("keys/pygit2_empty"), privKeyCopy)

    wd = tempDir.name + "/emptyrepo"
    pygit2.init_repository(wd)
    mainWindow.openRepo(wd)
    rw = waitForRepoWidget(mainWindow)

    # -------------------------------------------
    # Add remote with passphrase-protected keyfile

    triggerMenuAction(mainWindow.menuBar(), "repo/add remote")
    remoteDialog: RemoteDialog = findQDialog(rw, "add remote")
    remoteDialog.ui.urlEdit.setText("ssh://git@github.com/pygit2/empty")
    remoteDialog.ui.nameEdit.setText("origin")
    remoteDialog.ui.keyFilePicker.setPath(pubKeyCopy)
    assert remoteDialog.ui.fetchAfterAddCheckBox.isChecked()

    # Accept "add remote", kicking off a fetch
    remoteDialog.accept()

    # -------------------------------------------
    # Enter passphrase, don't remember it

    pd: PassphraseDialog = waitForQDialog(mainWindow, "passphrase-protected key file", timeout=NET_TIMEOUT)
    pd.lineEdit.setText("empty")

    # Make sure it's for the correct key
    assert "HelloTestKey" in rw.repo.get_config_value(("remote", "origin", "gitfourchette-keyfile"))
    assert any("HelloTestKey" in label.text() for label in pd.findChildren(QLabel))

    # Don't remember the passphrase
    assert pd.rememberCheckBox.isChecked()  # ticked by default
    pd.rememberCheckBox.setChecked(False)

    # Play with echo mode
    assert pd.lineEdit.echoMode() == QLineEdit.EchoMode.Password
    pd.lineEdit.actions()[0].trigger()
    assert pd.lineEdit.echoMode() == QLineEdit.EchoMode.Normal
    pd.lineEdit.actions()[0].trigger()
    assert pd.lineEdit.echoMode() == QLineEdit.EchoMode.Password

    # Accept
    pd.accept()
    waitForSignal(rw.taskRunner.ready, timeout=NET_TIMEOUT)
    assert "origin/master" in rw.repo.branches.remote

    # -------------------------------------------
    # Fetch, enter passphrase, remember it, but cancel

    triggerMenuAction(mainWindow.menuBar(), "repo/fetch remote branches")
    pd: PassphraseDialog = waitForQDialog(mainWindow, "passphrase-protected key file")
    assert any("HelloTestKey" in label.text() for label in pd.findChildren(QLabel))
    pd.lineEdit.setText("empty")
    assert not pd.rememberCheckBox.isChecked()  # we unticked it previously
    pd.rememberCheckBox.setChecked(True)
    pd.reject()
    waitForQMessageBox(mainWindow, "passphrase entry canceled").accept()

    # -------------------------------------------
    # Fetch, enter passphrase, remember it

    triggerMenuAction(mainWindow.menuBar(), "repo/fetch remote branches")
    pd: PassphraseDialog = waitForQDialog(mainWindow, "passphrase-protected key file")
    assert any("HelloTestKey" in label.text() for label in pd.findChildren(QLabel))
    pd.lineEdit.setText("empty")
    assert pd.rememberCheckBox.isChecked()  # we ticked it previously
    pd.accept()
    waitForSignal(rw.taskRunner.ready, timeout=NET_TIMEOUT)

    # -------------------------------------------
    # Fetch, shouldn't prompt for passphrase again

    triggerMenuAction(mainWindow.menuBar(), "repo/fetch remote branches")
    waitForSignal(rw.taskRunner.ready, timeout=NET_TIMEOUT)
