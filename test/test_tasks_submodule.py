# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os
import shutil
import subprocess

import pygit2
import pytest
from pygit2.enums import SubmoduleStatus

from gitfourchette.forms.checkoutcommitdialog import CheckoutCommitDialog
from gitfourchette.forms.registersubmoduledialog import RegisterSubmoduleDialog
from gitfourchette.gitdriver import GitDriver
from gitfourchette.nav import NavLocator
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from . import reposcenario
from .test_tasks_stage import doStage, doDiscard
from .util import *


@pytest.mark.parametrize("method", ["sidebarMenu", "sidebarKey", "sidebarDClick", "commitSpecialDiff", "commitFileList", "dirtyFileList", "stagedFileList"])
def testOpenSubmoduleWithinApp(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    submoAbsPath, submoCommit = reposcenario.submodule(wd)
    writeFile(f"{submoAbsPath}/dirty.txt", "coucou")

    rw = mainWindow.openRepo(wd)
    assert mainWindow.currentRepoWidget() is rw

    submoNode = rw.sidebar.findNodeByKind(SidebarItem.Submodule)
    assert "submoname" == submoNode.data

    if method == "sidebarMenu":
        menu = rw.sidebar.makeNodeMenu(submoNode)
        triggerMenuAction(menu, r"open submodule.+tab")

    elif method == "sidebarKey":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(submoNode)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Return)

    elif method == "sidebarDClick":
        rect = rw.sidebar.visualRect(submoNode.createIndex(rw.sidebar.sidebarModel))
        QTest.mouseDClick(rw.sidebar.viewport(), Qt.MouseButton.LeftButton, pos=rect.topLeft())

    elif method == "commitSpecialDiff":
        rw.jump(NavLocator.inCommit(oid=submoCommit, path="submodir"))
        assert rw.specialDiffView.isVisibleTo(rw)
        assert qteFind(rw.specialDiffView, r"submodule.+submo.+was added")
        qteClickLink(rw.specialDiffView, r"open submodule.+submo")

    elif method == "commitFileList":
        rw.jump(NavLocator.inCommit(oid=submoCommit, path="submodir"))
        triggerContextMenuAction(rw.committedFiles.viewport(), r"open.+submodule.+in new tab")

    elif method == "dirtyFileList":
        rw.jump(NavLocator.inUnstaged(path="submodir"))
        triggerContextMenuAction(rw.dirtyFiles.viewport(), r"open.+submodule.+in new tab")

    elif method == "stagedFileList":
        with RepoContext(submoAbsPath, write_index=True) as submoRepo:
            submoRepo.reset(Oid(hex="ac7e7e44c1885efb472ad54a78327d66bfc4ecef"), ResetMode.HARD)
        rw.repo.index.add("submodir")
        rw.refreshRepo()

        rw.jump(NavLocator.inStaged(path="submodir"))
        triggerContextMenuAction(rw.stagedFiles.viewport(), r"open.+submodule.+in new tab")

    else:
        raise NotImplementedError("unknown method")

    if WINDOWS:
        submoAbsPath = submoAbsPath.replace("\\", "/")

    assert mainWindow.currentRepoWidget() is not rw
    assert mainWindow.currentRepoWidget().repo.workdir == submoAbsPath + "/"


@pytest.mark.parametrize("method", ["key", "menu", "button"])
def testSubmoduleHeadUpdate(tempDir, mainWindow, method, gitBackend):
    wd = unpackRepo(tempDir)
    subWd, _dummy = reposcenario.submodule(wd)
    subHead = Oid(hex='49322bb17d3acc9146f98c97d078513228bbf3c0')
    with RepoContext(subWd) as submo:
        submo.checkout_commit(subHead)

    rw = mainWindow.openRepo(wd)

    assert qlvGetRowData(rw.dirtyFiles) == ["submodir"]
    assert qlvClickNthRow(rw.dirtyFiles, 0)

    special = rw.specialDiffView
    assert special.isVisibleTo(rw)
    assert qteFind(special, r"submodule.+submoname.+was updated")
    assert qteFind(special, r"new:\s+49322bb", plainText=True)

    doStage(rw, method)

    assert qlvGetRowData(rw.dirtyFiles) == []
    assert qlvGetRowData(rw.stagedFiles) == ["submodir"]


