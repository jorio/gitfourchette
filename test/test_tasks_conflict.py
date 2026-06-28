# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.gitdriver import GitConflictSides
from gitfourchette.nav import NavLocator
from . import reposcenario
from .util import *
from gitfourchette.porcelain import *


@pytest.mark.parametrize("viaContextMenu", [False, True])
def testConflictDeletedByUs(tempDir, mainWindow, viaContextMenu):
    scenario = """
        # Prepare "their" modification (modify a1.txt and a2.txt)
        git checkout -b THEIR-BRANCH
        echo 'they modified 1' > a/a1.txt
        echo 'they modified 2' > a/a2.txt
        git commit -a -m 'they modified 2 files'

        # no-parent has no a1.txt, a2.txt; create a conflict on those
        git checkout no-parent
        git cherry-pick THEIR-BRANCH || true
    """

    wd = unpackRepo(tempDir)
    runShellScript(scenario, directory=wd)

    rw = mainWindow.openRepo(wd)

    assert rw.repo.any_conflicts
    assert "a/a1.txt" in rw.repo.index.conflicts
    assert "a/a2.txt" in rw.repo.index.conflicts

    # -------------------------
    # Keep our deletion of a1.txt

    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt", "a/a2.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []
    rw.jump(NavLocator.inUnstaged("a/a1.txt"))
    assert rw.conflictView.currentConflict.sides == GitConflictSides.DeletedByUs
    assert rw.conflictView.ui.oursButton.isVisible()
    assert not rw.conflictView.ui.mergeToolButton.isVisible()
    assert "deleted by us" in rw.conflictView.ui.explainer.text().lower()

    if not viaContextMenu:
        rw.conflictView.ui.oursButton.click()
    else:
        triggerContextMenuAction(rw.dirtyFiles.viewport(), "resolve by.+ours")

    assert not Path(wd, "a/a1.txt").exists()

    # -------------------------
    # Take their a2.txt

    assert qlvGetRowData(rw.dirtyFiles) == ["a/a2.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []
    rw.jump(NavLocator.inUnstaged("a/a2.txt"))
    assert rw.conflictView.currentConflict.sides == GitConflictSides.DeletedByUs
    assert rw.conflictView.ui.theirsButton.isVisible()
    assert not rw.conflictView.ui.mergeToolButton.isVisible()

    if not viaContextMenu:
        rw.conflictView.ui.theirsButton.click()
    else:
        triggerContextMenuAction(rw.dirtyFiles.viewport(), "resolve by.+theirs")

    assert not rw.repo.index.conflicts
    assert not rw.conflictView.isVisible()
    assert rw.repo.status() == {"a/a2.txt": FileStatus.INDEX_NEW}
    assert readTextFile(f"{wd}/a/a2.txt").strip() == "they modified 2"


@pytest.mark.parametrize("viaContextMenu", [False, True])
def testConflictDeletedByThem(tempDir, mainWindow, viaContextMenu):
    scenario = """
        git checkout -b THEIR-BRANCH
        git rm a/a1.txt a/a2.txt
        git commit -m 'they deleted 2 files'

        git checkout no-parent
        mkdir -p a
        echo 'we modified' > a/a1.txt
        echo 'we modified' > a/a2.txt
        git add a/a1.txt a/a2.txt
        git commit -m 'we touched 2 files'
        git cherry-pick THEIR-BRANCH || true
    """

    wd = unpackRepo(tempDir)
    runShellScript(scenario, directory=wd)

    rw = mainWindow.openRepo(wd)

    assert rw.repo.any_conflicts
    assert "a/a1.txt" in rw.repo.index.conflicts
    assert "a/a2.txt" in rw.repo.index.conflicts

    # -------------------------
    # Keep our a1.txt

    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt", "a/a2.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []
    rw.jump(NavLocator.inUnstaged("a/a1.txt"))
    assert rw.conflictView.currentConflict.sides == GitConflictSides.DeletedByThem
    assert rw.conflictView.ui.oursButton.isVisible()
    assert not rw.conflictView.ui.mergeToolButton.isVisible()
    assert "deleted by them" in rw.conflictView.ui.explainer.text().lower()

    if not viaContextMenu:
        rw.conflictView.ui.oursButton.click()
    else:
        triggerContextMenuAction(rw.dirtyFiles.viewport(), "resolve by.+ours")

    # -------------------------
    # Take their deletion of a2.txt

    assert qlvGetRowData(rw.dirtyFiles) == ["a/a2.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []
    rw.jump(NavLocator.inUnstaged("a/a2.txt"))
    assert rw.conflictView.currentConflict.sides == GitConflictSides.DeletedByThem
    assert rw.conflictView.ui.theirsButton.isVisible()
    assert not rw.conflictView.ui.mergeToolButton.isVisible()
    if not viaContextMenu:
        rw.conflictView.ui.theirsButton.click()
    else:
        triggerContextMenuAction(rw.dirtyFiles.viewport(), "resolve by.+theirs")

    assert not rw.repo.index.conflicts
    assert not rw.conflictView.isVisible()
    assert rw.repo.status() == {"a/a2.txt": FileStatus.INDEX_DELETED}


@pytest.mark.parametrize("keepOurs", [False, True], ids=["theirs", "ours"])
@pytest.mark.parametrize("viaContextMenu", [False, True], ids=["button", "context"])
def testConflictAddedByBothWithSymlinks(tempDir, mainWindow, keepOurs, viaContextMenu):
    scenario = """
        git branch OUR-BRANCH
        git checkout -b THEIR-BRANCH
        ln -s a added_by_both
        git add added_by_both
        git commit -m 'Their Commit'

        git checkout OUR-BRANCH
        ln -s b added_by_both
        git add added_by_both
        git commit -m 'Our Commit'

        git merge THEIR-BRANCH || true
    """

    wd = unpackRepo(tempDir)
    runShellScript(scenario, directory=wd)

    rw = mainWindow.openRepo(wd)

    symlinkPath = Path(wd, "added_by_both")
    assert symlinkPath.is_symlink()
    assert symlinkPath.resolve().samefile(Path(wd, "b"))
    assert "added_by_both" in rw.repo.index.conflicts

    if keepOurs:
        solveButton = rw.conflictView.ui.oursButton
    else:
        solveButton = rw.conflictView.ui.theirsButton
    assert solveButton.isVisible()

    if viaContextMenu:
        label = "resolve by.+" + ("ours" if keepOurs else "theirs")
        triggerContextMenuAction(rw.dirtyFiles.viewport(), label)
    else:
        solveButton.click()

    assert symlinkPath.is_symlink()
    assert symlinkPath.resolve().samefile(Path(wd, "b" if keepOurs else "a"))
    assert rw.repo.index.conflicts is None


@pytest.mark.parametrize("viaContextMenuLabel", ["", "resolve by.+ours", "resolve by.+theirs"])
def testConflictDeletedByBothWithSymlinks(tempDir, mainWindow, viaContextMenuLabel):
    scenario = """
        mkdir -p xxx
        echo 'hello world' > xxx/zzz
        git add xxx/zzz
        git commit -m 'Fork Point'

        git branch OUR-BRANCH
        git checkout -b THEIR-BRANCH
        git mv xxx/zzz whateverA
        git commit -m 'Their Commit'

        git checkout OUR-BRANCH
        git mv xxx/zzz whateverB
        rmdir xxx
        ln -s master.txt xxx  # 'xxx' isn't a directory anymore
        git commit -m 'Our Commit'

        git merge THEIR-BRANCH || true
    """

    wd = unpackRepo(tempDir)
    runShellScript(scenario, directory=wd)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("xxx/zzz"), check=True)

    assert "xxx/zzz" in rw.repo.index.conflicts

    solveButton = rw.conflictView.ui.confirmDeletionButton
    assert solveButton.isVisible()

    if not viaContextMenuLabel:
        solveButton.click()
    else:
        # The context menu presents two options (accept theirs, keep ours)
        # because it doesn't have a special case for Deleted By Both.
        # Both options should yield the same outcome for Deleted By Both.
        triggerContextMenuAction(rw.dirtyFiles.viewport(), viaContextMenuLabel)

    assert not Path(wd, "xxx/zzz").exists()
    assert "xxx/zzz" not in rw.repo.index.conflicts


def testConflictDoesntPreventManipulatingIndexOnOtherFile(tempDir, mainWindow):
    scenario = """
        git checkout -b THEIR-BRANCH
        echo 'they modified' > a/a1.txt
        git commit -a -m 'they modified'

        # no-parent has no a1.txt; create a conflict on a1.txt
        git checkout no-parent
        git cherry-pick THEIR-BRANCH || true
    """

    wd = unpackRepo(tempDir)
    runShellScript(scenario, directory=wd)

    rw = mainWindow.openRepo(wd)
    assert "a/a1.txt" in rw.repo.index.conflicts

    # Modify some other file with both staged and unstaged changes
    writeFile(f"{wd}/b/b1.txt", "b1\nb1\nstaged change\n")
    rw.refreshRepo()
    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt", "b/b1.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []
    rw.jump(NavLocator.inUnstaged("b/b1.txt"), check=True)
    rw.diffArea.stageButton.click()
    assert qlvGetRowData(rw.stagedFiles) == ["b/b1.txt"]

    writeFile(f"{wd}/b/b1.txt", "b1\nb1\nunstaged change\nstaged change\n")
    rw.refreshRepo()
    assert qlvGetRowData(rw.dirtyFiles) == ["a/a1.txt", "b/b1.txt"]
    rw.jump(NavLocator.inUnstaged("b/b1.txt"), check=True)
    rw.diffArea.discardButton.click()
    acceptQMessageBox(rw, r"really discard changes.+b1\.txt")

    assert readTextFile(f"{wd}/b/b1.txt") == "b1\nb1\nstaged change\n"


def testShowConflictInBannerEvenIfNotViewingWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")))

    # Cause a conflict outside the app
    runShellScript("git cherry-pick ce112d052 || true", directory=wd)

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


def testMergeTool(tempDir, mainWindow):
    noopMergeToolPath = getTestDataPath("editor-shim.py")
    mergeToolPath = getTestDataPath("merge-shim.py")
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"

    wd = unpackRepo(tempDir, "testrepoformerging")
    rw = mainWindow.openRepo(wd)
    cv = rw.conflictView

    # Initiate merge of branch-conflicts into master
    node = rw.sidebar.findNodeByRef("refs/heads/branch-conflicts")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "merge into.+master")
    acceptQMessageBox(rw, "branch-conflicts.+into.+master.+may cause conflicts")

    rw.jump(NavLocator.inUnstaged(".gitignore"), check=True)
    assert rw.repo.index.conflicts
    assert cv.isVisible()

    # ------------------------------
    # Try merging with a tool that doesn't touch the output file

    mainWindow.onAcceptPrefsDialog({"externalMerge": f'"{noopMergeToolPath}" "{scratchPath}" $M $L $R $B'})

    assert "editor-shim" in cv.ui.mergeButton.text()
    assert cv.ui.mergeButton.isVisible()
    cv.ui.mergeButton.click()

    assert not cv.ui.mergeToolStatus.isVisible()
    waitUntilTrue(cv.ui.mergeToolStatus.isVisible)
    assert findTextInWidget(cv.ui.mergeToolStatus, r"didn.t complete")

    scratchLines = readTextFile(scratchPath, unlink=True).strip().splitlines()
    assert "[MERGED]" in scratchLines[0]
    assert "[OURS]" in scratchLines[1]
    assert "[THEIRS]" in scratchLines[2]

    cv.cancelMergeInProgress()

    # ------------------------------
    # Try merging with a missing command

    mainWindow.onAcceptPrefsDialog({"externalMerge": f'"{noopMergeToolPath}-BOGUS" "{scratchPath}" $M $L $R $B'})
    assert findTextInWidget(cv.ui.mergeButton, "BOGUS")  # warning: may be elided
    cv.ui.mergeButton.click()

    notInstalledMessage = waitForQMessageBox(rw, "not.+installed on your machine")
    notInstalledMessage.reject()

    cv.cancelMergeInProgress()

    # ------------------------------
    # Try merging with a tool that errors out (e.g. locked file)

    writeFile(scratchPath, "oops, file locked!")
    os.chmod(scratchPath, 0o400)

    mainWindow.onAcceptPrefsDialog({"externalMerge": f'"{mergeToolPath}" "{scratchPath}" $M $L $R $B CookieFoo'})

    assert findTextInWidget(cv.ui.mergeButton, "merge-shim")
    assert not findTextInWidget(cv.ui.mergeToolStatus, "exit code")
    cv.ui.mergeButton.click()

    waitUntilTrue(lambda: findTextInWidget(cv.ui.mergeToolStatus, "exit code"))

    os.chmod(scratchPath, 0o777)  # WINDOWS: Must revert mode before unlinking!
    os.unlink(scratchPath)

    cv.cancelMergeInProgress()

    # ------------------------------
    # Now try merging with a good tool

    mainWindow.onAcceptPrefsDialog({"externalMerge": f'"{mergeToolPath}" "{scratchPath}" $M $L $R $B CookieBar'})
    assert findTextInWidget(cv.ui.mergeButton, "merge-shim")
    cv.ui.mergeButton.click()

    assert cv.ui.mergeInProgressPage.isVisible()
    assert not cv.ui.mergeCompletePage.isVisible()
    waitUntilTrue(cv.ui.mergeCompletePage.isVisible)

    scratchText = readTextFile(scratchPath, unlink=True)
    scratchLines = scratchText.strip().splitlines()

    mergedPath = scratchLines[0]
    oursPath = scratchLines[1]
    theirsPath = scratchLines[2]

    assert "[MERGED]" in mergedPath
    assert "[OURS]" in oursPath
    assert "[THEIRS]" in theirsPath
    assert "CookieBar" == scratchLines[-1]
    assert "merge complete!" == readTextFile(mergedPath).strip()

    # ------------------------------
    # Hit "Merge Again"

    assert not os.path.exists(scratchPath)  # should have been unlinked above

    cv.ui.reworkMergeButton.click()
    assert cv.ui.mergeInProgressPage.isVisible()
    assert not cv.ui.mergeCompletePage.isVisible()
    waitUntilTrue(cv.ui.mergeCompletePage.isVisible)

    scratchText = readTextFile(scratchPath, unlink=True)
    scratchLines = scratchText.strip().splitlines()

    # Make sure the same command was run
    assert scratchLines[0] == mergedPath
    assert scratchLines[1] == oursPath
    assert scratchLines[2] == theirsPath
    assert "merge complete!" == readTextFile(mergedPath).strip()

    # ------------------------------
    # Accept merge resolution

    waitUntilTrue(cv.ui.mergeCompletePage.isVisible)
    cv.ui.confirmMergeButton.click()
    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inStaged(".gitignore"))

    assert rw.mergeBanner.isVisible()
    assert findTextInWidget(rw.mergeBanner.label, "all conflicts fixed")
    assert not rw.repo.index.conflicts


