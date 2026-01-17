# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.application import GFApplication
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


class AskpassShim:
    def __init__(self, password="empty", cancel=False):
        app = GFApplication.instance()
        self.password = password
        self.dumpFile = Path(app.tempDir.path()) / "askpass-dumpfile.txt"
        self.dumpFile.touch(exist_ok=True)
        self.environBackup = dict(os.environ)

        app.mainWindow.onAcceptPrefsDialog({"ownAskpass": False})

        os.environ.update({
            "SSH_ASKPASS": getTestDataPath("askpass-shim.py"),
            "SSH_ASKPASS_REQUIRE": "force",
            "GFTEST_ASKPASS_SHIM_PASSWORD": self.password,
            "GFTEST_ASKPASS_SHIM_DUMPFILE": str(self.dumpFile),
        })

        if cancel:
            os.environ["GFTEST_ASKPASS_SHIM_CANCEL"] = "1"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        os.environ.clear()
        os.environ.update(self.environBackup)


@requiresNetwork
def testHttpsCloneRepo(tempDir, mainWindow, taskThread):
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


@requiresNetwork
def testSshCloneRepo(tempDir, mainWindow, taskThread, passphraseProtectedKey):
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

    # Set custom passphrase-protected key
    cloneDialog.ui.keyFilePicker.setPath(passphraseProtectedKey)

    # Clone
    with AskpassShim() as askpassShim:
        cloneDialog.cloneButton.click()
        waitForSignal(cloneDialog.finished, timeout=NET_TIMEOUT)

        # Make sure we're prompted to enter the passphrase for the correct key
        assert re.search("Enter passphrase for key.+HelloTestKey", askpassShim.dumpFile.read_text())

    rw = waitForRepoWidget(mainWindow)
    assert "master" in rw.repo.branches.local
    assert "origin/master" in rw.repo.branches.remote
    assert "origin/no-parent" in rw.repo.branches.remote
    assert "HelloTestKey" in rw.repoModel.prefs.customKeyFile


@requiresNetwork
def testSshCloneRepoCancelAskpass(tempDir, mainWindow, taskThread, passphraseProtectedKey):
    triggerMenuAction(mainWindow.menuBar(), "file/clone")
    cloneDialog: CloneDialog = findQDialog(mainWindow, "clone")
    cloneDialog.ui.urlEdit.setEditText("git@github.com:libgit2/TestGitRepository")
    cloneDialog.ui.pathEdit.setText(tempDir.name + "/cloned")

    # Set custom passphrase-protected key
    cloneDialog.ui.keyFilePicker.setPath(passphraseProtectedKey)

    # Attempt to clone but cancel askpass
    with AskpassShim(cancel=True):
        cloneDialog.cloneButton.click()

    waitUntilTrue(lambda: not cloneDialog.taskRunner.isBusy(), timeout=NET_TIMEOUT)

    assert cloneDialog.ui.statusForm.ui.blurbLabel.isVisible()
    assert "passphrase input canceled from unit test" in cloneDialog.ui.statusForm.ui.blurbLabel.text()

    cloneDialog.reject()


@requiresNetwork
def testHttpsShallowClone(tempDir, mainWindow, taskThread):
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
def testHttpsAddRemoteAndFetch(tempDir, mainWindow, taskThread):
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


@requiresNetwork
@pytest.mark.skipif(WINDOWS, reason="TODO: flaky on Windows")
def testSshAddRemoteAndFetchWithPassphrase(tempDir, mainWindow, taskThread, passphraseProtectedKey):
    mainWindow.onAcceptPrefsDialog({"ownSshAgent": True})

    wd = tempDir.name + "/emptyrepo"
    pygit2.init_repository(wd)
    mainWindow.openRepo(wd)
    rw = waitForRepoWidget(mainWindow)

    # -------------------------------------------
    # Set passphrase-protected keyfile

    triggerMenuAction(mainWindow.menuBar(), "repo/settings")
    repoSettings = findQDialog(rw, "repo settings", RepoSettingsDialog)
    repoSettings.ui.keyFilePicker.setPath(passphraseProtectedKey)
    repoSettings.accept()

    # -------------------------------------------
    # Add remote

    triggerMenuAction(mainWindow.menuBar(), "repo/add remote")
    remoteDialog = findQDialog(rw, "add remote", RemoteDialog)
    remoteDialog.ui.urlEdit.setText("ssh://git@github.com/pygit2/empty")
    remoteDialog.ui.nameEdit.setText("origin")
    assert remoteDialog.ui.fetchAfterAddCheckBox.isChecked()

    # Accept "add remote", kicking off a fetch
    with AskpassShim() as askpass:
        remoteDialog.accept()
        waitForSignal(rw.taskRunner.ready, timeout=NET_TIMEOUT)

        assert askpass.dumpFile.read_text().startswith("Enter passphrase for key ")
        askpass.dumpFile.write_text("DO NOT LAUNCH ASKPASS AGAIN")

    assert "origin/master" in rw.repo.branches.remote

    # -------------------------------------------
    # Fetch, shouldn't prompt for passphrase again thanks to built-in ssh-agent

    with AskpassShim() as askpass:
        triggerMenuAction(mainWindow.menuBar(), "repo/fetch remote branches")
        waitForSignal(rw.taskRunner.ready, timeout=NET_TIMEOUT)

        # Make sure the dump file wasn't overwritten by another invocation of askpass
        assert askpass.dumpFile.read_text() == "DO NOT LAUNCH ASKPASS AGAIN", \
            "askpass was invoked again. Is ssh-agent running?"