@pytest.mark.parametrize("method", ["key", "menu", "button", "link"])
def testSubmoduleDirty(tempDir, mainWindow, method, gitBackend):
    wd = unpackRepo(tempDir)
    subWd, _dummy = reposcenario.submodule(wd)
    writeFile(f"{subWd}/dirty.txt", "hello untracked")
    writeFile(f"{subWd}/master.txt", "hello tracked")

    rw = mainWindow.openRepo(wd)

    assert rw.repo.status() == {"submodir": FileStatus.WT_MODIFIED}
    assert qlvClickNthRow(rw.dirtyFiles, 0)

    special = rw.specialDiffView
    assert special.isVisible()
    assert qteFind(special, r"submodule.+submo.+contains changes")
    assert qteFind(special, r"uncommitted changes")

    # Attempt to stage the submodule; this shouldn't do anything
    QTest.keyPress(rw.dirtyFiles, Qt.Key.Key_Return)  # attempt to stage it
    acceptQMessageBox(rw, "can.+t be staged from the parent repo")
    QTest.qWait(0)
    assert rw.repo.status() == {"submodir": FileStatus.WT_MODIFIED}  # shouldn't do anything

    if method == "link":
        qteClickLink(special, r"reset")
    else:
        doDiscard(rw, method)

    acceptQMessageBox(rw, r"discard changes in submodule.+submo.+uncommitted changes")
    assert rw.repo.status() == {}  # should've cleared everything


def testSubmoduleDeletedDiff(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    subWd, subAddId = reposcenario.submodule(wd)
    with RepoContext(wd) as repo:
        shutil.rmtree(f"{wd}/submodir")
        os.unlink(f"{wd}/.gitmodules")
        repo.index.remove(".gitmodules")
        repo.index.remove("submodir")
        subDelId = repo.create_commit_on_head("delete submo")

    rw = mainWindow.openRepo(wd)

    assert not rw.repo.listall_submodules_dict()
    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.Submodule)

    rw.jump(NavLocator.inCommit(subAddId, path="submodir"))
    assert rw.specialDiffView.isVisibleTo(rw)
    assert qteFind(rw.specialDiffView, r"submodule.+submo.+added")

    rw.jump(NavLocator.inCommit(subDelId, path="submodir"))
    assert rw.specialDiffView.isVisibleTo(rw)
    assert qteFind(rw.specialDiffView, r"submodule.+submo.+(deleted|removed)")


def testDeleteSubmodule(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.submodule(wd)
    rw = mainWindow.openRepo(wd)

    node = rw.sidebar.findNodeByKind(SidebarItem.Submodule)
    assert node.data == "submoname"
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, r"remove submodule")

    acceptQMessageBox(rw, r"remove submodule")
    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.Submodule)
    assert set(qlvGetRowData(rw.stagedFiles)) == {"submodir", ".gitmodules"}


