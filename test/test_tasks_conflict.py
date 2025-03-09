# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.nav import NavLocator
from . import reposcenario
from .util import *
from gitfourchette.porcelain import *


@pytest.mark.parametrize("viaContextMenu", [False, True])
def testConflictDeletedByUs(tempDir, mainWindow, viaContextMenu):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        # Prepare "their" modification (modify a1.txt and a2.txt)
        writeFile(f"{wd}/a/a1.txt", "they modified")
        writeFile(f"{wd}/a/a2.txt", "they modified")
        repo.index.add_all(["a/a1.txt", "a/a2.txt"])
        oid = repo.create_commit_on_head("they modified 2 files", TEST_SIGNATURE, TEST_SIGNATURE)

        # Switch to no-parent (it has no a1.txt and a2.txt) and merge "their" modification
        assert not repo.any_conflicts
        repo.checkout_local_branch("no-parent")
        repo.cherrypick(oid)
        assert repo.any_conflicts
        assert "a/a1.txt" in repo.index.conflicts
        assert "a/a2.txt" in repo.index.conflicts

    rw = mainWindow.openRepo(wd)

    # -------------------------
    # Keep our deletion of a1.txt

    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt", "a/a2.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []
    rw.jump(NavLocator.inUnstaged("a/a1.txt"))
    assert rw.conflictView.currentConflict.deleted_by_us
    assert rw.conflictView.ui.oursButton.isVisible()
    assert not rw.conflictView.ui.mergeToolButton.isVisible()
    assert "deleted by us" in rw.conflictView.ui.explainer.text().lower()

    if not viaContextMenu:
        rw.conflictView.ui.oursButton.click()
    else:
        menu = rw.dirtyFiles.makeContextMenu()
        triggerMenuAction(menu, "resolve by.+ours")

    # -------------------------
    # Take their a2.txt

    assert qlvGetRowData(rw.dirtyFiles) == ["a/a2.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []
    rw.jump(NavLocator.inUnstaged("a/a2.txt"))
    assert rw.conflictView.currentConflict.deleted_by_us
    assert rw.conflictView.ui.theirsButton.isVisible()
    assert not rw.conflictView.ui.mergeToolButton.isVisible()

    if not viaContextMenu:
        rw.conflictView.ui.theirsButton.click()
    else:
        menu = rw.dirtyFiles.makeContextMenu()
        triggerMenuAction(menu, "resolve by.+theirs")

    assert not rw.repo.index.conflicts
    assert not rw.conflictView.isVisible()
    assert rw.repo.status() == {"a/a2.txt": FileStatus.INDEX_NEW}


@pytest.mark.parametrize("viaContextMenu", [False, True])
def testConflictDeletedByThem(tempDir, mainWindow, viaContextMenu):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        # Prepare "their" modification (delete a1.txt and a2.txt)
        repo.index.remove_all(["a/a1.txt", "a/a2.txt"])
        oid = repo.create_commit_on_head("they deleted 2 files", TEST_SIGNATURE, TEST_SIGNATURE)

        repo.checkout_local_branch("no-parent")

        writeFile(f"{wd}/a/a1.txt", "we modified")
        writeFile(f"{wd}/a/a2.txt", "we modified")
        repo.index.add_all(["a/a1.txt", "a/a2.txt"])
        repo.create_commit_on_head("we touched 2 files", TEST_SIGNATURE, TEST_SIGNATURE)

        assert not repo.any_conflicts
        repo.cherrypick(oid)
        assert repo.any_conflicts
        assert "a/a1.txt" in repo.index.conflicts
        assert "a/a2.txt" in repo.index.conflicts

    rw = mainWindow.openRepo(wd)

    # -------------------------
    # Keep our a1.txt

    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt", "a/a2.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []
    rw.jump(NavLocator.inUnstaged("a/a1.txt"))
    assert rw.conflictView.currentConflict.deleted_by_them
    assert rw.conflictView.ui.oursButton.isVisible()
    assert not rw.conflictView.ui.mergeToolButton.isVisible()
    assert "deleted by them" in rw.conflictView.ui.explainer.text().lower()

    if not viaContextMenu:
        rw.conflictView.ui.oursButton.click()
    else:
        triggerMenuAction(rw.dirtyFiles.makeContextMenu(), "resolve by.+ours")

    # -------------------------
    # Take their deletion of a2.txt

    assert qlvGetRowData(rw.dirtyFiles) == ["a/a2.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []
    rw.jump(NavLocator.inUnstaged("a/a2.txt"))
    assert rw.conflictView.currentConflict.deleted_by_them
    assert rw.conflictView.ui.theirsButton.isVisible()
    assert not rw.conflictView.ui.mergeToolButton.isVisible()
    if not viaContextMenu:
        rw.conflictView.ui.theirsButton.click()
    else:
        triggerMenuAction(rw.dirtyFiles.makeContextMenu(), "resolve by.+theirs")

    assert not rw.repo.index.conflicts
    assert not rw.conflictView.isVisible()
    assert rw.repo.status() == {"a/a2.txt": FileStatus.INDEX_DELETED}


def testConflictDoesntPreventManipulatingIndexOnOtherFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        # Prepare "their" modification (modify a1.txt)
        writeFile(f"{wd}/a/a1.txt", "they modified")
        repo.index.add_all(["a/a1.txt"])
        oid = repo.create_commit_on_head("they modified a1.txt", TEST_SIGNATURE, TEST_SIGNATURE)

        # Switch to no-parent (it has no a1.txt) and merge "their" modification to cause a conflict on a1.txt
        assert not repo.any_conflicts
        repo.checkout_local_branch("no-parent")
        repo.cherrypick(oid)
        assert "a/a1.txt" in repo.index.conflicts

    rw = mainWindow.openRepo(wd)

    # Modify some other file with both staged and unstaged changes
    writeFile(f"{wd}/b/b1.txt", "b1\nb1\nstaged change\n")
    rw.refreshRepo()
    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt", "b/b1.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []
    qlvClickNthRow(rw.dirtyFiles, 1)
    QTest.keyPress(rw.dirtyFiles, Qt.Key.Key_Return)
    assert qlvGetRowData(rw.stagedFiles) == ["b/b1.txt"]

    writeFile(f"{wd}/b/b1.txt", "b1\nb1\nunstaged change\nstaged change\n")
    rw.refreshRepo()
    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt", "b/b1.txt"]
    qlvClickNthRow(rw.dirtyFiles, 1)
    QTest.keyPress(rw.dirtyFiles, Qt.Key.Key_Delete)
    acceptQMessageBox(rw, r"really discard changes.+b1\.txt")

    assert readFile(f"{wd}/b/b1.txt").decode() == "b1\nb1\nstaged change\n"


def testShowConflictInBannerEvenIfNotViewingWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")))

    # Cause a conflict outside the app
    with RepoContext(wd) as repo:
        oid = Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17")
        assert not repo.any_conflicts
        repo.cherrypick(oid)
        assert "c/c2.txt" in repo.index.conflicts

    rw.refreshRepo()
    assert rw.mergeBanner.isVisible()
    assert "conflicts need fixing" in rw.mergeBanner.label.text().lower()


def testResetIndexWithConflicts(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.statelessConflictingChange(wd)

    rw = mainWindow.openRepo(wd)
    assert rw.repo.any_conflicts
    assert rw.mergeBanner.isVisible()
    assert "fix the conflicts" in rw.mergeBanner.label.text().lower()
    assert "reset index" in rw.mergeBanner.buttons[-1].text().lower()

    # Now reset the index
    rw.mergeBanner.buttons[-1].click()
    acceptQMessageBox(rw, "reset the index")
    assert not rw.repo.any_conflicts
    assert not rw.mergeBanner.isVisible()


@pytest.mark.skipif(WINDOWS, reason="TODO: no editor shim for Windows yet!")
def testMergeTool(tempDir, mainWindow):
    noopMergeToolPath = getTestDataPath("editor-shim.py")
    mergeToolPath = getTestDataPath("merge-shim.py")
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"

    wd = unpackRepo(tempDir, "testrepoformerging")
    rw = mainWindow.openRepo(wd)
    conflictUI = rw.conflictView.ui

    # Initiate merge of branch-conflicts into master
    node = rw.sidebar.findNodeByRef("refs/heads/branch-conflicts")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "merge into.+master")
    acceptQMessageBox(rw, "branch-conflicts.+into.+master.+may cause conflicts")
    rw.jump(NavLocator.inUnstaged(".gitignore"))
    assert rw.repo.index.conflicts
    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged(".gitignore"))
    assert rw.conflictView.isVisible()

    # ------------------------------
    # Try merging with a tool that doesn't touch the output file

    mainWindow.onAcceptPrefsDialog({"externalMerge": f'"{noopMergeToolPath}" "{scratchPath}" $M $L $R $B'})

    assert "editor-shim" in conflictUI.mergeButton.text()
    assert conflictUI.mergeButton.isVisible()
    conflictUI.mergeButton.click()

    scratchLines = readFile(scratchPath, timeout=1000, unlink=True).decode("utf-8").strip().splitlines()
    assert "[MERGED]" in scratchLines[0]
    assert "[OURS]" in scratchLines[1]
    assert "[THEIRS]" in scratchLines[2]

    waitUntilTrue(lambda: conflictUI.mergeToolStatus.isVisible())
    waitUntilTrue(lambda: re.search("didn.t complete", conflictUI.mergeToolStatus.text(), re.I))

    rw.conflictView.cancelMergeInProgress()

    # ------------------------------
    # Try merging with a missing command

    mainWindow.onAcceptPrefsDialog({"externalMerge": f'"{noopMergeToolPath}-BOGUSCOMMAND" "{scratchPath}" $M $L $R $B'})
    assert "editor-shim" in conflictUI.mergeButton.text()
    conflictUI.mergeButton.click()

    notInstalledMessage = waitForQMessageBox(rw, "not.+installed on your machine")
    notInstalledMessage.reject()

    rw.conflictView.cancelMergeInProgress()

    # ------------------------------
    # Try merging with a tool that errors out (e.g. locked file)

    writeFile(scratchPath, "oops, file locked!")
    os.chmod(scratchPath, 0o400)

    mainWindow.onAcceptPrefsDialog({"externalMerge": f'"{mergeToolPath}" "{scratchPath}" $M $L $R $B CookieFoo'})
    assert "merge-shim" in conflictUI.mergeButton.text()
    assert "exit code" not in conflictUI.mergeToolStatus.text().lower()
    conflictUI.mergeButton.click()

    waitUntilTrue(lambda: "exit code" in conflictUI.mergeToolStatus.text().lower())
    os.unlink(scratchPath)

    rw.conflictView.cancelMergeInProgress()

    # ------------------------------
    # Now try merging with a good tool

    mainWindow.onAcceptPrefsDialog({"externalMerge": f'"{mergeToolPath}" "{scratchPath}" $M $L $R $B CookieBar'})
    assert "merge-shim" in conflictUI.mergeButton.text()
    conflictUI.mergeButton.click()

    assert conflictUI.stackedWidget.currentWidget() is conflictUI.mergeInProgressPage

    scratchText = readFile(scratchPath, timeout=1000, unlink=True).decode("utf-8").strip()
    scratchLines = scratchText.strip().splitlines()

    mergedPath = scratchLines[0]
    oursPath = scratchLines[1]
    theirsPath = scratchLines[2]

    assert "[MERGED]" in mergedPath
    assert "[OURS]" in oursPath
    assert "[THEIRS]" in theirsPath
    assert "CookieBar" == scratchLines[-1]
    assert "merge complete!" == readFile(mergedPath, timeout=1000).decode("utf-8").strip()

    waitUntilTrue(lambda: conflictUI.stackedWidget.currentWidget() is conflictUI.mergeCompletePage)

    # ------------------------------
    # Hit "Merge Again"

    assert not os.path.exists(scratchPath)  # should have been unlinked above

    conflictUI.reworkMergeButton.click()
    assert conflictUI.stackedWidget.currentWidget() is conflictUI.mergeInProgressPage

    scratchText = readFile(scratchPath, timeout=1000, unlink=True).decode("utf-8")
    scratchLines = scratchText.strip().splitlines()

    # Make sure the same command was run
    assert scratchLines[0] == mergedPath
    assert scratchLines[1] == oursPath
    assert scratchLines[2] == theirsPath
    assert "merge complete!" == readFile(mergedPath, timeout=1000).decode("utf-8").strip()

    # ------------------------------
    # Accept merge resolution

    waitUntilTrue(lambda: conflictUI.stackedWidget.currentWidget() is conflictUI.mergeCompletePage)
    conflictUI.confirmMergeButton.click()
    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inStaged(".gitignore"))

    assert rw.mergeBanner.isVisible()
    assert "all conflicts fixed" in rw.mergeBanner.label.text().lower()
    assert not rw.repo.index.conflicts


