# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest
import re

from gitfourchette.nav import NavLocator
from gitfourchette.repomodel import UC_FAKEID
from gitfourchette.sidebar.sidebarmodel import SidebarItem, SidebarModel
from gitfourchette.toolbox import naturalSort
from . import reposcenario
from .util import *


def _summonSearchBar(rw):
    rw.activateWindow()  # macOS offscreen compat (e.g. after a context menu)
    waitUntilTrue(rw.isActiveWindow)

    searchBar = rw.sidebar.searchBar
    assert not searchBar.isVisible()

    rw.sidebar.setFocus()
    assert rw.sidebar.hasFocus()

    QTest.keySequence(rw.window(), "Ctrl+F")
    assert searchBar.isVisible()

    return searchBar


def testCurrentBranchCannotSwitchOrMerge(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    node = rw.sidebar.findNodeByRef("refs/heads/master")
    menu = rw.sidebar.makeNodeMenu(node)

    assert not findMenuAction(menu, "switch to").isEnabled()
    assert not findMenuAction(menu, "merge").isEnabled()
    # assert not findMenuAction(menu, "rebase").isEnabled()


def testSidebarWithDetachedHead(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git checkout 7f82283", wd)

    rw = mainWindow.openRepo(wd)

    headNode = rw.sidebar.findNodeByRef("HEAD")
    assert headNode.kind == SidebarItem.DetachedHead
    assert headNode == rw.sidebar.findNodeByKind(SidebarItem.DetachedHead)

    toolTip = rw.sidebar.nodeToFilterIndex(headNode).data(Qt.ItemDataRole.ToolTipRole)
    assert re.search(r"detached head.+7f82283", toolTip, re.IGNORECASE)

    assert {'refs/heads/master', 'refs/heads/no-parent'
            } == {n.data for n in rw.sidebar.findNodesByKind(SidebarItem.LocalBranch)}


def testSidebarSelectionSync(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    rw.jump(NavLocator.inRef("HEAD"))
    assert sb.selectedIndexes()[0].data() == "master"

    rw.jump(NavLocator.inWorkdir())
    assert "workdir" in sb.selectedIndexes()[0].data().lower()

    rw.jump(NavLocator.inRef("refs/remotes/origin/first-merge"))
    assert sb.selectedIndexes()[0].data() == "first-merge"

    rw.jump(NavLocator.inRef("refs/tags/annotated_tag"))
    assert sb.selectedIndexes()[0].data() == "annotated_tag"

    # no refs point to this commit, so the sidebar shouldn't have a selection
    rw.jump(NavLocator.inCommit(Oid(hex="6db9c2ebf75590eef973081736730a9ea169a0c4")))
    assert not sb.selectedIndexes()


def testSidebarCollapsePersistent(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    sb = rw.sidebar
    sm = sb.sidebarModel
    assert sm.isAncestryChainExpanded(sb.findNodeByRef("refs/remotes/origin/master"))
    nodeToCollapse = sb.findNode(lambda n: n.data == "origin")
    indexToCollapse = sb.nodeToFilterIndex(nodeToCollapse)
    sb.collapse(indexToCollapse)
    sb.expand(indexToCollapse)  # go through both expand/collapse code paths
    sb.collapse(indexToCollapse)
    assert not sm.isAncestryChainExpanded(sb.findNodeByRef("refs/remotes/origin/master"))

    # Test that it's still hidden after a soft refresh
    mainWindow.currentRepoWidget().refreshRepo()
    assert not sm.isAncestryChainExpanded(sb.findNodeByRef("refs/remotes/origin/master"))

    # Test that it's still hidden after closing and reopening
    mainWindow.closeTab(0)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    assert not sm.isAncestryChainExpanded(sb.findNodeByRef("refs/remotes/origin/master"))


def testSidebarCollapsedHeaderShowsChildCount(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    sb = rw.sidebar

    indexes = [sb.nodeToFilterIndex(sb.findNodeByKind(kind))
               for kind in (SidebarItem.RemotesHeader,
                            SidebarItem.TagsHeader,
                            SidebarItem.StashesHeader,
                            SidebarItem.SubmodulesHeader)]

    assert [i.data() for i in indexes] == [
        "Remotes", "Tags", "Stashes", "Submodules"]

    sb.collapseAll()

    assert [i.data() for i in indexes] == [
        "Remotes (1)", "Tags (1)", "Stashes (0)", "Submodules (0)"]


def testSidebarCollapseExpandAllFolders(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        git branch delish/drink/gazpacho
        git branch delish/quiche
    """, wd)

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    sm = rw.sidebar.sidebarModel

    delish = sb.findNode(lambda n: n.data == "refs/heads/delish")
    drink = sb.findNode(lambda n: n.data == "refs/heads/delish/drink")
    quiche = sb.findNodeByRef("refs/heads/delish/quiche")
    gazpacho = sb.findNodeByRef("refs/heads/delish/drink/gazpacho")

    localBranchesNode = sb.findNodeByKind(SidebarItem.LocalBranchesHeader)
    sb.selectNode(localBranchesNode)

    def reachable():
        return {n for n in (delish, quiche, drink, gazpacho) if sm.isAncestryChainExpanded(n)}

    triggerContextMenuAction(sb.viewport(), "collapse all folders")
    assert reachable() == {delish}

    index = sb.nodeToFilterIndex(delish)
    sb.expand(index)
    assert reachable() == {delish, quiche, drink}

    triggerContextMenuAction(sb.viewport(), "expand all folders")
    assert reachable() == {delish, quiche, drink, gazpacho}


def testRefreshKeepsSidebarNonRefSelection(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    sb.setFocus()

    node = sb.findNodeByKind(SidebarItem.Remote)
    assert node.data == "origin"
    sb.selectNode(node)

    rw.refreshRepo()
    node = sb.filterIndexToNode(sb.selectedIndexes()[0])
    assert node.kind == SidebarItem.Remote
    assert node.data == "origin"


def testNewEmptyRemoteShowsUpInSidebar(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    assert 1 == sb.countNodesByKind(SidebarItem.Remote)

    rw.repo.remotes.create("toto", "https://github.com/jorio/bugdom")
    rw.refreshRepo()
    assert 2 == sb.countNodesByKind(SidebarItem.Remote)


@pytest.mark.parametrize("headerKind,leafKind", [
    (SidebarItem.LocalBranchesHeader, SidebarItem.LocalBranch),
    (SidebarItem.RemotesHeader, SidebarItem.RemoteBranch),
    (SidebarItem.TagsHeader, SidebarItem.Tag),
])
def testRefSortModes(tempDir, mainWindow, headerKind, leafKind):
    assert headerKind != leafKind

    wd = unpackRepo(tempDir)

    shell("""
        git tag version2 83834a7
        git tag version10 6e14752
        git tag VERSION3 49322bb
    """, wd)

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    headerNode = sb.findNodeByKind(headerKind)

    def getNodeDatas():
        return [node.data for node in rw.sidebar.findNodesByKind(leafKind)]

    sortedByTimeDesc = getNodeDatas()
    sortedByTimeAsc = list(reversed(sortedByTimeDesc))
    sortedByNameAsc = sorted(getNodeDatas(), key=naturalSort)
    sortedByNameDesc = list(reversed(sortedByNameAsc))

    triggerMenuAction(sb.makeNodeMenu(headerNode), "sort.+by/newest first")
    assert getNodeDatas() == sortedByTimeDesc

    triggerMenuAction(sb.makeNodeMenu(headerNode), "sort.+by/oldest first")
    assert getNodeDatas() == sortedByTimeAsc

    triggerMenuAction(sb.makeNodeMenu(headerNode), "sort.+by/name.+a-z")
    assert getNodeDatas() == sortedByNameAsc

    # Special case for tags - test natural sorting
    if leafKind == SidebarItem.Tag:
        assert [data.removeprefix("refs/tags/") for data in getNodeDatas()
                ] == ["annotated_tag", "version2", "VERSION3", "version10"]

    triggerMenuAction(sb.makeNodeMenu(headerNode), "sort.+by/name.+z-a")
    assert getNodeDatas() == sortedByNameDesc

    # Test clearing via prefs
    pause(1)  # Let a full second roll over so that refSortResetDate (timestamp) changes
    dlg = GFApplication.instance().openPrefsDialog("refSort")
    comboBox: QComboBox = dlg.findChild(QWidget, "prefctl_refSort")
    qcbSetIndex(comboBox, "name.+a-z")
    dlg.accept()
    acceptQMessageBox(mainWindow, "take effect.+until you reload")
    del rw, sb
    rw = mainWindow.currentRepoWidget()
    assert getNodeDatas() == sortedByNameAsc


def testRefFolderSidebarDisplayNames(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        git branch 1/2A/3A
        git branch 1/2A/3B
        git branch 1/2B
        git branch 4/5/6/7A
        git branch 4/5/6/7B
    """, wd)

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    def getRefFolderDisplayName(explicit):
        node = sb.findNode(lambda n: n.data == explicit and n.kind == SidebarItem.RefFolder)
        return node.displayName

    assert getRefFolderDisplayName("refs/heads/1") == "1"
    assert getRefFolderDisplayName("refs/heads/1/2A") == "2A"
    assert getRefFolderDisplayName("refs/heads/4/5/6") == "4/5/6"


@pytest.mark.parametrize("explicit,implicit", [
    ("refs/heads/1/2A/3B", []),
    ("refs/heads/1/2A", ["refs/heads/1/2A/3A", "refs/heads/1/2A/3B"]),
    ("refs/heads/1", ["refs/heads/1/2A/3A", "refs/heads/1/2A/3B", "refs/heads/1/2B"]),
    ("refs/remotes/origin/no-parent", []),
    ("origin", ["refs/remotes/origin/master", "refs/remotes/origin/no-parent", "refs/remotes/origin/first-merge"])
])
@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarclick"])
def testHideNestedRefFolders(tempDir, mainWindow, explicit, implicit, method):
    wd = unpackRepo(tempDir)
    shell("""
        git branch 1/2A/3A
        git branch 1/2A/3B
        git branch 1/2B
    """, wd)

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    sm = rw.sidebar.sidebarModel

    node = sb.findNode(lambda n: n.data == explicit)

    # Trigger wantHideNode(node)
    if method == "sidebarmenu":
        triggerMenuAction(sb.makeNodeMenu(node), "hide in graph")
    elif method == "sidebarclick":
        index = sb.nodeToFilterIndex(node)
        rect = sb.visualRect(index)
        QTest.mouseClick(sb.viewport(), Qt.MouseButton.LeftButton, pos=rect.topRight())
    else:
        raise NotImplementedError(f"unknown method {method}")

    for node in rw.sidebar.walk():
        index = sb.nodeToFilterIndex(node)
        tip = index.data(Qt.ItemDataRole.ToolTipRole)

        if not node.isLeafBranchKind():
            pass
        elif node.data == explicit:
            assert re.search(r"hidden", tip, re.IGNORECASE)
            assert sm.isExplicitlyHidden(node)
        else:
            hidden = node.data in implicit
            assert hidden == sm.isImplicitlyHidden(node)
            assert hidden ^ (not re.search(r"indirectly hidden", tip, re.IGNORECASE))


@pytest.mark.parametrize("explicit,implicit", [
    ("refs/heads/master", []),
    ("refs/heads/no-parent", []),
    ("refs/heads/1", ["refs/heads/1/2A/3A", "refs/heads/1/2A/3B", "refs/heads/1/2B"]),
    ("refs/heads/1/2A", ["refs/heads/1/2A/3A", "refs/heads/1/2A/3B"]),
    ("refs/remotes/origin/no-parent", []),
    ("origin", ["refs/remotes/origin/master", "refs/remotes/origin/no-parent", "refs/remotes/origin/first-merge"])
])
@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarclick"])
def testHideAllButThis(tempDir, mainWindow, explicit, implicit, method):
    leafRefs = {
        "refs/heads/master",
        "refs/heads/no-parent",
        "refs/heads/1/2B",
        "refs/heads/1/2A/3A",
        "refs/heads/1/2A/3B",
        "refs/remotes/origin/master",
        "refs/remotes/origin/no-parent",
        "refs/remotes/origin/first-merge",
    }

    wd = unpackRepo(tempDir)
    shell("""
        git branch 1/2A/3A
        git branch 1/2A/3B
        git branch 1/2B
    """, wd)

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    sm = rw.sidebar.sidebarModel

    node = sb.findNode(lambda n: n.data == explicit)

    # Trigger wantHideNode(node)
    if method == "sidebarmenu":
        triggerMenuAction(sb.makeNodeMenu(node), "hide all but this")
    elif method == "sidebarclick":
        index = sb.nodeToFilterIndex(node)
        rect = sb.visualRect(index)
        QTest.mouseClick(sb.viewport(), Qt.MouseButton.MiddleButton, pos=rect.topRight())
    else:
        raise NotImplementedError(f"unknown method {method}")

    assert sm.isHideAllButThisMode()

    hiddenRefs = leafRefs - set(implicit)
    hiddenRefs.discard(explicit)

    for node in rw.sidebar.walk():
        index = sb.nodeToFilterIndex(node)
        tip = index.data(Qt.ItemDataRole.ToolTipRole)

        if not node.isLeafBranchKind():
            pass
        elif node.data == explicit:
            assert sm.isExplicitlyShown(node)
            assert re.search(r"hiding everything but this", tip, re.IGNORECASE)
        else:
            hidden = node.data in hiddenRefs
            assert hidden == sm.isImplicitlyHidden(node)
            assert hidden ^ (not re.search(r"indirectly hidden", tip, re.IGNORECASE))

    # Workdir row must always be visible
    uncommittedChangesIndex = rw.graphView.getFilterIndexForCommit(UC_FAKEID)
    assert uncommittedChangesIndex.isValid()
    assert uncommittedChangesIndex.row() == 0


def testSidebarToolTips(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    shell("""
        git tag folder/leaf HEAD
        git branch folder/leaf
        mkdir -p .git/refs/remotes/origin/folder
        git rev-parse HEAD > .git/refs/remotes/origin/folder/leaf
    """, wd)

    rw = mainWindow.openRepo(wd)

    def test(kind, data, *patterns):
        node = rw.sidebar.findNode(lambda n: n.kind == kind and n.data == data)
        index = rw.sidebar.nodeToFilterIndex(node)
        tip = index.data(Qt.ItemDataRole.ToolTipRole)
        for pattern in patterns:
            assert re.search(pattern, tip, re.IGNORECASE), f"pattern missing in tooltip: {tip}"

    test(SidebarItem.LocalBranch, "refs/heads/master",
         r"local branch", r"upstream.+origin/master", r"checked.out")

    test(SidebarItem.RemoteBranch, "refs/remotes/origin/master",
         r"origin/master", r"remote-tracking branch", r"upstream for.+checked.out.+\bmaster\b")

    test(SidebarItem.Tag, "refs/tags/annotated_tag", r"\btag\b")
    test(SidebarItem.UncommittedChanges, "", r"go to working directory.+(ctrl|⌘)")
    test(SidebarItem.UncommittedChanges, "", r"0 uncommitted changes")
    test(SidebarItem.Remote, "origin", r"https://github.com/libgit2/TestGitRepository")
    test(SidebarItem.RefFolder, "refs/heads/folder", r"local branch folder")
    test(SidebarItem.RefFolder, "refs/remotes/origin/folder", r"remote branch folder")
    test(SidebarItem.RefFolder, "refs/tags/folder", r"tag folder")


def testSidebarHeadIconAfterSwitchingBranchesPointingToSameCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git branch other-master", wd)

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    masterIcon = sb.indexForRef("refs/heads/master").data(SidebarModel.Role.IconKey)
    otherIcon = sb.indexForRef("refs/heads/other-master").data(SidebarModel.Role.IconKey)
    assert masterIcon == "git-head"
    assert otherIcon == "git-branch"

    triggerMenuAction(sb.makeNodeMenu(sb.findNodeByRef("refs/heads/other-master")), "switch")
    acceptQMessageBox(rw, "switch")

    masterIcon = sb.indexForRef("refs/heads/master").data(SidebarModel.Role.IconKey)
    otherIcon = sb.indexForRef("refs/heads/other-master").data(SidebarModel.Role.IconKey)
    assert masterIcon == "git-branch"
    assert otherIcon == "git-head"


def testSidebarVisitRemoteWebPage(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git branch other-master", wd)

    rw = mainWindow.openRepo(wd)

    with MockDesktopServicesContext() as services:
        node = rw.sidebar.findNode(lambda n: n.data == "origin" and n.kind == SidebarItem.Remote)
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "visit web page")
        assert services.urls[-1] == QUrl("https://github.com/libgit2/TestGitRepository")

        node = rw.sidebar.findNodeByRef("refs/remotes/origin/master")
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "visit web page")
        assert services.urls[-1] == QUrl("https://github.com/libgit2/TestGitRepository/tree/master")


def testSidebarAheadBehind(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        git branch ahead17 6e14752
        git branch ahead17 -u origin/no-parent
        git branch behind3 6e14752
        git branch behind3 -u origin/master
        git branch ahead10-behind1 c070ad8
        git branch ahead10-behind1 -u origin/no-parent
    """, wd)

    rw = mainWindow.openRepo(wd)

    index = rw.sidebar.indexForRef("refs/heads/ahead17")
    tip = index.data(Qt.ItemDataRole.ToolTipRole)
    assert re.search("17 commits ahead", tip, re.IGNORECASE)
    assert not re.search("commits? behind", tip, re.IGNORECASE)

    index = rw.sidebar.indexForRef("refs/heads/behind3")
    tip = index.data(Qt.ItemDataRole.ToolTipRole)
    assert re.search("3 commits behind", tip, re.IGNORECASE)
    assert not re.search("commits? ahead", tip, re.IGNORECASE)

    index = rw.sidebar.indexForRef("refs/heads/ahead10-behind1")
    tip = index.data(Qt.ItemDataRole.ToolTipRole)
    assert re.search("10 commits ahead", tip, re.IGNORECASE)
    assert re.search("1 commit behind", tip, re.IGNORECASE)

    index = rw.sidebar.indexForRef("refs/heads/no-parent")
    tip = index.data(Qt.ItemDataRole.ToolTipRole)
    assert not re.search("commits? ahead", tip, re.IGNORECASE)
    assert not re.search("commit? behind", tip, re.IGNORECASE)
    assert re.search("up-to-date with upstream", tip, re.IGNORECASE)


def testSidebarMissingUpstream(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git config branch.master.merge refs/heads/missing-upstream", wd)

    rw = mainWindow.openRepo(wd)

    index = rw.sidebar.indexForRef("refs/heads/master")
    tip = index.data(Qt.ItemDataRole.ToolTipRole)
    assert re.search(r"upstream missing \(origin/missing-upstream\)", tip, re.IGNORECASE)

    node = rw.sidebar.findNodeByRef("refs/heads/master")
    menu = rw.sidebar.makeNodeMenu(node)
    missingUpstreamAction = findMenuAction(menu, r"upstream.+\(missing\)/origin.missing-upstream \(missing\)")
    assert missingUpstreamAction.isChecked()

    # If we ever choose to not disable this action, the action callback should be tested as well.
    assert not missingUpstreamAction.isEnabled()


def testSidebarFilterPersistsAcrossRefresh(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        git branch feature/login
        git branch bugfix/issue-123
    """, wd)

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    searchBar = _summonSearchBar(rw)

    # Apply filter
    sb.searchBar.lineEdit.setText("feature")
    assert sb.indexForRef("refs/heads/feature/login").isValid()
    assert not sb.indexForRef("refs/heads/bugfix/issue-123").isValid()

    # Modify the repo such that the sidebar model becomes stale, then refresh
    shell("git branch feature/logout", wd)
    rw.refreshRepo()

    # Filter should still be applied
    assert searchBar.rawSearchTerm == "feature"
    assert rw.sidebar.indexForRef("refs/heads/feature/login").isValid()
    assert rw.sidebar.indexForRef("refs/heads/feature/logout").isValid()
    assert not rw.sidebar.indexForRef("refs/heads/bugfix/issue-123").isValid()


def testSidebarFilter(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        git branch feature/login
        git branch feature/signup
        git branch bugfix/issue-123
        git branch hotfix/critical
    """, wd)

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    searchBar = _summonSearchBar(rw)

    # Test initial state
    assert searchBar.rawSearchTerm == ""
    allBranches = sb.findNodesByKind(SidebarItem.LocalBranch)
    assert len(allBranches) >= 6  # master, no-parent, feature/*, bugfix/*, hotfix/*

    # Test filtering by "feature"
    searchBar.lineEdit.setText("feature")

    # Visible: feature branches
    assert sb.indexForRef("refs/heads/feature/login").isValid()
    assert sb.indexForRef("refs/heads/feature/signup").isValid()
    # Hidden: unrelated branches
    assert not sb.indexForRef("refs/heads/no-parent").isValid()
    assert not sb.indexForRef("refs/heads/master").isValid()

    # Test clearing filter
    searchBar.lineEdit.clear()
    assert searchBar.rawSearchTerm == ""
    # All branches visible again after clearing
    assert sb.indexForRef("refs/heads/master").isValid()
    assert sb.indexForRef("refs/heads/no-parent").isValid()

    # Test case-insensitive filtering
    searchBar.lineEdit.setText("FEATURE")
    assert sb.indexForRef("refs/heads/feature/login").isValid()
    assert sb.indexForRef("refs/heads/feature/signup").isValid()
    assert not sb.indexForRef("refs/heads/no-parent").isValid()

    # Test substring matching
    searchBar.lineEdit.setText("fix")
    assert sb.indexForRef("refs/heads/bugfix/issue-123").isValid()
    assert sb.indexForRef("refs/heads/hotfix/critical").isValid()
    # "no-parent" doesn't contain "fix", so it must be hidden
    assert not sb.indexForRef("refs/heads/no-parent").isValid()

    # Hide with keyboard shortcut
    sb.setFocus()
    QTest.keyClick(sb, Qt.Key.Key_Escape)
    assert not searchBar.isVisible()


def testSidebarFilterWithFolders(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        git branch team/frontend/login
        git branch team/frontend/signup
        git branch team/backend/api
    """, wd)

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    searchBar = _summonSearchBar(rw)

    # Filtering by "login" should show the matching branch and hide others
    searchBar.lineEdit.setText("login")
    assert sb.indexForRef("refs/heads/team/frontend/login").isValid()
    assert not sb.indexForRef("refs/heads/team/backend/api").isValid()
    assert not sb.indexForRef("refs/heads/team/frontend/signup").isValid()

    # Test filtering remote branches
    searchBar.lineEdit.setText("origin")
    # Remote node should be visible
    assert sb.nodeToFilterIndex(sb.findNode(lambda n: n.data == "origin")).isValid()


def testSidebarFilterWithTags(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        git tag v1.0.0 HEAD
        git tag v2.0.0 HEAD
        git tag release-2024 HEAD
    """, wd)

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    searchBar = _summonSearchBar(rw)

    # Filtering by "v1" should show v1.0.0 and hide the others
    searchBar.lineEdit.setText("v1")
    assert sb.indexForRef("refs/tags/v1.0.0").isValid()
    assert not sb.indexForRef("refs/tags/v2.0.0").isValid()
    assert not sb.indexForRef("refs/tags/release-2024").isValid()


def testSidebarFilterPreservesSelection(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git branch feature/test", wd)

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    searchBar = _summonSearchBar(rw)

    # Select a branch
    featureNode = sb.findNodeByRef("refs/heads/feature/test")
    sb.selectNode(featureNode)

    selectedBefore = sb.selectedIndexes()[0].data()
    assert "test" in selectedBefore

    # Filter that keeps the selected item visible
    searchBar.lineEdit.setText("feature")

    # The selected item should still be visible in the proxy model
    assert sb.indexForRef("refs/heads/feature/test").isValid()
    assert len(sb.selectedIndexes()) > 0


def testSidebarFilterCollapseState(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("""
        git branch folder1/leaf
        git branch folder2/leaf
        git branch folder3/leaf
    """, wd)

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    # Bypass isAncestryChainExpanded
    def isExpanded(ref: str) -> bool:
        i = sb.indexForRef(ref)
        assert i.isValid()

        i = i.parent()
        while i.isValid():
            if not sb.isExpanded(i):
                return False
            i = i.parent()
        return True

    # Collapse all local branch folders first
    localBranchesNode = sb.findNodeByKind(SidebarItem.LocalBranchesHeader)
    sb.selectNode(localBranchesNode)
    triggerContextMenuAction(sb.viewport(), "collapse all folders")
    assert not isExpanded("refs/heads/folder1/leaf")
    assert not isExpanded("refs/heads/folder2/leaf")
    assert not isExpanded("refs/heads/folder3/leaf")

    # Summon search bar, search for "leaf"
    searchBar = _summonSearchBar(rw)
    searchBar.lineEdit.setText("leaf")
    assert isExpanded("refs/heads/folder1/leaf")
    assert isExpanded("refs/heads/folder2/leaf")
    assert isExpanded("refs/heads/folder3/leaf")

    # Search for a term with no matches, then revert to searching for "leaf"
    searchBar.lineEdit.setText("bogusbogus")
    assert not sb.indexForRef("refs/heads/folder1/leaf").isValid()
    searchBar.lineEdit.setText("leaf")
    assert isExpanded("refs/heads/folder1/leaf")
    assert isExpanded("refs/heads/folder2/leaf")
    assert isExpanded("refs/heads/folder3/leaf")

    # Select folder2/leaf before closing search bar
    sb.selectAnyRef("refs/heads/folder2/leaf")

    # Close search bar
    searchBar.bail()

    # folder1 & folder3 must be collapsed, as they were before filtering.
    assert not isExpanded("refs/heads/folder1/leaf")
    assert not isExpanded("refs/heads/folder3/leaf")
    # folder2 was originally collapsed, but it should now be expanded because
    # we selected it before closing the search bar.
    assert isExpanded("refs/heads/folder2/leaf")


# -----------------------------------------------------------------------------
# Enter/Rename/Delete actions on each node kind, and mouse click zones

@pytest.fixture
def beepCounter(monkeypatch):
    beeps = []
    monkeypatch.setattr(QApplication, "beep", lambda: beeps.append(True))
    return beeps


def _findSidebarNode(sb, kind: SidebarItem, data: str = ""):
    if not data:
        return sb.findNodeByKind(kind)
    return sb.findNode(lambda n: n.kind == kind and n.data == data)


def _enterSidebarNode(sb, node, method: str):
    if method == "key":
        sb.setFocus()
        sb.selectNode(node)
        QTest.keyPress(sb, Qt.Key.Key_Return)
    elif method == "dclick":
        rect = sb.visualRect(sb.nodeToFilterIndex(node))
        QTest.mouseDClick(sb.viewport(), Qt.MouseButton.LeftButton, pos=rect.topLeft())
    else:
        raise NotImplementedError(f"unknown method {method}")


def _keyOnSidebarNode(sb, node, key: Qt.Key):
    sb.setFocus()
    if node is None:
        sb.clearSelection()
    else:
        sb.selectNode(node)
    QTest.keyPress(sb, key)


def _sidebarClickPos(sb, node, zone: str) -> QPoint:
    rect = sb.visualRect(sb.nodeToFilterIndex(node))
    if zone == "select":
        return rect.center()
    elif zone == "expand":
        return QPoint(rect.left() - sb.indentation() // 2, rect.center().y())
    elif zone == "hide":
        return QPoint(rect.right(), rect.center().y())
    raise NotImplementedError(f"unknown zone {zone}")


@pytest.mark.parametrize("method", ["key", "dclick"])
def testSidebarEnterLocalBranchSwitches(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    _enterSidebarNode(sb, sb.findNodeByRef("refs/heads/no-parent"), method)
    acceptQMessageBox(rw, "switch to.+no-parent")
    assert rw.repo.head_branch_shorthand == "no-parent"


@pytest.mark.parametrize("method", ["key", "dclick"])
def testSidebarEnterCurrentBranch(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    _enterSidebarNode(sb, sb.findNodeByRef("refs/heads/master"), method)
    acceptQMessageBox(rw, "already checked.out")
    assert rw.repo.head_branch_shorthand == "master"


@pytest.mark.parametrize("method", ["key", "dclick"])
@pytest.mark.parametrize("kind,data,dialogPattern", [
    (SidebarItem.Remote, "origin", "edit remote"),
    (SidebarItem.RemotesHeader, "", "add remote"),
    (SidebarItem.LocalBranchesHeader, "", "new branch"),
    (SidebarItem.TagsHeader, "", "new tag"),
    (SidebarItem.RemoteBranch, "refs/remotes/origin/first-merge", "new branch"),
    (SidebarItem.Tag, "refs/tags/annotated_tag", "check.?out commit"),
])
def testSidebarEnterNodeOpensDialog(tempDir, mainWindow, method, kind, data, dialogPattern):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    _enterSidebarNode(sb, _findSidebarNode(sb, kind, data), method)
    dlg = findQDialog(rw, dialogPattern)

    if kind == SidebarItem.RemoteBranch:
        assert dlg.ui.nameEdit.text() == "first-merge"

    dlg.reject()


def testSidebarEnterDetachedHead(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git checkout 7f82283", wd)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    _enterSidebarNode(sb, sb.findNodeByKind(SidebarItem.DetachedHead), "key")
    dlg = findQDialog(rw, "new branch")
    dlg.ui.nameEdit.setText("rescued")
    dlg.accept()

    assert rw.repo.head_branch_shorthand == "rescued"
    assert str(rw.repo.head_commit_id).startswith("7f82283")


@pytest.mark.parametrize("method", ["key", "dclick"])
def testSidebarEnterUncommittedChanges(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    # Nothing is staged, so NewCommit asks about creating an empty commit
    _enterSidebarNode(sb, sb.findNodeByKind(SidebarItem.UncommittedChanges), method)
    rejectQMessageBox(rw, "empty commit")


def testSidebarEnterStashesHeaderWithoutChanges(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    _enterSidebarNode(sb, sb.findNodeByKind(SidebarItem.StashesHeader), "key")
    acceptQMessageBox(rw, "no.+changes to stash")


@pytest.mark.parametrize("method", ["key", "dclick"])
def testSidebarEnterStash(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    reposcenario.stashedChange(wd)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    _enterSidebarNode(sb, sb.findNodeByKind(SidebarItem.Stash), method)
    rejectQMessageBox(rw, "apply.+stash")
    assert len(rw.repo.listall_stashes()) == 1


def testSidebarEnterSubmodule(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    submoAbsPath, _submoCommit = reposcenario.submodule(wd)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    _enterSidebarNode(sb, sb.findNodeByKind(SidebarItem.Submodule), "key")

    if WINDOWS:
        submoAbsPath = submoAbsPath.replace("\\", "/")
    assert mainWindow.currentRepoWidget() is not rw
    assert mainWindow.currentRepoWidget().repo.workdir == submoAbsPath + "/"


@pytest.mark.parametrize("kind,data", [
    (None, ""),
    (SidebarItem.SubmodulesHeader, ""),
    (SidebarItem.RefFolder, "refs/heads/folder"),
    (SidebarItem.RefFolder, "refs/tags/folder"),
])
def testSidebarEnterUnsupportedNodeBeeps(tempDir, mainWindow, beepCounter, kind, data):
    wd = unpackRepo(tempDir)
    shell("""
        git branch folder/leaf
        git tag folder/leaf
    """, wd)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    node = _findSidebarNode(sb, kind, data) if kind is not None else None
    _keyOnSidebarNode(sb, node, Qt.Key.Key_Return)
    assert len(beepCounter) == 1


def testSidebarSpacerActionsAreNoOps(tempDir, mainWindow, beepCounter):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    spacer = sb.findNodesByKind(SidebarItem.Spacer)[0]
    sb.wantEnterNode(spacer)
    sb.wantRenameNode(spacer)
    sb.wantDeleteNode(spacer)
    assert not beepCounter

    # Spacers can't be clicked
    rect = sb.visualRect(sb.nodeToFilterIndex(spacer))
    mouseSpecialClick(sb.viewport(), "double", rect.center())
    assert not beepCounter


@pytest.mark.parametrize("kind,data,dialogPattern", [
    (SidebarItem.LocalBranch, "refs/heads/master", "rename.+branch"),
    (SidebarItem.Remote, "origin", "edit remote"),
    (SidebarItem.RefFolder, "refs/heads/folder", "rename.+folder"),
])
def testSidebarRenameNodeOpensDialog(tempDir, mainWindow, kind, data, dialogPattern):
    wd = unpackRepo(tempDir)
    shell("git branch folder/leaf", wd)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    _keyOnSidebarNode(sb, _findSidebarNode(sb, kind, data), Qt.Key.Key_F2)
    findQDialog(rw, dialogPattern).reject()


def testSidebarRenameRemoteBranchWithF2(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    _keyOnSidebarNode(sb, sb.findNodeByRef("refs/remotes/origin/first-merge"), Qt.Key.Key_F2)
    dlg = findQDialog(rw, "rename remote branch")
    assert dlg.lineEdit.text() == "first-merge"
    dlg.reject()


@pytest.mark.parametrize("kind,data", [
    (None, ""),
    (SidebarItem.Tag, "refs/tags/annotated_tag"),
    (SidebarItem.Stash, ""),
    (SidebarItem.UncommittedChanges, ""),
    (SidebarItem.LocalBranchesHeader, ""),
    (SidebarItem.RefFolder, "refs/tags/folder"),
    (SidebarItem.RefFolder, "refs/remotes/origin/folder"),
])
def testSidebarRenameUnsupportedNodeBeeps(tempDir, mainWindow, beepCounter, kind, data):
    wd = unpackRepo(tempDir)
    reposcenario.stashedChange(wd)
    shell("""
        git tag folder/leaf
        mkdir -p .git/refs/remotes/origin/folder
        git rev-parse HEAD > .git/refs/remotes/origin/folder/leaf
    """, wd)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    node = _findSidebarNode(sb, kind, data) if kind is not None else None
    _keyOnSidebarNode(sb, node, Qt.Key.Key_F2)
    assert len(beepCounter) == 1


@pytest.mark.parametrize("kind,data,prompt", [
    (SidebarItem.LocalBranch, "refs/heads/no-parent", "really delete.+branch"),
    (SidebarItem.Remote, "origin", "really remove remote"),
    (SidebarItem.RemoteBranch, "refs/remotes/origin/first-merge", "really delete branch.+from the remote"),
    (SidebarItem.RefFolder, "refs/heads/folder", "really delete.+branch folder"),
    (SidebarItem.Stash, "", "really delete.+stash"),
])
def testSidebarDeleteNodePrompts(tempDir, mainWindow, kind, data, prompt):
    wd = unpackRepo(tempDir)
    reposcenario.stashedChange(wd)
    shell("git branch folder/leaf", wd)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    _keyOnSidebarNode(sb, _findSidebarNode(sb, kind, data), Qt.Key.Key_Delete)
    rejectQMessageBox(rw, prompt)


def testSidebarDeleteTagOpensDialog(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    _keyOnSidebarNode(sb, sb.findNodeByRef("refs/tags/annotated_tag"), Qt.Key.Key_Delete)
    findQDialog(rw, "delete tag").reject()
    assert "refs/tags/annotated_tag" in rw.repo.references


@pytest.mark.parametrize("kind,data", [
    (None, ""),
    (SidebarItem.UncommittedChanges, ""),
    (SidebarItem.TagsHeader, ""),
    (SidebarItem.RefFolder, "refs/tags/folder"),
])
def testSidebarDeleteUnsupportedNodeBeeps(tempDir, mainWindow, beepCounter, kind, data):
    wd = unpackRepo(tempDir)
    shell("git tag folder/leaf", wd)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    node = _findSidebarNode(sb, kind, data) if kind is not None else None
    _keyOnSidebarNode(sb, node, Qt.Key.Key_Delete)
    assert len(beepCounter) == 1


def testSidebarClickSelectZone(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    node = sb.findNodeByRef("refs/heads/no-parent")
    QTest.mouseClick(sb.viewport(), Qt.MouseButton.LeftButton, pos=_sidebarClickPos(sb, node, "select"))
    assert sb.selectedNode() is node
    assert rw.graphView.currentCommitId == rw.repo.branches.local["no-parent"].target
    assert not sb.sidebarModel.isExplicitlyHidden(node)


def testSidebarMiddleClickSelectZoneDoesNothingSpecial(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.stashedChange(wd)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    sm = sb.sidebarModel

    for node in [sb.findNodeByRef("refs/heads/no-parent"), sb.findNodeByKind(SidebarItem.Stash)]:
        mouseSpecialClick(sb.viewport(), "middle", _sidebarClickPos(sb, node, "select"))
        assert not sm.isHideAllButThisMode()
        assert not sm.isExplicitlyHidden(node)

    # No prompts (e.g. drop stash) must have appeared
    assert not [qmb for qmb in rw.findChildren(QMessageBox) if qmb.isVisibleTo(rw)]
    assert len(rw.repo.listall_stashes()) == 1


def testSidebarClickHideZoneRequiresSameRowOnRelease(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    sm = sb.sidebarModel

    master = sb.findNodeByRef("refs/heads/master")
    noParent = sb.findNodeByRef("refs/heads/no-parent")

    # Press on master's eye, release on no-parent's eye: neither must be hidden
    QTest.mousePress(sb.viewport(), Qt.MouseButton.LeftButton, pos=_sidebarClickPos(sb, master, "hide"))
    QTest.mouseRelease(sb.viewport(), Qt.MouseButton.LeftButton, pos=_sidebarClickPos(sb, noParent, "hide"))
    assert not sm.isExplicitlyHidden(master)
    assert not sm.isExplicitlyHidden(noParent)

    # Press and release on the same eye: hides the branch
    QTest.mouseClick(sb.viewport(), Qt.MouseButton.LeftButton, pos=_sidebarClickPos(sb, noParent, "hide"))
    assert sm.isExplicitlyHidden(noParent)
    assert not sm.isExplicitlyHidden(master)


def testSidebarHideNodeWithoutPatternIsNoOp(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    emissions = []
    sb.toggleHideRefPattern.connect(lambda *args: emissions.append(args))
    sb.wantHideNode(sb.findNodeByKind(SidebarItem.TagsHeader))
    assert not emissions


def testSidebarClickExpandZone(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    sm = sb.sidebarModel

    remoteNode = sb.findNode(lambda n: n.kind == SidebarItem.Remote and n.data == "origin")
    remoteIndex = sb.nodeToFilterIndex(remoteNode)
    remoteBranch = sb.findNodeByRef("refs/remotes/origin/master")
    assert sb.isExpanded(remoteIndex)

    pos = _sidebarClickPos(sb, remoteNode, "expand")
    QTest.mouseClick(sb.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert not sb.isExpanded(remoteIndex)
    assert not sm.isAncestryChainExpanded(remoteBranch)

    QTest.mouseClick(sb.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert sb.isExpanded(remoteIndex)
    assert sm.isAncestryChainExpanded(remoteBranch)

    # Clicking the expand zone must not select the node
    assert sb.selectedNode() is not remoteNode

    # Double-clicking the expand zone must not "enter" the node (which would open the remote editor)
    mouseSpecialClick(sb.viewport(), "double", pos)
    assert not [dlg for dlg in rw.findChildren(QDialog) if dlg.isVisible()]
