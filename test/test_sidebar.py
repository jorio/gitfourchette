# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.nav import NavLocator
from gitfourchette.repomodel import UC_FAKEID
from gitfourchette.sidebar.sidebarmodel import SidebarItem, SidebarModel, SidebarNode
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

    toolTip = headNode.createIndex(rw.sidebar.sidebarModel).data(Qt.ItemDataRole.ToolTipRole)
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
    indexToCollapse = sb.findNode(lambda n: n.data == "origin").createIndex(sm)
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
    sm = sb.sidebarModel

    remotesHeader = sb.findNodeByKind(SidebarItem.RemotesHeader).createIndex(sm)
    tagsHeader = sb.findNodeByKind(SidebarItem.TagsHeader).createIndex(sm)
    stashesHeader = sb.findNodeByKind(SidebarItem.StashesHeader).createIndex(sm)
    submodulesHeader = sb.findNodeByKind(SidebarItem.SubmodulesHeader).createIndex(sm)

    assert sm.data(remotesHeader) == "Remotes"
    assert sm.data(tagsHeader) == "Tags"
    assert sm.data(stashesHeader) == "Stashes"
    assert sm.data(submodulesHeader) == "Submodules"

    sb.collapseAll()

    assert sm.data(remotesHeader) == "Remotes (1)"
    assert sm.data(tagsHeader) == "Tags (1)"
    assert sm.data(stashesHeader) == "Stashes (0)"
    assert sm.data(submodulesHeader) == "Submodules (0)"


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

    sb.expand(delish.createIndex(sm))
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
    node = SidebarNode.fromIndex(sb.selectedIndexes()[0])
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
        index = node.createIndex(sm)
        rect = sb.visualRect(index)
        QTest.mouseClick(sb.viewport(), Qt.MouseButton.LeftButton, pos=rect.topRight())
    else:
        raise NotImplementedError(f"unknown method {method}")

    for node in rw.sidebar.walk():
        index = node.createIndex(sm)
        tip = sm.data(index, Qt.ItemDataRole.ToolTipRole)

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
        index = node.createIndex(sm)
        rect = sb.visualRect(index)
        QTest.mouseClick(sb.viewport(), Qt.MouseButton.MiddleButton, pos=rect.topRight())
    else:
        raise NotImplementedError(f"unknown method {method}")

    assert sm.isHideAllButThisMode()

    hiddenRefs = leafRefs - set(implicit)
    hiddenRefs.discard(explicit)

    for node in rw.sidebar.walk():
        index = node.createIndex(sm)
        tip = sm.data(index, Qt.ItemDataRole.ToolTipRole)

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
        tip = node.createIndex(rw.sidebar.sidebarModel).data(Qt.ItemDataRole.ToolTipRole)
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
    sm = rw.sidebar.sidebarModel

    masterNode = sb.findNodeByRef("refs/heads/master")
    otherNode = sb.findNodeByRef("refs/heads/other-master")
    masterIcon = sm.data(masterNode.createIndex(sm), SidebarModel.Role.IconKey)
    otherIcon = sm.data(otherNode.createIndex(sm), SidebarModel.Role.IconKey)
    assert masterIcon == "git-head"
    assert otherIcon == "git-branch"

    triggerMenuAction(sb.makeNodeMenu(otherNode), "switch")
    acceptQMessageBox(rw, "switch")

    masterNode = sb.findNodeByRef("refs/heads/master")
    otherNode = sb.findNodeByRef("refs/heads/other-master")
    masterIcon = sm.data(masterNode.createIndex(sm), SidebarModel.Role.IconKey)
    otherIcon = sm.data(otherNode.createIndex(sm), SidebarModel.Role.IconKey)
    assert masterIcon == "git-branch"
    assert otherIcon == "git-head"


def testSidebarVisitRemoteWebPage(tempDir, mainWindow, mockDesktopServices):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.create_branch_on_head("other-master")

    rw = mainWindow.openRepo(wd)

    node = rw.sidebar.findNode(lambda n: n.data == "origin" and n.kind == SidebarItem.Remote)
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "visit web page")
    assert mockDesktopServices.urls[-1] == QUrl("https://github.com/libgit2/TestGitRepository")

    node = rw.sidebar.findNodeByRef("refs/remotes/origin/master")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "visit web page")
    assert mockDesktopServices.urls[-1] == QUrl("https://github.com/libgit2/TestGitRepository/tree/master")
