# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import re

import pytest

from gitfourchette.forms.commitdialog import CommitDialog
from gitfourchette.forms.newbranchdialog import NewBranchDialog
from gitfourchette.forms.resetheaddialog import ResetHeadDialog
from gitfourchette.nav import NavLocator
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from gitfourchette.toolbox import QHintButton
from . import reposcenario
from .util import *


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey", "sidebardclick", "shortcut"])
@pytest.mark.parametrize("switch", [False, True])
def testNewBranch(tempDir, mainWindow, method, switch):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    repo = rw.repo

    node = sb.findNodeByKind(SidebarItem.LocalBranchesHeader)

    if method == "sidebarmenu":
        menu = sb.makeNodeMenu(node)
        triggerMenuAction(menu, "new branch")
    elif method == "sidebarkey":
        sb.setFocus()
        sb.selectNode(node)
        QTest.keyPress(sb, Qt.Key.Key_Return)
    elif method == "sidebardclick":
        rect = sb.visualRect(node.createIndex(sb.sidebarModel))
        QTest.mouseDClick(sb.viewport(), Qt.MouseButton.LeftButton, pos=rect.topLeft())
    elif method == "shortcut":
        QTest.qWait(0)
        QTest.keySequence(rw, "Ctrl+B")
    else:
        raise NotImplementedError(f"unknown method {method}")

    dlg: NewBranchDialog = findQDialog(rw, "new branch")
    dlg.ui.nameEdit.setText("hellobranch")
    assert dlg.ui.switchToBranchCheckBox.isChecked()
    if not switch:
        dlg.ui.switchToBranchCheckBox.setChecked(False)
    dlg.accept()

    assert repo.branches.local['hellobranch'] is not None
    if switch:
        assert repo.head_branch_shorthand == 'hellobranch'
    else:
        assert repo.head_branch_shorthand == 'master'


def testNewBranchThenSwitchBlockedByConflicts(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.statelessConflictingChange(wd)

    rw = mainWindow.openRepo(wd)
    sb = rw.sidebar
    repo = rw.repo

    node = sb.findNodeByKind(SidebarItem.LocalBranchesHeader)
    menu = sb.makeNodeMenu(node)
    triggerMenuAction(menu, "new branch")

    dlg: NewBranchDialog = findQDialog(rw, "new branch")
    dlg.ui.nameEdit.setText("hellobranch")
    assert not dlg.ui.switchToBranchCheckBox.isChecked()
    assert not dlg.ui.switchToBranchCheckBox.isEnabled()
    dlg.accept()

    assert repo.branches.local['hellobranch'] is not None
    assert repo.head_branch_shorthand == 'master'


@pytest.mark.parametrize("branchSettings", [("master", "origin/master"), ("no-parent", "origin/no-parent")])
def testSetUpstreamBranch(tempDir, mainWindow, branchSettings: tuple[str, str]):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    def isUpstreamItalic():
        upstreamNode = rw.sidebar.findNodeByRef(f"refs/remotes/{upstreamName}")
        upstreamIndex = upstreamNode.createIndex(rw.sidebar.sidebarModel)
        upstreamFont: QFont = upstreamIndex.data(Qt.ItemDataRole.FontRole)
        return upstreamFont is not None and upstreamFont.italic()

    branchName, upstreamName = branchSettings
    isCurrentBranch = branchName == "master"
    upstreamMenuRegex = upstreamName.replace('/', '.')

    assert repo.branches.local[branchName].upstream_name == f"refs/remotes/{upstreamName}"

    node = rw.sidebar.findNodeByRef(f"refs/heads/{branchName}")

    toolTip = node.createIndex(rw.sidebar.sidebarModel).data(Qt.ItemDataRole.ToolTipRole)
    assert re.search(rf"{branchName}.+local branch", toolTip, re.I)
    assert (branchName == "master") == bool(re.search(r"checked.out", toolTip, re.I))
    assert re.search(rf"upstream.+{upstreamName}", toolTip, re.I)
    assert not isCurrentBranch or isUpstreamItalic()

    # Clear tracking reference
    menu = rw.sidebar.makeNodeMenu(node)
    originMasterAction = findMenuAction(menu, rf"upstream branch/{upstreamMenuRegex}")
    stopTrackingAction = findMenuAction(menu, r"upstream branch/stop tracking")
    assert originMasterAction.isChecked()
    stopTrackingAction.trigger()
    assert repo.branches.local[branchName].upstream is None
    assert not isUpstreamItalic()

    # Change tracking back to original upstream branch
    menu = rw.sidebar.makeNodeMenu(node)
    originMasterAction = findMenuAction(menu, rf"upstream branch/{upstreamMenuRegex}")
    notTrackingAction = findMenuAction(menu, r"upstream branch/not tracking")
    assert not originMasterAction.isChecked()
    assert notTrackingAction.isChecked()
    originMasterAction.trigger()
    assert repo.branches.local[branchName].upstream == repo.branches.remote[upstreamName]
    assert not isCurrentBranch or isUpstreamItalic()

    # Do that again to cover no-op case
    menu = rw.sidebar.makeNodeMenu(node)
    originMasterAction = findMenuAction(menu, rf"upstream branch/{upstreamMenuRegex}")
    assert originMasterAction.isChecked()
    originMasterAction.trigger()
    assert repo.branches.local[branchName].upstream == repo.branches.remote[upstreamName]
    assert not isCurrentBranch or isUpstreamItalic()


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey"])
def testRenameBranch(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.create_branch_on_head("folder1/folder2/leaf")
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    assert 'master' in repo.branches.local
    assert 'no-parent' in repo.branches.local
    assert 'mainbranch' not in repo.branches.local

    node = rw.sidebar.findNodeByRef("refs/heads/master")
    menu = rw.sidebar.makeNodeMenu(node)

    if method == "sidebarmenu":
        triggerMenuAction(menu, "rename")
    elif method == "sidebarkey":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_F2)
    else:
        raise NotImplementedError(f"unknown method {method}")

    dlg = findQDialog(rw, "rename.+branch")
    nameEdit: QLineEdit = dlg.findChild(QLineEdit)
    okButton: QPushButton = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)

    assert okButton
    assert okButton.isEnabled()

    badNames = [
        # Existing refs or folders
        "no-parent",
        "folder1/folder2",
        "folder1",
        # Illegal patterns
        "",
        "@",
        "nope.lock", "nope/", "nope.",
        "nope/.nope", "nope//nope", "nope@{nope", "no..pe",
        ".nope", "/nope",
        "no pe", "no~pe", "no^pe", "no:pe", "no[pe", "no?pe", "no*pe", "no\\pe",
        "nul", "nope/nul", "nul/nope", "lpt3", "com2",
    ]
    for bad in badNames:
        nameEdit.setText(bad)
        assert not okButton.isEnabled(), f"name shouldn't pass validation: {bad}"
        QTest.qWait(1)  # go through ValidatorMultiplexer's tooltip code path for coverage

    nameEdit.setText("mainbranch")
    assert okButton.isEnabled()

    dlg.accept()

    assert 'master' not in repo.branches.local
    assert 'mainbranch' in repo.branches.local


