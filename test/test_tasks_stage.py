# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os.path
import pytest

from .util import *
from . import reposcenario


def doStage(rw, method):
    if method == "key":
        rw.dirtyFiles.setFocus()
        QTest.keyPress(rw.dirtyFiles, Qt.Key.Key_Return)
    elif method == "menu":
        triggerContextMenuAction(rw.dirtyFiles.viewport(), "stage")
    elif method == "button":
        rw.diffArea.stageButton.click()
    else:
        raise NotImplementedError("unknown method")


def doDiscard(rw, method):
    if method == "key":
        rw.dirtyFiles.setFocus()
        QTest.keyPress(rw.dirtyFiles, Qt.Key.Key_Delete)
    elif method == "menu":
        triggerContextMenuAction(rw.dirtyFiles.viewport(), "(discard|delete)")
    elif method == "button":
        rw.diffArea.discardButton.click()
    else:
        raise NotImplementedError("unknown method")


def doUnstage(rw, method):
    if method == "key":
        rw.stagedFiles.setFocus()
        QTest.keyPress(rw.stagedFiles, Qt.Key.Key_Delete)
    elif method == "menu":
        triggerContextMenuAction(rw.stagedFiles.viewport(), "unstage")
    elif method == "button":
        rw.diffArea.unstageButton.click()
    else:
        raise NotImplementedError("unknown method")


@pytest.mark.parametrize("method", ["key", "menu", "button"])
def testStageEmptyUntrackedFile(tempDir, mainWindow, method):
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
def testDiscardUntrackedFile(tempDir, mainWindow, method):
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
def testDiscardFileModificationWithoutAffectingStagedChange(tempDir, mainWindow, method):
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


