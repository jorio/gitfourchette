# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pygit2.enums
import pytest

from gitfourchette.gitdriver import GitDriver
from gitfourchette.graphview.commitlogmodel import SpecialRow
from gitfourchette.graphview.graphview import GraphView
from gitfourchette.nav import NavLocator
from .util import *


def testCommitSearch(tempDir, mainWindow):
    # Commits that contain "first" in their summary
    matchingCommits = [
        Oid(hex="6462e7d8024396b14d7651e2ec11e2bbf07a05c4"),
        Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1"),
        Oid(hex="d31f5a60d406e831d056b8ac2538d515100c2df2"),
        Oid(hex="83d2f0431bcdc9c2fd2c17b828143be6ee4fbe80"),
        Oid(hex="2c349335b7f797072cf729c4f3bb0914ecb6dec9"),
        Oid(hex="ac7e7e44c1885efb472ad54a78327d66bfc4ecef"),
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    searchBar = rw.graphView.searchBar
    searchEdit = searchBar.lineEdit

    def getGraphRow():
        indexes = rw.graphView.selectedIndexes()
        assert len(indexes) == 1
        return indexes[0].row()

    assert not searchBar.isVisible()

    QTest.keySequence(mainWindow, "Ctrl+F")
    assert searchBar.isVisible()

    QTest.keyClicks(searchEdit, "first")

    previousRow = -1
    for oid in matchingCommits:
        QTest.keySequence(searchEdit, "Return")
        QTest.qWait(0)  # Give event loop a breather (for code coverage in commitlogdelegate)
        assert oid == rw.graphView.currentCommitId

        assert getGraphRow() > previousRow  # go down
        previousRow = getGraphRow()

    # end of log
    QTest.keySequence(searchEdit, "Return")
    assert getGraphRow() < previousRow  # wrap around to top of graph
    previousRow = getGraphRow()

    # select last
    lastRow = rw.graphView.clFilter.rowCount() - 1
    rw.graphView.setCurrentIndex(rw.graphView.clFilter.index(lastRow, 0))
    previousRow = lastRow

    # now search backwards
    for oid in reversed(matchingCommits):
        QTest.keySequence(searchEdit, "Shift+Return")
        assert oid == rw.graphView.currentCommitId

        assert getGraphRow() < previousRow  # go up
        previousRow = getGraphRow()

    # top of log
    QTest.keySequence(searchEdit, "Shift+Return")
    assert getGraphRow() > previousRow
    previousRow = getGraphRow()

    # escape closes search bar
    QTest.keySequence(searchEdit, "Escape")
    assert not searchBar.isVisibleTo(rw)


@pytest.mark.parametrize("rawNeedle", [
    "master.txt",
    "MaSTeR.tXt",
    "master.*",
])
def testCommitFileSearchByPath(tempDir, mainWindow, rawNeedle):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    gv = rw.graphView
    flt = gv.clFilter
    cbar = gv.commitFileSearchBar

    fullRows = flt.rowCount()
    assert not cbar.isVisible()

    rw.showCommitFileSearchBar()
    assert cbar.isVisible()

    QTest.keyClicks(cbar.lineEdit, rawNeedle)
    QTest.qWait(0)
    rw.taskRunner.joinWorkerThread()
    assert cbar._matchOids is not None
    assert len(cbar._matchOids) == 4

    cbar.ui.filterOnlyCheckBox.setChecked(True)
    assert flt.rowCount() == 4

    cbar.ui.filterOnlyCheckBox.setChecked(False)
    assert flt.rowCount() == fullRows

    QTest.keySequence(gv, "Escape")
    assert not cbar.isVisible()


def testJumpToHiddenRows(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/unstaged.txt", "hello")
    rw = mainWindow.openRepo(wd)
    cbar = rw.graphView.commitFileSearchBar

    rw.showCommitFileSearchBar()
    assert cbar.isVisible()
    cbar.ui.filterOnlyCheckBox.setChecked(True)

    QTest.keyClicks(cbar.lineEdit, "wontmatch")
    QTest.qWait(0)
    assert rw.graphView.clFilter.rowCount() == 0

    # These should not error out although all rows are hidden
    rw.jump(NavLocator.inCommit(Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0"), "a/a1"), check=True)
    rw.jump(NavLocator.inUnstaged("unstaged.txt"), check=True)


def testCommitSearchByHash(tempDir, mainWindow):
    searchCommits = [
        Oid(hex="6462e7d8024396b14d7651e2ec11e2bbf07a05c4"),
        Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1"),
        Oid(hex="d31f5a60d406e831d056b8ac2538d515100c2df2"),
        Oid(hex="83d2f0431bcdc9c2fd2c17b828143be6ee4fbe80"),
        Oid(hex="2c349335b7f797072cf729c4f3bb0914ecb6dec9"),
        Oid(hex="ac7e7e44c1885efb472ad54a78327d66bfc4ecef"),
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    searchBar = rw.graphView.searchBar
    # In this unit test, we're also going to exercise the search bar's "pulse"
    # feature, i.e. start searching automatically when the user stops typing,
    # without hitting the Return key.
    # Normally, the search bar waits for a fraction of a second before emitting
    # the pulse. Make it "instantaneous" for the unit test.
    searchBar.searchPulseTimer.setInterval(0)
    searchEdit = searchBar.lineEdit

    assert not searchBar.isVisibleTo(rw)
    QTest.qWait(0)
    QTest.keySequence(mainWindow, "Ctrl+F")
    assert searchBar.isVisibleTo(rw)

    for _j in range(2):  # first run in order, second run reversed
        for _i in range(2):  # do it twice to make it wrap around
            for oid in searchCommits:
                searchEdit.selectAll()
                QTest.keyClicks(searchEdit, str(oid)[:5])
                QTest.qWait(0)  # Don't press enter and let it auto-search (pulse timer)
                assert oid == rw.graphView.currentCommitId
        searchCommits.reverse()

    # Search for a bogus commit hash
    assert not searchBar.isRed()
    searchEdit.selectAll()
    QTest.keyClicks(searchEdit, "aaabbcc")
    QTest.qWait(0)
    assert searchBar.isRed()
    assert searchBar.searchTermBadStem == "aaabbcc"

    # Don't expand on a bad stem
    QTest.keyClicks(searchEdit, "def")
    QTest.qWait(0)
    assert searchBar.searchTermBadStem == "aaabbcc"

    # The pulse won't show an error message on its own.
    # Hit enter to bring up an error.
    QTest.keySequence(searchEdit, "Return")
    rejectQMessageBox(searchBar, "not found")


def testCommitSearchByAuthor(tempDir, mainWindow):
    # "A U Thor" has authored a ton of commits in the test repo, so take the first couple few
    searchCommits = [
        Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b"),
        Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17"),
        Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0"),
    ]

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    searchBar = rw.graphView.searchBar
    searchEdit = searchBar.lineEdit

    assert not searchBar.isVisibleTo(rw)
    QTest.qWait(0)
    QTest.keySequence(mainWindow, "Ctrl+F")
    assert searchBar.isVisibleTo(rw)
    QTest.keyClicks(searchEdit, "a u thor")

    for oid in searchCommits:
        QTest.keySequence(searchEdit, "Return")
        QTest.qWait(0)  # Give event loop a breather (for code coverage in commitlogdelegate)
        assert oid == rw.graphView.currentCommitId


@pytest.mark.parametrize("method", ["hotkey", "contextmenu"])
def testCommitInfo(tempDir, mainWindow, method):
    oid1 = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oid1, "a/a1.txt"), check=True)

    if method == "hotkey":
        rw.graphView.setFocus()
        QTest.keyClick(rw.graphView, Qt.Key.Key_Space)
    elif method == "contextmenu":
        # Use Alt modifier to bring up debug info (for coverage)
        QTest.keyPress(rw.graphView, Qt.Key.Key_Alt, Qt.KeyboardModifier.AltModifier)
        triggerContextMenuAction(rw.graphView.viewport(), "get info")
    else:
        raise NotImplementedError(f"unknown method {method}")

    qmb = findQMessageBox(rw, "Merge branch 'a' into c")
    assert str(oid1) in qmb.text()
    assert "A U Thor" in qmb.text()
    qmb.accept()


def testCommitInfoJumpToParent(tempDir, mainWindow):
    oid1 = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oid1, "a/a1.txt"), check=True)

    triggerContextMenuAction(rw.graphView.viewport(), "get info")
    qmb = findQMessageBox(rw, "Merge branch 'a' into c")

    # Click on a "parent" link; this should close the message box and jump to another commit
    label = qmb.findChild(QLabel, "qt_msgbox_label")
    parentLink = re.search(r'<a href="(.*\S+)">6462e7d.+</a>', label.text(), re.I).group(1)
    label.linkActivated.emit(parentLink)
    assert rw.navLocator.commit == Oid(hex="6462e7d8024396b14d7651e2ec11e2bbf07a05c4")


def testUncommittedChangesGraphHotkeys(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inWorkdir())

    assert rw.graphView.currentRowKind == SpecialRow.UncommittedChanges

    QTest.keyClick(rw.graphView, Qt.Key.Key_Return)
    rejectQMessageBox(rw, "empty commit")

    QTest.keyClick(rw.graphView, Qt.Key.Key_Space)
    # The mainWindow fixture will catch any leaked dialogs,
    # so if nothing happens here, we're good.


@pytest.mark.parametrize("method", ["hotkey", "contextmenu"])
def testCopyCommitHash(tempDir, mainWindow, method):
    oid1 = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oid1))

    if method == "hotkey":
        rw.graphView.setFocus()
        QTest.keySequence(rw.graphView, "Ctrl+C")
    elif method == "contextmenu":
        triggerContextMenuAction(rw.graphView.viewport(), "copy.+hash")
    else:
        raise NotImplementedError(f"unknown method {method}")

    QTest.qWait(1)
    assert QApplication.clipboard().text() == str(oid1)