def testRenameBranchIdenticalName(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    node = rw.sidebar.findNodeByRef("refs/heads/master")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "rename")

    dlg = findQDialog(rw, "rename.+branch")
    nameEdit: QLineEdit = dlg.findChild(QLineEdit)
    okButton: QPushButton = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)

    assert nameEdit.text() == "master"
    assert okButton.isEnabled()
    dlg.accept()
    assert 'master' in repo.branches.local


def testRenameBranchKeepsUpstreamStable(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    node = rw.sidebar.findNodeByRef("refs/heads/master")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "rename")

    dlg = findQDialog(rw, "rename.+branch")
    dlg.findChild(QLineEdit).setText("master2")
    dlg.accept()
    assert repo.branches.local["master2"].upstream_name == "refs/remotes/origin/master"

    toolTip = rw.sidebar.indexForRef("refs/heads/master2").data(Qt.ItemDataRole.ToolTipRole)
    assert "origin/master" in toolTip


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey"])
@pytest.mark.parametrize("newName", ["newfolder", "folder4", "", "folder1/folder2"])
def testRenameBranchFolder(tempDir, mainWindow, method, newName):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.create_branch_on_head("folder1/leaf")
        repo.create_branch_on_head("folder1/folder2/leaf")
        repo.create_branch_on_head("folder1/folder2/folder3/leaf")
        repo.create_branch_on_head("folder1/folder2_donttouchthis/leaf")
        repo.create_branch_on_head("folder4/wontclash")
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    node = rw.sidebar.findNode(lambda n: n.data == "refs/heads/folder1/folder2")
    assert node.kind == SidebarItem.RefFolder

    if method == "sidebarmenu":
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "name")
    elif method == "sidebarkey":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_F2)
    else:
        raise NotImplementedError(f"unknown method {method}")

    dlg = findQDialog(rw, "rename.+folder")
    nameEdit: QLineEdit = dlg.findChild(QLineEdit)
    okButton: QPushButton = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)

    assert okButton
    assert okButton.isEnabled()

    badNames = [
        # Folders with conflicting branch names
        "folder1",
        # Illegal patterns
        "@",
        "nope.lock", "nope/", "nope.",
        "nope/.nope", "nope//nope", "nope@{nope", "no..pe",
        ".nope", "/nope",
        "no pe", "no~pe", "no^pe", "no:pe", "no[pe", "no?pe", "no*pe", "no\\pe",
        "nul", "nope/nul", "nul/nope", "lpt3", "com2",
    ]
    for bad in badNames:
        nameEdit.setText(bad)
        assert not okButton.isEnabled(), f"name shouldn't pass validation: {bad}"
        print(bad, "-->", nameEdit.actions()[0].toolTip())

    nameEdit.setText(newName)
    assert okButton.isEnabled()
    dlg.accept()

    assert f"{newName}/leaf".removeprefix("/") in repo.branches.local
    assert f"{newName}/folder3/leaf".removeprefix("/") in repo.branches.local
    assert "folder1/folder2_donttouchthis/leaf" in repo.branches.local


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey"])
def testDeleteBranch(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        commit = repo['6e1475206e57110fcef4b92320436c1e9872a322']
        repo.branches.create("somebranch", commit)
        assert "somebranch" in repo.branches.local

    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    node = rw.sidebar.findNodeByRef("refs/heads/somebranch")

    if method == "sidebarmenu":
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "delete")
    elif method == "sidebarkey":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Delete)
    else:
        raise NotImplementedError(f"unknown method {method}")

    acceptQMessageBox(rw, "really delete.+branch")
    assert "somebranch" not in repo.branches.local


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey"])
def testDeleteBranchFolder(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.create_branch_on_head("folder1/leaf")
        repo.create_branch_on_head("folder1/folder2/leaf")
        repo.create_branch_on_head("folder1/folder2/folder3/leaf")
        repo.create_branch_on_head("folder1/folder2_donttouchthis/leaf")
        repo.create_branch_on_head("folder4/wontclash")

    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    node = rw.sidebar.findNode(lambda n: n.data == "refs/heads/folder1/folder2")

    if method == "sidebarmenu":
        triggerMenuAction(rw.sidebar.makeNodeMenu(node), "delete folder")
    elif method == "sidebarkey":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Delete)
    else:
        raise NotImplementedError(f"unknown method {method}")

    acceptQMessageBox(rw, "really delete.+branch folder")

    for gone in ["folder1/folder2/leaf", "folder1/folder2/folder3/leaf"]:
        assert gone not in repo.branches.local

    for keep in ["folder1/leaf", "folder1/folder2_donttouchthis/leaf", "folder4/wontclash", "master", "no-parent"]:
        assert keep in repo.branches.local


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey"])
def testDeleteCurrentBranch(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    assert "master" in repo.branches.local

    node = rw.sidebar.findNodeByRef("refs/heads/master")

    if method == "sidebarmenu":
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "delete")
    elif method == "sidebarkey":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Delete)
    else:
        raise NotImplementedError(f"unknown method {method}")

    acceptQMessageBox(rw, "can.+t delete.+current branch")
    assert "master" in repo.branches.local  # still there


