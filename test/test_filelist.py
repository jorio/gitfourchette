# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os.path

import pytest

from .util import *
from . import reposcenario
from gitfourchette.nav import NavLocator, NavContext


def testParentlessCommitFileList(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1")
    rw.jump(NavLocator.inCommit(oid))
    assert qlvGetRowData(rw.committedFiles) == ["c/c1.txt"]


def testSaveRevisionAtCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex="1203b03dc816ccbb67773f28b3c19318654b0bc8")
    loc = NavLocator.inCommit(oid, "c/c2.txt")
    rw.jump(loc)
    assert loc.isSimilarEnoughTo(rw.navLocator)

    triggerMenuAction(rw.committedFiles.makeContextMenu(), "save.+copy/as of.+commit")
    acceptQFileDialog(rw, "save.+revision as", tempDir.name, useSuggestedName=True)
    assert b"c2\nc2\n" == readFile(f"{tempDir.name}/c2@1203b03.txt")


def testSaveRevisionBeforeCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex="1203b03dc816ccbb67773f28b3c19318654b0bc8")
    loc = NavLocator.inCommit(oid, "c/c2.txt")
    rw.jump(loc)
    assert loc.isSimilarEnoughTo(rw.navLocator)

    triggerMenuAction(rw.committedFiles.makeContextMenu(), "save.+copy/before.+commit")
    acceptQFileDialog(rw, "save.+revision as", tempDir.name, useSuggestedName=True)
    assert b"c2\n" == readFile(f"{tempDir.name}/c2@before-1203b03.txt")


def testSaveOldRevisionOfDeletedFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    commitId = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    rw.jump(NavLocator.inCommit(commitId, "c/c2-2.txt"))

    # c2-2.txt was deleted by the commit. Expect a warning about this.
    triggerMenuAction(rw.committedFiles.makeContextMenu(), r"save.+copy/as of.+commit")
    acceptQMessageBox(rw, r"file.+deleted by.+commit")


@pytest.mark.parametrize(
    "commit,side,path,result",
    [
        ("bab66b4", "as of", "c/c1.txt", "c1\nc1\n"),
        ("bab66b4", "before", "c/c1.txt", "c1\n"),
        ("42e4e7c", "before", "c/c1.txt", "[DEL]"),  # delete file
        ("c9ed7bf", "before", "c/c2-2.txt", "c2\nc2\n"),  # undo deletion
        ("c9ed7bf", "as of", "c/c2-2.txt", "[NOP]"),  # no-op
    ])
def testRestoreRevisionAtCommit(tempDir, mainWindow, commit, side, path, result):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        writeFile(f"{wd}/c/c1.txt", "different\n")
        repo.index.add("c/c1.txt")
        repo.create_commit_on_head("dummy", TEST_SIGNATURE, TEST_SIGNATURE)

    rw = mainWindow.openRepo(wd)

    oid = rw.repo[commit].peel(Commit).id
    loc = NavLocator.inCommit(oid, path)
    rw.jump(loc)
    assert loc.isSimilarEnoughTo(rw.navLocator)

    triggerMenuAction(rw.committedFiles.makeContextMenu(), f"restore/{side}.+commit")
    if result == "[NOP]":
        acceptQMessageBox(rw, "working copy.+already matches.+revision")
    else:
        acceptQMessageBox(rw, "restore")
        if result == "[DEL]":
            assert not os.path.exists(f"{wd}/{path}")
        else:
            assert result.encode() == readFile(f"{wd}/{path}")

        # Make sure we've jumped to the file in the workdir
        assert NavLocator.inUnstaged(path).isSimilarEnoughTo(rw.navLocator)


def testRevertCommittedFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid = Oid(hex="58be4659bb571194ed4562d04b359d26216f526e")
    loc = NavLocator.inCommit(oid, "master.txt")
    rw.jump(loc)
    assert rw.navLocator.isSimilarEnoughTo(loc)

    assert b"On master\nOn master\n" == readFile(f"{wd}/master.txt")

    triggerMenuAction(rw.committedFiles.makeContextMenu(), "revert")
    acceptQMessageBox(rw, "revert.+patch")
    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged("master.txt"))

    # Make sure revert actually worked
    assert b"On master\n" == readFile(f"{wd}/master.txt")