@pytest.mark.parametrize("method", ["hotkey", "contextmenu"])
def testCopyCommitMessage(tempDir, mainWindow, method):
    oid1 = Oid(hex="83834a7afdaa1a1260568567f6ad90020389f664")
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(oid1))

    if method == "hotkey":
        rw.graphView.setFocus()
        QTest.keySequence(rw.graphView, "Ctrl+Shift+C")
    elif method == "contextmenu":
        triggerContextMenuAction(rw.graphView.viewport(), "copy.+message")
    else:
        raise NotImplementedError(f"unknown method {method}")

    QTest.qWait(1)
    assert QApplication.clipboard().text() == "Merge branch 'a' into c"


def testRefSortFavorsHeadBranch(tempDir, mainWindow):
    masterId = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")

    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        headCommit = repo.head_commit
        assert headCommit.id == masterId
        repo.create_branch_on_head("master-2")
        repo.checkout_local_branch("master-2")
        amendedId = repo.amend_commit_on_head("should appear above master in graph", headCommit.author, headCommit.committer)
        assert repo[amendedId].author.time == headCommit.author.time
        assert repo[amendedId].committer.time == headCommit.committer.time

    rw = mainWindow.openRepo(wd)
    masterIndex = rw.graphView.getFilterIndexForCommit(masterId)
    amendedIndex = rw.graphView.getFilterIndexForCommit(amendedId)
    assert amendedIndex.row() < masterIndex.row()