def testDeleteBranchFolderContainingCurrentBranch(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.rename_local_branch("master", "folder1/master")

    rw = mainWindow.openRepo(wd)
    repo = rw.repo
    node = rw.sidebar.findNode(lambda n: n.data == "refs/heads/folder1")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "delete folder")
    acceptQMessageBox(rw, "can.+t delete.+folder.+current branch")
    assert "folder1/master" in repo.branches.local


def testNewBranchTrackingRemoteBranch1(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    assert "newmaster" not in repo.branches.local

    node = rw.sidebar.findNodeByRef("refs/remotes/origin/master")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "(start|new).+local branch")

    dlg: NewBranchDialog = findQDialog(rw, "new.+branch")
    assert dlg.ui.upstreamCheckBox.isChecked()  # auto-track upstreams from remote branches
    assert dlg.ui.upstreamComboBox.isEnabled()
    assert dlg.ui.upstreamComboBox.currentText() == "origin/master"

    dlg.ui.nameEdit.setText("newmaster")
    dlg.accept()

    assert repo.branches.local["newmaster"].upstream == repo.branches.remote["origin/master"]


def testNewBranchTrackingRemoteBranch2(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    node = rw.sidebar.findNodeByRef("refs/remotes/origin/first-merge")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "(start|new).*local branch")

    dlg: NewBranchDialog = findQDialog(rw, "new.+branch")
    assert dlg.ui.nameEdit.text() == "first-merge"
    assert dlg.ui.upstreamCheckBox.isChecked()  # auto-track upstreams from remote branches
    assert dlg.ui.upstreamComboBox.isEnabled()
    assert dlg.ui.upstreamComboBox.currentText() == "origin/first-merge"

    dlg.accept()

    localBranch = repo.branches.local['first-merge']
    assert localBranch
    assert localBranch.upstream_name == "refs/remotes/origin/first-merge"
    assert str(localBranch.target) == "0966a434eb1a025db6b71485ab63a3bfbea520b6"


