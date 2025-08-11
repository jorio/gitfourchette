# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os.path
import pytest

from .util import *
from . import reposcenario


def doStage(rw, method):
    if method == "key":
        QTest.keyPress(rw.dirtyFiles, Qt.Key.Key_Return)
    elif method == "menu":
        triggerContextMenuAction(rw.dirtyFiles.viewport(), "stage")
    elif method == "button":
        rw.diffArea.stageButton.click()
    else:
        raise NotImplementedError("unknown method")


def doDiscard(rw, method):
    if method == "key":
        QTest.keyPress(rw.dirtyFiles, Qt.Key.Key_Delete)
    elif method == "menu":
        triggerContextMenuAction(rw.dirtyFiles.viewport(), "(discard|delete)")
    elif method == "button":
        rw.diffArea.discardButton.click()
    else:
        raise NotImplementedError("unknown method")


def doUnstage(rw, method):
    if method == "key":
        QTest.keyPress(rw.stagedFiles, Qt.Key.Key_Delete)
    elif method == "menu":
        triggerContextMenuAction(rw.stagedFiles.viewport(), "unstage")
    elif method == "button":
        rw.diffArea.unstageButton.click()
    else:
        raise NotImplementedError("unknown method")


@pytest.mark.parametrize("method", ["key", "menu", "button"])
def testStageEmptyUntrackedFile(tempDir, mainWindow, method, gitBackend):
    wd = unpackRepo(tempDir)
    touchFile(F"{wd}/SomeNewFile.txt")
    rw = mainWindow.openRepo(wd)

    assert qlvGetRowData(rw.dirtyFiles) == ["SomeNewFile.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []

    qlvClickNthRow(rw.dirtyFiles, 0)
    doStage(rw, method)

    assert qlvGetRowData(rw.dirtyFiles) == []
    assert qlvGetRowData(rw.stagedFiles) == ["SomeNewFile.txt"]
    assert rw.repo.status() == {"SomeNewFile.txt": FileStatus.INDEX_NEW}


@pytest.mark.parametrize("method", ["key", "menu", "button"])
def testDiscardUntrackedFile(tempDir, mainWindow, method, gitBackend):
    wd = unpackRepo(tempDir)
    touchFile(F"{wd}/SomeNewFile.txt")
    rw = mainWindow.openRepo(wd)

    assert qlvGetRowData(rw.dirtyFiles) == ["SomeNewFile.txt"]

    qlvClickNthRow(rw.dirtyFiles, 0)
    doDiscard(rw, method)
    acceptQMessageBox(rw, "really delete")

    assert rw.dirtyFiles.model().rowCount() == 0
    assert rw.stagedFiles.model().rowCount() == 0
    assert rw.repo.status() == {}


@pytest.mark.parametrize("method", ["key", "menu", "button"])
def testDiscardUnstagedFileModification(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/a/a1.txt", "a1\nPENDING CHANGE\n")  # unstaged change
    rw = mainWindow.openRepo(wd)

    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []
    qlvClickNthRow(rw.dirtyFiles, 0)

    doDiscard(rw, method)
    acceptQMessageBox(rw, "really discard changes")

    assert qlvGetRowData(rw.dirtyFiles) == []
    assert qlvGetRowData(rw.stagedFiles) == []
    assert rw.repo.status() == {}


@pytest.mark.parametrize("method", ["key", "menu", "button"])
def testDiscardFileModificationWithoutAffectingStagedChange(tempDir, mainWindow, method, gitBackend):
    wd = unpackRepo(tempDir)
    reposcenario.fileWithStagedAndUnstagedChanges(wd)
    rw = mainWindow.openRepo(wd)

    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt"]
    assert qlvGetRowData(rw.stagedFiles) == ["a/a1.txt"]
    qlvClickNthRow(rw.dirtyFiles, 0)

    doDiscard(rw, method)
    acceptQMessageBox(rw, "really discard changes")

    assert qlvGetRowData(rw.dirtyFiles) == []
    assert qlvGetRowData(rw.stagedFiles) == ["a/a1.txt"]
    assert rw.repo.status() == {"a/a1.txt": FileStatus.INDEX_MODIFIED}


@pytest.mark.skipif(WINDOWS, reason="file modes are flaky on Windows")
def testDiscardModeChange(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    path = f"{wd}/a/a1.txt"
    assert os.lstat(path).st_mode & 0o777 == 0o644

    writeFile(path, "keep this!")
    os.chmod(path, 0o777)

    rw = mainWindow.openRepo(wd)
    assert qlvGetRowData(rw.dirtyFiles) == ["[+x] a/a1.txt"]
    qlvClickNthRow(rw.dirtyFiles, 0)
    triggerContextMenuAction(rw.dirtyFiles.viewport(), "revert mode")
    acceptQMessageBox(rw, "(restore|revert|discard) mode")

    assert readFile(path).decode() == "keep this!"
    assert os.lstat(path).st_mode & 0o777 == 0o644


@pytest.mark.skipif(WINDOWS, reason="file modes are flaky on Windows")
def testUnstageModeChange(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    path = f"{wd}/a/a1.txt"
    assert os.lstat(path).st_mode & 0o777 == 0o644

    writeFile(path, "keep this!")
    os.chmod(path, 0o777)
    with RepoContext(wd, write_index=True) as repo:
        repo.index.add_all()

    rw = mainWindow.openRepo(wd)
    assert rw.repo.index["a/a1.txt"].mode == FileMode.BLOB_EXECUTABLE
    assert qlvGetRowData(rw.stagedFiles) == ["[+x] a/a1.txt"]

    qlvClickNthRow(rw.stagedFiles, 0)
    triggerContextMenuAction(rw.stagedFiles.viewport(), "revert mode")
    assert rw.repo.index["a/a1.txt"].mode == FileMode.BLOB


def testDiscardUntrackedTree(tempDir, mainWindow, gitBackend):
    outerWd = unpackRepo(tempDir, renameTo="outer")
    innerWd = unpackRepo(tempDir, renameTo="inner")
    innerWd = shutil.move(innerWd, outerWd)

    rw = mainWindow.openRepo(outerWd)
    assert rw.repo.status() == {"inner/": FileStatus.WT_NEW}

    assert os.path.exists(innerWd)
    assert qlvGetRowData(rw.dirtyFiles) == ["[tree] inner"]
    qlvClickNthRow(rw.dirtyFiles, 0)
    triggerContextMenuAction(rw.dirtyFiles.viewport(), "delete")
    acceptQMessageBox(rw, "really delete.+inner")

    assert not os.path.exists(innerWd)
    assert rw.repo.status() == {}


@pytest.mark.parametrize("method", ["key", "menu", "button"])
def testUnstageChangeInEmptyRepo(tempDir, mainWindow, method, gitBackend):
    wd = unpackRepo(tempDir, "TestEmptyRepository")
    reposcenario.stagedNewEmptyFile(wd)
    rw = mainWindow.openRepo(wd)

    assert qlvGetRowData(rw.dirtyFiles) == []
    assert qlvGetRowData(rw.stagedFiles) == ["SomeNewFile.txt"]
    qlvClickNthRow(rw.stagedFiles, 0)

    doUnstage(rw, method)

    assert qlvGetRowData(rw.dirtyFiles) == ["SomeNewFile.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []

    assert rw.repo.status() == {"SomeNewFile.txt": FileStatus.WT_NEW}


def testStagingBlockedBySafeCrlf(tempDir, mainWindow, gitBackend):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.config["core.autocrlf"] = "input"
        repo.config["core.safecrlf"] = True
    writeFile(f"{wd}/hello0.txt", "hello\r\ndos\r\n")
    writeFile(f"{wd}/hello1.txt", "hello\nunix\n")

    rw = mainWindow.openRepo(wd)
    rw.dirtyFiles.selectAll()
    rw.diffArea.stageButton.click()

    if gitBackend == "libgit2":
        # Note: Two lookups for a single qmb here because we're looking for parts of the message in different QLabels.
        findQMessageBox(rw, "hello0.+contains CRLF.+will not be replaced by LF.+safecrlf")
        acceptQMessageBox(rw, "stage files.+ran into an issue with 1 file.+1 other file was successful")
        assert rw.repo.status() == {'hello1.txt': FileStatus.INDEX_NEW, 'hello0.txt': FileStatus.WT_NEW}
    else:
        acceptQMessageBox(rw, "CRLF would be replaced by LF")
        # With vanilla git, the add operation is atomic, so nothing should be staged
        assert rw.repo.status() == {'hello0.txt': FileStatus.WT_NEW, 'hello1.txt': FileStatus.WT_NEW}


def testStagingBlockedByConflicts(tempDir, mainWindow, gitBackend):
    wd = unpackRepo(tempDir)
    reposcenario.statelessConflictingChange(wd)

    rw = mainWindow.openRepo(wd)
    rw.dirtyFiles.selectAll()
    rw.diffArea.stageButton.click()
    rejectQMessageBox(rw, "you have selected an unresolved merge conflict")

    writeFile(f"{wd}/hello.txt", "hello")
    rw.refreshRepo()
    rw.dirtyFiles.selectAll()
    rw.diffArea.discardButton.click()
    rejectQMessageBox(rw, "there is an unresolved merge conflict among your selection")
