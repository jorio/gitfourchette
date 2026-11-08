# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.forms.askpassdialog import AskpassDialog
from gitfourchette.forms.clonedialog import CloneDialog
from gitfourchette.forms.remotedialog import RemoteDialog
from gitfourchette.forms.reposettingsdialog import RepoSettingsDialog
from gitfourchette.nav import NavContext
from .util import *


NET_TIMEOUT = 30_000


@pytest.fixture
def passphraseProtectedKey(tempDir):
    # Copy keyfile to non-default location to make sure we're not automatically picking up another key
    pubKeyCopy = tempDir.name + "/HelloTestKey.pub"
    privKeyCopy = tempDir.name + "/HelloTestKey"
    shutil.copyfile(getTestDataPath("keys/pygit2_empty.pub"), pubKeyCopy)
    shutil.copyfile(getTestDataPath("keys/pygit2_empty"), privKeyCopy)
    os.chmod(privKeyCopy, 0o600)
    return pubKeyCopy


@requiresNetwork
def testHttpsCloneRepo(tempDir, mainWindow):
    triggerMenuAction(mainWindow.menuBar(), "file/clone")
    cloneDialog = findQDialog(mainWindow, "clone", t=CloneDialog)
    cloneDialog.ui.urlEdit.setEditText("  https://github.com/libgit2/TestGitRepository  ")  # whitespace should be stripped
    cloneDialog.ui.pathEdit.setText(tempDir.name + "/cloned")

    with AsynchronousTaskContext(cloneDialog.taskRunner, tearDown=False):
        cloneDialog.cloneButton.click()
        waitForSignal(cloneDialog.finished, timeout=NET_TIMEOUT)

    rw = waitForRepoWidget(mainWindow)

    assert "master" in rw.repo.branches.local
    assert "origin/master" in rw.repo.branches.remote
    assert "origin/no-parent" in rw.repo.branches.remote


@requiresNetwork
def testSshCloneRepo(tempDir, mainWindow, passphraseProtectedKey):
    triggerMenuAction(mainWindow.menuBar(), "file/clone")
    cloneDialog = findQDialog(mainWindow, "clone", t=CloneDialog)
    cloneDialog.ui.urlEdit.setEditText("https://github.com/libgit2/TestGitRepository")
    cloneDialog.ui.pathEdit.setText(tempDir.name + "/cloned")

    # Set SSH URL via protocol swap button
    protocolButton = cloneDialog.ui.protocolButton
    assert protocolButton.isVisible()
    assert protocolButton.text() == "https"
    protocolButton.menu().actions()[0].trigger()
    assert protocolButton.text() == "ssh"
    assert cloneDialog.ui.urlEdit.lineEdit().text() == "git@github.com:libgit2/TestGitRepository"

    # Set custom passphrase-protected key
    cloneDialog.ui.keyFilePicker.setPath(passphraseProtectedKey)

    # Clone
    with AsynchronousTaskContext(cloneDialog.taskRunner, tearDown=False):
        cloneDialog.cloneButton.click()

        # Enter password
        askpassDialog = waitForQDialog(mainWindow, "enter ssh credentials", t=AskpassDialog, timeout=NET_TIMEOUT)
        # Make sure we're prompted to enter the passphrase for the correct key
        assert findTextInWidget(askpassDialog.promptLabel, "Enter passphrase for key.+HelloTestKey")
        askpassDialog.lineEdit.setText("empty")
        askpassDialog.accept()

        waitForSignal(cloneDialog.finished, timeout=NET_TIMEOUT)

    rw = waitForRepoWidget(mainWindow)
    assert "master" in rw.repo.branches.local
    assert "origin/master" in rw.repo.branches.remote
    assert "origin/no-parent" in rw.repo.branches.remote
    assert "HelloTestKey" in rw.repoModel.prefs.customKeyFile