def testAbsorbSubmodule(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "submoroot")
    subWd = unpackRepo(wd, renameTo="newsubmo")

    with RepoContext(subWd) as subRepo:
        originURL = subRepo.remotes["origin"].url
        subRepo.delete_remote("origin")

    rw = mainWindow.openRepo(wd)
    assert rw.isVisibleTo(mainWindow)

    # Start with 1 submodule
    assert ["submosub"] == rw.repo.listall_submodules_fast()
    assert "submosub" == rw.sidebar.findNodeByKind(SidebarItem.Submodule).data

    # Select subfolder in dirty files
    rw.jump(NavLocator.inUnstaged("newsubmo"))
    assert rw.specialDiffView.isVisibleTo(rw)
    assert qteFind(rw.specialDiffView, "root of another git repo")

    # Absorb as submodule - won't work, it has no remotes
    qteClickLink(rw.specialDiffView, r"absorb.+as submodule")
    acceptQMessageBox(rw, "submodule.+has no remote")

    # Restore the remote and absorb as submodule
    with RepoContext(subWd) as subRepo:
        subRepo.remotes.create("origin", originURL)
    qteClickLink(rw.specialDiffView, r"absorb.+as submodule")

    # Play with RegisterSubmoduleDialog a bit
    # then let AbsorbSubmodule task run to completion
    dlg: RegisterSubmoduleDialog = findQDialog(rw, "absorb.+submodule")
    assert dlg.ui.nameEdit.text() == "newsubmo"
    assert dlg.okButton.isEnabled()
    assert not dlg.resetNameAction.isVisible()
    for badName in ["", "submosub"]:
        dlg.ui.nameEdit.setText(badName)
        assert not dlg.okButton.isEnabled()
        assert dlg.resetNameAction.isVisible()
    dlg.resetNameAction.trigger()
    assert dlg.ui.nameEdit.text() == "newsubmo"
    dlg.accept()

    # There must be a submodule now
    assert ["newsubmo", "submosub"] == sorted(rw.repo.listall_submodules_fast())
    assert ["newsubmo", "submosub"] == sorted(node.data for node in rw.sidebar.findNodesByKind(SidebarItem.Submodule))

    # The submodule is there, but it's unstaged
    rw.jump(NavLocator.inStaged("newsubmo"))

    # Click "open submodule" link
    qteClickLink(rw.specialDiffView, "open submodule")

    # That must have opened a new tab
    assert not rw.isVisibleTo(mainWindow)
    assert 2 == len(mainWindow.tabs)
    assert 1 == mainWindow.tabs.currentIndex()

    # Open superproject from tab context menu
    tabBar = mainWindow.tabs.tabs
    tabMenu = summonContextMenu(tabBar, tabBar.tabRect(1).center())
    triggerMenuAction(tabMenu, r"open superproject")
    assert 0 == mainWindow.tabs.currentIndex()  # back to first tab
    assert rw is mainWindow.tabs.currentWidget()  # back to first tab


def testSubmoduleStagingSuggestions(tempDir, mainWindow, gitBackend):
    wd = unpackRepo(tempDir, "submoroot")
    subWd = unpackRepo(wd, renameTo="newsubmo")

    # Create uncommitted change in submodule to keep it forever unstaged
    writeFile(f"{subWd}/uncommitted.txt", "hello")

    rw = mainWindow.openRepo(wd)
    assert rw.isVisibleTo(mainWindow)

    # Start without any submodules
    assert ["submosub"] == rw.repo.listall_submodules_fast()
    assert "submosub" == rw.sidebar.findNodeByKind(SidebarItem.Submodule).data

    # Jump to unstaged tree
    submoUnstagedLoc = NavLocator.inUnstaged("newsubmo")
    rw.jump(submoUnstagedLoc)
    assert rw.navLocator.isSimilarEnoughTo(submoUnstagedLoc)
    assert qteFind(rw.specialDiffView, r"subtree is.+root of.+git repo")

    # Stage tree without absorbing it
    rw.diffArea.stageButton.click()
    acceptQMessageBox(rw, "recommended to absorb")

    assert rw.navLocator.isSimilarEnoughTo(submoUnstagedLoc)
    assert qteFind(rw.specialDiffView, r"subtree.+newsubmo.+contains changes")

    # Absorb tree as submodule
    submoStagedLoc = NavLocator.inStaged("newsubmo")
    rw.jump(submoStagedLoc)
    assert rw.navLocator.isSimilarEnoughTo(submoStagedLoc)
    assert qteFind(rw.specialDiffView, r"subtree.+newsubmo.+was added")
    assert qteFind(rw.specialDiffView, r"isn.t a submodule yet")
    qteClickLink(rw.specialDiffView, r"absorb")
    findQDialog(rw, "absorb").accept()

    # Tree is now a submodule
    assert rw.navLocator.isSimilarEnoughTo(submoStagedLoc)
    assert qteFind(rw.specialDiffView, r"submodule.+newsubmo.+was added")
    assert qteFind(rw.specialDiffView, r"make sure to commit \.gitmodules")

    # Prompt submodule re-registration
    GitConfigHelper.delete_section(f"{wd}/.gitmodules", "submodule", "newsubmo")
    rw.refreshRepo()

    # Register a submodule that has already been absorbed
    assert rw.navLocator.isSimilarEnoughTo(submoStagedLoc)
    assert qteFind(rw.specialDiffView, r"to complete the addition.+register.+\.gitmodules")
    qteClickLink(rw.specialDiffView, r"register.+\.gitmodules")
    findQDialog(rw, "register submodule").accept()

    assert rw.navLocator.isSimilarEnoughTo(submoStagedLoc)
    assert qteFind(rw.specialDiffView, r"make sure to commit \.gitmodules")

    # Delete another submodule and stage the deletion
    shutil.rmtree(f"{wd}/submosub")
    rw.refreshRepo()
    rw.jump(NavLocator.inUnstaged("submosub"))
    assert qteFind(rw.specialDiffView, r"to complete the removal.+remove.+from.+\.gitmodules")
    rw.diffArea.stageButton.click()
    acceptQMessageBox(rw, r"remove.+from.+\.gitmodules")

    # Remove deleted submodules from .gitmodules and check new suggestion
    GitConfigHelper.delete_section(f"{wd}/.gitmodules", "submodule", "submosub")
    rw.jump(NavLocator.inStaged("submosub"))
    assert qteFind(rw.specialDiffView, r"to complete the removal.+commit \.gitmodules")