def testFake3WayMerge(tempDir, mainWindow):
    mergeToolPath = getTestDataPath("merge-shim.py")
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"
    mainWindow.onAcceptPrefsDialog({"externalMerge": f'"{mergeToolPath}" "{scratchPath}" $M $L $R $B'})

    wd = unpackRepo(tempDir, "testrepoformerging")
    with RepoContext(wd) as repo:
        repo.checkout_local_branch("i18n")

    rw = mainWindow.openRepo(wd)
    cv = rw.conflictView

    # Initiate merge of branch-conflicts into master
    node = rw.sidebar.findNodeByRef("refs/heads/pep8-fixes")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "merge into.+i18n")
    acceptQMessageBox(rw, "pep8-fixes.+into.+i18n.+may cause conflicts")
    rw.jump(NavLocator.inUnstaged("bye.txt"), check=True)
    assert rw.repo.index.conflicts
    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged("bye.txt"))
    assert cv.ui.mergePage.isVisible()

    assert findTextInWidget(cv.ui.mergeButton, "merge-shim")
    assert not cv.ui.mergeCompletePage.isVisible()
    cv.ui.mergeButton.click()

    waitUntilTrue(cv.ui.mergeCompletePage.isVisible)

    scratchLines = readTextFile(scratchPath).strip().splitlines()
    mergedPath = scratchLines[0]
    oursPath = scratchLines[1]
    theirsPath = scratchLines[2]
    fakeAncestorPath = scratchLines[3]
    assert "[MERGED]" in mergedPath
    assert "[OURS]" in oursPath
    assert "[THEIRS]" in theirsPath
    assert "[NO-ANCESTOR]" in fakeAncestorPath
    assert "merge complete!" == readTextFile(mergedPath).strip()
    assert readFile(fakeAncestorPath) == readFile(rw.repo.in_workdir("bye.txt"))


