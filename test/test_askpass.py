# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.forms.askpassdialog import AskpassDialog
from gitfourchette.sshagent import SshAgent
from .util import *


@pytest.fixture
def captureExitCode(monkeypatch):
    exitCalls = []
    monkeypatch.setattr(QApplication.instance(), "exit", lambda exitCode: exitCalls.append(exitCode))

    def getExitCode():
        assert exitCalls, "application has not exited yet!"
        return exitCalls[0]

    yield getExitCode


def testAskpassDialogPassphrase(tempDir, mainWindow, capfd, captureExitCode):
    # Monkeypatch environment to pretend our built-in ssh agent is running
    # (cover code path telling user the credential will be saved)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv(SshAgent.EnvBuiltInAgentPid, "999999")

        dialog = AskpassDialog.run("Enter passphrase for key '/home/criquette/.ssh/id_ed25519':")

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
    assert capfd.readouterr()[0] == "hello\n"
    assert captureExitCode() == 0


def testAskpassDialogUsername(tempDir, mainWindow, capfd, captureExitCode):
    dialog = AskpassDialog.run("Username for some.server.example:")
    assert dialog.lineEdit.echoMode() == QLineEdit.EchoMode.Normal
    dialog.lineEdit.setText("criquetterockwell")
    dialog.accept()
    assert capfd.readouterr()[0] == "criquetterockwell\n"
    assert captureExitCode() == 0


def testAskpassDialogCancel(tempDir, mainWindow, capfd, captureExitCode):
    dialog = AskpassDialog.run("Enter passphrase for key '/home/criquette/.ssh/id_ed25519':")
    dialog.lineEdit.setText("hello")
    dialog.reject()
    assert capfd.readouterr()[0] == ""
    assert captureExitCode() == 1


def testAskpassDialogAddToKnownHosts(tempDir, mainWindow, capfd, captureExitCode):
    dialog = AskpassDialog.run(
        "The authenticity of host '[0.0.0.0]:8888 ([0.0.0.0]:8888)' can't be established.\n"
        "ED25519 key fingerprint is SHA256:xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.\n"
        "This key is not known by any other names.\n"
        "Are you sure you want to continue connecting (yes/no/[fingerprint])? ")

    assert dialog.lineEdit.echoMode() == QLineEdit.EchoMode.Normal
    dialog.lineEdit.setText("yes")
    dialog.accept()
    out, _err = capfd.readouterr()
    assert out == "yes\n"
    assert captureExitCode() == 0


def testAskpassDialogConfirmMode(tempDir, mainWindow, capfd, captureExitCode):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SSH_ASKPASS_PROMPT", "confirm")
        dialog = AskpassDialog.run("Add key /home/criquette/.ssh/id_ed25519 (criquette@rockwell) to agent?")

    assert not dialog.lineEdit.isVisible()
    assert findTextInWidget(dialog.okButton, "yes")
    assert findTextInWidget(dialog.cancelButton, "no")
    dialog.okButton.click()
    assert capfd.readouterr()[0] == ""
    assert captureExitCode() == 0


def testAskpassDialogNoneMode(tempDir, mainWindow, capfd, captureExitCode):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SSH_ASKPASS_PROMPT", "none")
        dialog = AskpassDialog.run("ssh has something to say\nno input required")

    assert not dialog.lineEdit.isVisible()
    assert not dialog.cancelButton.isVisible()
    dialog.accept()
    assert capfd.readouterr()[0] == ""
    assert captureExitCode() == 0
