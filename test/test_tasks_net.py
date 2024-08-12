"""
Remote access tests.

Note: these tests don't actually access the network.
We use a bare repository on the local filesystem as a "remote server".
"""

import os.path

import pytest

from gitfourchette.forms.clonedialog import CloneDialog
from gitfourchette.forms.pushdialog import PushDialog
from gitfourchette.forms.remotedialog import RemoteDialog
from gitfourchette.mainwindow import NoRepoWidgetError
from gitfourchette.nav import NavLocator
from gitfourchette.sidebar.sidebarmodel import EItem
from . import reposcenario
from .util import *


@pytest.mark.skipif(pygit2OlderThan("1.15.1"), reason="old pygit2")
def testCloneRepoWithSubmodules(tempDir, mainWindow):
    wd = unpackRepo(tempDir, renameTo="unpacked-repo")
    subWd, _ = reposcenario.submodule(wd, True)  # spice it up with a submodule
    bare = makeBareCopy(wd, addAsRemote="", preFetch=False)
    target = str(Path(f"{tempDir.name}", "the-clone"))

    with pytest.raises(NoRepoWidgetError):
        mainWindow.currentRepoWidget()  # no repo opened yet

    # Bring up clone dialog
    triggerMenuAction(mainWindow.menuBar(), "file/clone")
    cloneDialog: CloneDialog = findQDialog(mainWindow, "clone")
    assert not cloneDialog.ui.pathEdit.text()  # path initially empty
    assert -1 == cloneDialog.ui.urlEdit.currentIndex()
    assert not cloneDialog.ui.urlEdit.lineEdit().text()  # URL initially empty
    assert not cloneDialog.cloneButton.isEnabled()  # disallow cloning without an URL
    assert cloneDialog.ui.recurseSubmodulesCheckBox.isChecked()

    # Set URL in clone dialog
    cloneDialog.ui.urlEdit.setEditText(bare)
    assert "unpacked-repo-bare" in cloneDialog.ui.pathEdit.text()  # autofilled after entering URL

    # Test expanduser on manual path entry
    cloneDialog.ui.pathEdit.setText("~/thisshouldwork")
    assert cloneDialog.path == str(Path("~/thisshouldwork").expanduser())

    # Set target path in clone dialog
    cloneDialog.ui.pathEdit.clear()
    cloneDialog.ui.browseButton.click()
    assert not cloneDialog.cloneButton.isEnabled()  # disallow cloning to empty path
    qfd: QFileDialog = cloneDialog.findChild(QFileDialog)
    assert "clone" in qfd.windowTitle().lower()
    qfd.selectFile(target)
    qfd.accept()
    assert cloneDialog.ui.pathEdit.text() == target
    QTest.qWait(0)  # wait for QFileDialog to be collected

    # Play with key file picker
    assert not cloneDialog.ui.keyFilePicker.checkBox.isChecked()
    cloneDialog.ui.keyFilePicker.checkBox.click()
    qfd: QFileDialog = cloneDialog.findChild(QFileDialog)
    assert "key file" in qfd.windowTitle().lower()
    qfd.reject()
    assert not cloneDialog.ui.keyFilePicker.checkBox.isChecked()
    QTest.qWait(0)  # wait for QFileDialog to be collected

    # Fire ze missiles
    assert cloneDialog.cloneButton.isEnabled()
    cloneDialog.cloneButton.click()
    assert not cloneDialog.isVisible()

    # Get RepoWidget for cloned repo
    rw = mainWindow.currentRepoWidget()
    assert rw is not None

    # Check that the cloned repo's state looks OK
    clonedRepo = rw.repo
    assert os.path.samefile(clonedRepo.workdir, target)
    assert "submoname" in clonedRepo.listall_submodules_dict()

    # Look at some commit within the repo
    oid = Oid(hex="bab66b48f836ed950c99134ef666436fb07a09a0")
    rw.jump(NavLocator.inCommit(oid))
    assert ["c/c1.txt"] == qlvGetRowData(rw.committedFiles)

    # Bring up clone dialog again and check that the URL was added to the history
    triggerMenuAction(mainWindow.menuBar(), "file/clone")
    cloneDialog: CloneDialog = findQDialog(mainWindow, "clone")
    urlEdit = cloneDialog.ui.urlEdit
    assert urlEdit.currentText() == ""
    assert 0 <= urlEdit.findText("clear", Qt.MatchFlag.MatchContains)
    assert 0 <= urlEdit.findText(bare)
    # Select past URL
    urlEdit.setCurrentIndex(urlEdit.findText(bare))
    assert urlEdit.currentText() == bare
    # Clear clone history (must emit 'activated' for this one)
    urlEdit.activated.emit(urlEdit.findText("clear", Qt.MatchFlag.MatchContains))
    assert urlEdit.count() == 1
    cloneDialog.reject()