@pytest.mark.parametrize("method", ["graphstart", "graphcheckout"])
def testNewBranchFromCommit(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    localBranches = rw.repo.branches.local

    assert "first-merge" not in localBranches
    with pytest.raises(KeyError):
        rw.sidebar.findNodeByRef("refs/heads/first-merge")

    oid1 = Oid(hex="0966a434eb1a025db6b71485ab63a3bfbea520b6")
    rw.jump(NavLocator.inCommit(oid1))

    if method == "graphstart":
        triggerMenuAction(rw.graphView.makeContextMenu(), r"(start|new) branch")
    elif method == "graphcheckout":
        QTest.keyPress(rw.graphView, Qt.Key.Key_Return)
        qd = findQDialog(rw, r"check ?out")
        qd.findChild(QRadioButton, "createBranchRadioButton").setChecked(True)
        qd.accept()
    else:
        raise NotImplementedError("unknown method")

    dlg: NewBranchDialog = findQDialog(rw, "new branch")
    assert dlg.ui.nameEdit.text() == "first-merge"  # nameEdit should be pre-filled with name of a (remote) branch pointing to this commit
    assert not dlg.ui.upstreamCheckBox.isChecked()  # don't auto-track upstream from commits
    assert not dlg.ui.upstreamComboBox.isEnabled()
    assert dlg.ui.upstreamComboBox.currentText() == "origin/first-merge"  # do suggest an upstream

    dlg.ui.switchToBranchCheckBox.setChecked(True)
    dlg.accept()

    assert "first-merge" in localBranches
    assert localBranches["first-merge"].target == oid1
    assert localBranches["first-merge"].is_checked_out()
    assert rw.sidebar.findNodeByRef("refs/heads/first-merge")


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey", "graphstart", "graphcheckout"])
def testNewBranchFromDetachedHead(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    oid = Oid(hex="f73b95671f326616d66b2afb3bdfcdbbce110b44")

    with RepoContext(wd) as repo:
        repo.checkout_commit(oid)
        assert repo.head_is_detached

    rw = mainWindow.openRepo(wd)
    localBranches = rw.repo.branches.local
    rw.jump(NavLocator.inCommit(oid))

    sidebarNode = rw.sidebar.findNodeByKind(SidebarItem.DetachedHead)

    if method == "sidebarmenu":
        triggerMenuAction(rw.sidebar.makeNodeMenu(sidebarNode), r"(start|new) branch")
    elif method == "sidebarkey":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(sidebarNode)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Return)
    elif method == "graphstart":
        triggerMenuAction(rw.graphView.makeContextMenu(), r"(start|new) branch")
    elif method == "graphcheckout":
        QTest.keyPress(rw.graphView, Qt.Key.Key_Return)
        qd = findQDialog(rw, r"check ?out")
        qd.findChild(QRadioButton, "createBranchRadioButton").setChecked(True)
        qd.accept()
    else:
        raise NotImplementedError("unknown method")

    dlg: NewBranchDialog = findQDialog(rw, "new branch")
    assert not dlg.ui.upstreamCheckBox.isChecked()  # don't auto-track upstream
    assert not dlg.ui.upstreamComboBox.isEnabled()

    dlg.ui.nameEdit.setText("coucou")
    dlg.ui.switchToBranchCheckBox.setChecked(True)
    dlg.accept()

    assert "coucou" in localBranches
    assert localBranches["coucou"].target == oid
    assert localBranches["coucou"].is_checked_out()
    assert rw.sidebar.findNodeByRef("refs/heads/coucou")


@pytest.mark.parametrize("method", ["sidebar", "graphstart", "graphcheckout"])
def testNewBranchFromLocalBranch(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    localBranches = rw.repo.branches.local

    if method == "sidebar":
        node = rw.sidebar.findNodeByRef("refs/heads/no-parent")
        menu = rw.sidebar.makeNodeMenu(node)
        findMenuAction(menu, "new.+branch.+here").trigger()
    elif method == "graphstart":
        rw.jump(NavLocator.inRef("refs/heads/no-parent"))
        triggerMenuAction(rw.graphView.makeContextMenu(), r"(start|new) branch")
    elif method == "graphcheckout":
        rw.jump(NavLocator.inRef("refs/heads/no-parent"))
        QTest.keyPress(rw.graphView, Qt.Key.Key_Return)
        qd = findQDialog(rw, r"check ?out")
        qd.findChild(QRadioButton, "createBranchRadioButton").setChecked(True)
        qd.accept()
    else:
        raise NotImplementedError("unknown method")

    dlg: NewBranchDialog = findQDialog(rw, "new.+branch")
    assert dlg.ui.nameEdit.text() == "no-parent-2"
    assert dlg.acceptButton.isEnabled()  # "no-parent-2" isn't taken
    assert not dlg.ui.upstreamCheckBox.isChecked()  # don't auto-track upstreams from local branches
    assert not dlg.ui.upstreamComboBox.isEnabled()

    dlg.ui.nameEdit.setText("no-parent")  # try to set a name that's taken
    assert not dlg.acceptButton.isEnabled()  # can't accept because branch name "no-parent" is taken

    dlg.ui.nameEdit.setText("no-parent-2")
    assert dlg.acceptButton.isEnabled()  # "no-parent-2" isn't taken
    dlg.accept()

    assert "no-parent-2" in localBranches
    assert localBranches["no-parent-2"].target == localBranches["no-parent"].target
    assert rw.sidebar.findNodeByRef("refs/heads/no-parent-2")


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey", "graphmenu", "graphkey"])
def testSwitchBranch(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    localBranches = rw.repo.branches.local

    def getActiveBranchTooltipText():
        node = rw.sidebar.findNodeByRef(rw.repo.head_branch_fullname)
        index = node.createIndex(rw.sidebar.sidebarModel)
        tip = index.data(Qt.ItemDataRole.ToolTipRole)
        assert re.search(r"(current|checked.out) branch", tip, re.I)
        return tip

    # make sure initial branch state is correct
    assert localBranches['master'].is_checked_out()
    assert not localBranches['no-parent'].is_checked_out()
    assert os.path.isfile(f"{wd}/master.txt")
    assert os.path.isfile(f"{wd}/c/c1.txt")
    assert "master" in getActiveBranchTooltipText()
    assert "no-parent" not in getActiveBranchTooltipText()

    if method == "sidebarmenu":
        node = rw.sidebar.findNodeByRef("refs/heads/no-parent")
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "switch to")
        acceptQMessageBox(rw, "switch to")
    elif method == "sidebarkey":
        rw.sidebar.setFocus()
        rw.sidebar.selectAnyRef("refs/heads/no-parent")
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Return)
        acceptQMessageBox(rw, "switch to")
    elif method in ["graphmenu", "graphkey"]:
        rw.jump(NavLocator.inRef("refs/heads/no-parent"))
        if method == "graphmenu":
            triggerMenuAction(rw.graphView.makeContextMenu(), "check out")
        else:
            rw.graphView.setFocus()
            QTest.keyPress(rw.graphView, Qt.Key.Key_Return)
        qd = findQDialog(rw, "check out")
        assert qd.findChild(QRadioButton, "switchToLocalBranchRadioButton").isChecked()
        qd.accept()
    else:
        raise NotImplementedError(f"unknown method {method}")

    assert not localBranches['master'].is_checked_out()
    assert localBranches['no-parent'].is_checked_out()
    assert not os.path.isfile(f"{wd}/master.txt")  # this file doesn't exist on the no-parent branch
    assert os.path.isfile(f"{wd}/c/c1.txt")

    # Active branch change should be reflected in sidebar UI
    assert "master" not in getActiveBranchTooltipText()
    assert "no-parent" in getActiveBranchTooltipText()


def testSwitchToCurrentBranch(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.sidebar.setFocus()
    rw.sidebar.selectAnyRef("refs/heads/master")
    QTest.keyPress(rw.sidebar, Qt.Key.Key_Return)
    acceptQMessageBox(rw, "already checked.out")


def testResetHeadToCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    oid1 = Oid(hex="0966a434eb1a025db6b71485ab63a3bfbea520b6")

    assert rw.repo.head.target != oid1  # make sure we're not starting from this commit
    assert rw.repo.branches.local['master'].target != oid1

    rw.jump(NavLocator.inCommit(oid1))
    triggerMenuAction(rw.graphView.makeContextMenu(), "reset.+here")

    dlg: ResetHeadDialog = findQDialog(rw, "reset.+master.+to.+0966a4")
    dlg.modeButtons[ResetMode.HARD].click()
    dlg.accept()

    assert rw.repo.head.target == oid1
    assert rw.repo.branches.local['master'].target == oid1


@pytest.mark.skipif(pygit2OlderThan("1.15.1"), reason="old pygit2")
def testResetHeadRecurseSubmodules(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "submoroot")
    uncommittedPath = f"{wd}/submosub/subhello.txt"
    uncommittedContents = "uncommitted change in submodule"
    writeFile(uncommittedPath, uncommittedContents)
    rw = mainWindow.openRepo(wd)

    rootId1 = Oid(hex="6d2168f6dcd314050ed1f6ad70b867aafa25a186")
    rootId2 = Oid(hex="ea953d3ba4c5326d530dc09b4ca9781b01c18e00")
    subId1 = Oid(hex="db85fb4ffb94ad4e2ea1d3a6881dc5ec1cfbce92")
    subId2 = Oid(hex="6c138ceb12d6fc505ebe9015dcc48a0616e1de23")

    assert rw.repo.head.target == rootId1  # make sure we're not starting from this commit
    assert rw.repo.submodules["submosub"].head_id == subId1
    assert uncommittedContents == readFile(uncommittedPath).decode("utf-8")

    rw.jump(NavLocator.inCommit(rootId2))
    triggerMenuAction(rw.graphView.makeContextMenu(), "reset.+here")

    dlg: ResetHeadDialog = findQDialog(rw, "reset.+master.+to.+ea953d3")
    dlg.modeButtons[ResetMode.HARD].click()
    assert dlg.ui.recurseCheckBox.isVisible()
    dlg.ui.recurseCheckBox.setChecked(True)
    dlg.accept()

    assert rw.repo.head.target == rootId2
    assert rw.repo.submodules["submosub"].head_id == subId2
    assert uncommittedContents != readFile(uncommittedPath).decode("utf-8")


def testSwitchBranchBlockedByConflicts(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    reposcenario.statelessConflictingChange(wd)

    rw = mainWindow.openRepo(wd)
    assert rw.repo.any_conflicts
    assert rw.mergeBanner.isVisible()
    assert "fix the conflicts" in rw.mergeBanner.label.text().lower()
    assert "reset index" in rw.mergeBanner.buttons[-1].text().lower()

    node = rw.sidebar.findNodeByRef("refs/heads/no-parent")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "switch to")
    acceptQMessageBox(rw, "fix merge conflicts before performing this action")


def testSwitchBranchWorkdirConflicts(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    writeFile(f"{wd}/c/c1.txt", "la menuiserie et toute la clique")

    rw = mainWindow.openRepo(wd)
    localBranches = rw.repo.branches.local

    assert not localBranches['no-parent'].is_checked_out()
    assert localBranches['master'].is_checked_out()

    node = rw.sidebar.findNodeByRef("refs/heads/no-parent")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "switch to")
    acceptQMessageBox(rw, "switch to.+no-parent")

    acceptQMessageBox(rw, "conflict.+with.+file")  # this will fail if the messagebox doesn't show up

    assert not localBranches['no-parent'].is_checked_out()  # still not checked out
    assert localBranches['master'].is_checked_out()


def testRecallCommit(tempDir, mainWindow):
    lostId = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.delete_remote("origin")
        repo.checkout_local_branch("no-parent")
        repo.delete_local_branch("master")
    rw = mainWindow.openRepo(wd)
    assert "master" not in rw.repoModel.refs
    assert lostId not in rw.repoModel.refsAt
    triggerMenuAction(mainWindow.menuBar(), "repo/lost commit")
    dlg = findQDialog(rw, "lost commit")
    qle: QLineEdit = dlg.findChild(QLineEdit)
    qle.setText(str(lostId)[:7])  # must work even with partial hash
    dlg.accept()
    assert lostId in rw.repoModel.refsAt
    assert rw.navLocator.commit == lostId


def testFastForwardCurrentBranch(tempDir, mainWindow):
    targetCommit = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")

    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        assert repo.branches["origin/master"].target == targetCommit
        assert repo.branches["no-parent"].target != targetCommit
        repo.checkout_local_branch("no-parent")
        repo.edit_upstream_branch("no-parent", "origin/master")
    rw = mainWindow.openRepo(wd)

    # This file doesn't exist on no-parent initally
    assert not os.path.exists(f"{wd}/a/a1")

    node = rw.sidebar.findNodeByRef("refs/heads/no-parent")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "fast.forward")

    # Make sure fastforward actually worked
    assert rw.repo.head_branch_shorthand == "no-parent"
    assert rw.repo.head_commit_id == targetCommit
    assert os.path.exists(f"{wd}/a/a1")  # should have checked out new file

    # UI should jump to new commit
    assert rw.navLocator.commit == targetCommit


def testFastForwardOtherBranch(tempDir, mainWindow):
    targetCommit = Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0")

    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        assert repo.branches["origin/master"].target == targetCommit
        assert repo.branches["no-parent"].target != targetCommit
        repo.checkout_local_branch("no-parent")
        repo.create_branch_on_head("no-parent-ffwd")
        repo.edit_upstream_branch("no-parent-ffwd", "origin/master")
    rw = mainWindow.openRepo(wd)

    node = rw.sidebar.findNodeByRef("refs/heads/no-parent-ffwd")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "fast.forward")

    # Make sure fastforward actually worked
    assert rw.repo.branches["no-parent-ffwd"].target == targetCommit

    # Make sure we're still on no-parent unaffected
    assert rw.repo.head_branch_shorthand == "no-parent"
    assert b"c1\n" == readFile(f"{wd}/c/c1.txt")
    assert not os.path.exists(f"{wd}/a/a1")
    assert not os.path.exists(f"{wd}/master.txt")

    # UI should jump to new commit
    assert rw.navLocator.commit == targetCommit


