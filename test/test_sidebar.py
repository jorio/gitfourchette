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
from .util import *


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

    with RepoContext(wd) as repo:
        repo.checkout_commit(Oid(hex="7f822839a2fe9760f386cbbbcb3f92c5fe81def7"))

    rw = mainWindow.openRepo(wd)

    headNode = rw.sidebar.findNodeByRef("HEAD")
    assert headNode.kind == SidebarItem.DetachedHead
    assert headNode == rw.sidebar.findNodeByKind(SidebarItem.DetachedHead)

    toolTip = rw.sidebar.nodeToFilterIndex(headNode).data(Qt.ItemDataRole.ToolTipRole)
    assert re.search(r"detached head.+7f82283", toolTip, re.I)

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

    with RepoContext(wd) as repo:
        repo.create_branch_on_head("delish/drink/gazpacho")
        repo.create_branch_on_head("delish/quiche")

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

    with RepoContext(wd) as repo:
        repo.create_tag("version2", Oid(hex='83834a7afdaa1a1260568567f6ad90020389f664'), ObjectType.COMMIT, TEST_SIGNATURE, "")
        repo.create_tag("version10", Oid(hex='6e1475206e57110fcef4b92320436c1e9872a322'), ObjectType.COMMIT, TEST_SIGNATURE, "")
        repo.create_tag("VERSION3", Oid(hex='49322bb17d3acc9146f98c97d078513228bbf3c0'), ObjectType.COMMIT, TEST_SIGNATURE, "")

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
    dlg = mainWindow.openPrefsDialog("refSort")
    comboBox: QComboBox = dlg.findChild(QWidget, "prefctl_refSort")
    qcbSetIndex(comboBox, "name.+a-z")
    dlg.accept()
    acceptQMessageBox(mainWindow, "take effect.+until you reload")
    del rw, sb
    rw = mainWindow.currentRepoWidget()
    assert getNodeDatas() == sortedByNameAsc