def testFetchNewRemoteBranches(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    makeBareCopy(wd, addAsRemote="localfs", preFetch=False)
    rw = mainWindow.openRepo(wd)

    assert "localfs/master" not in rw.repo.branches.remote
    assert all(n.data.startswith("refs/remotes/origin/") for n in rw.sidebar.walk() if n.kind == EItem.RemoteBranch)

    node = rw.sidebar.findNode(lambda n: n.kind == EItem.Remote and n.data == "localfs")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "fetch")

    assert "localfs/master" in rw.repo.branches.remote
    assert any(n.data.startswith("refs/remotes/localfs/") for n in rw.sidebar.walk() if n.kind == EItem.RemoteBranch)


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey"])
def testDeleteRemoteBranch(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    makeBareCopy(wd, addAsRemote="localfs", preFetch=True)
    rw = mainWindow.openRepo(wd)

    assert "localfs/no-parent" in rw.repo.branches.remote

    node = rw.sidebar.findNodeByRef("refs/remotes/localfs/no-parent")

    if method == "sidebarmenu":
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "delete")
    elif method == "sidebarkey":
        rw.sidebar.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Delete)
    else:
        raise NotImplementedError(f"unknown method {method}")

    acceptQMessageBox(rw, "really delete.+from.+remote repository")

    assert "localfs/no-parent" not in rw.repo.branches.remote
    with pytest.raises(KeyError):
        rw.sidebar.findNodeByRef("refs/remotes/localfs/no-parent")


def testRenameRemoteBranch(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    makeBareCopy(wd, addAsRemote="localfs", preFetch=True)
    rw = mainWindow.openRepo(wd)

    assert "localfs/no-parent" in rw.repo.branches.remote

    node = rw.sidebar.findNodeByRef("refs/remotes/localfs/no-parent")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "rename")

    dlg = findQDialog(rw, "rename")
    dlg.findChild(QLineEdit).setText("new-name")
    dlg.accept()

    assert "localfs/no-parent" not in rw.repo.branches.remote
    assert "localfs/new-name" in rw.repo.branches.remote
    with pytest.raises(KeyError):
        rw.sidebar.findNodeByRef("refs/remotes/localfs/no-parent")
    rw.sidebar.findNodeByRef("refs/remotes/localfs/new-name")


@pytest.mark.parametrize("method", ["sidebar", "toolbar"])
def testFetchRemote(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)

    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True)

    # Make some modifications to the bare repository that serves as a remote.
    # We're going to create a new branch and delete another.
    # The client must pick up on those modifications once it fetches the remote.
    with RepoContext(barePath) as bareRepo:
        assert bareRepo.is_bare
        bareRepo.create_branch_on_head("new-remote-branch")
        bareRepo.delete_local_branch("no-parent")

    rw = mainWindow.openRepo(wd)

    # We only know about master and no-parent in the remote for now
    assert {"localfs/master", "localfs/no-parent"} == set(x for x in rw.repo.branches.remote if x.startswith("localfs/"))

    # Fetch the remote
    if method == "sidebar":
        node = rw.sidebar.findNode(lambda n: n.kind == EItem.Remote and n.data == "localfs")
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "fetch")
    elif method == "toolbar":
        findQToolButton(mainWindow.mainToolBar, "fetch").click()
    else:
        raise NotImplementedError(f"Unsupported method {method}")

    # We must see that no-parent is gone and that new-remote-branch appeared
    assert {"localfs/master", "localfs/new-remote-branch"} == set(x for x in rw.repo.branches.remote if x.startswith("localfs/"))