@pytest.mark.skipif(WINDOWS, reason="TODO: no editor shim for Windows yet!")
def testFake3WayMerge(tempDir, mainWindow):
    mergeToolPath = getTestDataPath("merge-shim.py")
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"

    wd = unpackRepo(tempDir, "testrepoformerging")

    with RepoContext(wd) as repo:
        repo.checkout_local_branch("i18n")

    rw = mainWindow.openRepo(wd)
    conflictUI = rw.conflictView.ui

    # Initiate merge of branch-conflicts into master
    node = rw.sidebar.findNodeByRef("refs/heads/pep8-fixes")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "merge into.+i18n")
    acceptQMessageBox(rw, "pep8-fixes.+into.+i18n.+may cause conflicts")
    rw.jump(NavLocator.inUnstaged("bye.txt"))
    assert rw.repo.index.conflicts
    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged("bye.txt"))
    assert conflictUI.mergePage.isVisible()

    mainWindow.onAcceptPrefsDialog({"externalMerge": f'"{mergeToolPath}" "{scratchPath}" $M $L $R $B'})
    assert "merge-shim" in conflictUI.mergeButton.text()
    conflictUI.mergeButton.click()

    scratchText = readFile(scratchPath, timeout=1000, unlink=True).decode("utf-8")
    scratchLines = scratchText.strip().splitlines()

    mergedPath = scratchLines[0]
    oursPath = scratchLines[1]
    theirsPath = scratchLines[2]
    fakeAncestorPath = scratchLines[3]
    assert "[MERGED]" in mergedPath
    assert "[OURS]" in oursPath
    assert "[THEIRS]" in theirsPath
    assert "[NO-ANCESTOR]" in fakeAncestorPath
    mergedContents = readFile(mergedPath, timeout=1000).decode("utf-8").strip()
    assert "merge complete!" == mergedContents
    assert readFile(fakeAncestorPath) == readFile(rw.repo.in_workdir("bye.txt"))

    waitUntilTrue(lambda: conflictUI.stackedWidget.currentWidget() is conflictUI.mergeCompletePage)