def testRefFolderSidebarDisplayNames(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.create_branch_on_head("1/2A/3A")
        repo.create_branch_on_head("1/2A/3B")
        repo.create_branch_on_head("1/2B")
        repo.create_branch_on_head("4/5/6/7A")
        repo.create_branch_on_head("4/5/6/7B")

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
    with RepoContext(wd) as repo:
        repo.create_branch_on_head("1/2A/3A")
        repo.create_branch_on_head("1/2A/3B")
        repo.create_branch_on_head("1/2B")

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
            assert re.search(r"hidden", tip, re.I)
            assert sm.isExplicitlyHidden(node)
        else:
            hidden = node.data in implicit
            assert hidden == sm.isImplicitlyHidden(node)
            assert hidden ^ (not re.search(r"indirectly hidden", tip, re.I))


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
    with RepoContext(wd) as repo:
        repo.create_branch_on_head("1/2A/3A")
        repo.create_branch_on_head("1/2A/3B")
        repo.create_branch_on_head("1/2B")

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
            assert re.search(r"hiding everything but this", tip, re.I)
        else:
            hidden = node.data in hiddenRefs
            assert hidden == sm.isImplicitlyHidden(node)
            assert hidden ^ (not re.search(r"indirectly hidden", tip, re.I))

    # Workdir row must always be visible
    uncommittedChangesIndex = rw.graphView.getFilterIndexForCommit(UC_FAKEID)
    assert uncommittedChangesIndex.isValid()
    assert uncommittedChangesIndex.row() == 0


def testSidebarToolTips(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.create_tag("folder/leaf", repo.head_commit_id, ObjectType.COMMIT, TEST_SIGNATURE, "hello")
        repo.create_branch_on_head("folder/leaf")
        writeFile(f"{wd}/.git/refs/remotes/origin/folder/leaf", str(repo.head_commit_id) + "\n")

    rw = mainWindow.openRepo(wd)

    def test(kind, data, *patterns):
        node = rw.sidebar.findNode(lambda n: n.kind == kind and n.data == data)
        index = rw.sidebar.nodeToFilterIndex(node)
        tip = index.data(Qt.ItemDataRole.ToolTipRole)
        for pattern in patterns:
            assert re.search(pattern, tip, re.I), f"pattern missing in tooltip: {tip}"

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

    with RepoContext(wd) as repo:
        repo.create_branch_on_head("other-master")

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

    with RepoContext(wd) as repo:
        repo.create_branch_on_head("other-master")

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

    with RepoContext(wd) as repo:
        b = repo.create_branch_from_commit("ahead17", Oid(hex=("6e1475206e57110fcef4b92320436c1e9872a322")))
        b.upstream = repo.branches.remote["origin/no-parent"]

        b = repo.create_branch_from_commit("behind3", Oid(hex=("6e1475206e57110fcef4b92320436c1e9872a322")))
        b.upstream = repo.branches.remote["origin/master"]

        b = repo.create_branch_from_commit("ahead10-behind1", Oid(hex=("c070ad8c08840c8116da865b2d65593a6bb9cd2a")))
        b.upstream = repo.branches.remote["origin/no-parent"]

    rw = mainWindow.openRepo(wd)

    index = rw.sidebar.indexForRef("refs/heads/ahead17")
    tip = index.data(Qt.ItemDataRole.ToolTipRole)
    assert re.search("17 commits ahead", tip, re.I)
    assert not re.search("commits? behind", tip, re.I)

    index = rw.sidebar.indexForRef("refs/heads/behind3")
    tip = index.data(Qt.ItemDataRole.ToolTipRole)
    assert re.search("3 commits behind", tip, re.I)
    assert not re.search("commits? ahead", tip, re.I)

    index = rw.sidebar.indexForRef("refs/heads/ahead10-behind1")
    tip = index.data(Qt.ItemDataRole.ToolTipRole)
    assert re.search("10 commits ahead", tip, re.I)
    assert re.search("1 commit behind", tip, re.I)

    index = rw.sidebar.indexForRef("refs/heads/no-parent")
    tip = index.data(Qt.ItemDataRole.ToolTipRole)
    assert not re.search("commits? ahead", tip, re.I)
    assert not re.search("commit? behind", tip, re.I)
    assert re.search("up-to-date with upstream", tip, re.I)


def testSidebarMissingUpstream(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.config["branch.master.merge"] = "refs/heads/missing-upstream"

    rw = mainWindow.openRepo(wd)

    index = rw.sidebar.indexForRef("refs/heads/master")
    tip = index.data(Qt.ItemDataRole.ToolTipRole)
    assert re.search(r"upstream missing \(origin/missing-upstream\)", tip, re.I)

    node = rw.sidebar.findNodeByRef("refs/heads/master")
    menu = rw.sidebar.makeNodeMenu(node)
    missingUpstreamAction = findMenuAction(menu, r"upstream.+\(missing\)/origin.missing-upstream \(missing\)")
    assert missingUpstreamAction.isChecked()

    # If we ever choose to not disable this action, the action callback should be tested as well.
    assert not missingUpstreamAction.isEnabled()


def testSidebarFilter(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.create_branch_on_head("feature/login")
        repo.create_branch_on_head("feature/signup")
        repo.create_branch_on_head("bugfix/issue-123")
        repo.create_branch_on_head("hotfix/critical")

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    sidebarFilter = rw.sidebarFilter

    # Test initial state
    assert sidebarFilter.filterText == ""
    allBranches = sb.findNodesByKind(SidebarItem.LocalBranch)
    assert len(allBranches) >= 6  # master, no-parent, feature/*, bugfix/*, hotfix/*

    # Test filtering by "feature"
    sidebarFilter.lineEdit.setText("feature")

    # Visible: feature branches
    assert sb.indexForRef("refs/heads/feature/login").isValid()
    assert sb.indexForRef("refs/heads/feature/signup").isValid()
    # Hidden: unrelated branches
    assert not sb.indexForRef("refs/heads/no-parent").isValid()
    assert not sb.indexForRef("refs/heads/master").isValid()

    # Test clearing filter
    sidebarFilter.clear()
    assert sidebarFilter.filterText == ""
    # All branches visible again after clearing
    assert sb.indexForRef("refs/heads/master").isValid()
    assert sb.indexForRef("refs/heads/no-parent").isValid()

    # Test case-insensitive filtering
    sidebarFilter.lineEdit.setText("FEATURE")
    assert sb.indexForRef("refs/heads/feature/login").isValid()
    assert sb.indexForRef("refs/heads/feature/signup").isValid()
    assert not sb.indexForRef("refs/heads/no-parent").isValid()

    # Test substring matching
    sidebarFilter.lineEdit.setText("fix")
    assert sb.indexForRef("refs/heads/bugfix/issue-123").isValid()
    assert sb.indexForRef("refs/heads/hotfix/critical").isValid()
    # "no-parent" doesn't contain "fix", so it must be hidden
    assert not sb.indexForRef("refs/heads/no-parent").isValid()


def testSidebarFilterWithFolders(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.create_branch_on_head("team/frontend/login")
        repo.create_branch_on_head("team/frontend/signup")
        repo.create_branch_on_head("team/backend/api")

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    sidebarFilter = rw.sidebarFilter

    # Filtering by "login" should show the matching branch and hide others
    sidebarFilter.lineEdit.setText("login")
    assert sb.indexForRef("refs/heads/team/frontend/login").isValid()
    assert not sb.indexForRef("refs/heads/team/backend/api").isValid()
    assert not sb.indexForRef("refs/heads/team/frontend/signup").isValid()


def testSidebarFilterKeyboardShortcuts(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sidebarFilter = rw.sidebarFilter

    # Test setting filter text
    sidebarFilter.lineEdit.setText("test")
    assert sidebarFilter.filterText == "test"

    # Test clearing filter
    sidebarFilter.clear()
    assert sidebarFilter.filterText == ""


def testSidebarFilterWithTags(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.create_tag("v1.0.0", repo.head_commit_id, ObjectType.COMMIT, TEST_SIGNATURE, "")
        repo.create_tag("v2.0.0", repo.head_commit_id, ObjectType.COMMIT, TEST_SIGNATURE, "")
        repo.create_tag("release-2024", repo.head_commit_id, ObjectType.COMMIT, TEST_SIGNATURE, "")

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    sidebarFilter = rw.sidebarFilter

    # Filtering by "v1" should show v1.0.0 and hide the others
    sidebarFilter.lineEdit.setText("v1")
    assert sb.indexForRef("refs/tags/v1.0.0").isValid()
    assert not sb.indexForRef("refs/tags/v2.0.0").isValid()
    assert not sb.indexForRef("refs/tags/release-2024").isValid()


def testSidebarFilterPreservesSelection(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.create_branch_on_head("feature/test")

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    sidebarFilter = rw.sidebarFilter

    # Select a branch
    featureNode = sb.findNodeByRef("refs/heads/feature/test")
    sb.selectNode(featureNode)

    selectedBefore = sb.selectedIndexes()[0].data()
    assert "test" in selectedBefore

    # Filter that keeps the selected item visible
    sidebarFilter.lineEdit.setText("feature")

    # The selected item should still be visible in the proxy model
    assert sb.indexForRef("refs/heads/feature/test").isValid()
    assert len(sb.selectedIndexes()) > 0


def testSidebarFilterExpandsAll(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.create_branch_on_head("team/frontend/login")
        repo.create_branch_on_head("team/backend/api")

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    sm = sb.sidebarModel
    sidebarFilter = rw.sidebarFilter

    # Collapse all folders first so we have something to expand
    localBranchesNode = sb.findNodeByKind(SidebarItem.LocalBranchesHeader)
    sb.selectNode(localBranchesNode)
    triggerContextMenuAction(sb.viewport(), "collapse all folders")

    # Confirm the nested branch is now unreachable (ancestry chain collapsed)
    loginNode = sb.findNodeByRef("refs/heads/team/frontend/login")
    assert not sm.isAncestryChainExpanded(loginNode)

    # Applying a filter should expand all matching items
    sidebarFilter.lineEdit.setText("login")

    # The branch must now be visible in the proxy model
    assert sb.indexForRef("refs/heads/team/frontend/login").isValid()
    # And its entire parent chain must be expanded in the source model
    assert sm.isAncestryChainExpanded(loginNode)
