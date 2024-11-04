# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.nav import NavLocator
from gitfourchette.sidebar.sidebarmodel import EItem, SidebarModel, SidebarNode
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
    assert headNode.kind == EItem.DetachedHead
    assert [headNode] == list(rw.sidebar.findNodesByKind(EItem.DetachedHead))

    toolTip = headNode.createIndex(rw.sidebar.sidebarModel).data(Qt.ItemDataRole.ToolTipRole)
    assert re.search(r"detached head.+7f82283", toolTip, re.I)

    assert {'refs/heads/master', 'refs/heads/no-parent'
            } == {n.data for n in rw.sidebar.findNodesByKind(EItem.LocalBranch)}


def testSidebarSelectionSync(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar

    rw.jump(NavLocator.inRef("HEAD"))
    assert sb.selectedIndexes()[0].data() == "master"

    rw.jump(NavLocator.inWorkdir())
    assert "uncommitted" in sb.selectedIndexes()[0].data().lower()

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


def testRefreshKeepsSidebarNonRefSelection(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    sb.setFocus()

    node = next(sb.findNodesByKind(EItem.Remote))
    assert node.data == "origin"
    sb.selectNode(node)

    rw.refreshRepo()
    node = SidebarNode.fromIndex(sb.selectedIndexes()[0])
    assert node.kind == EItem.Remote
    assert node.data == "origin"


def testNewEmptyRemoteShowsUpInSidebar(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    assert 1 == len(list(sb.findNodesByKind(EItem.Remote)))

    rw.repo.remotes.create("toto", "https://github.com/jorio/bugdom")
    rw.refreshRepo()
    assert 2 == len(list(sb.findNodesByKind(EItem.Remote)))


@pytest.mark.parametrize("headerKind,leafKind", [
    (EItem.LocalBranchesHeader, EItem.LocalBranch),
    (EItem.RemotesHeader, EItem.RemoteBranch),
    (EItem.TagsHeader, EItem.Tag),
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

    headerNode = next(sb.findNodesByKind(headerKind))

    def getNodeDatas():
        return [node.data for node in sb.findNodesByKind(leafKind)]

    sortedByTime = getNodeDatas()
    sortedAlpha = sorted(getNodeDatas(), key=naturalSort)

    triggerMenuAction(sb.makeNodeMenu(headerNode), "sort.+by/newest first")
    assert getNodeDatas() == sortedByTime

    triggerMenuAction(sb.makeNodeMenu(headerNode), "sort.+by/oldest first")
    assert getNodeDatas() == list(reversed(sortedByTime))

    triggerMenuAction(sb.makeNodeMenu(headerNode), "sort.+by/name.+a-z")
    assert getNodeDatas() == sortedAlpha

    # Special case for tags - test natural sorting
    if leafKind == EItem.Tag:
        assert [data.removeprefix("refs/tags/") for data in getNodeDatas()
                ] == ["annotated_tag", "version2", "VERSION3", "version10"]

    triggerMenuAction(sb.makeNodeMenu(headerNode), "sort.+by/name.+z-a")
    assert getNodeDatas() == list(reversed(sortedAlpha))


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
        triggerMenuAction(sb.makeNodeMenu(node), "hide")
    elif method == "sidebarclick":
        index = node.createIndex(sm)
        rect = sb.visualRect(index)
        QTest.mouseClick(sb.viewport(), Qt.MouseButton.LeftButton, pos=rect.topRight())
    else:
        raise NotImplementedError(f"unknown method {method}")

    for node in rw.sidebar.walk():
        if not node.data:
            continue
        if node.data == explicit:
            assert sm.isExplicitlyHidden(node)
        else:
            assert sm.isImplicitlyHidden(node) == (node.data in implicit)


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

    test(EItem.LocalBranch, "refs/heads/master",
         r"local branch", r"upstream.+origin/master", r"checked.out")

    test(EItem.RemoteBranch, "refs/remotes/origin/master",
         r"origin/master", r"remote-tracking branch", r"upstream for.+checked.out.+\bmaster\b")

    test(EItem.Tag, "refs/tags/annotated_tag", r"\btag\b")
    test(EItem.UncommittedChanges, "", r"go to uncommitted changes.+(ctrl|⌘)")
    test(EItem.Remote, "origin", r"https://github.com/libgit2/TestGitRepository")
    test(EItem.RefFolder, "refs/heads/folder", r"local branch folder")
    test(EItem.RefFolder, "refs/remotes/origin/folder", r"remote branch folder")
    test(EItem.RefFolder, "refs/tags/folder", r"tag folder")


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
