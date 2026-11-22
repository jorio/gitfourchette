# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import trtables
from gitfourchette.codeview.codewindow import CodeWindow
from gitfourchette.gitdriver import GitConflictSides
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import *
from . import reposcenario
from .util import *


# These are C files to exercise syntax highlighting in CodeWindow
_conflictScenarios = {
    GitConflictSides.BothDeleted: """
        echo 'int dontCare;' > conflict.c
        git add conflict.c && git commit -m 'initial commit'

        git switch -c THEIR-BRANCH
        git mv conflict.c dummy-theirs.c
        git commit -m 'they renamed'

        git switch master
        git mv conflict.c dummy-ours.c
        git commit -m 'we renamed'
        git cherry-pick THEIR-BRANCH || true

        # Clean up dummy files
        git add dummy-ours.c
        git rm dummy-theirs.c
    """,

    GitConflictSides.AddedByUs: """
        echo 'int ours;' > dummy.c
        git add dummy.c && git commit -m 'initial commit'

        git switch -c THEIR-BRANCH
        git mv dummy.c dummy-theirs.c  # dummy.c goes BothDeleted, dummy-theirs.c goes AddedByThem
        git commit -m 'they renamed'

        git switch master
        git mv dummy.c conflict.c
        git commit -m 'we renamed'
        git cherry-pick THEIR-BRANCH || true
        git rm 'dummy*.c'  # clean up dummy files
    """,

    GitConflictSides.AddedByThem: """
        echo 'int theirs;' > dummy.c
        git add dummy.c && git commit -m 'initial commit'

        git switch -c THEIR-BRANCH
        git mv dummy.c conflict.c
        git commit -m 'they renamed'

        git switch master
        git mv dummy.c dummy-ours.c  # dummy.c goes BothDeleted, dummy-theirs.c goes AddedByUs
        git commit -m 'we renamed'
        git cherry-pick THEIR-BRANCH || true
        git add 'dummy*.c'  # clean up dummy files
    """,

    GitConflictSides.DeletedByUs: """
        echo 'int dontCare;' > conflict.c
        git add conflict.c && git commit -m 'initial commit'

        git switch -c THEIR-BRANCH
        echo 'int theirs;' > conflict.c
        git commit -a -m 'they modified'

        git switch master
        git rm conflict.c
        git commit -m 'we deleted'
        git cherry-pick THEIR-BRANCH || true
    """,

    GitConflictSides.DeletedByThem: """
        echo 'int dontCare;' > conflict.c
        git add conflict.c && git commit -m 'initial commit'

        git switch -c THEIR-BRANCH
        git rm conflict.c
        git commit -a -m 'they deleted'

        git switch master
        echo 'int ours;' > conflict.c
        git commit -a -m 'we modified'
        git cherry-pick THEIR-BRANCH || true
    """,

    GitConflictSides.BothAdded: """
        git commit --allow-empty -m 'initial commit'

        git switch -c THEIR-BRANCH
        echo 'int theirs;' > conflict.c
        git add conflict.c && git commit -m 'they added'

        git switch master
        echo 'int ours;' > conflict.c
        git add conflict.c && git commit -m 'we added'
        git cherry-pick THEIR-BRANCH || true
    """,

    GitConflictSides.BothModified: """
        echo 'int dontCare;' > conflict.c
        git add conflict.c && git commit -m 'initial commit'

        git switch -c THEIR-BRANCH
        echo 'int theirs;' > conflict.c
        git commit -a -m 'they modified'

        git switch master
        echo 'int ours;' > conflict.c
        git commit -a -m 'we modified'
        git cherry-pick THEIR-BRANCH || true
    """,
}


