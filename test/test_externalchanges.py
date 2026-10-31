# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.diffview.diffdocument import DiffDocument
from gitfourchette.nav import NavLocator
from .util import *


def testExternalUnstage(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/master.txt", "same old file -- brand new contents!\n")

    rw = mainWindow.openRepo(wd)

    rw.dirtyFiles.setFocus()
    waitUntilTrue(rw.dirtyFiles.hasFocus)

    # Stage master.txt
    assert (qlvGetRowData(rw.dirtyFiles), qlvGetRowData(rw.stagedFiles)) == (["master.txt"], [])
    qlvClickNthRow(rw.dirtyFiles, 0)
    QTest.keyPress(rw.dirtyFiles, Qt.Key.Key_Return)
    assert (qlvGetRowData(rw.dirtyFiles), qlvGetRowData(rw.stagedFiles)) == ([], ["master.txt"])

    # Unstage master.txt outside of GF
    shell("git restore --staged master.txt", wd)

    rw.refreshRepo()
    assert (qlvGetRowData(rw.dirtyFiles), qlvGetRowData(rw.stagedFiles)) == (["master.txt"], [])


@pytest.mark.parametrize("branchName,hidePattern", [("master2", "refs/heads/master2"), ("group/master2", "refs/heads/group/")])
@pytest.mark.parametrize("closeAndReopen", [True, False])
def testHiddenBranchGotDeleted(tempDir, mainWindow, closeAndReopen, branchName, hidePattern):
    wd = unpackRepo(tempDir)
    shell(f"git branch {branchName}", wd)

    rw = mainWindow.openRepo(wd)
    rw.toggleHideRefPattern(hidePattern)
    rw.repoModel.prefs.write(force=True)

    shell(f"git branch -d {branchName}", wd)

    # Reopening or refreshing the repo must not crash after the branch is deleted
    if closeAndReopen:
        mainWindow.openRepo(wd)
    else:
        mainWindow.currentRepoWidget().refreshRepo()


def testStayOnFileAfterPartialPatchDespiteExternalChange(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    writeFile(f"{wd}/a/a2.txt", "change a\nchange b\nchange c\n")
    writeFile(f"{wd}/b/b2.txt", "change a\nchange b\nchange c\n")
    writeFile(f"{wd}/c/c1.txt", "change a\nchange b\nchange c\n")

    rw = mainWindow.openRepo(wd)

    assert qlvGetRowData(rw.dirtyFiles) == ["a/a2.txt", "b/b2.txt", "c/c1.txt"]

    # Create a new change to a file that comes before b2.txt alphabetically
    writeFile(f"{wd}/a/a1.txt", "change a\nchange b\nchange c\n")

    # Stage a single line
    qlvClickNthRow(rw.dirtyFiles, 1)
    rw.diffView.setFocus()
    waitUntilTrue(rw.diffView.hasFocus)
    qteClickBlock(rw.diffView, 1)
    QTest.keyPress(rw.diffView, Qt.Key.Key_Return)

    # This was a partial patch, so b2 is both dirty and staged;
    # also, a1 should appear among the dirty files now
    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt", "a/a2.txt", "b/b2.txt", "c/c1.txt"]
    assert qlvGetRowData(rw.stagedFiles) == ["b/b2.txt"]

    # Ensure we're still selecting b2.txt despite a1.txt appearing before us in the list
    assert qlvGetSelection(rw.dirtyFiles) == ["b/b2.txt"]


@pytest.mark.parametrize("scenario", [0, 1, 2])
def testPatchBecameInvalid(tempDir, mainWindow, scenario):
    wd = unpackRepo(tempDir)

    relPath = "b/b2.txt"
    absPath = f"{wd}/{relPath}"

    oldText = "change a\nchange b\nchange c\n"
    newText = "surprise!"

    writeFile(f"{wd}/a/a2.txt", "\x00Binary")
    writeFile(absPath, oldText)

    timestamp = TEST_SIGNATURE.time
    os.utime(absPath, (timestamp, timestamp))

    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inUnstaged(relPath), check=True)
    assert oldText.strip() in rw.diffView.toPlainText()

    if scenario == 0:
        # Different timestamp, different size
        writeFile(absPath, newText)
    elif scenario == 1:
        # SAME timestamp, different size
        writeFile(absPath, newText)
        os.utime(absPath, (timestamp, timestamp))
    elif scenario == 2:
        # Different timestamp, SAME size
        padChars = len(oldText) - len(newText)
        assert padChars > 0
        writeFile(absPath, newText + ("x" * padChars))
    else:
        raise NotImplementedError()

    # Select something else, won't clear the DiffView because it's a binary file
    rw.jump(NavLocator.inUnstaged("a/a2.txt"), check=True)
    assert not rw.diffView.isVisible()  # should be showing a SpecialDiff for "binary file"
    assert oldText.strip() in rw.diffView.toPlainText()  # DiffView retains the old patch

    # Back to b2.txt
    rw.jump(NavLocator.inUnstaged(relPath), check=True)
    assert newText.strip() in rw.diffView.toPlainText()


def testUnstagedFileChangedBetweenGitDiffAndLexJob(monkeypatch, tempDir, mainWindow):
    smallText = "goedendag = 0"
    largeText = "\n".join(f"hello = {i}" for i in range(25))

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    # Race condition scenario:
    # 1. RefreshRepo detects a change in hello.py and calls LoadPatch.
    #    The GitDelta for hello.py doesn't contain a valid hash yet.
    # 2. LoadPatch calls "git diff", which creates a patch with largeText.
    #    The preamble in this patch contains the hash for largeText.
    #    hello.py's GitDelta is filled in with this hash.
    # 3. RACE: As LoadPatch prepares DiffDocument for rendering, an external
    #    program overwrites hello.py with smallText.
    # 4. LoadPatch primes the lexer, which needs to read the raw file from disk
    #    (can't lex the patch itself). The file now contains smallText, so we
    #    should detect that the hash in GitDelta is stale.

    writeFile(f"{wd}/hello.py", largeText)

    with monkeypatch.context() as m:
        # To simulate this race condition deterministically, write smallText just
        # before LoadPatch builds DiffDocument from git diff's output.
        injectFunctionPrefix(m, DiffDocument, "fromPatch",
                             lambda: writeFile(f"{wd}/hello.py", smallText))

        # Trigger the scenario.
        rw.refreshRepo()

    assert findTextInWidget(rw.specialDiffView, "file was modified while we were reading")

    qteClickLink(rw.specialDiffView, "try to reload")
    assert rw.diffView.isVisible()
    assert findTextInWidget(rw.diffView, "goedendag")


def testExternalChangeWhileTaskIsBusyThenAborts(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    rw = mainWindow.openRepo(wd)

    rw.diffArea.commitButton.click()
    assert findQMessageBox(rw, r"empty commit")

    writeFile(f"{wd}/sneaky.txt", "tee hee")

    # needed for onRegainForeground
    waitUntilTrue(lambda: QGuiApplication.applicationState() == Qt.ApplicationState.ApplicationActive)

    mainWindow.onRegainForeground()
    rejectQMessageBox(rw, r"empty commit")

    # Even though the task aborts, the repo should auto-refresh
    assert qlvGetRowData(rw.dirtyFiles) == ["sneaky.txt"]


def testLineEndingsChangedWithAutocrlfInput(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git config core.autocrlf input", wd)

    writeFile(f"{wd}/hello.txt", "hello\r\ndos\r\n")
    rw = mainWindow.openRepo(wd)
    assert "hello\ndos" in rw.diffView.toPlainText()

    writeFile(f"{wd}/hello.txt", "hello\ndos\n")
    rw.refreshRepo()  # Must not fail (no failed assertions, etc)
    assert "hello\ndos" in rw.diffView.toPlainText()


def testStableDeltasAfterLineEndingsChangedWithAutocrlfInput(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git config core.autocrlf input", wd)

    # Convert these files to CRLF
    crlfFiles = ["a/a1.txt", "a/a2.txt", "b/b1.txt", "b/b2.txt"]
    for filePath in crlfFiles:
        contents = readFile(f"{wd}/{filePath}")
        contents = contents.replace(b'\n', b'\r\n')
        writeFile(f"{wd}/{filePath}", contents.decode('utf-8'))

    rw = mainWindow.openRepo(wd)

    assert rw.repo.status() == dict.fromkeys(crlfFiles, FileStatus.WT_MODIFIED)

    # Look at each file 3 times.
    # There seems to be a bug in libgit2 where patch.delta is unstable (returning erroneous
    # status, or returning no delta altogether) if the patch has been re-generated several times from
    # the same diff while a CRLF filter applies. To work around this, we should cache the patch.
    # (Note: this doesn't apply to vanilla git diffs anymore - but it doesn't hurt to keep the loop as-is)
    for _i in range(3):
        for filePath in crlfFiles:
            rw.jump(NavLocator.inUnstaged(filePath), check=True)
            assert rw.specialDiffView.isVisible()
            assert "crlf will be replaced by lf" in rw.specialDiffView.toPlainText().lower()

    # Stage them to dismiss the messages
    for filePath in crlfFiles:
        rw.jump(NavLocator.inUnstaged(filePath), check=True)
        rw.diffArea.stageButton.click()

    assert rw.repo.status() == {}
