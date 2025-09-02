# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from . import reposcenario
from .util import *
from gitfourchette.nav import NavLocator
from gitfourchette.sidebar.sidebarmodel import SidebarItem


def testExportPatchFromWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/master.txt", "some changes\n")
    writeFile(f"{wd}/untracked-file.txt", "hello\n")
    rw = mainWindow.openRepo(wd)
    assert qlvGetRowData(rw.dirtyFiles) == ["master.txt", "untracked-file.txt"]

    node = rw.sidebar.findNodeByKind(SidebarItem.UncommittedChanges)
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), r"export.+patch")
    acceptQFileDialog(rw, "export.+patch", f"{wd}/workdir.patch")

    # Since we've exported the patch to the workdir, make sure we can see it after the UI has refreshed.
    assert os.path.isfile(f"{wd}/workdir.patch")
    assert "workdir.patch" in qlvGetRowData(rw.dirtyFiles)

    triggerMenuAction(mainWindow.menuBar(), "file/revert patch")
    acceptQFileDialog(rw, "revert patch", f"{wd}/workdir.patch")
    acceptQMessageBox(rw, "revert.+patch")
    assert qlvGetRowData(rw.dirtyFiles) == ["workdir.patch"]

    triggerMenuAction(mainWindow.menuBar(), "file/revert patch")
    acceptQFileDialog(rw, "revert patch", f"{wd}/workdir.patch")
    acceptQMessageBox(rw, "patch does not apply")

    triggerMenuAction(mainWindow.menuBar(), "file/apply patch")
    acceptQFileDialog(rw, "apply patch", f"{wd}/workdir.patch")
    acceptQMessageBox(rw, "apply.+patch")
    assert qlvGetRowData(rw.dirtyFiles) == ["master.txt", "untracked-file.txt", "workdir.patch"]


def testExportPatchFromEmptyWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    node = rw.sidebar.findNodeByKind(SidebarItem.UncommittedChanges)
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), r"export.+patch")
    acceptQMessageBox(rw, "patch is empty")


def testExportPatchFromHandPickedSelectionOfBinaryFiles(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/master.txt", "\x00\x01\x02\x03")
    writeFile(f"{wd}/untracked.txt", "hello")
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged("master.txt"), check=True)
    rw.dirtyFiles.savePatchAs()
    acceptQMessageBox(rw, "cannot export binary patches from a hand-picked selection of files")

    rw.dirtyFiles.selectAll()
    rw.dirtyFiles.savePatchAs()
    acceptQMessageBox(rw, "cannot export binary patches from a hand-picked selection of files"
                          ".+binary file will be omitted.+master.txt")
    acceptQFileDialog(rw, "export patch", f"{wd}/nobinary.patch")

    assert "master.txt" not in readTextFile(f"{wd}/nobinary.patch")
    assert "untracked.txt" in readTextFile(f"{wd}/nobinary.patch")


def testExportPatchFromCommit(tempDir, mainWindow):
    oid = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(oid))
    triggerContextMenuAction(rw.graphView.viewport(), r"export.+patch")
    acceptQFileDialog(rw, "export.+patch", f"{tempDir.name}/foo.patch")

    triggerMenuAction(mainWindow.menuBar(), "file/revert patch")
    acceptQFileDialog(rw, "revert patch", f"{tempDir.name}/foo.patch")
    acceptQMessageBox(rw, "revert.+patch")
    assert rw.navLocator.context.isWorkdir()
    assert qlvGetRowData(rw.dirtyFiles) == ["c/c2-2.txt"]

    triggerMenuAction(mainWindow.menuBar(), "file/apply patch")
    acceptQFileDialog(rw, "apply patch", f"{tempDir.name}/foo.patch")
    acceptQMessageBox(rw, "apply.+patch")
    assert qlvGetRowData(rw.dirtyFiles) == []


def testExportPatchFromStash(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stashedChange(wd)
    rw = mainWindow.openRepo(wd)

    assert 1 == rw.sidebar.countNodesByKind(SidebarItem.Stash)
    node = rw.sidebar.findNodeByRef("stash@{0}")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, r"export.+patch")
    acceptQFileDialog(rw, "export stash.+patch", f"{tempDir.name}/foo.patch")

    triggerMenuAction(mainWindow.menuBar(), "file/apply patch")
    acceptQFileDialog(rw, "apply patch", f"{tempDir.name}/foo.patch")
    acceptQMessageBox(rw, "apply.+patch")
    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt"]

    triggerMenuAction(mainWindow.menuBar(), "file/revert patch")
    acceptQFileDialog(rw, "revert patch", f"{tempDir.name}/foo.patch")
    acceptQMessageBox(rw, "revert.+patch")
    assert qlvGetRowData(rw.dirtyFiles) == []


@pytest.mark.parametrize("commitHex,path", [
    ("c9ed7bf12c73de26422b7c5a44d74cfce5a8993b", "c/c2-2.txt"),
    ("7f822839a2fe9760f386cbbbcb3f92c5fe81def7", "b/b2.txt"),
    ("f73b95671f326616d66b2afb3bdfcdbbce110b44", "a/a1"),
])
def testExportPatchFromFileList(tempDir, mainWindow, commitHex, path):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(Oid(hex=commitHex), path), check=True)
    rw.committedFiles.savePatchAs()
    acceptQFileDialog(rw, "export patch", f"{tempDir.name}/foo.patch")

    triggerMenuAction(mainWindow.menuBar(), "file/revert patch")
    acceptQFileDialog(rw, "revert patch", f"{tempDir.name}/foo.patch")
    acceptQMessageBox(rw, "revert.+patch")