def testFetchRemoteBranch(tempDir, mainWindow):
    oldHead = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    newHead = Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322")

    wd = unpackRepo(tempDir)

    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True)

    # Modify the master branch in the bare repository that serves as a remote.
    # The client must pick up on this modification once it fetches the remote branch.
    with RepoContext(barePath) as bareRepo:
        assert bareRepo.is_bare
        assert bareRepo.head.target == oldHead
        bareRepo.reset(newHead, ResetMode.SOFT)  # can't reset hard in bare repos, whatever...
        assert bareRepo.head.target == newHead

    rw = mainWindow.openRepo(wd)

    # We still think the remote's master branch is on the old head for now
    assert rw.repo.branches.remote["localfs/master"].target == oldHead

    # Fetch the remote branch
    node = rw.sidebar.findNodeByRef("refs/remotes/localfs/master")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "fetch")
    acceptQMessageBox(rw, fr"localfs/master.+moved.+{str(oldHead)[:7]}.+{str(newHead)[:7]}")

    # The position of the remote's master branch should be up-to-date now
    assert rw.repo.branches.remote["localfs/master"].target == newHead


@pytest.mark.parametrize("pull", [False, True])
def testFetchRemoteBranchVanishes(tempDir, mainWindow, pull):
    oldHead = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    wd = unpackRepo(tempDir)

    # Modify the master branch in the bare repository that serves as a remote.
    # The client must pick up on this modification once it fetches the remote branch.
    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True)
    with RepoContext(barePath) as bareRepo:
        assert bareRepo.is_bare
        bareRepo.branches.local['master'].rename('switcheroo')

    rw = mainWindow.openRepo(wd)

    # We still think the remote's master branch is on the old head for now
    assert rw.sidebar.findNodeByRef("refs/remotes/localfs/master")
    assert rw.repo.branches.remote["localfs/master"].target == oldHead

    if not pull:
        # Fetch the remote branch
        node = rw.sidebar.findNodeByRef("refs/remotes/localfs/master")
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "fetch")
    else:
        # Pull the remote branch
        node = rw.sidebar.findNodeByRef("refs/heads/master")
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "pull")
    acceptQMessageBox(rw, fr"localfs/master.+disappeared")

    # It's gone
    assert "localfs/master" not in rw.repo.branches.remote
    with pytest.raises(KeyError):
        rw.sidebar.findNodeByRef("refs/remotes/localfs/master")


@pytest.mark.parametrize("pull", [False, True])
def testFetchRemoteBranchNoChange(tempDir, mainWindow, pull):
    oldHead = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")

    wd = unpackRepo(tempDir)
    makeBareCopy(wd, addAsRemote="localfs", preFetch=True)
    rw = mainWindow.openRepo(wd)

    assert rw.repo.branches.remote["localfs/master"].target == oldHead

    if not pull:
        node = rw.sidebar.findNodeByRef("refs/remotes/localfs/master")
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "fetch")
        acceptQMessageBox(rw, "no new commits")
    else:
        node = rw.sidebar.findNodeByRef("refs/heads/master")
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "pull")
        # No message box on pull

    assert rw.repo.branches.remote["localfs/master"].target == oldHead