@requiresNetwork
def testSshCloneRepoCancelAskpass(tempDir, mainWindow, passphraseProtectedKey):
    triggerMenuAction(mainWindow.menuBar(), "file/clone")
    cloneDialog = findQDialog(mainWindow, "clone", t=CloneDialog)
    cloneDialog.ui.urlEdit.setEditText("git@github.com:libgit2/TestGitRepository")
    cloneDialog.ui.pathEdit.setText(tempDir.name + "/cloned")

    # Set custom passphrase-protected key
    cloneDialog.ui.keyFilePicker.setPath(passphraseProtectedKey)

    # Attempt to clone but cancel askpass
    with AsynchronousTaskContext(cloneDialog.taskRunner, tearDownTimeout=NET_TIMEOUT):
        cloneDialog.cloneButton.click()
        askpassDialog = waitForQDialog(mainWindow, "enter ssh credentials", t=AskpassDialog, timeout=NET_TIMEOUT)
        askpassDialog.cancelButton.click()

    assert not cloneDialog.taskRunner.isBusy()
    assert cloneDialog.ui.statusForm.ui.blurbLabel.isVisible()
    assert findTextInWidget(cloneDialog.ui.statusForm.ui.blurbLabel, "you clicked the cancel button")

    cloneDialog.reject()


@requiresNetwork
def testHttpsShallowClone(tempDir, mainWindow):
    triggerMenuAction(mainWindow.menuBar(), "file/clone")
    cloneDialog = waitForQDialog(mainWindow, "clone", t=CloneDialog)
    cloneDialog.ui.urlEdit.setEditText("https://github.com/libgit2/TestGitRepository")
    cloneDialog.ui.pathEdit.setText(tempDir.name + "/cloned")
    cloneDialog.ui.shallowCloneCheckBox.setChecked(True)
    cloneDialog.cloneButton.click()

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
def testHttpsAddRemoteAndFetch(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git remote remove origin", wd)
    rw = mainWindow.openRepo(wd)
    assert "origin/master" not in rw.repo.branches.remote

    with AsynchronousTaskContext(rw.taskRunner, tearDownTimeout=NET_TIMEOUT):
        triggerMenuAction(mainWindow.menuBar(), "repo/add remote")
        remoteDialog = waitForQDialog(rw, "add remote", t=RemoteDialog)
        remoteDialog.ui.urlEdit.setText("https://github.com/libgit2/TestGitRepository")
        remoteDialog.ui.nameEdit.setText("origin")
        remoteDialog.accept()

    assert "origin/master" in rw.repo.branches.remote


@requiresNetwork
@pytest.mark.skipif(WINDOWS, reason="TODO: flaky on Windows - fails to start own SshAgent")
def testSshAddRemoteAndFetchWithPassphrase(tempDir, mainWindow, passphraseProtectedKey):
    GFApplication.applyPrefs(ownSshAgent=True)

    wd = tempDir.name + "/emptyrepo"
    pygit2.init_repository(wd)
    rw = mainWindow.openRepo(wd)

    # -------------------------------------------
    # Set passphrase-protected keyfile

    triggerMenuAction(mainWindow.menuBar(), "repo/settings")
    repoSettings = findQDialog(rw, "repo settings", t=RepoSettingsDialog)
    repoSettings.ui.keyFilePicker.setPath(passphraseProtectedKey)
    repoSettings.accept()

    # -------------------------------------------
    # Add remote

    with AsynchronousTaskContext(rw.taskRunner, tearDownTimeout=NET_TIMEOUT):
        triggerMenuAction(mainWindow.menuBar(), "repo/add remote")
        remoteDialog = waitForQDialog(rw, "add remote", t=RemoteDialog)
        remoteDialog.ui.urlEdit.setText("ssh://git@github.com/pygit2/empty")
        remoteDialog.ui.nameEdit.setText("origin")
        assert remoteDialog.ui.fetchAfterAddCheckBox.isChecked()

        # Accept "add remote", kicking off a fetch
        remoteDialog.accept()

        askpassDialog = waitForQDialog(mainWindow, "enter ssh credentials", t=AskpassDialog, timeout=NET_TIMEOUT)
        assert findTextInWidget(askpassDialog.promptLabel, "Enter passphrase for key ")
        askpassDialog.lineEdit.setText("empty")
        askpassDialog.accept()

    assert not rw.taskRunner.isBusy()
    assert "origin/master" in rw.repo.branches.remote

    # -------------------------------------------
    # Fetch, shouldn't prompt for passphrase again thanks to built-in ssh-agent

    with AsynchronousTaskContext(rw.taskRunner, tearDownTimeout=NET_TIMEOUT):
        triggerMenuAction(mainWindow.menuBar(), "repo/fetch remote branches")

    # Make sure askpass wasn't invoked again (ssh-agent should have remembered the credentials)
    with pytest.raises(KeyError):
        findQDialog(mainWindow, "enter ssh credentials", t=AskpassDialog)
