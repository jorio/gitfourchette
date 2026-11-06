# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.forms.askpassdialog import AskpassDialog
from gitfourchette.ipc.ipcprotocol import GFIpcProtocol
from .util import *


def testAskpassDialogPassphrase(tempDir, mainWindow):
    messages = []
    dialog = AskpassDialog(
        mainWindow,
        prompt="Enter passphrase for key '/home/criquette/.ssh/id_ed25519':",
        # Pretend our built-in ssh agent is running
        # (cover code path telling user the credential will be saved)
        sshAgentPid="999999")
    dialog.messageForClient.connect(messages.append)

    assert any(
        findTextInWidget(label, "ssh.agent.+will remember this credential")
        for label in dialog.findChildren(QLabel))

    dialog.lineEdit.setText("hello")

    assert dialog.lineEdit.echoMode() == QLineEdit.EchoMode.Password
    dialog.echoModeAction.trigger()
    assert dialog.lineEdit.echoMode() == QLineEdit.EchoMode.Normal
    dialog.echoModeAction.trigger()
    assert dialog.lineEdit.echoMode() == QLineEdit.EchoMode.Password

    dialog.accept()
    assert messages.pop() == GFIpcProtocol.Response(print="hello")


@pytest.mark.parametrize("sandboxedGit", [False, True])
@pytest.mark.parametrize("prompt", [
    "Username for 'https://example.com': ",
    "Password for 'https://alice@example.com': ",
])
def testAskpassDialogHttpsCredentials(tempDir, mainWindow, monkeypatch, prompt, sandboxedGit):
    from gitfourchette import settings
    monkeypatch.setattr(settings.prefs, "gitPath", "flatpak:/app/bin/git" if sandboxedGit else "git")

    dialog = AskpassDialog(mainWindow, prompt=prompt)
    labels = dialog.findChildren(QLabel)

    assert "SSH" not in dialog.windowTitle()
    assert not any(findTextInWidget(label, "ssh.agent") for label in labels)
    assert sandboxedGit == any(findTextInWidget(label, "can.t run credential helpers") for label in labels)

    isPassword = prompt.startswith("Password")
    expectedEchoMode = QLineEdit.EchoMode.Password if isPassword else QLineEdit.EchoMode.Normal
    assert dialog.lineEdit.echoMode() == expectedEchoMode
    dialog.reject()


def testAskpassDialogUsername(tempDir, mainWindow):
    messages = []
    dialog = AskpassDialog(
        mainWindow,
        prompt="Username for some.server.example:")
    dialog.messageForClient.connect(messages.append)

    assert dialog.lineEdit.echoMode() == QLineEdit.EchoMode.Normal
    dialog.lineEdit.setText("criquetterockwell")
    dialog.accept()
    assert messages.pop() == GFIpcProtocol.Response(print="criquetterockwell")


def testAskpassDialogCancel(tempDir, mainWindow):
    messages = []
    dialog = AskpassDialog(mainWindow, "Enter passphrase for key '/home/criquette/.ssh/id_ed25519':")
    dialog.messageForClient.connect(messages.append)

    dialog.lineEdit.setText("hello")
    dialog.reject()
    assert messages.pop() == GFIpcProtocol.Response(abort="You clicked the Cancel button.")


@pytest.mark.parametrize("verifyFingerprint", [False, True])
def testAskpassDialogAddToKnownHosts(tempDir, mainWindow, verifyFingerprint):
    messages = []
    dialog = AskpassDialog(
        mainWindow,
        "The authenticity of host 'github.com:8888 ([0.0.0.0]:8888)' can't be established.\n"
        "ED25519 key fingerprint is: SHA256:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n"
        "This key is not known by any other names.\n"
        "Are you sure you want to continue connecting (yes/no/[fingerprint])? ")
    dialog.messageForClient.connect(messages.append)

    verify = dialog.findChild(QCheckBox, "VerifyFingerprintQCheckBox")

    assert findTextInWidget(dialog.okButton, "trust")
    assert not verify.isChecked()

    if verifyFingerprint:
        verify.setChecked(True)
        assert not dialog.okButton.isEnabled()
        dialog.lineEdit.setText("SHA256:FINGERPRINT_MISMATCH")
        assert not dialog.okButton.isEnabled()
        dialog.lineEdit.setText("SHA256:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        expectedStdout = "SHA256:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    else:
        expectedStdout = "yes"

    assert dialog.okButton.isEnabled()
    dialog.accept()
    assert messages.pop() == GFIpcProtocol.Response(print=expectedStdout)


def testAskpassDialogConfirmMode(tempDir, mainWindow):
    messages = []
    dialog = AskpassDialog(
        mainWindow,
        prompt="Add key /home/criquette/.ssh/id_ed25519 (criquette@rockwell) to agent?",
        sshAskpassPrompt="confirm")
    dialog.messageForClient.connect(messages.append)
    dialog.show()

    assert not dialog.lineEdit.isVisible()
    assert findTextInWidget(dialog.okButton, "yes")
    assert findTextInWidget(dialog.cancelButton, "no")
    dialog.okButton.click()
    assert messages.pop() == GFIpcProtocol.Response()

    dialog = AskpassDialog(
        mainWindow,
        prompt="Add key /home/criquette/.ssh/id_ed25519 (criquette@rockwell) to agent?",
        sshAskpassPrompt="confirm")
    dialog.messageForClient.connect(messages.append)
    dialog.show()
    dialog.cancelButton.click()
    assert messages.pop() == GFIpcProtocol.Response(abort="You clicked the Cancel button.")


def testAskpassDialogNoneMode(tempDir, mainWindow):
    messages = []
    dialog = AskpassDialog(
        mainWindow,
        prompt="ssh has something to say\nno input required",
        sshAskpassPrompt="none")
    dialog.messageForClient.connect(messages.append)

    assert not dialog.lineEdit.isVisible()
    assert not dialog.cancelButton.isVisible()
    dialog.accept()
    assert messages.pop() == GFIpcProtocol.Response()