def testDeleteAbsorbedSubmoduleThenRestoreIt(tempDir, mainWindow, gitBackend):
    wd = unpackRepo(tempDir)
    reposcenario.submodule(wd, absorb=True)

    rw = mainWindow.openRepo(wd)

    assert rw.repo.config["submodule.submoname.url"]

    # Delete the submodule
    node = rw.sidebar.findNodeByKind(SidebarItem.Submodule)
    assert node.data == "submoname"
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "remove")
    acceptQMessageBox(rw, "remove submodule")

    with pytest.raises(KeyError):
        rw.repo.config["submodule.submoname.url"]
    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.Submodule)
    assert set(qlvGetRowData(rw.stagedFiles)) == {".gitmodules", "submodir"}

    # Discard submodule deletion
    rw.stagedFiles.selectAll()
    rw.stagedFiles.unstage()
    rw.dirtyFiles.selectAll()
    rw.dirtyFiles.discard()
    acceptQMessageBox(rw, "discard changes")

    node = rw.sidebar.findNodeByKind(SidebarItem.Submodule)
    assert node.data == "submoname"
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "update")


def testInitSubmoduleInFreshNonRecursiveClone(tempDir, mainWindow, gitBackend):
    sm = "submosub"

    # Unpack full-blown repo (complete with submodule) as our upstream
    upstreamWd = unpackRepo(tempDir, "submoroot", renameTo="upstream")
    upstreamSub = f"{upstreamWd}/{sm}"

    # Do a non-recursive clone (using the local filesystem as an upstream)
    repo = pygit2.clone_repository(upstreamWd, f"{tempDir.name}/submoroot")
    wd = repo.workdir
    repo.free()
    del repo

    # Prevent submo from hitting network in this unit test
    # NOTE: We're modifying .gitmodules, NOT .git/config, so that the module appears UNinitialized!
    GitConfig(f"{wd}/.gitmodules")[f"submodule.{sm}.url"] = upstreamSub
    assert f"submodule.{sm}.url" not in GitConfig(f"{wd}/.git/config")

    # Open the repo
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    # At this point the submodule isn't initialized and its worktree is empty
    assert [] == os.listdir(f"{wd}/{sm}")
    assert repo.submodules.status(sm) & SubmoduleStatus.WD_UNINITIALIZED

    # Get sidebar node for submodule (must say "not initialized")
    node = rw.sidebar.findNodeByKind(SidebarItem.Submodule)
    assert node.data == sm
    assert "not initialized" in node.createIndex(rw.sidebar.sidebarModel).data(Qt.ItemDataRole.ToolTipRole)

    # Update the submodule
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "update")

    # Submodule must be initialized
    assert ".git" in os.listdir(f"{wd}/{sm}")
    assert not repo.submodules.status(sm) & SubmoduleStatus.WD_UNINITIALIZED
    assert repo.submodule_dotgit_present(sm)

    # Sidebar node for the submodule shouldn't say "not initialized" anymore
    node = rw.sidebar.findNodeByKind(SidebarItem.Submodule)
    assert node.data == sm
    assert "not initialized" not in node.createIndex(rw.sidebar.sidebarModel).data(Qt.ItemDataRole.ToolTipRole)


