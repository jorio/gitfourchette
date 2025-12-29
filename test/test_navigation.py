# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.graphview.commitlogmodel import SpecialRow
from gitfourchette.nav import NavContext, NavLocator
from gitfourchette.repowidget import RepoWidget
from . import reposcenario
from .util import *


def assertHistoryMatches(rw: RepoWidget, locator: NavLocator):
    assert rw.navLocator.isSimilarEnoughTo(locator)
    assert rw.diffView.currentDelta.old.path == locator.path
    if locator.context.isWorkdir():
        assert rw.graphView.currentRowKind == SpecialRow.UncommittedChanges
        assert rw.diffArea.fileStackPage() == "workdir"
        if locator.context == NavContext.UNSTAGED:
            assert qlvGetSelection(rw.dirtyFiles) == [locator.path]
            assert qlvGetSelection(rw.stagedFiles) == []
        else:
            assert qlvGetSelection(rw.stagedFiles) == [locator.path]
            assert qlvGetSelection(rw.dirtyFiles) == []
    else:
        assert rw.graphView.currentCommitId == locator.commit
        assert rw.diffArea.fileStackPage() == "commit"
        assert qlvGetSelection(rw.committedFiles) == [locator.path]


@pytest.mark.parametrize("method", ["menubar", "toolbar", "mousebuttons"])
def testNavigation(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    reposcenario.fileWithStagedAndUnstagedChanges(wd)
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")
    oid2 = Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322")
    oid3 = Oid(hex="bab66b48f836ed950c99134ef666436fb07a09a0")
    oid4 = Oid(hex="58be4659bb571194ed4562d04b359d26216f526e")

    # ..........................................# -9 select a1.txt in UNSTAGED
    rw.jump(NavLocator.inCommit(oid1))          # -8 select a1.txt in 83834a7
    qlvClickNthRow(rw.committedFiles, 1)        # -7 select a2.txt in 83834a7
    rw.jump(NavLocator.inCommit(oid2))          # -6 select b1.txt in 6e14752
    qlvClickNthRow(rw.committedFiles, 1)        # -5 select b2.txt in 6e14752
    rw.jump(NavLocator.inWorkdir())             # -4 select a1.txt in UNSTAGED
    qlvClickNthRow(rw.stagedFiles, 0)           # -3 select a1.txt in STAGED
    qlvClickNthRow(rw.dirtyFiles, 0)            # -2 select a1.txt in UNSTAGED again
    rw.jump(NavLocator.inCommit(oid3))          # -1 select c1.txt in bab66b4

    history = [
        NavLocator.inCommit(oid1, "a/a1.txt"),  # -8
        NavLocator.inCommit(oid1, "a/a2.txt"),  # -7
        NavLocator.inCommit(oid2, "b/b1.txt"),  # -6
        NavLocator.inCommit(oid2, "b/b2.txt"),  # -5
        NavLocator.inUnstaged("a/a1.txt"),      # -4
        NavLocator.inStaged("a/a1.txt"),        # -3
        NavLocator.inUnstaged("a/a1.txt"),      # -2
        NavLocator.inCommit(oid3, "c/c1.txt"),  # -1
    ]

    def back(expectEnabled=True):
        if method == "menubar":
            triggerMenuAction(mainWindow.menuBar(), "view/navigate back")
        elif method == "toolbar":
            button: QToolButton = mainWindow.mainToolBar.widgetForAction(mainWindow.mainToolBar.backAction)
            assert expectEnabled == button.isEnabled()
            button.click()
        elif method == "mousebuttons":
            QTest.mouseClick(mainWindow, Qt.MouseButton.BackButton)

    def forward(expectEnabled=True):
        if method == "menubar":
            triggerMenuAction(mainWindow.menuBar(), "view/navigate forward")
        elif method == "toolbar":
            button: QToolButton = mainWindow.mainToolBar.widgetForAction(mainWindow.mainToolBar.forwardAction)
            assert expectEnabled == button.isEnabled()
            button.click()
        elif method == "mousebuttons":
            QTest.mouseClick(mainWindow, Qt.MouseButton.ForwardButton)

    assertHistoryMatches(rw, history[-1])

    forward(False)  # can't go further
    assertHistoryMatches(rw, history[-1])

    back()
    assertHistoryMatches(rw, history[-2])
    forward()
    assertHistoryMatches(rw, history[-1])

    back()
    assertHistoryMatches(rw, history[-2])

    back()
    assertHistoryMatches(rw, history[-3])

    back()
    assertHistoryMatches(rw, history[-4])

    back()
    assertHistoryMatches(rw, history[-5])

    back()
    assertHistoryMatches(rw, history[-6])

    back()
    assertHistoryMatches(rw, history[-7])

    back()
    assertHistoryMatches(rw, history[-8])

    forward()
    forward()
    forward()
    forward()
    forward()
    assertHistoryMatches(rw, history[-3])

    # now fork from linear history
    rw.jump(NavLocator.inCommit(oid4))
    historyFork = NavLocator.inCommit(oid4, "master.txt")
    assertHistoryMatches(rw, historyFork)

    # can't go further
    forward(False)
    assertHistoryMatches(rw, historyFork)

    # go back to -3
    back()
    assertHistoryMatches(rw, history[-3])

    back()
    assertHistoryMatches(rw, history[-4])

    forward()
    forward()
    assertHistoryMatches(rw, historyFork)


def testNavigationButtonsEnabledState(tempDir, mainWindow):
    tb = mainWindow.mainToolBar
    backButton = tb.widgetForAction(tb.backAction)
    forwardButton = tb.widgetForAction(tb.forwardAction)
    assert not backButton.isEnabled() and not forwardButton.isEnabled()

    wd1 = unpackRepo(tempDir, renameTo="repo1")
    rw1 = mainWindow.openRepo(wd1)

    oid1 = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")
    oid2 = Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322")
    oid3 = Oid(hex="bab66b48f836ed950c99134ef666436fb07a09a0")

    assert not backButton.isEnabled() and not forwardButton.isEnabled()
    rw1.jump(NavLocator.inCommit(oid1))
    rw1.jump(NavLocator.inCommit(oid2))
    rw1.jump(NavLocator.inWorkdir())
    rw1.jump(NavLocator.inCommit(oid3))
    assert backButton.isEnabled() and not forwardButton.isEnabled()

    wd2 = unpackRepo(tempDir, renameTo="repo2")
    rw2 = mainWindow.openRepo(wd2)
    assert not backButton.isEnabled() and not forwardButton.isEnabled()
    rw2.jump(NavLocator.inCommit(oid3))
    rw2.navigateBack()
    assert not backButton.isEnabled() and forwardButton.isEnabled()

    mainWindow.tabs.setCurrentIndex(0)
    assert backButton.isEnabled() and not forwardButton.isEnabled()

    mainWindow.closeAllTabs()
    assert not backButton.isEnabled() and not forwardButton.isEnabled()


def testNavigationAfterDiscardingChangeInMiddleOfHistory(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    writeFile(F"{wd}/a/a1", "blah blah a1")
    writeFile(F"{wd}/a/a1.txt", "blah blah a1.txt")
    writeFile(F"{wd}/b/b1.txt", "blah blah b1")
    writeFile(F"{wd}/c/c1.txt", "blah blah c1")
    writeFile(F"{wd}/c/c2.txt", "blah blah c2")

    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)  # a/a1
    qlvClickNthRow(rw.dirtyFiles, 1)  # a/a1.txt
    qlvClickNthRow(rw.dirtyFiles, 2)  # b/b1.txt
    qlvClickNthRow(rw.dirtyFiles, 3)  # c/c1.txt
    qlvClickNthRow(rw.dirtyFiles, 4)  # c/c2.txt

    assertHistoryMatches(rw, NavLocator.inUnstaged("c/c2.txt"))

    rw.navigateBack()
    assertHistoryMatches(rw, NavLocator.inUnstaged("c/c1.txt"))
    rw.navigateBack()
    assertHistoryMatches(rw, NavLocator.inUnstaged("b/b1.txt"))

    rw.dirtyFiles.discard()  # discard b/b1.txt
    acceptQMessageBox(rw, "really discard changes")

    assertHistoryMatches(rw, NavLocator.inUnstaged("c/c1.txt"))

    # can't go further; the FLV's selection has snapped to c1, which has in turn trimmed the history
    rw.navigateForward()
    assertHistoryMatches(rw, NavLocator.inUnstaged("c/c1.txt"))

    # navigating back must skip over b1.txt because it's gone
    rw.navigateBack()
    assertHistoryMatches(rw, NavLocator.inUnstaged("a/a1.txt"))

    # navigating forward must skip over b1.txt because it's gone
    rw.navigateForward()
    assertHistoryMatches(rw, NavLocator.inUnstaged("c/c1.txt"))


def testNavigationAfterDiscardingChangeAtTopOfHistory(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/a/a1", "blah blah a1")
    writeFile(F"{wd}/a/a1.txt", "blah blah a1.txt")
    writeFile(F"{wd}/b/b1.txt", "blah blah b1")
    writeFile(F"{wd}/c/c1.txt", "blah blah c1")
    writeFile(F"{wd}/c/c2.txt", "blah blah c2")
    rw = mainWindow.openRepo(wd)

    qlvClickNthRow(rw.dirtyFiles, 0)
    qlvClickNthRow(rw.dirtyFiles, 1)
    qlvClickNthRow(rw.dirtyFiles, 2)
    qlvClickNthRow(rw.dirtyFiles, 3)
    qlvClickNthRow(rw.dirtyFiles, 4)

    assertHistoryMatches(rw, NavLocator.inUnstaged("c/c2.txt"))
    rw.dirtyFiles.discard()
    acceptQMessageBox(rw, "really delete")

    assertHistoryMatches(rw, NavLocator.inUnstaged("c/c1.txt"))

    # Can't go further
    for _ in range(10):
        rw.navigateForward()
        assertHistoryMatches(rw, NavLocator.inUnstaged("c/c1.txt"))

    qlvClickNthRow(rw.dirtyFiles, 0)
    assertHistoryMatches(rw, NavLocator.inUnstaged("a/a1"))

    rw.navigateBack()
    assertHistoryMatches(rw, NavLocator.inUnstaged("c/c1.txt"))

    rw.navigateBack()
    assertHistoryMatches(rw, NavLocator.inUnstaged("b/b1.txt"))


def testRestoreLastSelectedFileInContext(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/a/a1", "blah blah a1")
    writeFile(F"{wd}/a/a1.txt", "blah blah a1.txt")
    writeFile(F"{wd}/b/b1.txt", "blah blah b1")
    writeFile(F"{wd}/c/c1.txt", "blah blah c1")
    writeFile(F"{wd}/c/c2.txt", "blah blah c2")
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")
    oid2 = Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322")

    # Stage c1 and c2
    assert "c/c2.txt" == qlvClickNthRow(rw.dirtyFiles, 4)
    rw.dirtyFiles.stage()
    assert "c/c1.txt" == qlvClickNthRow(rw.dirtyFiles, 3)
    rw.dirtyFiles.stage()

    # Select b1.txt in UNSTAGED context
    qlvClickNthRow(rw.dirtyFiles, 2)
    assertHistoryMatches(rw, NavLocator.inUnstaged("b/b1.txt"))

    # Select c2.txt in STAGED context
    qlvClickNthRow(rw.stagedFiles, 1)
    assertHistoryMatches(rw, NavLocator.inStaged("c/c2.txt"))

    # Select a2.txt in COMMITTED context (83834a7)
    rw.jump(NavLocator.inCommit(oid1))
    qlvClickNthRow(rw.committedFiles, 1)
    assertHistoryMatches(rw, NavLocator.inCommit(oid1, "a/a2.txt"))

    # Select b2.txt in COMMITTED context (6e14752)
    rw.jump(NavLocator.inCommit(oid2))
    qlvClickNthRow(rw.committedFiles, 1)
    assertHistoryMatches(rw, NavLocator.inCommit(oid2, "b/b2.txt"))

    # Rewind
    rw.navigateBack()  # back to first file in 6e14752
    rw.navigateBack()  # back to a2.txt in 83834a7
    rw.navigateBack()  # back to first file in 83834a7
    rw.navigateBack()  # back to STAGED
    rw.navigateBack()  # back to UNSTAGED

    # Back to UNSTAGED context
    assertHistoryMatches(rw, NavLocator.inUnstaged("b/b1.txt"))

    # Advance to STAGED context
    rw.navigateForward()
    assertHistoryMatches(rw, NavLocator.inStaged("c/c2.txt"))

    # Advance to COMMITTED context (83834a7)
    rw.navigateForward()  # skip automatically selected file in 83834a7
    rw.navigateForward()
    assertHistoryMatches(rw, NavLocator.inCommit(oid1, "a/a2.txt"))

    # Advance to COMMITTED context (6e14752)
    rw.navigateForward()  # skip automatically selected file in 6e14752
    rw.navigateForward()
    assertHistoryMatches(rw, NavLocator.inCommit(oid2, "b/b2.txt"))


def testAbstractWorkdirLocatorRedirectsToConcreteLocator(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/a/a1", "blah blah a1")
    writeFile(F"{wd}/a/a1.txt", "blah blah a1.txt")
    writeFile(F"{wd}/b/b1.txt", "blah blah b1")
    writeFile(F"{wd}/c/c1.txt", "blah blah c1")
    writeFile(F"{wd}/c/c2.txt", "blah blah c2")
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")

    # Ensure we're starting from the workdir
    assertHistoryMatches(rw, NavLocator.inUnstaged("a/a1"))

    # Stage c1 and c2
    assert "c/c2.txt" == qlvClickNthRow(rw.dirtyFiles, 4)
    rw.dirtyFiles.stage()
    assert "c/c1.txt" == qlvClickNthRow(rw.dirtyFiles, 3)
    rw.dirtyFiles.stage()

    # Select an unstaged file, jump to a commit, and then back to the workdir.
    # Ensure our selection is kept.
    qlvClickNthRow(rw.dirtyFiles, 1)  # select second unstaged file
    assertHistoryMatches(rw, NavLocator.inUnstaged("a/a1.txt"))
    rw.jump(NavLocator.inCommit(oid1))  # jump out of workdir
    rw.jump(NavLocator.inWorkdir())  # jump to abstract workdir locator
    assertHistoryMatches(rw, NavLocator.inUnstaged("a/a1.txt"))  # shouldn't have lost our position in the workidr

    # Select a staged file, jump to a commit, and then back to the workdir.
    # Ensure our selection is kept.
    qlvClickNthRow(rw.stagedFiles, 1)  # select second staged file
    assertHistoryMatches(rw, NavLocator.inStaged("c/c2.txt"))
    rw.jump(NavLocator.inCommit(oid1))  # jump out of workdir
    rw.jump(NavLocator.inWorkdir())  # jump to abstract workdir locator
    assertHistoryMatches(rw, NavLocator.inStaged("c/c2.txt"))  # shouldn't have lost our position in the workdir


def testSaveScrollPosition(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(F"{wd}/long.txt", "\n".join(f"cats are cute {i}" for i in range(1, 10_000)))
    writeFile(F"{wd}/memo.txt", "feed the cat")
    rw = mainWindow.openRepo(wd)
    vsb: QScrollBar = rw.diffView.verticalScrollBar()

    locLong = NavLocator.inUnstaged("long.txt")
    locMemo = NavLocator.inUnstaged("memo.txt")

    # Jump to very long file
    rw.jump(locLong)
    assert rw.diffView.isVisibleTo(rw)
    assert vsb.value() == 0

    vsb.setValue(1)  # note: line 0 is hunk header
    assert rw.diffView.firstVisibleBlock().text().startswith("cats are cute 1")

    # Scroll down halfway through
    vsb.setValue(5000)
    assert rw.diffView.firstVisibleBlock().text().startswith("cats are cute 5000")

    # Jump to some other file, scroll bar gets reset
    rw.jump(locMemo)
    assert rw.navLocator.isSimilarEnoughTo(locMemo)
    assert vsb.value() == 0

    # Jump back to long file, we should land on the same line
    rw.jump(locLong)
    assert rw.navLocator.isSimilarEnoughTo(locLong)
    assert vsb.value() == 5000

    # Navigate away from long file via history
    rw.navigateBack()
    assert rw.navLocator.isSimilarEnoughTo(locMemo)
    assert vsb.value() == 0

    # Come back to long file
    rw.navigateBack()
    assert rw.navLocator.isSimilarEnoughTo(locLong)
    assert vsb.value() == 5000


def testSelectNextOrPreviousFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.fileWithStagedAndUnstagedChanges(wd)
    rw = mainWindow.openRepo(wd)

    def clearCurrentFileListSelection():
        fl = rw.diffArea.fileListByContext(rw.navLocator.context)
        fl.setFocus()
        fl.clearSelection()

    def test(nextPrev: str, locator: NavLocator):
        triggerMenuAction(mainWindow.menuBar(), f"view/{nextPrev}.+file")
        fl = rw.diffArea.fileListByContext(locator.context)
        assert fl.isVisible()
        return locator.isSimilarEnoughTo(rw.navLocator)

    # In workdir
    clearCurrentFileListSelection()
    assert test("next", NavLocator.inUnstaged("a/a1.txt"))
    assert test("next", NavLocator.inStaged("a/a1.txt"))
    assert test("next", NavLocator.inStaged("a/a1.txt"))
    assert test("prev", NavLocator.inUnstaged("a/a1.txt"))
    assert test("prev", NavLocator.inUnstaged("a/a1.txt"))

    # In workdir, dirty file list empty: next/prev must skip over empty list
    rw.diffArea.stageButton.click()
    clearCurrentFileListSelection()
    assert test("next", NavLocator.inStaged("a/a1.txt"))
    clearCurrentFileListSelection()
    assert test("prev", NavLocator.inStaged("a/a1.txt"))

    # In a commit
    oid = Oid(hex='83834a7afdaa1a1260568567f6ad90020389f664')
    rw.jump(NavLocator.inCommit(oid, "a/a1.txt"), check=True)
    assert test("next", NavLocator.inCommit(oid, "a/a2.txt"))
    assert test("next", NavLocator.inCommit(oid, "master.txt"))
    assert test("next", NavLocator.inCommit(oid, "master.txt"))
    assert test("prev", NavLocator.inCommit(oid, "a/a2.txt"))
    assert test("prev", NavLocator.inCommit(oid, "a/a1.txt"))
    assert test("prev", NavLocator.inCommit(oid, "a/a1.txt"))
