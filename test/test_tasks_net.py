"""
Remote access tests.

Note: these tests don't actually access the network.
We use a bare repository on the local filesystem as a "remote server".
"""

import os.path
import pytest

from .util import *
from gitfourchette.forms.clonedialog import CloneDialog
from gitfourchette.forms.pushdialog import PushDialog
from gitfourchette.nav import NavLocator
from gitfourchette.sidebar.sidebarmodel import EItem
from gitfourchette import porcelain


def testCloneRepo(tempDir, mainWindow):
    wd = unpackRepo(tempDir, renameTo="unpacked-repo")
    bare = makeBareCopy(wd, addAsRemote="", preFetch=False)
    target = f"{tempDir.name}/the-clone"

    assert not mainWindow.currentRepoWidget()  # no repo opened yet

    triggerMenuAction(mainWindow.menuBar(), "file/clone")
    cloneDialog: CloneDialog = findQDialog(mainWindow, "clone")
    cloneDialog.ui.urlEdit.setEditText(bare)
    cloneDialog.ui.pathEdit.setText(target)
    cloneDialog.cloneButton.click()

    rw = mainWindow.currentRepoWidget()
    assert rw is not None
    assert os.path.samefile(rw.workdir, target)

    # Look at some commit within the repo
    oid = Oid(hex="bab66b48f836ed950c99134ef666436fb07a09a0")
    rw.jump(NavLocator.inCommit(oid))
    assert ["c/c1.txt"] == qlvGetRowData(rw.committedFiles)


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


def testDeleteRemoteBranch(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    makeBareCopy(wd, addAsRemote="localfs", preFetch=True)
    rw = mainWindow.openRepo(wd)

    assert "localfs/no-parent" in rw.repo.branches.remote

    node = rw.sidebar.findNodeByRef("refs/remotes/localfs/no-parent")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "delete")
    acceptQMessageBox(rw, "really delete.+from.+remote repository")

    assert "localfs/no-parent" not in rw.repo.branches.remote
    with pytest.raises(KeyError):
        rw.sidebar.findNodeByRef("refs/remotes/localfs/no-parent")


def testFetchRemote(tempDir, mainWindow):
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
    node = rw.sidebar.findNode(lambda n: n.kind == EItem.Remote and n.data == "localfs")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "fetch")

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
    acceptQMessageBox(rw, fr"localfs/master.+moved.+{oldHead.hex[:7]}.+{newHead.hex[:7]}")

    # The position of the remote's master branch should be up-to-date now
    assert rw.repo.branches.remote["localfs/master"].target == newHead


@pytest.mark.parametrize("asNewBranch", [False, True])
def testPush(tempDir, mainWindow, asNewBranch):
    oldHead = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")

    wd = unpackRepo(tempDir)
    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True)

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
