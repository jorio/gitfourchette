# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from . import reposcenario
from .util import *
from gitfourchette.filelists.filelistmodel import FileListModel
from gitfourchette.forms.stashdialog import StashDialog
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from gitfourchette.trash import Trash
import os
import pytest


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey", "sidebardclick", "menubar"])
def testNewStash(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    shell("""
        echo 'a1\nPENDING CHANGE' > a/a1.txt
        echo 'b1\nPENDING CHANGE (staged)' > b/b1.txt
        echo 'this file is untracked' > a/untracked.txt
        git add b/b1.txt
    """, wd)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    repo = rw.repo

    assert len(repo.listall_stashes()) == 0

    with pytest.raises(KeyError):
        sb.findNodeByKind(SidebarItem.Stash)
    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt", "a/untracked.txt"]
    assert qlvGetRowData(rw.stagedFiles) == ["b/b1.txt"]

    node = sb.findNodeByKind(SidebarItem.StashesHeader)

    if method == "sidebarmenu":
        menu = sb.makeNodeMenu(node)
        triggerMenuAction(menu, "stash changes")
    elif method == "sidebarkey":
        sb.setFocus()
        sb.selectNode(node)
        QTest.keyPress(sb, Qt.Key.Key_Return)
    elif method == "sidebardclick":
        index = sb.nodeToFilterIndex(node)
        rect = sb.visualRect(index)
        QTest.mouseDClick(sb.viewport(), Qt.MouseButton.LeftButton, pos=rect.topLeft())
    elif method == "menubar":
        triggerMenuAction(mainWindow.menuBar(), "repo/stash")
    else:
        raise NotImplementedError("unknown method")

    dlg: StashDialog = findQDialog(rw, "new stash")
    assert not dlg.ui.indexAndWtWarning.isVisible()
    assert not dlg.ui.keepCheckBox.isChecked()
    dlg.ui.messageEdit.setText("helloworld")
    dlg.accept()

    assert not os.path.isfile(f"{wd}/a/untracked.txt"), "untracked file must be gone after stashing"
    assert qlvGetRowData(rw.dirtyFiles) == [], "workdir must be clean after stashing"
    assert qlvGetRowData(rw.stagedFiles) == [], "workdir must be clean after stashing"
    assert len(repo.listall_stashes()) == 1, "there must be one stash in the repo"

    stashIndex = sb.indexForRef("stash@{0}")
    assert "helloworld" == stashIndex.data(Qt.ItemDataRole.DisplayRole)
    assert "helloworld" in stashIndex.data(Qt.ItemDataRole.ToolTipRole)

    rw.selectRef("refs/stash")
    assert rw.committedFiles.isVisibleTo(rw)
    assert qlvGetRowData(rw.committedFiles) == ["a/a1.txt", "a/untracked.txt", "b/b1.txt"]


@pytest.mark.parametrize("method", ["stashcommand", "filelist"])
def testNewPartialStash(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    shell("""
        echo 'a1\nPENDING CHANGE 1' > a/a1.txt
        echo 'a2\nPENDING CHANGE 2' > a/a2.txt
        echo 'b1\nPENDING CHANGE (staged)' > b/b1.txt
        echo 'STAGED' > both.txt
        echo 'this file is untracked 1' > a/untracked1.txt
        echo 'this file is untracked 2' > a/untracked2.txt
        git add b/b1.txt b/b2.txt both.txt
        echo 'STAGED\nUNSTAGED' > both.txt
    """, wd)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    dirtyFiles = {"a/a1.txt", "a/a2.txt", "a/untracked1.txt", "a/untracked2.txt", "both.txt"}
    stagedFiles = {"b/b1.txt", "both.txt"}
    stashedFiles = {"a/a2.txt", "a/untracked2.txt", "both.txt"}
    keptFiles = dirtyFiles.union(stagedFiles).difference(stashedFiles)

    assert len(repo.listall_stashes()) == 0
    assert rw.sidebar.countNodesByKind(SidebarItem.Stash) == 0
    assert set(qlvGetRowData(rw.dirtyFiles)) == dirtyFiles

    if method == "stashcommand":
        node = rw.sidebar.findNodeByKind(SidebarItem.StashesHeader)
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "stash changes")
    elif method == "filelist":
        rw.dirtyFiles.clearSelection()
        for file in stashedFiles:
            row = qlvFindRow(rw.dirtyFiles, file)
            index = rw.dirtyFiles.flModel.index(row, 0)
            rw.dirtyFiles.selectionModel().select(index, QItemSelectionModel.SelectionFlag.Select)
        triggerContextMenuAction(rw.dirtyFiles.viewport(), "stash")
    else:
        raise NotImplementedError(f"unknown method {method}")

    dlg: StashDialog = findQDialog(rw, "new stash")
    assert dlg.ui.indexAndWtWarning.isVisible()
    assert not dlg.ui.keepCheckBox.isChecked()
    dlg.ui.messageEdit.setText("helloworld")

    fl = dlg.ui.fileList
    assert set(qlvGetRowData(fl, Qt.ItemDataRole.UserRole)) == dirtyFiles.union(stagedFiles)

    # Uncheck some files to produce a partial stash
    if method == "stashcommand":
        for uncheckFile in keptFiles:
            row = qlvFindRow(fl, uncheckFile)
            qlvClickNthRow(fl, row)
            fl.selectedItems()[0].setCheckState(Qt.CheckState.Unchecked)

    dlg.accept()

    assert os.path.isfile(f"{wd}/a/untracked1.txt"), "untracked file 1 should still be here"
    assert not os.path.isfile(f"{wd}/a/untracked2.txt"), "untracked file 2 must be gone"
    assert keptFiles == set(qlvGetRowData(rw.dirtyFiles) + qlvGetRowData(rw.stagedFiles))

    rw.selectRef("refs/stash")
    assert rw.committedFiles.isVisibleTo(rw)
    assert set(qlvGetRowData(rw.committedFiles)) == stashedFiles


def testNewStashWithoutIdentity(tempDir, mainWindow):
    clearSessionwideIdentity()
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/a/untracked.txt", "this file is untracked\n")  # unstaged change
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    repo = rw.repo

    node = sb.findNodeByKind(SidebarItem.StashesHeader)
    menu = sb.makeNodeMenu(node)
    triggerMenuAction(menu, "stash changes")

    dlg: StashDialog = findQDialog(rw, "new stash")
    dlg.ui.messageEdit.setText("helloworld")
    dlg.accept()

    assert not os.path.isfile(f"{wd}/a/untracked.txt")

    assert len(repo.listall_stashes()) == 1
    stash = repo.listall_stashes()[0]
    stashCommit: Commit = repo[stash.commit_id].peel(Commit)
    assert "unknown" == stashCommit.author.name.lower()
    assert "unknown" == stashCommit.committer.name.lower()

    assert "helloworld" == sb.indexForRef("stash@{0}").data(Qt.ItemDataRole.DisplayRole)
    assert qlvGetRowData(rw.dirtyFiles) == []


def testNewStashNothingToStash(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    node = rw.sidebar.findNodeByKind(SidebarItem.StashesHeader)
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "stash changes")

    acceptQMessageBox(rw, "no.+changes to stash")


def testNewStashCantStashSubmoduleOrSubtree(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    # Create untracked subtree
    shell("git init new_untracked_tree", wd)
    # pygit2.init_repository(f"{wd}new_untracked_tree")

    # Create tracked submodule + a pending change within
    submoAbsPath, _submoCommit = reposcenario.submodule(wd)
    writeFile(f"{submoAbsPath}/dirty.txt", "coucou")

    rw = mainWindow.openRepo(wd)
    assert qlvGetRowData(rw.dirtyFiles, FileListModel.Role.FilePath) == ["new_untracked_tree", "submodir"]

    node = rw.sidebar.findNodeByKind(SidebarItem.StashesHeader)
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "stash changes")

    acceptQMessageBox(rw, "cannot stash submodules")


def testNewStashNoIgnoredFiles(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    shell("""
        mkdir -p recipes/drinks
        echo 'recipes/*\n!recipes/drinks' > .gitignore
        echo 'ginger' > recipes/drinks/kombucha.txt
        git add .
        git commit -m 'kombucha'

        # Convoluted ignore scenario that fails if NewStash uses repo.status()
        # instead of vanilla git status
        echo 'unrelated change, stashing OK' > master.txt
        echo 'recipes' > .git/info/exclude
        echo 'yikes!' > recipes/drinks/DONT_SUGGEST_STASHING THIS
    """, wd)

    rw = mainWindow.openRepo(wd)
    assert qlvGetRowData(rw.dirtyFiles) == ["master.txt"]

    triggerMenuAction(mainWindow.menuBar(), "repo/stash")

    stashDialog = findQDialog(rw, "stash", t=StashDialog)
    assert qlvGetRowData(stashDialog.ui.fileList) == ["master.txt"]

    stashDialog.reject()


@pytest.mark.parametrize("trashEnabled", [True, False])
def testPopStash(tempDir, mainWindow, trashEnabled):
    GFApplication.instance().applyPrefs(maxTrashFiles=250 if trashEnabled else 0)

    wd = unpackRepo(tempDir)
    reposcenario.stashedChange(wd)
    rw = mainWindow.openRepo(wd)
    stash = rw.repo.listall_stashes()[-1]

    assert 1 == rw.sidebar.countNodesByKind(SidebarItem.Stash)
    node = rw.sidebar.findNodeByRef("stash@{0}")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "^apply")

    qmb = findQMessageBox(rw, "apply.*stash")
    assert "delete" in qmb.checkBox().text().lower()
    qmb.checkBox().setChecked(True)
    qmb.accept()

    assert 0 == len(rw.repo.listall_stashes())
    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.Stash)
    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt"]

    if trashEnabled:
        # Popped stash goes to trash
        lastTrashFile = Trash.instance().trashFiles[-1]
        assert "DELETED_STASH" in lastTrashFile.name
        assert str(stash.commit_id) in readTextFile(lastTrashFile)
    else:
        assert 0 == Trash.instance().count()


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey", "sidebardclick"])
def testApplyStash(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    reposcenario.stashedChange(wd)
    rw = mainWindow.openRepo(wd)

    assert 1 == rw.sidebar.countNodesByKind(SidebarItem.Stash)
    node = rw.sidebar.findNodeByRef("stash@{0}")

    # Jump to stash
    rw.sidebar.selectNode(node)
    assert not rw.navLocator.context.isWorkdir()
    assert rw.navLocator.commit == rw.repoModel.stashes[0]

    if method == "sidebarmenu":
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, r"^apply")
    elif method == "sidebarkey":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Return)
    elif method == "sidebardclick":
        index = rw.sidebar.nodeToFilterIndex(node)
        rect = rw.sidebar.visualRect(index)
        QTest.mouseDClick(rw.sidebar.viewport(), Qt.MouseButton.LeftButton, pos=rect.topLeft())
    else:
        raise NotImplementedError(f"unknown method {method}")

    qmb = findQMessageBox(rw, "apply.+stash")
    assert "delete" in qmb.checkBox().text().lower()
    qmb.checkBox().setChecked(False)
    qmb.accept()

    # After applying the stash, should have jumped to workdir
    assert rw.navLocator.context.isWorkdir()

    # Check that the UI matches the expected post-apply state
    assert 1 == len(rw.repo.listall_stashes())
    assert 1 == rw.sidebar.countNodesByKind(SidebarItem.Stash)
    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt"]


