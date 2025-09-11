# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

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
    with RepoContext(wd, write_index=True) as repo2:
        patch = repo2.get_staged_changes()[0]
        assert "master.txt" in patch.text
        repo2.unstage_files([patch])

    rw.refreshRepo()
    assert (qlvGetRowData(rw.dirtyFiles), qlvGetRowData(rw.stagedFiles)) == (["master.txt"], [])


@pytest.mark.parametrize("branchName,hidePattern", [("master2", "refs/heads/master2"), ("group/master2", "refs/heads/group/")])
@pytest.mark.parametrize("closeAndReopen", [True, False])
def testHiddenBranchGotDeleted(tempDir, mainWindow, closeAndReopen, branchName, hidePattern):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo2:
        repo2.create_branch_on_head(branchName)

    rw = mainWindow.openRepo(wd)
    rw.toggleHideRefPattern(hidePattern)
    rw.repoModel.prefs.write(force=True)

    with RepoContext(wd) as repo2:
        repo2.delete_local_branch(branchName)

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


@pytest.mark.skipif(WINDOWS, reason="TODO: Windows clings to a file handle")
def testPatchBecameInvalid(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    writeFile(f"{wd}/a/a2.txt", "change a\nchange b\nchange c\n")
    writeFile(f"{wd}/b/b2.txt", "change a\nchange b\nchange c\n")

    rw = mainWindow.openRepo(wd)

    assert qlvGetRowData(rw.dirtyFiles) == ["a/a2.txt", "b/b2.txt"]

    qlvClickNthRow(rw.dirtyFiles, 1)  # Select b/b2.txt
    writeFile(f"{wd}/b/b2.txt", "pulled the rug out from under the cached patch")
    qlvClickNthRow(rw.dirtyFiles, 0)  # Select something else
    qlvClickNthRow(rw.dirtyFiles, 1)  # Select b/b2.txt

    assert not rw.diffView.isVisibleTo(rw)
    assert rw.specialDiffView.isVisibleTo(rw)
    doc = rw.specialDiffView.document()
    text = doc.toRawText()
    assert "changed on disk" in text.lower()

    qteClickLink(rw.specialDiffView, "try to reload the file")
    assert rw.diffView.isVisibleTo(rw)
    assert not rw.specialDiffView.isVisibleTo(rw)


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


def testLineEndingsChangedWithAutocrlfInputCauseDiffReload(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.config["core.autocrlf"] = "input"

    writeFile(f"{wd}/hello.txt", "hello\r\ndos\r\n")
    rw = mainWindow.openRepo(wd)
    oldPatch = rw.diffView.currentPatch

    writeFile(f"{wd}/hello.txt", "hello\ndos\n")
    rw.refreshRepo()  # Must not fail (no failed assertions, etc)
    assert oldPatch is not rw.diffView.currentPatch


@pytest.mark.skipif(pygit2OlderThan("1.18.3"), reason="old pygit2 - https://github.com/libgit2/pygit2/pull/1412")
def testStableDeltasAfterLineEndingsChangedWithAutocrlfInput(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    # Convert these files to CRLF
    crlfFiles = [ "a/a1.txt", "a/a2.txt", "b/b1.txt", "b/b2.txt" ]
    for filePath in crlfFiles:
        contents = readFile(f"{wd}/{filePath}")
        contents = contents.replace(b'\n', b'\r\n')
        writeFile(f"{wd}/{filePath}", contents.decode('utf-8'))

    with RepoContext(wd) as repo:
        repo.config["core.autocrlf"] = "input"

    rw = mainWindow.openRepo(wd)

    assert rw.repo.status() == dict.fromkeys(crlfFiles, FileStatus.WT_MODIFIED)

    # Look at each file 3 times.
    # There seems to be a bug in libgit2 where patch.delta is unstable (returning erroneous
    # status, or returning no delta altogether) if the patch has been re-generated several times from
    # the same diff while a CRLF filter applies. To work around this, we should cache the patch.
    for _i in range(3):
        for filePath in crlfFiles:
            rw.jump(NavLocator.inUnstaged(filePath), check=True)
            assert rw.specialDiffView.isVisible()
            assert "canonical file contents unchanged" in rw.specialDiffView.toPlainText().lower()

    # Stage them to dismiss the messages
    for filePath in crlfFiles:
        rw.jump(NavLocator.inUnstaged(filePath), check=True)
        rw.diffArea.stageButton.click()

    assert rw.repo.status() == {}