def testMergeToolInBackground(tempDir, mainWindow):
    mergeToolPath = getTestDataPath("merge-shim.py")
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"
    mainWindow.onAcceptPrefsDialog({"externalMerge": f'"{mergeToolPath}" "{scratchPath}" $M $L $R $B'})

    wd = unpackRepo(tempDir, "testrepoformerging")
    writeFile(f"{wd}/SomeOtherFile.txt", "hello")

    rw = mainWindow.openRepo(wd)
    cv = rw.conflictView
    node = rw.sidebar.findNodeByRef("refs/heads/branch-conflicts")

    # Initiate merge of branch-conflicts into master
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "merge into.+master")
    acceptQMessageBox(rw, "branch-conflicts.+into.+master.+may cause conflicts")
    rw.jump(NavLocator.inUnstaged(".gitignore"), check=True)
    assert rw.repo.index.conflicts
    assert cv.isVisible()

    assert findTextInWidget(cv.ui.mergeButton, "merge-shim")
    assert cv.ui.mergePage.isVisible()
    cv.ui.mergeButton.click()
    assert cv.ui.mergeInProgressPage.isVisible()

    # Immediately switch to another file
    rw.jump(NavLocator.inUnstaged("SomeOtherFile.txt"), check=True)

    # Wait for the merge tool to complete in the background
    waitForFile(scratchPath)
    scratchLines = readTextFile(scratchPath).strip().splitlines()
    assert "[MERGED]" in scratchLines[0]
    assert "[OURS]" in scratchLines[1]
    assert "[THEIRS]" in scratchLines[2]
    assert "merge complete!" == readTextFile(scratchLines[0]).strip()

    # Switch back to the merge conflict
    rw.jump(NavLocator.inUnstaged(".gitignore"), check=True)
    waitUntilTrue(cv.ui.mergeCompletePage.isVisible)

    # Confirm the merge
    cv.ui.confirmMergeButton.click()

    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inStaged(".gitignore"))
    assert rw.mergeBanner.isVisible()
    assert findTextInWidget(rw.mergeBanner.label, "all conflicts fixed")
    assert not rw.repo.index.conflicts