def testFetchRemoteBranchNoUpstream(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.edit_upstream_branch("master", "")

    rw = mainWindow.openRepo(wd)
    triggerMenuAction(mainWindow.menuBar(), "repo/fetch")
    acceptQMessageBox(rw, "n.t tracking.+upstream")


def testFetchRemoteHistoryWithUnbornHead(tempDir, mainWindow):
    originWd = unpackRepo(tempDir)

    rw = mainWindow.newRepo(tempDir.name + "/newrepo")
    triggerMenuAction(mainWindow.menuBar(), "repo/add remote")
    remoteDialog: RemoteDialog = findQDialog(rw, "add remote")
    remoteDialog.ui.urlEdit.setText(originWd)
    remoteDialog.ui.nameEdit.setText("localfs")
    remoteDialog.accept()
    QTest.qWait(1)

    assert rw.sidebar.findNode(lambda n: n.kind == EItem.UnbornHead)
    assert rw.sidebar.findNode(lambda n: n.kind == EItem.Remote)
    assert rw.sidebar.findNodeByRef("refs/remotes/localfs/master")
    with pytest.raises(StopIteration):
        rw.sidebar.findNode(lambda n: n.kind == EItem.LocalBranch)


@pytest.mark.skipif((PYQT5 or PYQT6) and os.environ.get("COV_CORE_SOURCE", None) is not None,
                    reason="QMetaObject.connectSlotsByName somehow hangs under coverage with PyQt6")
@pytest.mark.parametrize("asNewBranch", [False, True])
def testPush(tempDir, mainWindow, asNewBranch):
    oldHead = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")

    wd = unpackRepo(tempDir)
    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True, keepOldUpstream=True)

    # Make some update in our repo
    with RepoContext(wd) as repo:
        writeFile(f"{wd}/pushme.txt", "till I can get my satisfaction")
        repo.index.add("pushme.txt")
        repo.index.write()
        newHead = repo.create_commit_on_head("push this commit to the remote")

    rw = mainWindow.openRepo(wd)

    # We still think the remote's master branch is on the old head for now
    assert rw.repo.branches.remote["localfs/master"].target == oldHead
    assert "localfs/new" not in rw.repo.branches.remote

    node = rw.sidebar.findNodeByRef("refs/heads/master")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "push")

    dlg: PushDialog = findQDialog(rw, "push.+branch")
    assert isinstance(dlg, PushDialog)

    i = dlg.ui.remoteBranchEdit.currentIndex()
    assert dlg.ui.remoteBranchEdit.itemText(i).startswith("origin/master")
    assert dlg.ui.trackCheckBox.isChecked()
    assert re.search(r"already tracks.+origin/master", dlg.ui.trackingLabel.text(), re.I)

    if not asNewBranch:
        i = dlg.ui.remoteBranchEdit.findText("localfs/master")
    else:
        i = dlg.ui.remoteBranchEdit.findText(r"new.+branch on.+localfs", Qt.MatchFlag.MatchRegularExpression)
    assert i >= 0
    dlg.ui.remoteBranchEdit.setCurrentIndex(i)
    dlg.ui.remoteBranchEdit.activated.emit(i)  # this signal is normally only emitted on user interaction, so fake it

    if not asNewBranch:
        assert not dlg.ui.trackCheckBox.isChecked()
    else:
        assert dlg.ui.trackCheckBox.isChecked()
        assert dlg.ui.newRemoteBranchNameEdit.text() == "master-2"
        dlg.ui.newRemoteBranchNameEdit.clear()
        QTest.keyClicks(dlg.ui.newRemoteBranchNameEdit, "new")  # keyClicks ensures the correct signal is emitted
        assert re.search(r"will track.+localfs/new.+instead of.+origin/master", dlg.ui.trackingLabel.text(), re.I)

    dlg.startOperationButton.click()

    if not asNewBranch:
        assert rw.repo.branches.remote["localfs/master"].target == newHead
    else:
        assert rw.repo.branches.remote["localfs/new"].target == newHead


def testPushNoBranch(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.checkout_commit(Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0"))
    rw = mainWindow.openRepo(wd)
    triggerMenuAction(mainWindow.menuBar(), "repo/push")
    acceptQMessageBox(rw, "switch to.+local branch")


def testPushNoRemotes(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.delete_remote("origin")
    rw = mainWindow.openRepo(wd)

    node = rw.sidebar.findNodeByRef("refs/heads/master")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "push")
    acceptQMessageBox(rw, "add a remote")
