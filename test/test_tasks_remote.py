# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Remote management tests.
"""

import pytest

from gitfourchette.forms.remotedialog import RemoteDialog
from gitfourchette.forms.reposettingsdialog import RepoSettingsDialog
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from .util import *


@pytest.mark.parametrize("method", ["menubar", "sidebarmenu", "sidebarkey"])
def testNewRemote(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    # Make a bare copy of the repo to use as a remote "server"
    barePath = makeBareCopy(wd, addAsRemote="", preFetch=False)

    # Ensure we're starting with the expected settings
    assert len(repo.remotes) == 1
    assert repo.remotes[0].name == "origin"
    assert rw.sidebar.findNodeByKind(SidebarItem.Remote).data == "origin"

    node = rw.sidebar.findNodeByKind(SidebarItem.RemotesHeader)

    # Cover different ways to open the Add Remote dialog
    if method == "menubar":
        triggerMenuAction(mainWindow.menuBar(), "repo/add remote")
    elif method == "sidebarmenu":
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "add remote")
    elif method == "sidebarkey":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Return)
    else:
        raise NotImplementedError(f"unknown method {method}")

    dlg: RemoteDialog = findQDialog(rw, "add remote")
    okButton = dlg.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)

    dlg.ui.urlEdit.setText(barePath)
    dlg.ui.fetchAfterAddCheckBox.setChecked(True)

    # Test name validator
    for badName in ("", "origin", ".remote", "-remote"):
        dlg.ui.nameEdit.setText(badName)
        assert not okButton.isEnabled()

    # Set correct name
    dlg.ui.nameEdit.setText("otherremote")
    assert okButton.isEnabled()
    okButton.click()

    assert len(repo.remotes) == 2
    theRemote = next(r for r in repo.remotes if r.name == "otherremote")
    assert theRemote.url == barePath
    assert rw.sidebar.countNodesByKind(SidebarItem.Remote) == 2
    assert next(n for n in rw.sidebar.findNodesByKind(SidebarItem.Remote) if n.data == "origin")
    assert next(n for n in rw.sidebar.findNodesByKind(SidebarItem.Remote) if n.data == "otherremote")

    # Ensure that fetch-after-add did work
    assert repo.branches.remote["otherremote/master"].target == repo.branches.local["master"].target


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey1", "sidebarkey2"])
def testEditRemote(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    # Ensure we're starting with the expected settings
    assert len(repo.remotes) == 1
    assert repo.remotes[0].name == "origin"
    assert any("/origin/" in n.data for n in rw.sidebar.findNodesByKind(SidebarItem.RemoteBranch))

    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Remote and n.data == "origin")

    if method == "sidebarmenu":
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "edit remote")
    elif method == "sidebarkey1":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_F2)
    elif method == "sidebarkey2":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Return)
    else:
        raise NotImplementedError(f"unknown method {method}")

    dialog: RemoteDialog = findQDialog(rw, "edit remote")
    dialog.ui.nameEdit.setText("mainremote")
    dialog.ui.urlEdit.setText("   https://127.0.0.1/example-repo.git   ")  # test whitespace stripping
    assert dialog.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.accept()

    assert len(repo.remotes) == 1
    assert repo.remotes[0].name == "mainremote"
    assert repo.remotes[0].url == "https://127.0.0.1/example-repo.git"
    assert any("/mainremote/" in n.data for n in rw.sidebar.findNodesByKind(SidebarItem.RemoteBranch))
    assert not any("/origin/" in n.data for n in rw.sidebar.findNodesByKind(SidebarItem.RemoteBranch))


@pytest.mark.parametrize("globalSkip", [False, True])
@pytest.mark.parametrize("skip", [False, True])
def testNewRemoteSkipFetchAll(tempDir, mainWindow, skip, globalSkip):
    wd = unpackRepo(tempDir)
    if globalSkip:
        shell("git config --global remote.otherremote.skipFetchAll true", wd)
    rw = mainWindow.openRepo(wd)
    barePath = makeBareCopy(wd, addAsRemote="", preFetch=False)

    triggerMenuAction(mainWindow.menuBar(), "repo/add remote")
    dlg: RemoteDialog = findQDialog(rw, "add remote")
    dlg.ui.nameEdit.setText("otherremote")
    dlg.ui.urlEdit.setText(barePath)
    dlg.ui.fetchAfterAddCheckBox.setChecked(False)
    dlg.ui.skipFetchAllCheckBox.setChecked(skip)
    dlg.accept()

    assert rw.repo.get_remote_skipfetchall("otherremote") == skip
    assert not rw.repo.get_remote_skipfetchall("origin")


@pytest.mark.parametrize(["before", "after"], [
    (True, True), (True, False), (False, True),
    ("global", True), ("global", False),
    ("duplicate", True), ("duplicate", False),
    ("skipDefaultUpdate", True), ("skipDefaultUpdate", False),
])
@pytest.mark.parametrize("newName", ["origin", "renamed"])
def testEditRemoteSkipFetchAll(tempDir, mainWindow, before, after, newName):
    wd = unpackRepo(tempDir)
    if before == "global":  # "git remote rename" doesn't move this one
        shell("git config --global remote.origin.skipFetchAll true", wd)
    elif before == "duplicate":  # Hand-edited config: the last value counts
        shell("git config --add remote.origin.skipFetchAll false", wd)
        shell("git config --add remote.origin.skipFetchAll true", wd)
    elif before == "skipDefaultUpdate":  # Deprecated synonym of skipFetchAll
        shell("git config remote.origin.skipDefaultUpdate true", wd)
    elif before:
        shell("git config remote.origin.skipFetchAll true", wd)  # Old syntax: CI also runs git 2.34
    rw = mainWindow.openRepo(wd)

    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Remote and n.data == "origin")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "edit remote")
    dialog: RemoteDialog = findQDialog(rw, "edit remote")
    assert dialog.ui.skipFetchAllCheckBox.isChecked() == bool(before)
    dialog.ui.nameEdit.setText(newName)
    dialog.ui.skipFetchAllCheckBox.setChecked(after)
    dialog.accept()

    config = readTextFile(f"{wd}/.git/config")
    assert "skipFetchAll" not in config.split(f'[remote "{newName}"]')[0]  # Nothing left under the old name
    assert "skipDefaultUpdate" not in config
    assert rw.repo.get_remote_skipfetchall(newName) == after


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey"])
def testDeleteRemote(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    assert rw.repo.remotes["origin"] is not None
    assert any("/origin/" in n.data for n in rw.sidebar.findNodesByKind(SidebarItem.RemoteBranch))

    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Remote and n.data == "origin")

    if method == "sidebarmenu":
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "remove remote")
    elif method == "sidebarkey":
        rw.sidebar.setFocus()
        rw.sidebar.selectNode(node)
        QTest.keyPress(rw.sidebar, Qt.Key.Key_Delete)
    else:
        raise NotImplementedError(f"unknown method {method}")

    acceptQMessageBox(rw, "really remove remote")

    assert len(list(rw.repo.remotes)) == 0
    assert not any("/origin/" in n.data for n in rw.sidebar.findNodesByKind(SidebarItem.RemoteBranch))


def testRemoteFromGlobalConfig(tempDir, mainWindow):
    """
    Git also reads remotes from the global config. GF listed remotes from
    .git/config alone, so it hid such a remote and wouldn't fetch it.
    """
    wd = unpackRepo(tempDir)
    barePath = makeBareCopy(wd, addAsRemote="", preFetch=False)
    shell("git remote remove origin", wd)

    globalConfig = pygit2.Config.get_global_config()
    globalConfig["remote.globalremote.url"] = barePath
    globalConfig["remote.globalremote.fetch"] = "+refs/heads/*:refs/remotes/globalremote/*"

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Remote and n.data == "globalremote")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "fetch")
    assert "refs/remotes/globalremote/master" in rw.repo.references

    # Not "add a remote first"
    triggerMenuAction(mainWindow.menuBar(), "repo/push")
    findQDialog(rw, "push.+branch").reject()


def testRemoteUrlIsTheOneGitUses(tempDir, mainWindow):
    """
    With several url values and url.<base>.insteadOf, Git uses the first url,
    rewritten. libgit2 returned the last one as written.
    """
    wd = unpackRepo(tempDir)
    shell("""
        git config url.https://example.com/.insteadOf ex:
        git remote set-url origin ex:first.git
        git config --add remote.origin.url https://example.com/second.git
    """, wd)

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Remote and n.data == "origin")
    toolTip = rw.sidebar.nodeToFilterIndex(node).data(Qt.ItemDataRole.ToolTipRole)

    assert "https://example.com/first.git" in toolTip


def testEditRemoteShowsUrlAsWritten(tempDir, mainWindow):
    """
    Saving the dialog writes its URL to the config, so it must be the URL as
    written there, not the one after url.<base>.insteadOf.
    """
    wd = unpackRepo(tempDir)
    shell("""
        git config url.https://example.com/.insteadOf ex:
        git remote set-url origin ex:first.git
    """, wd)

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Remote and n.data == "origin")
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "edit remote")
    dialog: RemoteDialog = findQDialog(rw, "edit remote")

    assert dialog.ui.urlEdit.text() == "ex:first.git"
    dialog.reject()


def testRemoteWithNegativeRefspec(tempDir, mainWindow):
    """
    pygit2 1.14.1 couldn't load a remote with a negative refspec (Git 2.29+),
    so its tooltip raised.
    """
    wd = unpackRepo(tempDir)
    shell("git config --add remote.origin.fetch ^refs/heads/no-parent", wd)

    rw = mainWindow.openRepo(wd)
    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Remote and n.data == "origin")
    toolTip = rw.sidebar.nodeToFilterIndex(node).data(Qt.ItemDataRole.ToolTipRole)
    assert "TestGitRepository" in toolTip  # origin's URL


def testCustomKeyUI(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    def openSettings():
        triggerMenuAction(mainWindow.menuBar(), "repo/settings")
        dialog: RepoSettingsDialog = findQDialog(rw, "repo settings", RepoSettingsDialog)
        picker = dialog.ui.keyFilePicker
        return dialog, picker

    assert not rw.repoModel.prefs.customKeyFile

    dialog, picker = openSettings()
    assert not picker.checkBox.isChecked()
    assert not picker.pathLabel.isVisible()

    # Set key files
    for path, warning in [
        ("keys/doesntexist", "file not found"),
        ("keys/missingpriv.pub", "private key not found"),
        ("keys/missingpub", "public key not found"),
        ("keys/simple", ""),
    ]:
        if not picker.checkBox.isChecked():
            picker.checkBox.click()
        else:
            picker.browseButton.click()
        acceptQFileDialog(picker, "key file", getTestDataPath(path))
        if WINDOWS:
            path = path.replace("/", "\\")
        assert picker.pathLabel.text().endswith(path)
        assert bool(warning) == picker.warningButton.isVisible()
        if warning:
            assert warning in picker.warningButton.toolTip().lower()

    # Save settings
    dialog.accept()
    assert rw.repoModel.prefs.customKeyFile.endswith("keys/simple")

    # Reopen dialog and check that the setting is still set
    dialog, picker = openSettings()
    assert picker.checkBox.isChecked()
    assert picker.pathLabel.isVisible()
    assert picker.pathLabel.text().endswith("keys/simple" if not WINDOWS else "keys\\simple")
    assert picker.browseButton.isVisible()
    assert not picker.warningButton.isVisible()
    dialog.accept()

    # Reopen dialog and unset custom key
    dialog, picker = openSettings()
    picker.checkBox.setChecked(False)
    dialog.accept()
    assert not rw.repoModel.prefs.customKeyFile


def testRemoteUrlProtocolSwap(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Remote and n.data == "origin")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "edit remote")
    dialog: RemoteDialog = findQDialog(rw, "edit remote")

    for url, protocol, alternative in [
        ("file:///home/toto/bugdom", "", ""),
        ("https://github.com/jorio/bugdom", "https", "git@github.com:jorio/bugdom"),
        ("https://github.com:80/jorio/bugdom", "https", "git@github.com:jorio/bugdom"),
        ("git@github.com:jorio/bugdom", "ssh", "https://github.com/jorio/bugdom"),
        ("git@github.com:jorio/bugdom.git", "ssh", "https://github.com/jorio/bugdom"),
        ("github.com:jorio/bugdom", "ssh", "https://github.com/jorio/bugdom"),
        ("   github.com:jorio/bugdom   ", "ssh", "https://github.com/jorio/bugdom"),
        ("ssh://github.com:21/jorio/bugdom", "ssh", "https://github.com/jorio/bugdom"),
        ("ssh://git@github.com/jorio/bugdom", "ssh", "https://github.com/jorio/bugdom"),
        ("git://github.com/jorio/bugdom", "git", "git@github.com:jorio/bugdom"),
        ("whatever", "", ""),
    ]:
        print("testing", url, protocol, alternative)
        dialog.ui.urlEdit.setText(url)
        if not protocol:
            assert dialog.ui.protocolButton.isHidden()
            continue
        assert dialog.ui.protocolButton.isVisible()
        protocolMenu = dialog.ui.protocolButton.menu()
        assert len(protocolMenu.actions()) == 1
        action = protocolMenu.actions()[0]
        assert action.text() == alternative
        action.trigger()
        assert dialog.ui.urlEdit.text() == alternative

    dialog.reject()