def testCannotRevertCommittedFileIfNowDeleted(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    assert not os.path.exists(f"{wd}/c/c2.txt")

    commitId = Oid(hex="1203b03dc816ccbb67773f28b3c19318654b0bc8")
    rw.jump(NavLocator.inCommit(commitId, "c/c2.txt"))
    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inCommit(commitId, "c/c2.txt"))

    triggerMenuAction(rw.committedFiles.makeContextMenu(), "revert")
    rejectQMessageBox(rw, "operation failed")
    assert not os.path.exists(f"{wd}/c/c2.txt")


@pytest.mark.parametrize("context", [NavContext.UNSTAGED, NavContext.STAGED])
def testRefreshKeepsMultiFileSelection(tempDir, mainWindow, context):
    wd = unpackRepo(tempDir)
    N = 10
    for i in range(N):
        writeFile(f"{wd}/UNSTAGED{i}", f"dirty{i}")
        writeFile(f"{wd}/STAGED{i}", f"staged{i}")
    with RepoContext(wd) as repo:
        repo.index.add_all([f"STAGED{i}" for i in range(N)])
        repo.index.write()

    rw = mainWindow.openRepo(wd)
    fl = rw.diffArea.fileListByContext(context)
    fl.selectAll()
    rw.refreshRepo()
    assert list(fl.selectedPaths()) == [f"{context.name}{i}" for i in range(N)]


def testSearchFileList(tempDir, mainWindow):
    oid = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(oid))
    assert rw.committedFiles.isVisibleTo(rw)
    rw.committedFiles.setFocus()
    QTest.keySequence(rw, QKeySequence.StandardKey.Find)

    fileList = rw.committedFiles
    searchBar = fileList.searchBar
    assert searchBar.isVisibleTo(rw)
    searchBar.lineEdit.setText(".txt")
    QTest.qWait(0)
    assert not searchBar.isRed()

    # Send StandardKey instead of "F3" because the bindings are different on macOS
    keyNext = QKeySequence.StandardKey.FindNext
    keyPrev = QKeySequence.StandardKey.FindPrevious

    assert qlvGetSelection(fileList) == ["a/a1.txt"]
    QTest.keySequence(rw, keyNext)
    assert qlvGetSelection(fileList) == ["a/a2.txt"]
    QTest.keySequence(rw, keyNext)
    assert qlvGetSelection(fileList) == ["master.txt"]
    QTest.keySequence(rw, keyNext)
    assert qlvGetSelection(fileList) == ["a/a1.txt"]  # wrap around
    QTest.keySequence(rw, keyPrev)
    assert qlvGetSelection(fileList) == ["master.txt"]

    searchBar.lineEdit.setText("a2")
    QTest.qWait(0)
    assert qlvGetSelection(fileList) == ["a/a2.txt"]

    searchBar.lineEdit.setText("bogus")
    QTest.qWait(0)
    assert searchBar.isRed()

    QTest.keySequence(rw, QKeySequence.StandardKey.FindNext)
    acceptQMessageBox(rw, "not found")

    QTest.keySequence(rw, QKeySequence.StandardKey.FindPrevious)
    acceptQMessageBox(rw, "not found")

    if QT5:
        # TODO: Can't get Qt 5 unit tests to hide the searchbar this way, but it does work manually.
        # Qt 5 is on the way out so it's not worth troubleshooting this.
        return
    QTest.keyClick(fileList, Qt.Key.Key_Escape)
    assert not searchBar.isVisible()