@pytest.mark.skipif(pygit2OlderThan("1.15.1"), reason="old pygit2")
@pytest.mark.parametrize("method", ["single", "recurse"])
def testUpdateSubmoduleWithMissingIncomingCommit(tempDir, mainWindow, method, gitBackend):
    sm = "submosub"

    # Unpack full-blown repo (complete with submodule) as our upstream
    upstreamWd = unpackRepo(tempDir, "submoroot", renameTo="upstream")
    upstreamSub = f"{upstreamWd}/{sm}"

    # Do a non-recursive clone (using the local filesystem as an upstream) and init the submodule
    repo = pygit2.clone_repository(upstreamWd, f"{tempDir.name}/submoroot")
    wd = repo.workdir
    GitConfig(f"{wd}/.git/config")[f"submodule.{sm}.url"] = upstreamSub  # don't hit the network during update!
    repo.submodules.update(init=True)
    repo.free()
    del repo

    # Create new commit in UPSTREAM submo
    with RepoContext(upstreamSub, write_index=True) as sub:
        oldSubCommit = sub.head_commit_id
        writeFile(f"{upstreamSub}/foo.txt", "bar baz")
        sub.index.add("foo.txt")
        newSubCommit = sub.create_commit_on_head("yet another new commit in submodule", TEST_SIGNATURE, TEST_SIGNATURE)

    # In the outer repo, create a commit that moves the submodule's HEAD to newSubCommit.
    # (i.e. simulate a scenario where the user does a non-recursive fetch of the root repo,
    # and they receive this commit, but they don't have newSubCommit in the submodule)
    with RepoContext(wd, write_index=True) as repo:
        treeBuilder = repo.TreeBuilder(repo.head_tree.id)
        treeBuilder.insert(sm, newSubCommit, FileMode.COMMIT)
        newTreeId = treeBuilder.write()
        newTree = repo[newTreeId].peel(Tree)
        repo.index.read_tree(newTree)
        repo.create_commit("HEAD", TEST_SIGNATURE, TEST_SIGNATURE, f"move submo to {str(newSubCommit)[:7]}",
                           newTreeId, [repo.head_commit_id])

    # Now open the outer repo...
    rw = mainWindow.openRepo(wd)

    # The submodule will appear as dirty; the diff says that the submodule's head is being moved
    # from newSubCommit to the previous commit. This tracks with vanilla git status.
    # In fact, the submodule's gitlink file points to our local copy of the submodule,
    # which is indeed still on the previous commit, so this technically makes sense (although unintuitive).
    assert sm in qlvGetRowData(rw.dirtyFiles)
    assert sm not in qlvGetRowData(rw.stagedFiles)
    rw.jump(NavLocator.inUnstaged(sm))
    newHash = str(newSubCommit)[:7]
    oldHash = str(oldSubCommit)[:7]
    assert qteFind(rw.specialDiffView, fr"old.+{newHash}.+new.+{oldHash}", True)  # yes, old/new look inverted, that's on purpose

    # Update the submodule
    if method == "single":
        node = rw.sidebar.findNodeByKind(SidebarItem.Submodule)
        assert node.data == sm
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "update")
    elif method == "recurse":
        node = rw.sidebar.findNodeByKind(SidebarItem.SubmodulesHeader)
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "update.+recursively")
    else:
        raise NotImplementedError(f"Unsupported method {method}")

    QTest.qWait(1)
    assert sm not in qlvGetRowData(rw.dirtyFiles)
    assert sm not in qlvGetRowData(rw.stagedFiles)