@pytest.mark.parametrize("branch", ["master", "no-parent"])
def testFastForwardNotNecessary(tempDir, mainWindow, branch):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    node = rw.sidebar.findNodeByRef(f"refs/heads/{branch}")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "fast.forward")

    acceptQMessageBox(rw, "(is ahead of)|(already up.to.date)")


def testFastForwardDivergent(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.checkout_local_branch("no-parent")
        repo.edit_upstream_branch("no-parent", "origin/first-merge")
    rw = mainWindow.openRepo(wd)

    node = rw.sidebar.findNodeByRef("refs/heads/no-parent")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "fast.forward")
    acceptQMessageBox(rw, "can.+t fast.forward.+branches are divergent")


def testMergeUpToDate(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    node = rw.sidebar.findNodeByRef("refs/remotes/origin/first-merge")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "merge")
    acceptQMessageBox(rw, "already up.to.date")


def testMergeFastForward(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.checkout_local_branch('no-parent')
    rw = mainWindow.openRepo(wd)

    assert rw.repo.head.target != rw.repo.branches.local['master'].target

    node = rw.sidebar.findNodeByRef("refs/heads/master")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "merge")

    qmb = findQMessageBox(rw, "can .*fast.forward")

    # Clicking the help button should not close the message box
    helpButton = next(b for b in qmb.buttons() if isinstance(b, QHintButton))
    helpButton.click()
    assert qmb.isVisible()

    # Accept fast-forwarding
    qmb.accept()

    assert rw.repo.head.target == rw.repo.branches.local['master'].target


