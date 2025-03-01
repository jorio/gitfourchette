# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Remote management tests.
"""

import pytest
from .util import *
from gitfourchette.forms.remotedialog import RemoteDialog
from gitfourchette.sidebar.sidebarmodel import SidebarItem


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

    q: RemoteDialog = findQDialog(rw, "add remote")
    q.ui.nameEdit.setText("otherremote")
    q.ui.urlEdit.setText(barePath)
    q.ui.fetchAfterAddCheckBox.setChecked(True)
    q.accept()

    assert len(repo.remotes) == 2
    assert repo.remotes[1].name == "otherremote"
    assert repo.remotes[1].url == barePath
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


@pytest.mark.parametrize("method", ["sidebarmenu", "sidebarkey"])
def testDeleteRemote(tempDir, mainWindow, method):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    repo = rw.repo

    assert repo.remotes["origin"] is not None
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

    assert len(list(repo.remotes)) == 0
    assert not any("/origin/" in n.data for n in rw.sidebar.findNodesByKind(SidebarItem.RemoteBranch))


def testRemoteCustomKeyUI(tempDir, mainWindow):
    keyfileConfigKey = "remote.origin.gitfourchette-keyfile"

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    def openRemoteDialog():
        node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Remote and n.data == "origin")
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "edit remote")
        dialog: RemoteDialog = findQDialog(rw, "edit remote")
        picker = dialog.ui.keyFilePicker
        return dialog, picker

    assert keyfileConfigKey not in rw.repo.config

    dialog, picker = openRemoteDialog()
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
        assert picker.pathLabel.text().endswith(path)
        assert bool(warning) == picker.warningButton.isVisible()
        if warning:
            assert warning in picker.warningButton.toolTip().lower()

    # Save settings
    dialog.accept()
    assert rw.repo.config[keyfileConfigKey].endswith("keys/simple")

    # Reopen remote dialog and check that the setting is still set
    dialog, picker = openRemoteDialog()
    assert picker.checkBox.isChecked()
    assert picker.pathLabel.isVisible()
    assert picker.pathLabel.text().endswith("keys/simple")
    assert picker.browseButton.isVisible()
    assert not picker.warningButton.isVisible()
    dialog.accept()

    # Reopen remote dialog and unset custom key
    dialog, picker = openRemoteDialog()
    picker.checkBox.setChecked(False)
    dialog.accept()
    assert keyfileConfigKey not in rw.repo.config


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
