from . import reposcenario
from .fixtures import *
from .util import *
from gitfourchette.sidebar.sidebarmodel import EItem
from gitfourchette.forms.newbranchdialog import NewBranchDialog
import re


def testNewBranch(qtbot, tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    menu = rw.sidebar.generateMenuForEntry(EItem.LocalBranchesHeader)
    findMenuAction(menu, "new branch").trigger()

    q = findQDialog(rw, "new branch")
    q.findChild(QLineEdit).setText("hellobranch")
    q.accept()

    assert repo.branches.local['hellobranch'] is not None


def testSetTrackedBranch(qtbot, tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    assert repo.branches.local['master'].upstream_name == "refs/remotes/origin/master"

    menu = rw.sidebar.generateMenuForEntry(EItem.LocalBranch, "master")

    findMenuAction(menu, "tracked branch").trigger()

    # Change tracking from origin/master to nothing
    q = findQDialog(rw, "tracked branch")
    combobox: QComboBox = q.findChild(QComboBox)
    assert "origin/master" in combobox.currentText()
    assert re.match(r".*don.t track.*", combobox.itemText(0).lower())
    combobox.setCurrentIndex(0)
    q.accept()
    assert repo.branches.local['master'].upstream is None

    # Change tracking back to origin/master
    findMenuAction(menu, "tracked branch").trigger()
    q = findQDialog(rw, "tracked branch")
    combobox: QComboBox = q.findChild(QComboBox)
    assert re.match(r".*don.t track.*", combobox.currentText().lower())
    for i in range(combobox.count()):
        if "origin/master" in combobox.itemText(i):
            combobox.setCurrentIndex(i)
            break
    q.accept()

    assert repo.branches.local['master'].upstream == repo.branches.remote['origin/master']


def testRenameBranch(qtbot, tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    assert 'master' in repo.branches.local
    assert 'no-parent' in repo.branches.local
    assert 'mainbranch' not in repo.branches.local

    menu = rw.sidebar.generateMenuForEntry(EItem.LocalBranch, "master")

    findMenuAction(menu, "rename").trigger()

    dlg = findQDialog(rw, "rename.+branch")
    nameEdit: QLineEdit = dlg.findChild(QLineEdit)
    okButton: QPushButton = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)

    assert okButton
    assert okButton.isEnabled()

    nameEdit.setText("this-wont-pass-validation.lock")  # illegal suffix
    assert not okButton.isEnabled()

    nameEdit.setText("no-parent")  # already taken by another local branch
    assert not okButton.isEnabled()

    nameEdit.setText("")  # cannot be empty
    assert not okButton.isEnabled()

    nameEdit.setText("mainbranch")
    assert okButton.isEnabled()

    dlg.accept()

    assert 'master' not in repo.branches.local
    assert 'mainbranch' in repo.branches.local


def testDeleteBranch(qtbot, tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    commit = repo['6e1475206e57110fcef4b92320436c1e9872a322']
    repo.branches.create("somebranch", commit)
    assert "somebranch" in repo.branches.local

    menu = rw.sidebar.generateMenuForEntry(EItem.LocalBranch, "somebranch")
    findMenuAction(menu, "delete").trigger()
    acceptQMessageBox(rw, "really delete.+branch")
    assert "somebranch" not in repo.branches.local


def testDeleteCurrentBranch(qtbot, tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    assert "master" in repo.branches.local

    menu = rw.sidebar.generateMenuForEntry(EItem.LocalBranch, "master")
    findMenuAction(menu, "delete").trigger()
    acceptQMessageBox(rw, "can.+t delete.+current branch")
    assert "master" in repo.branches.local  # still there


def testNewBranchTrackingRemoteBranch1(qtbot, tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    assert "newmaster" not in repo.branches.local

    menu = rw.sidebar.generateMenuForEntry(EItem.RemoteBranch, "origin/master")

    findMenuAction(menu, "(start|new).+local branch").trigger()

    dlg: NewBranchDialog = findQDialog(rw, "new.+branch")
    dlg.ui.nameEdit.setText("newmaster")
    dlg.ui.upstreamCheckBox.setChecked(True)
    dlg.accept()

    assert repo.branches.local["newmaster"].upstream == repo.branches.remote["origin/master"]


def testNewBranchTrackingRemoteBranch2(qtbot, tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    menu = rw.sidebar.generateMenuForEntry(EItem.RemoteBranch, "origin/first-merge")
    findMenuAction(menu, "(start|new).*local branch").trigger()

    dlg: NewBranchDialog = findQDialog(rw, "new.+branch")
    assert dlg.ui.nameEdit.text() == "first-merge"
    assert dlg.ui.upstreamCheckBox.isChecked()
    assert dlg.ui.upstreamComboBox.currentText() == "origin/first-merge"
    dlg.accept()

    localBranch = repo.branches.local['first-merge']
    assert localBranch
    assert localBranch.upstream_name == "refs/remotes/origin/first-merge"
    assert localBranch.target.hex == "0966a434eb1a025db6b71485ab63a3bfbea520b6"


def testNewBranchFromCommit(qtbot, tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    localBranches = rw.repo.branches.local

    assert "first-merge" not in localBranches
    assert "first-merge" not in rw.sidebar.datasForItemType(EItem.LocalBranch)

    oid1 = Oid(hex="0966a434eb1a025db6b71485ab63a3bfbea520b6")

    rw.graphView.selectCommit(oid1)
    triggerMenuAction(rw.graphView.makeContextMenu(), r"(start|new) branch")

    dlg: NewBranchDialog = findQDialog(rw, "new branch")
    assert dlg.ui.nameEdit.text() == "first-merge"  # nameEdit should be pre-filled with name of a (remote) branch pointing to this commit
    dlg.ui.switchToBranchCheckBox.setChecked(True)
    dlg.accept()

    assert "first-merge" in localBranches
    assert localBranches["first-merge"].target == oid1
    assert localBranches["first-merge"].is_checked_out()
    assert "first-merge" in rw.sidebar.datasForItemType(EItem.LocalBranch)


def testNewBranchFromLocalBranch(qtbot, tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    localBranches = rw.repo.branches.local

    menu = rw.sidebar.generateMenuForEntry(EItem.LocalBranch, 'no-parent')
    findMenuAction(menu, "new.+branch from here").trigger()

    dlg: NewBranchDialog = findQDialog(rw, "new.+branch")
    assert dlg.ui.nameEdit.text() == "no-parent-2"
    assert dlg.acceptButton.isEnabled()  # "no-parent-2" isn't taken

    dlg.ui.nameEdit.setText("no-parent")  # try to set a name that's taken
    assert not dlg.acceptButton.isEnabled()  # can't accept because branch name "no-parent" is taken

    dlg.ui.nameEdit.setText("no-parent-2")
    assert dlg.acceptButton.isEnabled()  # "no-parent-2" isn't taken
    dlg.accept()

    assert "no-parent-2" in localBranches
    assert localBranches["no-parent-2"].target == localBranches["no-parent"].target
    assert "no-parent-2" in rw.sidebar.datasForItemType(EItem.LocalBranch)


def testSwitchBranch(qtbot, tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    localBranches = rw.repo.branches.local

    def getActiveBranchTooltipText():
        return next(tt for tt in rw.sidebar.datasForItemType(EItem.LocalBranch, Qt.ItemDataRole.ToolTipRole)
                    if "active branch" in tt.lower())

    # make sure initial branch state is correct
    assert localBranches['master'].is_checked_out()
    assert not localBranches['no-parent'].is_checked_out()
    assert os.path.isfile(f"{wd}/master.txt")
    assert os.path.isfile(f"{wd}/c/c1.txt")
    assert "master" in getActiveBranchTooltipText()
    assert "no-parent" not in getActiveBranchTooltipText()

    menu = rw.sidebar.generateMenuForEntry(EItem.LocalBranch, 'no-parent')
    findMenuAction(menu, "switch to").trigger()

    assert not localBranches['master'].is_checked_out()
    assert localBranches['no-parent'].is_checked_out()
    assert not os.path.isfile(f"{wd}/master.txt")  # this file doesn't exist on the no-parent branch
    assert os.path.isfile(f"{wd}/c/c1.txt")

    # Active branch change should be reflected in sidebar UI
    assert "master" not in getActiveBranchTooltipText()
    assert "no-parent" in getActiveBranchTooltipText()


def testSwitchBranchWorkdirConflicts(qtbot, tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    writeFile(f"{wd}/c/c1.txt", "la menuiserie et toute la clique")

    rw = mainWindow.openRepo(wd)
    localBranches = rw.repo.branches.local

    assert not localBranches['no-parent'].is_checked_out()
    assert localBranches['master'].is_checked_out()

    menu = rw.sidebar.generateMenuForEntry(EItem.LocalBranch, 'no-parent')
    findMenuAction(menu, "switch to").trigger()

    acceptQMessageBox(rw, "conflict.+with.+file")  # this will fail if the messagebox doesn't show up

    assert not localBranches['no-parent'].is_checked_out()  # still not checked out
    assert localBranches['master'].is_checked_out()