def testFastForwardPossibleCreateMergeCommitAnyway(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        repo.checkout_local_branch('no-parent')
    rw = mainWindow.openRepo(wd)

    assert rw.repo.head.target != rw.repo.branches.local['master'].target

    node = rw.sidebar.findNodeByRef("refs/heads/master")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "merge")

    qmb = findQMessageBox(rw, "can .*fast.forward")
    mergeCommitButton = next(b for b in qmb.buttons() if b.text().lower() == "create merge commit")
    mergeCommitButton.click()
    assert not qmb.isVisible()

    assert rw.mergeBanner.isVisibleTo(rw)
    assert rw.repo.state() == RepositoryState.MERGE
    assert rw.repo.status() == {
        "a/a1": FileStatus.INDEX_NEW,
        "a/a1.txt": FileStatus.INDEX_NEW,
        "a/a2.txt": FileStatus.INDEX_NEW,
        "b/b1.txt": FileStatus.INDEX_NEW,
        "b/b2.txt": FileStatus.INDEX_NEW,
        "c/c1.txt": FileStatus.INDEX_MODIFIED,
        "master.txt": FileStatus.INDEX_NEW,
    }
    assert re.search(r"all conflicts fixed", rw.mergeBanner.label.text(), re.I)


def testAbortMerge(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "testrepoformerging")
    rw = mainWindow.openRepo(wd)
    assert rw.repo.state() == RepositoryState.NONE

    # Initiate merge of pep8-fixes into master
    node = rw.sidebar.findNodeByRef("refs/heads/pep8-fixes")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "merge into.+master")
    acceptQMessageBox(rw, "pep8-fixes.+into.+master.+may cause conflicts")
    assert rw.mergeBanner.isVisible()
    assert rw.repo.state() == RepositoryState.MERGE
    assert rw.repo.status() == {"bye.txt": FileStatus.INDEX_NEW}
    assert re.search(r"all conflicts fixed", rw.mergeBanner.label.text(), re.I)
    assert re.search(r"abort", rw.mergeBanner.buttons[-1].text(), re.I)
    assert rw.repoModel.prefs.draftCommitMessage.startswith("Merge branch 'pep8-fixes'")

    # Abort the merge
    rw.mergeBanner.buttons[-1].click()
    acceptQMessageBox(rw, "abort.+merge")
    assert not rw.mergeBanner.isVisible()
    assert rw.repo.state() == RepositoryState.NONE
    assert rw.repo.status() == {}
    assert not rw.repoModel.prefs.draftCommitMessage