@pytest.mark.skipif(WINDOWS, reason="TODO: no editor shim for Windows yet!")
def testMergeToolInBackground(tempDir, mainWindow):
    mergeToolPath = getTestDataPath("merge-shim.py")
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"
    mainWindow.onAcceptPrefsDialog({"externalMerge": f'"{mergeToolPath}" "{scratchPath}" $M $L $R $B'})

    wd = unpackRepo(tempDir, "testrepoformerging")
    writeFile(f"{wd}/SomeOtherFile.txt", "hello")

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNodeByRef("refs/heads/branch-conflicts")

    # Initiate merge of branch-conflicts into master
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "merge into.+master")
    acceptQMessageBox(rw, "branch-conflicts.+into.+master.+may cause conflicts")
    rw.jump(NavLocator.inUnstaged(".gitignore"), check=True)
    assert rw.repo.index.conflicts
    assert rw.conflictView.isVisible()

    assert "merge-shim" in rw.conflictView.ui.mergeButton.text()
    assert rw.conflictView.ui.mergePage.isVisible()
    rw.conflictView.ui.mergeButton.click()
    assert rw.conflictView.ui.mergeInProgressPage.isVisible()

    # Immediately switch to another file
    rw.jump(NavLocator.inUnstaged("SomeOtherFile.txt"), check=True)

    scratchText = readFile(scratchPath, timeout=1000, unlink=True).decode("utf-8")
    scratchLines = scratchText.strip().splitlines()
    assert "[MERGED]" in scratchLines[0]
    assert "[OURS]" in scratchLines[1]
    assert "[THEIRS]" in scratchLines[2]
    assert "merge complete!" == readFile(scratchLines[0]).decode("utf-8").strip()

    # Switch back to the merge conflict
    rw.jump(NavLocator.inUnstaged(".gitignore"), check=True)
    waitUntilTrue(lambda: rw.conflictView.ui.mergeCompletePage.isVisible())

    # Confirm the merge
    rw.conflictView.ui.confirmMergeButton.click()

    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inStaged(".gitignore"))
    assert rw.mergeBanner.isVisible()
    assert "all conflicts fixed" in rw.mergeBanner.label.text().lower()
    assert not rw.repo.index.conflicts