def testCancelApplyStash(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stashedChange(wd)
    rw = mainWindow.openRepo(wd)

    assert 1 == rw.sidebar.countNodesByKind(SidebarItem.Stash)
    node = rw.sidebar.findNodeByRef("stash@{0}")

    # Jump to stash
    rw.sidebar.selectNode(node)
    assert not rw.navLocator.context.isWorkdir()
    assert rw.navLocator.commit == rw.repoModel.stashes[0]

    # Bring up apply stash confirmation then cancel
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, r"^apply")
    rejectQMessageBox(rw, "apply.+stash")

    # After canceling, should NOT jump to workdir
    assert not rw.navLocator.context.isWorkdir()
    assert rw.navLocator.commit == rw.repoModel.stashes[0]


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey", "contextheader"])
def testDropStash(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    reposcenario.stashedChange(wd)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    assert qlvGetRowData(rw.dirtyFiles) == []

    assert 1 == rw.sidebar.countNodesByKind(SidebarItem.Stash)
    node = rw.sidebar.findNodeByRef("stash@{0}")

    if method == "sidebarmenu":
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "delete")
    elif method == "sidebarkey":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Delete)
    elif method == "contextheader":
        rw.sidebar.selectNode(node)
        button = next(b for b in rw.diffArea.contextHeader.buttons if "delete" in b.text().lower())
        button.click()
    else:
        raise NotImplementedError(f"unknown method {method}")

    acceptQMessageBox(rw, "really delete.+stash")

    assert 0 == len(repo.listall_stashes())
    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.Stash)
    assert qlvGetRowData(rw.dirtyFiles) == []