def testMergeConcludedByCommit(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "testrepoformerging")
    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNodeByRef("refs/heads/pep8-fixes")

    # Initiate merge of pep8-fixes into master
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "merge into.+master")
    acceptQMessageBox(rw, "pep8-fixes.+into.+master.+may cause conflicts")
    assert rw.mergeBanner.isVisibleTo(rw)
    assert rw.repo.state() == RepositoryState.MERGE
    assert rw.repo.status() == {"bye.txt": FileStatus.INDEX_NEW}
    assert re.search(r"all conflicts fixed", rw.mergeBanner.label.text(), re.I)

    # Commit to conclude the merge
    rw.diffArea.commitButton.click()
    commitDialog: CommitDialog = rw.findChild(CommitDialog)
    assert commitDialog.ui.infoText.isVisible()
    assert re.search(r"conclude the merge", commitDialog.ui.infoText.text(), re.I)
    commitDialog.ui.summaryEditor.setText("yup")
    commitDialog.accept()
    assert not rw.mergeBanner.isVisible()
    assert rw.repo.state() == RepositoryState.NONE
    assert rw.repo.status() == {}


def testMergeCausesConflicts(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "testrepoformerging")
    rw = mainWindow.openRepo(wd)
    conflictUI = rw.conflictView.ui
    node = rw.sidebar.findNodeByRef("refs/heads/branch-conflicts")

    # Initiate merge of branch-conflicts into master
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "merge into.+master")
    acceptQMessageBox(rw, "branch-conflicts.+into.+master.+may cause conflicts")
    assert rw.mergeBanner.isVisible()
    assert rw.repo.state() == RepositoryState.MERGE
    assert rw.repo.status() == {".gitignore": FileStatus.CONFLICTED}
    assert re.search(r"conflicts need fixing", rw.mergeBanner.label.text(), re.I)

    # Shouldn't be able to commit
    rw.diffArea.commitButton.click()
    acceptQMessageBox(rw, "fix.+conflicts before")

    # Shouldn't be able to merge again
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "merge into.+master")
    acceptQMessageBox(rw, "merging is not possible.+fix the conflicts")

    rw.jump(NavLocator.inUnstaged(".gitignore"))
    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged(".gitignore"))
    assert rw.conflictView.isVisible()

    assert conflictUI.oursButton.isVisible()
    assert conflictUI.theirsButton.isVisible()
    assert conflictUI.mergeButton.isVisible()

    conflictUI.oursButton.click()
    assert not rw.conflictView.isVisible()
    assert re.search(r"all conflicts fixed", rw.mergeBanner.label.text(), re.I)

    rw.diffArea.commitButton.click()
    acceptQMessageBox(rw, "empty commit")
    commitDialog: CommitDialog = findQDialog(rw, "commit")
    preparedMessage = commitDialog.getFullMessage()
    assert "Merge branch 'branch-conflicts' into 'master'" == commitDialog.getFullMessage()
    assert "Conflicts" not in preparedMessage
    assert "#" not in preparedMessage

    commitDialog.accept()
    assert rw.repo.state() == RepositoryState.NONE


