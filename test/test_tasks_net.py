# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Remote access tests.

Note: these tests don't actually access the network.
We use a bare repository on the local filesystem as a "remote server".
"""

import os.path
import re

import pytest

from gitfourchette.forms.clonedialog import CloneDialog
from gitfourchette.forms.deletetagdialog import DeleteTagDialog
from gitfourchette.forms.newbranchdialog import NewBranchDialog
from gitfourchette.forms.newtagdialog import NewTagDialog
from gitfourchette.forms.pushdialog import PushDialog
from gitfourchette.forms.remotedialog import RemoteDialog
from gitfourchette.gitdriver import GitDriver
from gitfourchette.mainwindow import NoRepoWidgetError
from gitfourchette.nav import NavLocator
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from gitfourchette.tasks.nettasks import AutoFetchRemotes
from . import reposcenario
from .util import *


@pytest.mark.skipif(pygit2OlderThan("1.15.1"), reason="old pygit2")
def testCloneRepoWithSubmodules(tempDir, mainWindow):
    wd = unpackRepo(tempDir, renameTo="unpacked-repo")
    subWd, _dummy = reposcenario.submodule(wd, True)  # spice it up with a submodule
    bare = makeBareCopy(wd, addAsRemote="", preFetch=False)
    target = str(Path(f"{tempDir.name}", "the-clone"))

    with pytest.raises(NoRepoWidgetError):
        mainWindow.currentRepoWidget()  # no repo opened yet

    # Bring up clone dialog
    triggerMenuAction(mainWindow.menuBar(), "file/clone")
    cloneDialog: CloneDialog = findQDialog(mainWindow, "clone")
    waitUntilTrue(cloneDialog.isActiveWindow)
    assert not cloneDialog.ui.pathEdit.text()  # path initially empty
    assert -1 == cloneDialog.ui.urlEdit.currentIndex()
    assert not cloneDialog.ui.urlEdit.lineEdit().text()  # URL initially empty
    assert not cloneDialog.cloneButton.isEnabled()  # disallow cloning without an URL
    assert cloneDialog.ui.recurseSubmodulesCheckBox.isChecked()

    # Set URL in clone dialog
    cloneDialog.ui.urlEdit.setEditText(bare)
    QTest.qWait(0)
    assert "unpacked-repo-bare" in cloneDialog.ui.pathEdit.text()  # autofilled after entering URL
    assert cloneDialog.ui.protocolButton.isHidden()  # protocol swap button shouldn't be visible for file URLs

    # Test expanduser on manual path entry + whitespace stripping
    cloneDialog.ui.pathEdit.setFocus()
    cloneDialog.ui.pathEdit.setText("   ~/thisshouldwork   ")
    assert cloneDialog.path == str(Path("~/thisshouldwork").expanduser())

    # Disallow cloning to non-empty directory
    cloneDialog.ui.pathEdit.setText(tempDir.name)
    QTest.qWait(0)
    assert not cloneDialog.cloneButton.isEnabled()
    assert re.search(r"isn.t empty", QToolTip.text(), re.I)

    # Disallow cloning to empty path
    cloneDialog.ui.pathEdit.setText("")
    QTest.qWait(0)
    assert not cloneDialog.cloneButton.isEnabled()
    assert re.search(r"enter.+absolute path", QToolTip.text(), re.I)

    # Disallow cloning to file path
    cloneDialog.ui.pathEdit.setText(f"{wd}/master.txt")
    QTest.qWait(0)
    assert not cloneDialog.cloneButton.isEnabled()
    assert re.search(r"file at this path", QToolTip.text(), re.I)

    # Set target path in clone dialog
    cloneDialog.ui.browseButton.click()
    acceptQFileDialog(cloneDialog, "clone repository into", target)
    assert cloneDialog.ui.pathEdit.text() == target

    # Play with key file picker
    assert not cloneDialog.ui.keyFilePicker.checkBox.isChecked()
    cloneDialog.ui.keyFilePicker.checkBox.click()
    findQDialog(cloneDialog, "key file", QFileDialog).reject()
    assert not cloneDialog.ui.keyFilePicker.checkBox.isChecked()

    # Fire ze missiles
    assert cloneDialog.cloneButton.isEnabled()
    cloneDialog.cloneButton.click()
    del cloneDialog

    # Get RepoWidget for cloned repo
    rw = mainWindow.currentRepoWidget()

    # Check that the cloned repo's state looks OK
    clonedRepo = rw.repo
    assert os.path.samefile(clonedRepo.workdir, target)
    assert "submoname" in clonedRepo.listall_submodules_dict()

    # Look at some commit within the repo
    oid = Oid(hex="bab66b48f836ed950c99134ef666436fb07a09a0")
    rw.jump(NavLocator.inCommit(oid, "c/c1.txt"), check=True)

    # Bring up clone dialog again and check that the URL was added to the history
    triggerMenuAction(mainWindow.menuBar(), "file/clone")
    cloneDialog: CloneDialog = findQDialog(mainWindow, "clone")
    waitUntilTrue(cloneDialog.isActiveWindow)
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
    assert all(n.data.startswith("refs/remotes/origin/") for n in rw.sidebar.walk() if n.kind == SidebarItem.RemoteBranch)

    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Remote and n.data == "localfs")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "fetch")

    assert "localfs/master" in rw.repo.branches.remote
    assert any(n.data.startswith("refs/remotes/localfs/") for n in rw.sidebar.walk() if n.kind == SidebarItem.RemoteBranch)


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey"])
def testDeleteRemoteBranch(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)
    rw = mainWindow.openRepo(wd)

    assert "localfs/no-parent" in rw.repo.branches.remote

    node = rw.sidebar.findNodeByRef("refs/remotes/localfs/no-parent")

    if method == "sidebarmenu":
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "delete")
    elif method == "sidebarkey":
        rw.sidebar.setFocus()
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
    bareCopy = makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)

    with RepoContext(bareCopy) as bareRepo:
        bareBranch = bareRepo.branches.local["no-parent"]
        unknownCommitId = bareRepo.create_commit(
            "refs/heads/no-parent",
            TEST_SIGNATURE,
            TEST_SIGNATURE,
            "new commit on remote that local copy doesn't have yet",
            bareRepo.head_tree.id, # bareBranch.peel(Tree).id,
            [bareBranch.peel(Commit).id])

    rw = mainWindow.openRepo(wd)

    assert "localfs/no-parent" in rw.repo.branches.remote
    assert rw.repo.branches.local["no-parent"].upstream_name == "refs/remotes/localfs/no-parent"

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

    assert rw.repo.branches.local["no-parent"].upstream_name == "refs/remotes/localfs/new-name"

    assert rw.repo.branches.remote["localfs/new-name"].target == unknownCommitId


@pytest.mark.parametrize("method", ["sidebar", "toolbar"])
def testFetchRemote(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)

    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)

    # Make some modifications to the bare repository that serves as a remote.
    # We're going to create a new branch and delete another.
    # The client must pick up on those modifications once it fetches the remote.
    with RepoContext(barePath) as bareRepo:
        assert bareRepo.is_bare
        bareRepo.create_branch_on_head("new-remote-branch")
        bareRepo.delete_local_branch("no-parent")

    rw = mainWindow.openRepo(wd)

    # We only know about master and no-parent in the remote for now
    assert {"localfs/master", "localfs/no-parent"} == {
        x for x in rw.repo.branches.remote if x.startswith("localfs/") and x != "localfs/HEAD"}

    # Fetch the remote
    if method == "sidebar":
        node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Remote and n.data == "localfs")
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "fetch")
    elif method == "toolbar":
        findChildWithText(mainWindow.mainToolBar, "fetch", QToolButton).click()
    else:
        raise NotImplementedError(f"Unsupported method {method}")

    # We must see that no-parent is gone and that new-remote-branch appeared
    assert {"localfs/master", "localfs/new-remote-branch"} == {
        x for x in rw.repo.branches.remote if x.startswith("localfs/") and x != "localfs/HEAD"}


def testFetchRemoteBranch(tempDir, mainWindow):
    oldHead = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    newHead = Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322")

    wd = unpackRepo(tempDir)

    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)

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

    # Skip status bar test if vanilla git is pre-2.41 - we don't parse non-porcelain output
    if GitDriver.supportsFetchPorcelain():
        assert re.search(
            fr"localfs/master.+{str(oldHead)[:7]}.+{str(newHead)[:7]}",
            mainWindow.statusBar().currentMessage(),
            re.I)

    # The position of the remote's master branch should be up to date now
    assert rw.repo.branches.remote["localfs/master"].target == newHead


@pytest.mark.parametrize("pull", [False, True])
def testFetchRemoteBranchVanishes(tempDir, mainWindow, pull):
    oldHead = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    wd = unpackRepo(tempDir)

    # Modify the master branch in the bare repository that serves as a remote.
    # The client must pick up on this modification once it fetches the remote branch.
    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)
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

    # if gitBackend == "libgit2":
    #     acceptQMessageBox(rw, "localfs/master.+disappeared")
    #
    #     # It's gone
    #     assert "localfs/master" not in rw.repo.branches.remote
    #     with pytest.raises(KeyError):
    #         rw.sidebar.findNodeByRef("refs/remotes/localfs/master")

    acceptQMessageBox(rw, "couldn.+t find remote ref master")
    # TODO: Should we automatically prune the branch in this case?


def testFetchRemoteBranchNoChange(tempDir, mainWindow):
    oldHead = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    wd = unpackRepo(tempDir)
    makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)

    rw = mainWindow.openRepo(wd)
    assert rw.repo.branches.remote["localfs/master"].target == oldHead

    node = rw.sidebar.findNodeByRef("refs/remotes/localfs/master")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "fetch")

    # Skip status bar test if vanilla git is pre-2.41 - we don't parse non-porcelain output
    if GitDriver.supportsFetchPorcelain():
        assert re.search(r"no new commits", mainWindow.statusBar().currentMessage(), re.I)

    assert rw.repo.branches.remote["localfs/master"].target == oldHead


def testPullRemoteBranchAlreadyUpToDate(tempDir, mainWindow):
    oldHead = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    wd = unpackRepo(tempDir)
    makeBareCopy(wd, "localfs", preFetch=True, deleteOtherRemotes=True)

    rw = mainWindow.openRepo(wd)
    assert rw.repo.branches.remote["localfs/master"].target == oldHead
    assert rw.navLocator.context.isWorkdir()

    triggerMenuAction(mainWindow.menuBar(), "repo/pull")
    assert rw.navLocator.context.isWorkdir()
    assert "already up to date" in mainWindow.statusBar2.currentMessage().lower()
    assert rw.repo.branches.remote["localfs/master"].target == oldHead


def testFetchRemoteHistoryWithUnbornHead(tempDir, mainWindow):
    originWd = unpackRepo(tempDir)
    wd = tempDir.name + "/newrepo"

    pygit2.init_repository(wd)
    rw = mainWindow.openRepo(wd)
    triggerMenuAction(mainWindow.menuBar(), "repo/add remote")
    remoteDialog: RemoteDialog = findQDialog(rw, "add remote")
    remoteDialog.ui.urlEdit.setText(originWd)
    remoteDialog.ui.nameEdit.setText("localfs")
    remoteDialog.accept()

    assert rw.sidebar.findNodeByKind(SidebarItem.UnbornHead)
    assert rw.sidebar.findNodeByKind(SidebarItem.Remote)
    assert rw.sidebar.findNodeByRef("refs/remotes/localfs/master")
    with pytest.raises(KeyError):
        rw.sidebar.findNodeByKind(SidebarItem.LocalBranch)


def testFetchRemoteBranchNoUpstream(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.edit_upstream_branch("master", "")

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNodeByRef("refs/heads/master")
    menu = rw.sidebar.makeNodeMenu(node)
    assert not findMenuAction(menu, "fetch").isEnabled()


def testFetchRemoteBranchUnbornHead(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "TestEmptyRepository")
    upstreamWd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.remotes.set_url("origin", upstreamWd)
        repo.remotes["origin"].fetch()
        master = repo.branches.remote["origin/master"]
        masterTip = master.target
        # Move origin/master back to initial commit so we have something to fetch
        master.set_target(Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1"))
        assert masterTip != master.target

    rw = mainWindow.openRepo(wd)
    assert masterTip != rw.repo.branches.remote["origin/master"].target

    node = rw.sidebar.findNodeByRef("refs/remotes/origin/master")
    menu = rw.sidebar.makeNodeMenu(node)
    assert not findMenuAction(menu, "merge").isEnabled()
    triggerMenuAction(menu, "fetch")
    assert masterTip == rw.repo.branches.remote["origin/master"].target


def testPullRemoteBranchNoUpstream(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        tip = repo.head_commit_id
        repo.edit_upstream_branch("master", "")

    rw = mainWindow.openRepo(wd)
    triggerMenuAction(mainWindow.menuBar(), "repo/pull")
    acceptQMessageBox(rw, "n.t tracking.+upstream")
    assert tip == rw.repo.head_commit_id


@pytest.mark.parametrize("remoteNeedsFetching", [True, False])
def testPullRemoteBranchAutoFastForward(tempDir, mainWindow, remoteNeedsFetching):
    newTip = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    oldTip = Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1")

    wd = unpackRepo(tempDir)
    makeBareCopy(wd, "localfs", preFetch=True, deleteOtherRemotes=True)

    with RepoContext(wd) as repo:
        assert newTip == repo.head_commit_id
        repo.reset(oldTip, ResetMode.HARD)
        if remoteNeedsFetching:
            # "Forget" top of graph
            writeFile(f"{repo.path}/refs/remotes/localfs/master", str(oldTip))

    rw = mainWindow.openRepo(wd)
    assert oldTip == rw.repo.head_commit_id

    try:
        rw.repoModel.graph.getCommitRow(newTip)
        assert not remoteNeedsFetching
    except KeyError:
        assert remoteNeedsFetching
    rw.repoModel.graph.getCommitRow(oldTip)  # must not raise

    triggerMenuAction(mainWindow.menuBar(), "repo/pull")

    assert newTip == rw.repo.head_commit_id
    rw.repoModel.graph.getCommitRow(newTip)  # must not raise


def testPullRemoteBranchAutomaticFastForwardBlockedByConfig(tempDir, mainWindow):
    newTip = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    oldTip = Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1")

    wd = unpackRepo(tempDir)
    makeBareCopy(wd, "localfs", preFetch=True, deleteOtherRemotes=True)

    with RepoContext(wd) as repo:
        assert newTip == repo.head_commit_id
        repo.reset(oldTip, ResetMode.HARD)
        repo.config["pull.ff"] = "false"

    rw = mainWindow.openRepo(wd)
    assert oldTip == rw.repo.head_commit_id

    rw.repoModel.graph.getCommitRow(newTip)
    rw.repoModel.graph.getCommitRow(oldTip)  # must not raise

    triggerMenuAction(mainWindow.menuBar(), "repo/pull")

    acceptQMessageBox(rw, r"can simply be fast-forwarded to .*localfs/master.+automatic fast-forward.+blocked by.+pull\.ff")

    assert newTip == rw.repo.head_commit_id
    rw.repoModel.graph.getCommitRow(newTip)  # must not raise


def testPullRemoteBranchCausesConflict(tempDir, mainWindow):
    wd = unpackRepo(tempDir, testRepoName="testrepoformerging")
    makeBareCopy(wd, "localfs", preFetch=True, deleteOtherRemotes=True)

    with RepoContext(wd) as repo:
        repo.edit_upstream_branch("master", "localfs/branch-conflicts")

        # "Forget" top of graph
        repo.delete_local_branch("branch-conflicts")
        newTip = repo.branches.remote["localfs/branch-conflicts"].target
        writeFile(f"{repo.path}/refs/remotes/localfs/branch-conflicts", str(repo[newTip].peel(Commit).parent_ids[0]))

    rw = mainWindow.openRepo(wd)
    assert not rw.repo.any_conflicts

    # "New" tip of branch-conflicts must not be visible in graph prior to pulling
    with pytest.raises(KeyError):
        rw.repoModel.graph.getCommitRow(newTip)

    # Pull, and detect a conflict.
    masterNode = rw.sidebar.findNodeByRef("refs/heads/master")
    triggerMenuAction(rw.sidebar.makeNodeMenu(masterNode), "pull")
    confirmMergeMessage = findQMessageBox(rw, "fix the conflicts")

    # After the fetch part of the pull is complete, the new tip must be visible
    # beneath the message box asking whether we want to merge.
    rw.repoModel.graph.getCommitRow(newTip)  # must not raise

    # Go ahead with the merge.
    confirmMergeMessage.accept()
    assert rw.repo.any_conflicts
    assert rw.navLocator.context.isWorkdir()


@pytest.mark.skipif((PYQT5 or PYQT6) and os.environ.get("COV_CORE_SOURCE", None) is not None,
                    reason="QMetaObject.connectSlotsByName somehow hangs under coverage with PyQt6")
@pytest.mark.parametrize("asNewBranch", [False, True])
def testPush(tempDir, mainWindow, asNewBranch):
    oldHead = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")

    wd = unpackRepo(tempDir)
    makeBareCopy(wd, addAsRemote="localfs", preFetch=True, keepOldUpstream=True)

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
    assert not dlg.willPushToNewBranch
    assert dlg.currentRemoteBranchFullName == "origin/master"
    assert re.search(r"already tracks.+origin/master", dlg.ui.trackingLabel.text(), re.I)

    if not asNewBranch:
        qcbSetIndex(dlg.ui.remoteBranchEdit, "localfs/master")
        assert not dlg.ui.trackCheckBox.isChecked()
        assert not dlg.willPushToNewBranch
        assert dlg.currentRemoteBranchFullName == "localfs/master"
    else:
        qcbSetIndex(dlg.ui.remoteBranchEdit, "new.+branch on .+localfs")
        assert dlg.ui.trackCheckBox.isChecked()
        assert dlg.ui.newRemoteBranchNameEdit.text() == "master-2"
        assert dlg.currentRemoteBranchFullName == "localfs/master-2"
        assert dlg.willPushToNewBranch

        dlg.ui.newRemoteBranchNameEdit.clear()
        assert dlg.willPushToNewBranch

        QTest.keyClicks(dlg.ui.newRemoteBranchNameEdit, "new")  # keyClicks ensures the correct signal is emitted
        assert re.search(r"will track.+localfs/new.+instead of.+origin/master", dlg.ui.trackingLabel.text(), re.I)
        assert dlg.currentRemoteBranchFullName == "localfs/new"
        assert dlg.willPushToNewBranch

    dlg.startOperationButton.click()

    if not asNewBranch:
        assert rw.repo.branches.remote["localfs/master"].target == newHead
    else:
        assert rw.repo.branches.remote["localfs/new"].target == newHead
        assert rw.repo.branches["master"].upstream_name == "refs/remotes/localfs/new"


@pytest.mark.skipif((PYQT5 or PYQT6) and os.environ.get("COV_CORE_SOURCE", None) is not None,
                    reason="QMetaObject.connectSlotsByName somehow hangs under coverage with PyQt6")
def testShadowUpstream(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    makeBareCopy(wd, addAsRemote="remote2", preFetch=True, keepOldUpstream=True)

    # Make local branch 'master' track no upstream
    with RepoContext(wd) as repo:
        repo.branches.local['master'].upstream = None

    rw = mainWindow.openRepo(wd)
    pushDialog: PushDialog

    # Push master to remote2/master-2 without tracking it.
    triggerMenuAction(mainWindow.menuBar(), "repo/push")
    pushDialog = findQDialog(rw, "push.+branch")
    assert pushDialog.currentRemoteBranchFullName == "origin/master-2"
    qcbSetIndex(pushDialog.ui.remoteBranchEdit, r"new remote branch on.+remote2")
    assert pushDialog.currentRemoteBranchFullName == "remote2/master-2"
    pushDialog.ui.trackCheckBox.setChecked(False)
    pushDialog.okButton().click()

    # Open PushDialog on master again, remote2/master-2 should be automatically selected.
    triggerMenuAction(mainWindow.menuBar(), "repo/push")
    pushDialog = findQDialog(rw, "push.+branch")
    assert pushDialog.currentRemoteBranchFullName == "remote2/master-2"
    pushDialog.ui.trackCheckBox.setChecked(False)

    # Push master to remote2/no-parent, still without tracking it.
    qcbSetIndex(pushDialog.ui.remoteBranchEdit, r"remote2/no-parent")
    assert pushDialog.currentRemoteBranchFullName == "remote2/no-parent"
    pushDialog.ui.forcePushCheckBox.setChecked(True)
    pushDialog.ui.trackCheckBox.setChecked(False)
    pushDialog.okButton().click()

    # Open PushDialog on master again, remote2/no-parent should be automatically selected.
    triggerMenuAction(mainWindow.menuBar(), "repo/push")
    pushDialog = findQDialog(rw, "push.+branch")
    assert pushDialog.currentRemoteBranchFullName == "remote2/no-parent"
    pushDialog.reject()

    # Clear shadow upstream reference by setting an upstream manually.
    node = rw.sidebar.findNodeByRef("refs/heads/master")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "upstream branch/origin.master")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "upstream branch/stop tracking upstream")

    # Open PushDialog; the shadow upstream reference should be lost (it used to be remote2/no-parent).
    triggerMenuAction(mainWindow.menuBar(), "repo/push")
    pushDialog = findQDialog(rw, "push.+branch")
    assert pushDialog.currentRemoteBranchFullName == "origin/master-2"
    pushDialog.reject()


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


def testPushTagOnCreate(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True, keepOldUpstream=True)

    with RepoContext(barePath) as bareRepo:
        assert "etiquette" not in bareRepo.listall_tags()

    # Remove origin so that we don't attempt to push to the network
    with RepoContext(wd) as repo:
        repo.remotes.delete("origin")

    rw = mainWindow.openRepo(wd)

    node = rw.sidebar.findNodeByKind(SidebarItem.TagsHeader)
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "new tag.+HEAD")

    dlg: NewTagDialog = findQDialog(rw, "new tag")
    dlg.ui.nameEdit.setText("etiquette")
    assert not dlg.ui.pushCheckBox.isChecked()
    dlg.ui.pushCheckBox.setChecked(True)
    dlg.accept()

    with RepoContext(barePath) as bareRepo:
        assert "etiquette" in bareRepo.listall_tags()


def testPushExistingTag(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True, keepOldUpstream=True)

    with RepoContext(wd) as repo:
        repo.create_reference("refs/tags/etiquette", repo.head_commit_id)

    with RepoContext(barePath) as bareRepo:
        assert "etiquette" not in bareRepo.listall_tags()

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNodeByRef("refs/tags/etiquette")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "push to/localfs")

    with RepoContext(barePath) as bareRepo:
        assert "etiquette" in bareRepo.listall_tags()


def testPushAllTags(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)

    with RepoContext(wd) as repo, RepoContext(barePath) as bareRepo:
        repo.create_reference("refs/tags/etiquette1", repo.head_commit_id)
        repo.create_reference("refs/tags/etiquette2", repo.head_commit_id)
        repo.create_reference("refs/tags/etiquette3", repo.head_commit_id)

    with RepoContext(barePath) as bareRepo:
        assert "etiquette1" not in bareRepo.listall_tags()
        assert "etiquette2" not in bareRepo.listall_tags()
        assert "etiquette3" not in bareRepo.listall_tags()

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNodeByKind(SidebarItem.TagsHeader)
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "push all tags to/localfs")

    with RepoContext(barePath) as bareRepo:
        assert "etiquette1" in bareRepo.listall_tags()
        assert "etiquette2" in bareRepo.listall_tags()
        assert "etiquette3" in bareRepo.listall_tags()


def testPushDeleteTag(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.create_reference("refs/tags/etiquette", repo.head_commit_id)

    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)
    with RepoContext(barePath) as bareRepo:
        assert "etiquette" in bareRepo.listall_tags()

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNodeByRef("refs/tags/etiquette")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "delete")

    dlg: DeleteTagDialog = findQDialog(rw, "delete tag")
    assert not dlg.ui.pushCheckBox.isChecked()
    dlg.ui.pushCheckBox.setChecked(True)
    qcbSetIndex(dlg.ui.remoteComboBox, "localfs")
    dlg.accept()

    with RepoContext(barePath) as bareRepo:
        assert "etiquette" not in bareRepo.listall_tags()


def testForcePushWithLeasePass(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    makeBareCopy(wd, addAsRemote="remote2", preFetch=True, deleteOtherRemotes=True)

    with RepoContext(wd) as repo:
        newOid = repo.amend_commit_on_head("amended locally", TEST_SIGNATURE, TEST_SIGNATURE)

    rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/push")
    pushDialog: PushDialog = findQDialog(rw, "push.+branch")
    pushDialog.ui.forcePushCheckBox.click()
    pushDialog.okButton().click()

    assert rw.repo.branches.remote["remote2/master"].target == newOid


def testForcePushWithLeaseRejected(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    bareCopy = makeBareCopy(wd, addAsRemote="remote2", preFetch=True, deleteOtherRemotes=True)

    with RepoContext(bareCopy) as bareRepo:
        _unknownCommitId = bareRepo.create_commit(
            "refs/heads/master",
            TEST_SIGNATURE,
            TEST_SIGNATURE,
            "new commit on remote that local copy doesn't have yet",
            bareRepo.head_tree.id,
            [bareRepo.head_commit_id])

    with RepoContext(wd) as repo:
        newOid = repo.amend_commit_on_head("amended locally", TEST_SIGNATURE, TEST_SIGNATURE)

    rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/push")
    pushDialog: PushDialog = findQDialog(rw, "push.+branch")
    pushDialog.ui.forcePushCheckBox.click()
    pushDialog.okButton().click()

    blurbLabel = pushDialog.ui.statusForm.ui.blurbLabel
    assert blurbLabel.isVisible()
    assert re.search(r"force.push.+rejected to prevent data loss", blurbLabel.text(), re.I)
    pushDialog.reject()

    assert rw.repo.branches.remote["remote2/master"].target != newOid


def testAbortPushInProgress(tempDir, mainWindow, taskThread):
    mainWindow.onAcceptPrefsDialog({"gitPath": delayGitCommand()})

    wd = unpackRepo(tempDir)
    makeBareCopy(wd, addAsRemote="remote2", preFetch=True, deleteOtherRemotes=True)

    with RepoContext(wd) as repo:
        oldOid = repo.head_commit_id
        newOid = repo.create_commit_on_head("hello", TEST_SIGNATURE, TEST_SIGNATURE)

    mainWindow.openRepo(wd)
    rw = waitForRepoWidget(mainWindow)

    assert rw.repo.branches.local["master"].target == newOid
    assert rw.repo.branches.remote["remote2/master"].target == oldOid

    triggerMenuAction(mainWindow.menuBar(), "repo/push")
    pushDialog = waitForQDialog(rw, "push.+branch", t=PushDialog)
    statusLabel = pushDialog.ui.statusForm.ui.statusLabel
    blurbLabel = pushDialog.ui.statusForm.ui.blurbLabel
    okButton = pushDialog.okButton()
    cancelButton = pushDialog.cancelButton()

    okButton.click()
    assert not okButton.isEnabled()
    assert statusLabel.isVisible()
    assert findTextInWidget(statusLabel, "please wait")

    # Wait for wrapper script to actually start
    waitUntilTrue(lambda: findTextInWidget(statusLabel, "delaying"))

    # Send SIGTERM
    cancelButton.click()
    waitUntilTrue(okButton.isEnabled)

    # FLATPAK: Look for return code 143 (SIGTERM=15, 15+128=143) because
    # we're running non-sandboxed commands through /usr/bin/env
    failMessage = "git.+exited with.+" + ("143" if FLATPAK else "SIGTERM")
    assert findTextInWidget(blurbLabel, failMessage)
    assert blurbLabel.isVisible()

    # Click cancel button again to dismiss the dialog
    cancelButton.click()

    assert rw.repo.branches.remote["remote2/master"].target == oldOid
    with RepoContext(wd) as repo:
        repo.fetch_remote("remote2", None)
        assert repo.branches.remote["remote2/master"].target == oldOid


def testAbortPullInProgress(tempDir, mainWindow, taskThread):
    mainWindow.onAcceptPrefsDialog({"gitPath": delayGitCommand()})

    wd = unpackRepo(tempDir)
    bareCopy = makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)

    with RepoContext(bareCopy) as bareRepo:
        _unknownCommitId = bareRepo.create_commit(
            "refs/heads/master",
            TEST_SIGNATURE,
            TEST_SIGNATURE,
            "new commit on remote that local copy doesn't have yet",
            bareRepo.head_tree.id,
            [bareRepo.head_commit_id])

    with RepoContext(wd) as repo:
        oldHead = repo.head_commit_id

    mainWindow.openRepo(wd)
    rw = waitForRepoWidget(mainWindow)

    assert rw.repo.branches.remote["localfs/master"].target == oldHead

    QTest.qWait(0)
    triggerMenuAction(mainWindow.menuBar(), "repo/pull")

    waitForSignal(rw.processDialog.becameVisible)
    assert rw.processDialog.isVisible()

    assert rw.processDialog.abortButton.isEnabled()
    assert "Abort" in rw.processDialog.abortButton.text()
    rw.processDialog.abortButton.click()
    assert "SIGKILL" in rw.processDialog.abortButton.text()
    waitUntilTrue(lambda: not rw.taskRunner.isBusy())

    # FLATPAK: Look for return code 143 (SIGTERM=15, 15+128=143) because
    # we're running non-sandboxed commands through /usr/bin/env
    failMessage = "git.+exited with.+" + ("143" if FLATPAK else "SIGTERM")
    waitForQMessageBox(rw, failMessage).reject()

    rw.refreshRepo()
    waitUntilTrue(lambda: not rw.taskRunner.isBusy())
    assert rw.repo.branches.remote["localfs/master"].target == oldHead


@pytest.mark.parametrize("enabled", [True, False])
def testAutoFetch(tempDir, mainWindow, enabled, taskThread):
    """Test that auto-fetch works when enabled and conditions are met."""
    wd = unpackRepo(tempDir)
    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)

    # Enable or disable auto-fetch.
    # Force 'git fetch' to take a little while so we can check the status message.
    mainWindow.onAcceptPrefsDialog({
        "autoFetch": enabled,
        "autoFetchMinutes": 1,
        "gitPath": delayGitCommand(delay=2),
    })

    with RepoContext(barePath) as bareRepo:
        assert bareRepo.is_bare
        bareRepo.create_branch_on_head("new-remote-branch")
        bareRepo.delete_local_branch("no-parent")

    mainWindow.openRepo(wd)
    rw = waitForRepoWidget(mainWindow)
    assert not rw.taskRunner.isBusy()

    assert {"localfs/master", "localfs/no-parent"} == {
        x for x in rw.repo.branches.remote if x.startswith("localfs/") and x != "localfs/HEAD"}

    # Manually trigger the auto-fetch timer timeout to simulate the timer firing
    rw.lastAutoFetchTime = 0
    rw.onAutoFetchTimerTimeout()

    # Check auto-fetch status message
    if enabled:
        waitUntilTrue(rw.taskRunner.isBusy)
        waitUntilTrue(mainWindow.statusBar2.busyLabel.isVisible)
        assert findTextInWidget(mainWindow.statusBar2.busyLabel, "auto-fetch")

    # Big timeout: Mac CI sometimes takes its sweet time to complete the fetch here
    waitUntilTrue(lambda: not rw.taskRunner.isBusy(), timeout=10_000)

    branches = {x for x in rw.repo.branches.remote if x.startswith("localfs/") and x != "localfs/HEAD"}
    if enabled:
        assert branches == {"localfs/master", "localfs/new-remote-branch"}
    else:
        assert branches == {"localfs/master", "localfs/no-parent"}


def testOngoingAutoFetchDoesntBlockOtherTasks(tempDir, mainWindow, taskThread):
    from gitfourchette import settings
    gitCmd = settings.prefs.gitPath

    # Enable auto-fetch and make sure it'll keep RepoTaskRunner busy for a few seconds
    mainWindow.onAcceptPrefsDialog({
        "autoFetch": True,
        "autoFetchMinutes": 1,
        "gitPath": delayGitCommand(),
    })

    wd = unpackRepo(tempDir)
    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)
    with RepoContext(barePath) as bareRepo:
        bareRepo.create_branch_on_head("new-remote-branch")

    # Open the repo and wait for it to settle
    mainWindow.openRepo(wd)
    rw = waitForRepoWidget(mainWindow)

    # Manually trigger the auto-fetch timer timeout to simulate the timer firing
    rw.lastAutoFetchTime = 0
    rw.onAutoFetchTimerTimeout()

    # Make sure we're auto-fetching right now
    assert isinstance(rw.taskRunner.currentTask, AutoFetchRemotes)

    # Don't delay git for the next task
    mainWindow.onAcceptPrefsDialog({"gitPath": gitCmd})
    assert isinstance(rw.taskRunner.currentTask, AutoFetchRemotes)  # just making sure a future version of onAcceptPrefsDialog doesn't kill the task...

    # Perform a task - any task! - while auto-fetching is in progress.
    # It shouldn't be blocked by an ongoing auto-fetch.
    triggerMenuAction(mainWindow.menuBar(), "repo/new local branch")
    newBranchDialog = waitForQDialog(rw, "new branch", t=NewBranchDialog)
    newBranchDialog.ui.nameEdit.setText("not-blocked-by-auto-fetch")
    newBranchDialog.accept()
    waitUntilTrue(lambda: not rw.taskRunner.isBusy())
    assert "not-blocked-by-auto-fetch" in rw.repo.branches.local
    assert "localfs/new-remote-branch" not in rw.repo.branches.remote


def testTaskTerminationTerminatesProcess(tempDir, mainWindow, taskThread):
    """Test that terminating a task also terminates its associated process."""
    mainWindow.onAcceptPrefsDialog({"gitPath": delayGitCommand(delay=0.5)})

    wd = unpackRepo(tempDir)
    barePath = makeBareCopy(wd, addAsRemote="localfs", preFetch=True, deleteOtherRemotes=True)
    with RepoContext(barePath) as bareRepo:
        bareRepo.create_branch_on_head("new-remote-branch")
    mainWindow.openRepo(wd)
    rw = waitForRepoWidget(mainWindow)

    # Start a fetch task that will take 0.5 seconds due to the delay command
    triggerMenuAction(mainWindow.menuBar(), "repo/fetch remote branches")
    assert rw.taskRunner.isBusy()
    QTest.qWait(100)
    assert rw.taskRunner.isBusy(), "task should still be running"
    process = rw.taskRunner.currentTask.currentProcess
    assert process.state() != QProcess.ProcessState.NotRunning, "process should be running"

    rw.taskRunner.killCurrentTask()
    waitUntilTrue(lambda: not rw.taskRunner.isBusy())
    assert rw.taskRunner.currentTask is None, "task should be terminated"
    QTest.qWait(1000)

    # Check that the branch was not fetched
    assert "localfs/new-remote-branch" not in rw.repo.branches.remote
