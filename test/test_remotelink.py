# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.application import GFApplication
from gitfourchette.forms.clonedialog import CloneDialog
from gitfourchette.forms.remotedialog import RemoteDialog
from gitfourchette.nav import NavContext
from .util import *


NET_TIMEOUT = 30_000


class AskpassShim:
    def __init__(self, password="empty"):
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
    os.chmod(privKeyCopy, 0o600)

    # Set custom passphrase-protected key
    cloneDialog.ui.keyFilePicker.setPath(pubKeyCopy)

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
    assert "HelloTestKey" in rw.repo.get_config_value(("remote", "origin", "gitfourchette-keyfile"))


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
def testSshAddRemoteAndFetchWithPassphrase(tempDir, mainWindow, taskThread):
    # Copy keyfile to non-default location to make sure we're not automatically picking up another key
    pubKeyCopy = tempDir.name + "/HelloTestKey.pub"
    privKeyCopy = tempDir.name + "/HelloTestKey"
    shutil.copyfile(getTestDataPath("keys/pygit2_empty.pub"), pubKeyCopy)
    shutil.copyfile(getTestDataPath("keys/pygit2_empty"), privKeyCopy)
    os.chmod(privKeyCopy, 0o600)

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