@pytest.mark.parametrize("method", ["switchbranch", "newbranch", "checkout"])
def testMightLoseDetachedHead(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.checkout_commit(repo.head_commit_id)
        looseOid = repo.create_commit_on_head("lost commit", TEST_SIGNATURE, TEST_SIGNATURE)

    rw = mainWindow.openRepo(wd)

    assert rw.repo.head_is_detached
    assert looseOid in rw.repoModel.graph.commitRows

    if method == "switchbranch":
        node = rw.sidebar.findNodeByRef("refs/heads/master")
        triggerMenuAction(rw.sidebar.makeNodeMenu(node), "switch to")
        acceptQMessageBox(rw, "switch to")
        acceptQMessageBox(rw, "lose track of this commit")
    elif method == "newbranch":
        oid = Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b")
        rw.jump(NavLocator.inCommit(oid))
        triggerMenuAction(rw.graphView.makeContextMenu(), "new branch")
        findQDialog(rw, "new branch").accept()
        acceptQMessageBox(rw, "lose track of this commit")
    elif method == "checkout":
        oid = Oid(hex="ce112d052bcf42442aa8563f1e2b7a8aabbf4d17")
        rw.jump(NavLocator.inCommit(oid))
        triggerMenuAction(rw.graphView.makeContextMenu(), "check out")
        findQDialog(rw, "check out").accept()
        acceptQMessageBox(rw, "lose track of this commit")
    else:
        raise NotImplementedError(f"unknown method {method}")

    assert looseOid not in rw.repoModel.graph.commitRows


def testCreateBranchOnDetachedHead(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        repo.checkout_commit(repo.head_commit_id)
        looseOid = repo.create_commit_on_head("lost commit", TEST_SIGNATURE, TEST_SIGNATURE)

    rw = mainWindow.openRepo(wd)
    assert rw.repo.head_is_detached

    rw.jump(NavLocator.inCommit(looseOid))
    triggerMenuAction(rw.graphView.makeContextMenu(), "new branch")
    dlg: NewBranchDialog = findQDialog(rw, "new branch")
    dlg.ui.nameEdit.setText("hellobranch")
    assert dlg.ui.switchToBranchCheckBox.isChecked()
    dlg.accept()

    # Create the branch without complaining about losing detached HEAD
    assert "hellobranch" in rw.repo.branches.local