@pytest.mark.skipif(WAYLAND and not OFFSCREEN, reason="wayland blocks cursor control (note: offscreen is fine)")
@pytest.mark.skipif(QT5, reason="Qt 5 (deprecated) is finicky with this test, but Qt 6 is fine")
def testCommitToolTip(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    row = 1

    mainWindow.resize(1500, 600)
    QTest.qWait(0)
    with pytest.raises(TimeoutError):
        qlvSummonToolTip(rw.graphView, row, x=16)

    QTest.qWait(100)
    toolTip = qlvSummonToolTip(rw.graphView, row)
    assert "Delete c/c2-2.txt" not in toolTip
    assert "a.u.thor@example.com" in toolTip

    mainWindow.resize(300, 600)
    QTest.qWait(0)
    toolTip = qlvSummonToolTip(rw.graphView, row)
    assert "Delete c/c2-2.txt" in toolTip
    assert "a.u.thor@example.com" in toolTip

    # Amend, committer and author are different
    rw.repo.amend_commit_on_head("AMENDED 1", committer=TEST_SIGNATURE)
    rw.refreshRepo()
    toolTip = qlvSummonToolTip(rw.graphView, row)
    assert re.search("Committed by.+Test Person", toolTip)

    # Amend, committer and author are the same person, but they use different times
    longMessage = "AMENDED 2\n\nand while we're here, let's cover the code path that wraps very long commit messages in tooltips, yadda yadda, filler filler"
    signature2 = Signature(TEST_SIGNATURE.name, TEST_SIGNATURE.email, TEST_SIGNATURE.time + 3600, 0)
    rw.repo.amend_commit_on_head(longMessage, committer=TEST_SIGNATURE, author=signature2)
    rw.refreshRepo()
    toolTip = qlvSummonToolTip(rw.graphView, row)
    toolTip = stripHtml(toolTip)
    assert longMessage in toolTip
    assert "(committed)" in toolTip
    assert "(authored)" in toolTip


def testUnknownRefPrefix(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    # Write unsupported ref to a commit within the graph
    visibleOid = Oid(hex="f73b95671f326616d66b2afb3bdfcdbbce110b44")
    writeFile(f"{wd}/.git/refs/weird", str(visibleOid)+"\n")

    # Write unsupported ref to a commit outside the graph
    # (Create new commit then reset master to previous HEAD)
    with RepoContext(wd) as repo:
        oldHead = repo.head_commit_id
        writeFile(f"{wd}/toto.txt", "hello world\n")
        repo.index.add("toto.txt")
        ghostOid = repo.create_commit_on_head("this commit shouldnt appear")
        writeFile(f"{wd}/.git/refs/ghost", str(ghostOid))
        repo.reset(oldHead, pygit2.enums.ResetMode.HARD)

    # Painting must not raise an exception
    # (either skip the unsupported ref or draw a refbox for it, but don't crash)
    rw = mainWindow.openRepo(wd)

    assert any(c and c.id == visibleOid for c in rw.repoModel.commitSequence)
    assert not any(c and c.id == ghostOid for c in rw.repoModel.commitSequence)

    # Ghost commit can still be reached
    rw.jump(NavLocator.inCommit(ghostOid))
    assert rw.navLocator.commit == ghostOid
    assert rw.diffArea.diffBanner.isVisible()
    assert re.search(r"n.t shown in the graph", rw.diffArea.diffBanner.label.text(), re.I)


def testCommitAmendedOutsideAppVanishesFromGraph(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    assert rw.navLocator.context.isWorkdir()

    rw.jump(NavLocator.inCommit(rw.repo.head_commit_id))
    assert rw.navLocator.commit == rw.repo.head_commit_id

    with RepoContext(rw.repo) as repo:
        newHeadId = repo.amend_commit_on_head("blahblah", TEST_SIGNATURE, TEST_SIGNATURE)

    rw.refreshRepo()
    assert rw.navLocator.commit == newHeadId


def testRestoreHiddenBranchOnBoot(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.checkout_local_branch("no-parent")
    Path(f"{wd}/.git/{APP_SYSTEM_NAME}.json").write_text('{ "hidePatterns": ["refs/heads/master"] }')

    rw = mainWindow.openRepo(wd)

    hiddenOid = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    with pytest.raises(GraphView.SelectCommitError, match="hidden branch"):
        rw.graphView.getFilterIndexForCommit(hiddenOid)

    visibleOid = Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1")
    assert rw.graphView.getFilterIndexForCommit(visibleOid)


def testCommitLogFilterUpdatesAfterRebase(tempDir, mainWindow):
    wd = f"{tempDir.name}/hello"
    pygit2.init_repository(wd)

    with RepoContext(wd) as repo:
        sig = TEST_SIGNATURE

        def newCommit():
            nonlocal sig
            sig = Signature(sig.name, sig.email, sig.time + 60)
            message = "hello from " + repo.head_branch_shorthand
            return repo.create_commit_on_head(message, sig, sig)

        repo.create_commit_on_head("root commit", sig, sig)
        repo.create_branch_on_head("donthide")
        repo.checkout_local_branch("donthide")
        newCommit()
        donthideTip = newCommit()
        repo.checkout_local_branch("master")
        newCommit()
        repo.create_branch_on_head("rebase")
        newCommit()
        repo.create_branch_on_head("hidethis")
        newCommit()
        hidethisTip = newCommit()
        repo.checkout_local_branch("rebase")
        newCommit()
        newCommit()
        newCommit()
        rebaseTip = newCommit()
        repo.checkout_local_branch("master")
        repo.delete_local_branch("rebase")

    Path(f"{wd}/.git/{APP_SYSTEM_NAME}.json").write_text('{ "hidePatterns": ["refs/heads/hidethis"] }')
    rw = mainWindow.openRepo(wd)

    # Initially, the tip of hidethis is visible because it's part of master
    index = rw.graphView.getFilterIndexForCommit(hidethisTip)
    assert index.isValid()

    # Simulate a rebase
    rw.repo.reset(rebaseTip, ResetMode.HARD)
    rw.refreshRepo()

    # The tip of donthide must still exist
    index = rw.graphView.getFilterIndexForCommit(donthideTip)
    assert index.isValid()

    # Now, hidethis must be gone
    with pytest.raises(GraphView.SelectCommitError):
        rw.graphView.getFilterIndexForCommit(hidethisTip)


@pytest.mark.parametrize("swapSelectionOrder", [False, True])
def testCompare2Commits(tempDir, mainWindow, swapSelectionOrder):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322")
    oid2 = Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17")
    row1 = rw.graphView.getFilterIndexForCommit(oid1).row()
    row2 = rw.graphView.getFilterIndexForCommit(oid2).row()

    if swapSelectionOrder:
        # A/B sides must be inferred from row positions, not the order in which
        # the selection was made.
        row1, row2 = row2, row1

    # Compare 6e1475 to ce112d
    qlvClickNthRow(rw.graphView, row1)
    qlvClickNthRow(rw.graphView, row2, modifier=Qt.KeyboardModifier.ControlModifier)

    assert qlvGetRowData(rw.committedFiles) == ["a/a1", "c/c2-2.txt"]
    assert findTextInWidget(rw.diffArea.contextHeader.mainLabel, r"comparing.+6e1475.+ce112d")
    assert findTextInWidget(rw.diffArea.diffHeader, r"6e1475.+ce112d")
    assert rw.diffView.isVisible()


@pytest.mark.parametrize("method", ["button", "graphcm"])
def testCompare2CommitsSwapAB(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322")
    oid2 = Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17")
    row1 = rw.graphView.getFilterIndexForCommit(oid1).row()
    row2 = rw.graphView.getFilterIndexForCommit(oid2).row()

    # Compare 6e1475 to ce112d
    qlvClickNthRow(rw.graphView, row1)
    qlvClickNthRow(rw.graphView, row2, modifier=Qt.KeyboardModifier.ControlModifier)

    # Swap comparison
    if method == "button":
        swapButton = next(b for b in rw.diffArea.contextHeader.findChildren(QToolButton)
                          if findTextInWidget(b, r"swap a.b"))
        swapButton.click()
    elif method == "graphcm":
        triggerContextMenuAction(rw.graphView.viewport(), r"swap a.b")
    else:
        raise NotImplementedError(f"unsupported method {method}")

    assert qlvGetRowData(rw.committedFiles) == ["a/a1", "c/c2.txt"]
    assert findTextInWidget(rw.diffArea.contextHeader.mainLabel, r"comparing.+ce112d.+6e1475")
    assert findTextInWidget(rw.diffArea.diffHeader, r"ce112d.+6e1475")


def testSelect3PlusCommits(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="6e1475206e57110fcef4b92320436c1e9872a322")
    oid2 = Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17")
    row1 = rw.graphView.getFilterIndexForCommit(oid1).row()
    row2 = rw.graphView.getFilterIndexForCommit(oid2).row()

    # Select all commits between 6e1475 and ce112d
    qlvClickNthRow(rw.graphView, row1)
    qlvClickNthRow(rw.graphView, row2, modifier=Qt.KeyboardModifier.ShiftModifier)

    assert not rw.diffView.isVisible()
    assert rw.specialDiffView.isVisible()
    assert findTextInWidget(rw.specialDiffView, "5 items selected")

    cm = summonContextMenu(rw.graphView.viewport())
    assert cm.actions()[0].text().lower().startswith("no actions available")
    cm.close()


def testIllegalRowComparisons(tempDir, mainWindow):
    mainWindow.onAcceptPrefsDialog({"maxCommits": 5})

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")
    row1 = rw.graphView.getFilterIndexForCommit(oid1).row()
    row2 = rw.graphView.getFilterIndexForLocator(NavLocator.inSpecial(SpecialRow.TruncatedHistory)).row()

    for a, b in [(0, row1), (0, row2), (row1, row2)]:
        qlvClickNthRow(rw.graphView, a)
        qlvClickNthRow(rw.graphView, b, modifier=Qt.KeyboardModifier.ControlModifier)

        assert not rw.diffView.isVisible()
        assert rw.specialDiffView.isVisible()
        assert findTextInWidget(rw.specialDiffView, "selected items cannot be compared")

        cm = summonContextMenu(rw.graphView.viewport())
        assert cm.actions()[0].text().lower().startswith("no actions available")
        cm.close()


def testRestoreCurrentIndexAfterGraphSplicing(tempDir, mainWindow):
    # Check out 'no-parent' before opening the repo.
    # This will create a dotted line past 'master' in the graph.
    wd = unpackRepo(tempDir)
    GitDriver.runSync("checkout", "no-parent", directory=wd, strict=True)
    rw = mainWindow.openRepo(wd)

    # Select tip of 'master' branch
    qlvClickNthRow(rw.graphView, 1)
    assert rw.graphView.currentCommitId == rw.repo.branches.local["master"].target

    # Check out 'master'. The top of the graph will be rebuilt,
    # and the selected commit must remain consistent.
    GitDriver.runSync("checkout", "master", directory=wd, strict=True)
    rw.refreshRepo()
    assert rw.graphView.currentCommitId == rw.repo.branches.local["master"].target


def testDontScrollToSameCommitOnRefresh(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    # Create enough commits to get scroll bars
    bogusCommits = []
    with RepoContext(wd) as repo:
        for i in range(200):
            oid = repo.create_commit_on_head(f"bogus {i}", TEST_SIGNATURE, TEST_SIGNATURE)
            bogusCommits.append(oid)

    rw = mainWindow.openRepo(wd)
    vsb = rw.graphView.verticalScrollBar()

    # Ensure we've got a scroll bar and we're looking at the workdir
    assert vsb.isVisible()
    assert vsb.sliderPosition() == 0
    assert rw.graphView.navLocator.context.isWorkdir()

    # Scroll down, then refresh. The scroll bar's position shouldn't change.
    vsb.setSliderPosition(1000)
    assert vsb.sliderPosition() == 1000
    rw.refreshRepo()
    assert vsb.sliderPosition() == 1000

    # Jump to top commit. This will scroll it into view.
    rw.jump(NavLocator.inCommit(bogusCommits[-1]), check=True)
    assert vsb.sliderPosition() < 1000

    # Scroll down, then refresh. The scroll bar's position shouldn't change.
    vsb.setSliderPosition(1000)
    rw.refreshRepo()
    assert vsb.sliderPosition() == 1000