def testDiscardMergeResolution(tempDir, mainWindow):
    mergeToolPath = getTestDataPath("merge-shim.py")
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"
    mainWindow.onAcceptPrefsDialog({"externalMerge": f'"{mergeToolPath}" "{scratchPath}" $M $L $R $B'})

    wd = unpackRepo(tempDir, "testrepoformerging")

    rw = mainWindow.openRepo(wd)
    cv = rw.conflictView
    node = rw.sidebar.findNodeByRef("refs/heads/branch-conflicts")

    # Initiate merge of branch-conflicts into master
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "merge into.+master")
    acceptQMessageBox(rw, "branch-conflicts.+into.+master.+may cause conflicts")
    assert ".gitignore" in rw.repo.index.conflicts
    assert cv.isVisible()

    assert findTextInWidget(cv.ui.mergeButton, "merge-shim")
    assert cv.ui.mergePage.isVisible()
    cv.ui.mergeButton.click()
    assert cv.ui.mergeInProgressPage.isVisible()

    waitUntilTrue(cv.ui.mergeCompletePage.isVisible)
    scratchLines = readTextFile(scratchPath).strip().splitlines()
    assert "[MERGED]" in scratchLines[0]
    assert "[OURS]" in scratchLines[1]
    assert "[THEIRS]" in scratchLines[2]
    assert "merge complete!" == readTextFile(scratchLines[0]).strip()

    # Discard the merge
    cv.ui.discardMergeButton.click()

    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged(".gitignore"))
    assert cv.ui.mergePage.isVisible()
    assert ".gitignore" in rw.repo.index.conflicts