@pytest.mark.parametrize("viaContextMenu", [False, True], ids=["button", "menu"])
@pytest.mark.parametrize("keep", ["oursWD", "ours", "theirs"])
@pytest.mark.parametrize("conflictSides", GitConflictSides)
def testHardSolveConflictBlob(tempDir, mainWindow, conflictSides, viaContextMenu, keep):
    wd = initEmptyRepo(tempDir)
    shell(_conflictScenarios[conflictSides], directory=wd)

    assert keep in ("oursWD", "ours", "theirs")
    keepOurs = keep in ("oursWD", "ours")
    keepOursWd = keep == "oursWD"
    bothDeleted = conflictSides == GitConflictSides.BothDeleted
    hasBothSides = conflictSides.hasOurs() and conflictSides.hasTheirs()
    conflictPath = Path(wd, "conflict.c")

    rw = mainWindow.openRepo(wd)
    cv = rw.conflictView

    assert rw.repo.any_conflicts
    assert conflictPath.name in rw.repo.index.conflicts
    assert qlvGetRowData(rw.dirtyFiles) == [conflictPath.name]
    assert qlvGetRowData(rw.stagedFiles) == []

    if bothDeleted:
        assert not conflictPath.exists()
        button = cv.ui.confirmDeletionButton
    else:
        assert (">>>>>>>" in readTextFile(str(conflictPath))) == hasBothSides
        button = cv.ui.oursButton if keepOurs else cv.ui.theirsButton

    if keepOursWd:
        writeFile(str(conflictPath), "int workdir;")
        rw.refreshRepo()

    cmLabel = "keep our" if keepOurs else "accept their"
    qmbLabel = "keep your edit" if keepOursWd else "confirm deletion" if bothDeleted else cmLabel

    # Jump to conflict
    rw.jump(NavLocator.inUnstaged(conflictPath.name), check=True)
    assert cv.currentConflict.sides == conflictSides
    assert cv.ui.mergeToolButton.isVisible() == hasBothSides
    assert trtables.enum(conflictSides) in rw.conflictView.ui.explainer.text().lower()
    assert button.isVisible()

    # Resolve conflict
    if not viaContextMenu:
        button.click()
    else:
        triggerContextMenuAction(rw.dirtyFiles.viewport(), cmLabel)

    qmb = findQMessageBox(rw, qmbLabel)
    if keepOursWd:
        findWidgetWithText(qmb.buttons(), "keep your edit").click()
    else:
        qmb.accept()

    # Check outcome
    if keepOurs:
        expectedContents = "int workdir;" if keepOursWd else "int ours;" if conflictSides.hasOurs() else None
        expectedStatus = (None if not keepOursWd
                          else FileStatus.INDEX_MODIFIED if conflictSides.hasOurs()
                          else FileStatus.INDEX_NEW)
    else:
        expectedContents = "int theirs;" if conflictSides.hasTheirs() else None
        expectedStatus = (FileStatus.INDEX_MODIFIED if hasBothSides
                          else FileStatus.INDEX_NEW if conflictSides.hasTheirs()
                          else FileStatus.INDEX_DELETED if not bothDeleted
                          else None)

    if expectedContents is not None:
        assert readTextFile(str(conflictPath)).strip() == expectedContents
    else:
        assert not conflictPath.exists()

    assert rw.repo.status().get(conflictPath.name, None) == expectedStatus
    assert rw.repo.index.conflicts is None

    assert rw.repo.index.conflicts is None


@requiresSymlinks
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
    shell(scenario, directory=wd)

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
        triggerContextMenuAction(rw.dirtyFiles.viewport(), "keep our" if keepOurs else "accept their")
    else:
        solveButton.click()
    acceptQMessageBox(rw, "keep our" if keepOurs else "accept their")

    assert symlinkPath.is_symlink()
    assert symlinkPath.resolve().samefile(Path(wd, "b" if keepOurs else "a"))
    assert rw.repo.index.conflicts is None


@pytest.mark.parametrize("keepOurs", [False, True], ids=["theirs", "ours"])
def testHardSolveSubmoduleConflict(tempDir, mainWindow, keepOurs):
    wd = unpackRepo(tempDir)
    reposcenario.submodule(wd)
    shell("""
        git checkout -b THEIR-BRANCH
        git -C submodir commit --allow-empty -m 'their submodule commit'
        git commit -am 'their submodule bump'
        git checkout master
        git submodule update
        git -C submodir commit --allow-empty -m 'our submodule commit'
        git commit -am 'our submodule bump'
        git merge THEIR-BRANCH || true
    """, wd)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("submodir"), check=True)
    assert "submodir" in rw.repo.index.conflicts

    if keepOurs:
        rw.conflictView.ui.oursButton.click()
        acceptQMessageBox(rw, "keep our")
    else:
        rw.conflictView.ui.theirsButton.click()
        acceptQMessageBox(rw, "accept their")

    assert not rw.repo.index.conflicts


@pytest.mark.parametrize("viaContextMenuLabel", ["", "keep our", "accept their"])
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
    shell(scenario, directory=wd)

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
    acceptQMessageBox(rw, "confirm deletion")

    assert not Path(wd, "xxx/zzz").exists()
    assert "xxx/zzz" not in rw.repo.index.conflicts