@requiresFileModes
def testDiscardModeChange(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    shell("""
        echo 'keep this!' > a/a1.txt
        chmod 777 a/a1.txt
    """, wd)

    rw = mainWindow.openRepo(wd)
    assert qlvGetRowData(rw.dirtyFiles) == ["[+x] a/a1.txt"]
    qlvClickNthRow(rw.dirtyFiles, 0)
    triggerContextMenuAction(rw.dirtyFiles.viewport(), "revert mode")
    acceptQMessageBox(rw, "(restore|revert|discard) mode")

    assert readTextFile(f"{wd}/a/a1.txt").strip() == "keep this!"
    assert not fileHasUserExecutableBit(f"{wd}/a/a1.txt")


@requiresFileModes
def testUnstageModeChange(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    shell("""
        echo 'keep this!' > a/a1.txt
        chmod 777 a/a1.txt
        git add a/a1.txt
    """, wd)

    rw = mainWindow.openRepo(wd)
    assert rw.repo.index["a/a1.txt"].mode == FileMode.BLOB_EXECUTABLE
    assert qlvGetRowData(rw.stagedFiles) == ["[+x] a/a1.txt"]

    qlvClickNthRow(rw.stagedFiles, 0)
    triggerContextMenuAction(rw.stagedFiles.viewport(), "revert mode")
    assert rw.repo.index["a/a1.txt"].mode == FileMode.BLOB


def testDiscardUntrackedTree(tempDir, mainWindow):
    outerWd = unpackRepo(tempDir, renameTo="outer")
    innerWd = unpackRepo(tempDir, renameTo="inner")
    innerWd = shutil.move(innerWd, outerWd)

    rw = mainWindow.openRepo(outerWd)
    assert rw.repo.status() == {"inner/": FileStatus.WT_NEW}

    assert os.path.exists(innerWd)
    assert qlvGetRowData(rw.dirtyFiles) == ["[new subtree] inner"]
    qlvClickNthRow(rw.dirtyFiles, 0)
    triggerContextMenuAction(rw.dirtyFiles.viewport(), "delete")
    acceptQMessageBox(rw, "really delete.+inner")

    assert not os.path.exists(innerWd)
    assert rw.repo.status() == {}


@pytest.mark.skipif(WINDOWS or os.geteuid() == 0, reason="needs symlinks without special privileges, and a non-root user")
def testDiscardUntrackedTreeKeepsSymlinkTargetPermissions(tempDir, monkeypatch):
    # The read-only workaround must not chmod a file outside the tree through a symlink
    from gitfourchette.tasks import indextasks
    monkeypatch.setattr(indextasks, "WINDOWS", True)

    outside = Path(tempDir.name, "outside.txt")
    outside.write_text("hello")
    outside.chmod(0o644)

    readOnlyDir = Path(tempDir.name, "tree", "ro")
    readOnlyDir.mkdir(parents=True)
    (readOnlyDir / "link").symlink_to(outside)
    readOnlyDir.chmod(0o555)

    try:
        with pytest.raises(PermissionError):
            shutil.rmtree(readOnlyDir.parent, onexc=indextasks._removeReadOnly)
    finally:
        readOnlyDir.chmod(0o755)

    assert outside.stat().st_mode & 0o777 == 0o644


def testDiscardUntrackedTreeKeepsOtherErrors(tempDir, monkeypatch):
    # On Windows, the read-only workaround must only handle "access denied"
    from gitfourchette.tasks import indextasks
    monkeypatch.setattr(indextasks, "WINDOWS", True)

    path = Path(tempDir.name, "file.txt")
    path.write_text("hello")
    error = OSError("some other problem")

    with pytest.raises(OSError, match="some other problem"):
        indextasks._removeReadOnly(os.unlink, str(path), error)

    assert path.exists()


@pytest.mark.parametrize("method", ["key", "menu", "button"])
def testUnstageChangeInEmptyRepo(tempDir, mainWindow, method):
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


def testStagingBlockedBySafeCrlf(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.config["core.autocrlf"] = "input"
        repo.config["core.safecrlf"] = True
    writeFile(f"{wd}/hello0.txt", "hello\r\ndos\r\n")
    writeFile(f"{wd}/hello1.txt", "hello\nunix\n")

    rw = mainWindow.openRepo(wd)
    rw.dirtyFiles.selectAll()
    rw.diffArea.stageButton.click()

    # if gitBackend == "libgit2":
    #     # Note: Two lookups for a single qmb here because we're looking for parts of the message in different QLabels.
    #     findQMessageBox(rw, "hello0.+contains CRLF.+will not be replaced by LF.+safecrlf")
    #     acceptQMessageBox(rw, "stage files.+ran into an issue with 1 file.+1 other file was successful")
    #     assert rw.repo.status() == {'hello1.txt': FileStatus.INDEX_NEW, 'hello0.txt': FileStatus.WT_NEW}

    acceptQMessageBox(rw, "CRLF would be replaced by LF")
    # With vanilla git, the add operation is atomic, so nothing should be staged
    assert rw.repo.status() == {'hello0.txt': FileStatus.WT_NEW, 'hello1.txt': FileStatus.WT_NEW}


def testStagingBlockedByConflicts(tempDir, mainWindow):
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


@pytest.mark.parametrize("action", ["stage", "unstage", "discard", "discardUntracked"])
def testBracketsInFileNameMatchOnlyThatFile(tempDir, mainWindow, action):
    # As a glob, "a[1].txt" would also match "a1.txt"
    wd = unpackRepo(tempDir)
    names = ["a1.txt", "a[1].txt"]
    for name in names:
        writeFile(f"{wd}/{name}", "original\n")
    if action != "discardUntracked":
        shell("git add -A && git commit -qm brackets", wd)
        for name in names:
            writeFile(f"{wd}/{name}", "changed\n")
    if action == "unstage":
        shell("git add -A", wd)

    rw = mainWindow.openRepo(wd)
    fileList = rw.stagedFiles if action == "unstage" else rw.dirtyFiles
    assert qlvGetRowData(fileList) == names
    qlvClickNthRow(fileList, 1)

    if action == "stage":
        doStage(rw, "button")
        expected = {"a1.txt": FileStatus.WT_MODIFIED, "a[1].txt": FileStatus.INDEX_MODIFIED}
    elif action == "unstage":
        doUnstage(rw, "button")
        expected = {"a1.txt": FileStatus.INDEX_MODIFIED, "a[1].txt": FileStatus.WT_MODIFIED}
    elif action == "discard":
        doDiscard(rw, "button")
        acceptQMessageBox(rw, "really discard")
        expected = {"a1.txt": FileStatus.WT_MODIFIED}
    else:
        doDiscard(rw, "button")
        acceptQMessageBox(rw, "really delete")
        expected = {"a1.txt": FileStatus.WT_NEW}

    assert rw.repo.status() == expected


def testStageWithLiteralPathspecsEnv(tempDir, mainWindow, monkeypatch):
    # With GIT_LITERAL_PATHSPECS=1, git would read ":(literal)" as part of the file name
    monkeypatch.setenv("GIT_LITERAL_PATHSPECS", "1")
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/a1.txt", "new\n")
    writeFile(f"{wd}/a[1].txt", "new\n")
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 1)
    doStage(rw, "button")
    assert rw.repo.status() == {"a1.txt": FileStatus.WT_NEW, "a[1].txt": FileStatus.INDEX_NEW}


def testHookCanUseGlobPathspecs(tempDir, mainWindow):
    # Hooks inherit GIT_LITERAL_PATHSPECS from git. GitDriver passes ":(literal)" per path
    # instead of --literal-pathspecs, so "*.txt" still matches in hooks.
    wd = unpackRepo(tempDir)

    # printf, not writeFile: on Windows, writeFile would give the hook CRLF line endings
    shell("""
        printf '#!/usr/bin/env bash\\ngit diff --cached --name-only -- "*.txt" > .git/hook-ran\\n' > .git/hooks/post-index-change
        chmod +x .git/hooks/post-index-change
        echo whatever >> master.txt
    """, wd)

    rw = mainWindow.openRepo(wd)
    qlvClickNthRow(rw.dirtyFiles, 0)
    doStage(rw, "button")

    assert "master.txt" == readTextFile(f"{wd}/.git/hook-ran").strip()