@pytest.mark.skipif(pygit2OlderThan("1.15.1"), reason="old pygit2")
@pytest.mark.parametrize("recurse", [True, False])
@pytest.mark.parametrize("method", ["switch1", "switch2", "detach", "newbranch"])
def testSwitchBranchAskRecurse(tempDir, mainWindow, method, recurse, gitBackend):
    contentsHead = b"hello from submodule\nan update!\n"
    contentsOld = b"hello from submodule\n"

    wd = unpackRepo(tempDir, "submoroot")

    # TODO: Figure out why this specific test needs this
    if recurse and gitBackend == "git":
        subprocess.call([GitDriver._gitPath, "update-index", "--really-refresh"], cwd=wd+"/submosub")

    rw = mainWindow.openRepo(wd)
    assert contentsHead == readFile(f"{wd}/submosub/subhello.txt")

    node = rw.sidebar.findNodeByRef("refs/heads/just-added-submodule")
    rw.jump(NavLocator.inRef("refs/heads/just-added-submodule"))

    if method == "switch1":
        triggerMenuAction(rw.sidebar.makeNodeMenu(node), "switch")
        qmb = findQMessageBox(rw, "switch to")
        assert "submodule" in qmb.checkBox().text().lower()
        assert qmb.checkBox().isChecked()
        qmb.checkBox().setChecked(recurse)
        qmb.accept()
    elif method == "newbranch":
        triggerMenuAction(rw.sidebar.makeNodeMenu(node), "new branch")
        dlg: CheckoutCommitDialog = findQDialog(rw, "new branch")
        dlg.ui.nameEdit.setText("blahblah")
        assert dlg.ui.recurseSubmodulesCheckBox.isVisible()
        assert dlg.ui.recurseSubmodulesCheckBox.isChecked()
        dlg.ui.recurseSubmodulesCheckBox.setChecked(recurse)
        dlg.accept()
    elif method == "switch2":
        triggerContextMenuAction(rw.graphView.viewport(), "check.?out")
        dlg: CheckoutCommitDialog = findQDialog(rw, "check.?out")
        assert dlg.ui.switchRadioButton.isChecked()
        assert dlg.ui.recurseSubmodulesCheckBox.isVisible()
        assert dlg.ui.recurseSubmodulesCheckBox.isChecked()
        dlg.ui.recurseSubmodulesCheckBox.setChecked(recurse)
        dlg.accept()
    elif method == "detach":
        triggerContextMenuAction(rw.graphView.viewport(), "check.?out")
        dlg = findQDialog(rw, "check.?out")
        dlg.ui.detachHeadRadioButton.setChecked(True)
        dlg.ui.recurseSubmodulesCheckBox.setChecked(recurse)
        dlg.accept()
    else:
        raise NotImplementedError("unsupported method")

    if recurse:
        assert contentsOld == readFile(f"{wd}/submosub/subhello.txt")
    else:
        assert contentsHead == readFile(f"{wd}/submosub/subhello.txt")


def testDetachHeadBeforeFirstSubmodule(tempDir, mainWindow, gitBackend):
    initialCommit = Oid(hex="2b6471b8999e560c9601ffaa0a5b8376ac403ce4")

    wd = unpackRepo(tempDir, "submoroot")

    # TODO: Figure out why this specific test needs this
    if gitBackend == "git":
        subprocess.call([GitDriver._gitPath, "update-index", "--really-refresh"], cwd=wd+"/submosub")

    rw = mainWindow.openRepo(wd)

    assert 1 == rw.sidebar.countNodesByKind(SidebarItem.Submodule)
    rw.jump(NavLocator.inCommit(initialCommit))

    triggerContextMenuAction(rw.graphView.viewport(), "check.?out")
    dlg = findQDialog(rw, "check.?out")
    dlg.ui.detachHeadRadioButton.setChecked(True)
    dlg.ui.recurseSubmodulesCheckBox.setChecked(True)
    dlg.accept()

    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.Submodule)