def testSearchEmptyFileList(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        oid = repo.create_commit_on_head("EMPTY COMMIT")
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(oid))
    assert rw.committedFiles.isVisibleTo(rw)
    assert not qlvGetRowData(rw.committedFiles)
    rw.committedFiles.setFocus()
    QTest.keySequence(rw, QKeySequence.StandardKey.Find)

    fileList = rw.committedFiles
    searchBar = fileList.searchBar
    assert searchBar.isVisibleTo(rw)
    searchBar.lineEdit.setText("blah.txt")
    QTest.qWait(0)
    assert searchBar.isRed()

    QTest.keySequence(rw, QKeySequence.StandardKey.FindNext)
    acceptQMessageBox(rw, "not found")

    QTest.keySequence(rw, QKeySequence.StandardKey.FindPrevious)
    acceptQMessageBox(rw, "not found")


@pytest.mark.skipif(WINDOWS, reason="TODO: no editor shim for Windows yet!")
@pytest.mark.skipif(MACOS and os.environ.get("QT_QPA_PLATFORM", "") != "offscreen",
                    reason="flaky on macOS unless executed offscreen")
def testEditFileInExternalEditor(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0"), "a/a1"))

    editorPath = getTestDataPath("editor-shim.sh")
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"

    # First, set the editor to an incorrect command to go through the "locate" code path
    mainWindow.onAcceptPrefsDialog({"externalEditor": f'"{editorPath}-BOGUSCOMMAND" "{scratchPath}"'})
    triggerMenuAction(rw.committedFiles.makeContextMenu(), r"open.+in editor-shim.+BOGUSCOMMAND$/current")
    QTest.qWait(100 if not MACOS else 500)
    qmb = findQMessageBox(mainWindow, "couldn.t start.+editor-shim.+text editor")
    qmb.button(QMessageBox.StandardButton.Open).click()  # click "locate" button
    # Set correct command; this must retain the arguments from the incorrect command
    acceptQFileDialog(mainWindow, "where is.+editor-shim", editorPath)

    # Now open the file in our shim
    # HEAD revision
    triggerMenuAction(rw.committedFiles.makeContextMenu(), r"open.+in editor-shim\.sh$/current")
    assert b"a/a1" in readFile(scratchPath, timeout=1000, unlink=True)

    # New revision
    triggerMenuAction(rw.committedFiles.makeContextMenu(), r"open.+in editor-shim\.sh$/before.+commit")
    acceptQMessageBox(mainWindow, "file did.?n.t exist")

    # Old revision
    triggerMenuAction(rw.committedFiles.makeContextMenu(), r"open.+in editor-shim\.sh$/as of.+commit")
    assert b"a1@49322bb" in readFile(scratchPath, timeout=1000, unlink=True)


@pytest.mark.skipif(WINDOWS, reason="TODO: no editor shim for Windows yet!")
def testEditFileInExternalDiffTool(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(Oid(hex="7f822839a2fe9760f386cbbbcb3f92c5fe81def7"), "b/b2.txt"))

    editorPath = getTestDataPath("editor-shim.sh")
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"

    # First, set the diff tool to an empty command to go through the "set up" code path
    mainWindow.onAcceptPrefsDialog({"externalDiff": ""})
    triggerMenuAction(rw.committedFiles.makeContextMenu(), "open diff in.+diff tool")
    acceptQMessageBox(mainWindow, "diff tool.+n.t (set up|configured)")
    findQDialog(mainWindow, "settings").reject()

    mainWindow.onAcceptPrefsDialog({"externalDiff": f'"{editorPath}" "{scratchPath}" $L $R'})
    triggerMenuAction(rw.committedFiles.makeContextMenu(), "open diff in editor-shim")
    scratchText = readFile(scratchPath, 1000, unlink=True).decode("utf-8")
    assert "[OLD]b2.txt" in scratchText
    assert "[NEW]b2.txt" in scratchText


def testFileListToolTip(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.fileWithStagedAndUnstagedChanges(wd)
    writeFile(f"{wd}/newexe", "okay\n")
    os.chmod(f"{wd}/newexe", 0o777)
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged("a/a1.txt"))
    tip = rw.dirtyFiles.currentIndex().data(Qt.ItemDataRole.ToolTipRole)
    assert all(re.search(p, tip, re.I) for p in ("a/a1.txt", "modified"))

    # look at staged counterpart of current index
    tip = rw.stagedFiles.model().index(0, 0).data(Qt.ItemDataRole.ToolTipRole)
    assert all(re.search(p, tip, re.I) for p in ("a/a1.txt", "modified", "also.+staged"))

    rw.jump(NavLocator.inUnstaged("newexe"))
    tip = rw.dirtyFiles.currentIndex().data(Qt.ItemDataRole.ToolTipRole)
    assert re.search("untracked", tip, re.I)
    assert re.search("executable", tip, re.I) or WINDOWS  # skip mode on windows

    rw.jump(NavLocator.inCommit(Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17"), "c/c2-2.txt"))
    tip = rw.committedFiles.currentIndex().data(Qt.ItemDataRole.ToolTipRole)
    assert all(re.search(p, tip, re.I) for p in ("c/c2.txt", "c/c2-2.txt", "renamed", "similarity"))


def testFileListCopyPath(tempDir, mainWindow):
    """
    WARNING: THIS TEST MODIFIES THE SYSTEM'S CLIPBOARD.
    (No worries if you're running the tests offscreen.)
    """

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    # Make sure the clipboard is clean before we begin
    clipboard = QApplication.clipboard()
    clipboard.clear()
    assert not clipboard.text()

    rw.jump(NavLocator.inCommit(Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17"), "c/c2-2.txt"))
    QTest.keySequence(rw.committedFiles, "Ctrl+C")
    clipped = clipboard.text()
    assert clipped == os.path.normpath(f"{wd}/c/c2-2.txt")


def testFileListChangePathDisplayStyle(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17"), "c/c2-2.txt"))
    assert ["c/c2-2.txt"] == qlvGetRowData(rw.committedFiles)

    menu = rw.committedFiles.makeContextMenu()
    triggerMenuAction(menu, "path display style/name only")
    assert ["c2-2.txt"] == qlvGetRowData(rw.committedFiles)

    menu = rw.committedFiles.makeContextMenu()
    triggerMenuAction(menu, "path display style/full")
    assert ["c/c2-2.txt"] == qlvGetRowData(rw.committedFiles)


def testMiddleClickToStageFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.fileWithStagedAndUnstagedChanges(wd)
    rw = mainWindow.openRepo(wd)

    from gitfourchette import settings

    initialStatus = rw.repo.status()
    assert initialStatus == {'a/a1.txt': FileStatus.INDEX_MODIFIED | FileStatus.WT_MODIFIED}

    # Middle-clicking has no effect as long as middleClickToStage is off (by default)
    QTest.mouseClick(rw.stagedFiles.viewport(), Qt.MouseButton.MiddleButton, pos=QPoint(2, 2))
    assert initialStatus == rw.repo.status()

    # Enable middleClickToStage
    settings.prefs.middleClickToStage = True

    # Unstage file by middle-clicking
    QTest.mouseClick(rw.stagedFiles.viewport(), Qt.MouseButton.MiddleButton, pos=QPoint(2, 2))
    assert rw.repo.status() == {'a/a1.txt': FileStatus.WT_MODIFIED}

    # Stage file by middle-clicking
    QTest.mouseClick(rw.dirtyFiles.viewport(), Qt.MouseButton.MiddleButton, pos=QPoint(2, 2))
    assert rw.repo.status() == {'a/a1.txt': FileStatus.INDEX_MODIFIED}


def testGrayOutStageButtonsAfterDiscardingOnlyFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/SomeNewFile.txt", "hi")
    rw = mainWindow.openRepo(wd)

    assert NavLocator.inUnstaged("SomeNewFile.txt").isSimilarEnoughTo(rw.navLocator)
    assert rw.diffArea.stageButton.isEnabled()
    assert rw.diffArea.discardButton.isEnabled()
    assert not rw.diffArea.unstageButton.isEnabled()

    rw.diffArea.discardButton.click()
    acceptQMessageBox(rw, "discard")

    assert not rw.diffArea.stageButton.isEnabled()
    assert not rw.diffArea.discardButton.isEnabled()
    assert not rw.diffArea.unstageButton.isEnabled()
