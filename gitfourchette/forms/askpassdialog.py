# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.pycompat import *

import os
import re
import shlex
import sys
from enum import StrEnum
from pathlib import Path

from gitfourchette.application import GFApplication
from gitfourchette.localization import *
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.qt import *
from gitfourchette.sshagent import SshAgent
from gitfourchette.toolbox import escape, stockIcon, tquo


class AskpassPrompt(StrEnum):
    """
    AskpassDialog behaviors driven by the SSH_ASKPASS_PROMPT environment variable.
    """

    Entry = ""
    """
    Normal text input with ok/cancel buttons.
    """

    Confirm = "confirm"
    """
    No text input, yes/no buttons, exit code 0 if yes (e.g. `ssh -o AddKeysToAgent=ask`).
    Per `man ssh-add`: "Successful confirmation is signaled by a zero exit
    status from ssh-askpass, rather than text entered into the requester."
    """

    Message = "none"
    """
    No text input, just a dismiss button.
    """


class AskpassDialog(TextInputDialog):
    ClearTextPatterns = [
        # When connecting to an HTTPS remote with user/pass, the username is requested first.
        r"^Username(:| for )",

        # First time connecting to a host that's not in ~/.ssh/known_hosts
        r"Are you sure you want to continue connecting \(yes/no",

        # Follow-up question to the above
        r"Please type 'yes'"
    ]

    def __init__(self, parent: QWidget | None, prompt: str):
        promptKind = os.environ.get("SSH_ASKPASS_PROMPT", AskpassPrompt.Entry)
        self.promptKind = promptKind

        if promptKind == AskpassPrompt.Confirm:
            title = _("SSH is asking for your confirmation")
        elif promptKind == AskpassPrompt.Message:
            title = _("Message from SSH")
        else:
            title = _("Enter SSH credentials")

        clearText = any(re.search(pattern, prompt) for pattern in self.ClearTextPatterns)

        subtitle = ""
        if promptKind == AskpassPrompt.Entry and not clearText:
            hasBuiltInAgent = bool(os.environ.get(SshAgent.EnvBuiltInAgentPid, ""))
            hasAgentSocket = os.path.exists(os.environ.get("SSH_AUTH_SOCK", ""))
            if hasBuiltInAgent:
                subtitle = _("{app}’s ssh-agent will remember this credential "
                             "until you quit the application.", app=qAppName())
            elif hasAgentSocket:
                subtitle = _("An ssh-agent is running on your system. It will remember this credential "
                             "if {0} is enabled in your SSH configuration.", tquo("AddKeysToAgent"))
            else:
                subtitle = _("This credential will not be remembered "
                             "because ssh-agent isn’t running on your system.")

        htmlPrompt = f"<html style='white-space: pre-wrap;'>{escape(prompt)}"

        super().__init__(parent, title, htmlPrompt, subtitle, multilineSubtitle=True)

        self.lineEdit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

        if not clearText:
            self.lineEdit.setEchoMode(QLineEdit.EchoMode.Password)
            self.echoModeAction = self.lineEdit.addAction(stockIcon("view-visible"), QLineEdit.ActionPosition.TrailingPosition)
            self.echoModeAction.setToolTip(_("Reveal passphrase"))
            self.echoModeAction.triggered.connect(self.onToggleEchoMode)

        self.finished.connect(self.onFinish)

        if promptKind == AskpassPrompt.Confirm:

            self.okButton.setText(_("Yes"))
            self.cancelButton.setText(_("No"))
            self.lineEdit.setVisible(False)
        elif promptKind == AskpassPrompt.Message:
            self.cancelButton.setVisible(False)
            self.lineEdit.setVisible(False)

    def onToggleEchoMode(self):
        passwordMode = self.lineEdit.echoMode() == QLineEdit.EchoMode.Password
        passwordMode = not passwordMode
        self.lineEdit.setEchoMode(QLineEdit.EchoMode.Password if passwordMode else QLineEdit.EchoMode.Normal)
        self.echoModeAction.setIcon(stockIcon("view-visible" if passwordMode else "view-hidden"))
        self.echoModeAction.setToolTip(_("Reveal passphrase") if passwordMode else _("Hide passphrase"))
        self.echoModeAction.setChecked(not passwordMode)

    def onFinish(self, result: int):
        if not result:
            QApplication.instance().exit(1)
            return

        if self.promptKind == AskpassPrompt.Entry:
            secret = self.lineEdit.text()
            print(secret)

        QApplication.instance().exit(0)

    @classmethod
    def run(cls, prompt: str = ""):
        app = QApplication.instance()
        prompt = prompt or " ".join(app.arguments()[1:])
        dialog = AskpassDialog(None, prompt)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()
        return dialog

    @classmethod
    def environmentForChildProcess(cls, sandbox: bool = False):
        launcherScript = Path(qTempDir()) / ("askpass_sandboxed.sh" if sandbox else "askpass.sh")

        if not launcherScript.exists():
            script = "#!/usr/bin/env bash\n"
            script += f"export {GFApplication.AskpassEnvKey}=1\n"

            if FLATPAK and not sandbox:
                tokens = ["flatpak", "run", os.environ["FLATPAK_ID"]]
            else:
                script += f"export PYTHONPATH={shlex.quote(':'.join(sys.path))}\n"
                tokens = sys.orig_argv
                trimArgs = len(sys.argv) - 1
                assert trimArgs >= 0
                if trimArgs:
                    tokens = tokens[:-trimArgs]
                assert tokens

            # Throw away stderr to avoid forwarding Qt error spam to ProcessDialog.
            script += f"""exec {shlex.join(tokens)} "$@" 2>/dev/null\n"""
            launcherScript.write_text(script, "utf-8")
            launcherScript.chmod(0o755)

        return {
            "SSH_ASKPASS": str(launcherScript),
            "SSH_ASKPASS_REQUIRE": "force",
        }
