# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import textwrap
import pytest

from . import reposcenario
from .util import *
from gitfourchette.nav import NavLocator
from gitfourchette.sidebar.sidebarmodel import SidebarItem


@pytest.mark.skipif(WINDOWS, reason="TODO: Fix this on Windows")
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


def testExportPatchContainingBinaryFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/master.txt", "\x00\x01\x02\x03")
    writeFile(f"{wd}/untracked.txt", "hello")
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged("master.txt"), check=True)

    rw.dirtyFiles.selectAll()
    rw.dirtyFiles.savePatchAs()
    acceptQFileDialog(rw, "export patch", f"{wd}/hello.patch")

    patchData = readTextFile(f"{wd}/hello.patch")
    assert "master.txt" in patchData
    assert "GIT binary patch" in patchData
    assert "untracked.txt" in readTextFile(f"{wd}/hello.patch")


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


def testExportPatchFromABDiff(tempDir, mainWindow):
    contents = textwrap.dedent("""\
        diff --git a/c/c1.txt b/c/c1.txt
        index ae9304576a6ec3419b231b2b9c8e33a06f97f9fb..1fd7d579fb6ae3fe942dc09c2c783443d04cf21e 100644
        --- a/c/c1.txt
        +++ b/c/c1.txt
        @@ -1 +1,2 @@
         c1
        +c1
        diff --git a/c/c2.txt b/c/c2.txt
        index 16f9ec009e5568c435f473ba3a1df732d49ce8c3..55a1a760df4b86a02094a904dfa511deb5655905 100644
        --- a/c/c2.txt
        +++ b/c/c2.txt
        @@ -1 +1,2 @@
         c2
        +c2
        """)

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")
    oid2 = Oid(hex="1203b03dc816ccbb67773f28b3c19318654b0bc8")
    row1 = rw.graphView.getFilterIndexForCommit(oid1).row()
    row2 = rw.graphView.getFilterIndexForCommit(oid2).row()

    qlvClickNthRow(rw.graphView, row1)
    qlvClickNthRow(rw.graphView, row2, modifier=Qt.KeyboardModifier.ControlModifier)

    triggerContextMenuAction(rw.graphView.viewport(), r"export.+patch")
    path = acceptQFileDialog(rw, "export.+patch", tempDir.name, useSuggestedName=True)

    assert "83834a" in path
    assert "1203b0" in path
    assert readTextFile(path).strip() == contents.strip()


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