def testApplyStashWithConflicts(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stashedChange(wd)
    writeFile(f"{wd}/a/a1.txt", "a1\nCONFLICTING CHANGE\n")
    rw = mainWindow.openRepo(wd)

    # First try to apply the stash - which isn't allowed because it would conflict with a1.txt in the workdir
    node = rw.sidebar.findNodeByRef("stash@{0}")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, r"^apply")
    acceptQMessageBox(rw, "apply.+stash")
    acceptQMessageBox(rw, "your local changes to the following files would be overwritten")

    # Commit a1.txt
    shell("git commit -am'conflicting thing'", wd)
    rw.refreshRepo()

    # Apply the stash again - this time it works but conflicts appear in the index
    node = rw.sidebar.findNodeByRef("stash@{0}")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, r"^apply")
    acceptQMessageBox(rw, "apply.+stash")
    acceptQMessageBox(rw, "has caused merge conflicts")

    assert rw.sidebar.findNodeByRef("stash@{0}")  # stash not deleted

    assert rw.repo.any_conflicts
    assert rw.mergeBanner.isVisible()
    assert "fix the conflicts" in rw.mergeBanner.label.text().lower()

    rw.dirtyFiles.selectFile("a/a1.txt")
    assert rw.conflictView.isVisible()
    assert rw.conflictView.currentConflict.ours.path == "a/a1.txt"