def testConflictDoesntPreventManipulatingIndexOnOtherFile(tempDir, mainWindow):
    wd = initEmptyRepo(tempDir)
    shell(_conflictScenarios[GitConflictSides.DeletedByUs], directory=wd)

    rw = mainWindow.openRepo(wd)
    assert "conflict.c" in rw.repo.index.conflicts

    # Modify some other file with both staged and unstaged changes
    writeFile(f"{wd}/other.txt", "b1\nb1\nstaged change\n")
    rw.refreshRepo()
    assert qlvGetRowData(rw.dirtyFiles) == ["conflict.c", "other.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []
    rw.jump(NavLocator.inUnstaged("other.txt"), check=True)
    rw.diffArea.stageButton.click()
    assert qlvGetRowData(rw.stagedFiles) == ["other.txt"]

    writeFile(f"{wd}/other.txt", "b1\nb1\nunstaged change\nstaged change\n")
    rw.refreshRepo()
    assert qlvGetRowData(rw.dirtyFiles) == ["conflict.c", "other.txt"]
    rw.jump(NavLocator.inUnstaged("other.txt"), check=True)
    rw.diffArea.discardButton.click()
    acceptQMessageBox(rw, r"really discard changes.+other.txt")

    assert readTextFile(f"{wd}/other.txt") == "b1\nb1\nstaged change\n"


def testShowConflictInBannerEvenIfNotViewingWorkdir(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")))

    # Cause a conflict outside the app
    shell("git cherry-pick ce112d052 || true", directory=wd)

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
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"
    noopShim = getShimCommand("editor.py", scratchPath, "$M", "$L", "$R", "$B")
    mergeShim = getShimCommand("merge.py", scratchPath, "$M", "$L", "$R", "$B")
    missingShim = "BOGUS_PROGRAM_DOES_NOT_EXIST $M $L $R $B"

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

    GFApplication.applyPrefs(externalMerge=noopShim)

    assert "editor.py" in cv.ui.mergeButton.text()
    assert cv.ui.mergeButton.isVisible()
    cv.ui.mergeButton.click()

    assert not cv.ui.confirmMergeLabel.isVisible()
    waitUntilTrue(cv.ui.confirmMergeLabel.isVisible)
    assert findTextInWidget(cv.ui.confirmMergeLabel, r"file seems unchanged")

    scratchLines = readTextFile(scratchPath, unlink=True).strip().splitlines()
    assert "[MERGED]" in scratchLines[0]
    assert "[OURS]" in scratchLines[1]
    assert "[THEIRS]" in scratchLines[2]

    cv.cancelMergeInProgress()

    # ------------------------------
    # Try merging with a missing command

    GFApplication.applyPrefs(externalMerge=missingShim)
    assert findTextInWidget(cv.ui.mergeButton, "BOGUS")  # warning: may be elided
    cv.ui.mergeButton.click()

    notInstalledMessage = waitForQMessageBox(rw, "not.+installed on your machine")
    notInstalledMessage.reject()

    cv.cancelMergeInProgress()

    # ------------------------------
    # Try merging with a tool that errors out (e.g. locked file)

    writeFile(scratchPath, "oops, file locked!")
    os.chmod(scratchPath, 0o400)

    GFApplication.applyPrefs(externalMerge=mergeShim + " CookieFoo")

    assert findTextInWidget(cv.ui.mergeButton, "merge.py")
    assert not findTextInWidget(cv.ui.mergeToolStatus, "exit code")
    cv.ui.mergeButton.click()

    waitUntilTrue(lambda: findTextInWidget(cv.ui.mergeToolStatus, "exit code"))

    os.chmod(scratchPath, 0o777)  # WINDOWS: Must revert mode before unlinking!
    os.unlink(scratchPath)

    cv.cancelMergeInProgress()

    # ------------------------------
    # Now try merging with a good tool

    GFApplication.applyPrefs(externalMerge=mergeShim + " CookieBar")
    assert findTextInWidget(cv.ui.mergeButton, "merge.py")
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
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"
    shim = getShimCommand("merge.py", scratchPath, "$M", "$L", "$R", "$B")
    GFApplication.applyPrefs(externalMerge=shim)

    wd = unpackRepo(tempDir, "testrepoformerging")
    shell("git switch i18n", wd)

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

    assert findTextInWidget(cv.ui.mergeButton, "merge.py")
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
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"
    shim = getShimCommand("merge.py", scratchPath, "$M", "$L", "$R", "$B")
    GFApplication.applyPrefs(externalMerge=shim)

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

    assert findTextInWidget(cv.ui.mergeButton, "merge.py")
    assert cv.ui.mergePage.isVisible()
    cv.ui.mergeButton.click()
    assert cv.ui.mergeInProgressPage.isVisible()

    # Immediately switch to another file
    rw.jump(NavLocator.inUnstaged("SomeOtherFile.txt"), check=True)

    # Wait for the merge tool to complete in the background
    scratchLines = readTextFile(scratchPath, wait=True).strip().splitlines()
    assert "[MERGED]" in scratchLines[0]
    assert "[OURS]" in scratchLines[1]
    assert "[THEIRS]" in scratchLines[2]
    assert "merge complete!" == readTextFile(scratchLines[0], wait=True).strip()

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
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"
    shim = getShimCommand("merge.py", scratchPath, "$M", "$L", "$R", "$B")
    GFApplication.applyPrefs(externalMerge=shim)

    wd = unpackRepo(tempDir, "testrepoformerging")

    # Initiate merge of branch-conflicts into master
    shell("git merge branch-conflicts || true", directory=wd)

    rw = mainWindow.openRepo(wd)
    cv = rw.conflictView

    assert ".gitignore" in rw.repo.index.conflicts
    assert cv.isVisible()

    assert findTextInWidget(cv.ui.mergeButton, "merge.py")
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


def testMergeToolDelayedWrite(tempDir, mainWindow):
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"
    # Chain detach, delay, merge
    shim = getShimCommand("merge.py", scratchPath, "$M", "$L", "$R", "$B")
    shim = getShimCommand("delay.py", "-d2", *ToolCommands.splitCommandTokens(shim))
    shim = getShimCommand("detach.py", *ToolCommands.splitCommandTokens(shim))
    GFApplication.applyPrefs(externalMerge=shim)

    wd = unpackRepo(tempDir, "testrepoformerging")

    # Initiate merge of branch-conflicts into master
    shell("git merge branch-conflicts || true", directory=wd)

    rw = mainWindow.openRepo(wd)
    cv = rw.conflictView

    assert ".gitignore" in rw.repo.index.conflicts
    assert cv.isVisible()
    assert cv.ui.mergePage.isVisible()
    assert findTextInWidget(cv.ui.mergeButton, "detach.py")
    cv.ui.mergeButton.click()
    waitUntilTrue(cv.ui.mergeCompletePage.isVisible)
    assert findTextInWidget(cv.ui.confirmMergeLabel, "unchanged.+was the merge successful")

    def refreshUntilMerged():
        rw.refreshRepo()
        return findTextInWidget(cv.ui.confirmMergeLabel, "it looks like you.ve finished")

    waitUntilTrue(refreshUntilMerged, interval=500)

    assert cv.ui.confirmMergeButton.isVisible()
    cv.ui.confirmMergeButton.click()
    assert not rw.repo.any_conflicts


def testConflictSidePreview(tempDir, mainWindow):
    wd = initEmptyRepo(tempDir)
    shell(_conflictScenarios[GitConflictSides.DeletedByUs], wd)

    rw = mainWindow.openRepo(wd)
    assert "conflict.c" in rw.repo.index.conflicts

    assert not CodeWindow._liveWindows

    cv = rw.conflictView
    assert not cv.ui.oursPreviewButton.isEnabled()
    assert cv.ui.theirsPreviewButton.isEnabled()
    cv.ui.theirsPreviewButton.click()

    window = findWindow("their.+conflict.c", t=CodeWindow)
    waitUntilTrue(lambda: QApplication.activeWindow() is window)
    assert window.codeView.toPlainText().strip() == 'int theirs;'

    # Ensure that clicking the button again re-raises the existing window.
    # Bring mainWindow back to the foreground first.
    mainWindow.activateWindow()
    waitUntilTrue(lambda: QApplication.activeWindow() is mainWindow)
    # Change window title to force findWindow to fail below
    window.setWindowTitle("YOINK!")
    # Click the button - no new window must be created
    cv.ui.theirsPreviewButton.click()
    with pytest.raises(KeyError):
        findWindow("their.+conflict.c", t=CodeWindow)
    # Clicking the button should have raised the existing window
    waitUntilTrue(lambda: QApplication.activeWindow() is window)

    # When the conflict vanishes, so should the window
    assert findWindow("YOINK", t=CodeWindow)
    cv.ui.theirsButton.click()
    acceptQMessageBox(rw, "accept their")

    with pytest.raises(KeyError):
        findWindow("YOINK", t=CodeWindow)

    waitUntilTrue(lambda: not CodeWindow._liveWindows)


def testConflictSidesHasOursHasTheirs():
    def get(sides):
        return sides.hasOurs(), sides.hasTheirs()

    assert get(GitConflictSides.BothDeleted) == (False, False)
    assert get(GitConflictSides.AddedByUs) == (True, False)
    assert get(GitConflictSides.DeletedByThem) == (True, False)
    assert get(GitConflictSides.AddedByThem) == (False, True)
    assert get(GitConflictSides.DeletedByUs) == (False, True)
    assert get(GitConflictSides.BothAdded) == (True, True)
    assert get(GitConflictSides.BothModified) == (True, True)