def testApplyStashWithUnrelatedConflictsInIndex(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    shell("""
       echo "unrelated change in index 1 - will wind up in stash's index parent commit" > master.txt
       echo "UNSTASH THIS" > a/a1.txt
       git add master.txt
    """, wd)

    # Must create this stash with libgit2 (vanilla git adds master.txt in the stash)
    with RepoContext(wd, write_index=True) as repo:
        repo.create_stash("helloworld", paths=["a/a1.txt"])

    shell("""
        git checkout HEAD -- a/a1.txt
        echo "unrelated change in index 2 - conflicts with stash's index parent commit" > master.txt
        git add .
        git commit -m 'unrelated'
    """, wd)

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNodeByRef("stash@{0}")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, r"^apply")
    acceptQMessageBox(rw, "apply.+stash")

    # Make sure we've been able to apply the stash even though its index
    # conflicts with ours, i.e. don't pass "--index" to "git stash apply".
    assert readTextFile(f"{wd}/a/a1.txt").rstrip() == "UNSTASH THIS"


def testRevealStashParent(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stashedChange(wd)
    rw = mainWindow.openRepo(wd)

    assert rw.navLocator.commit != rw.repo.head_commit_id

    node = rw.sidebar.findNodeByRef("stash@{0}")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, r"^reveal.+parent")

    assert rw.navLocator.commit == rw.repo.head_commit_id
