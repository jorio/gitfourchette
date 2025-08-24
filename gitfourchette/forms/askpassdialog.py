# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os
import re
import shlex
import sys
from pathlib import Path

from gitfourchette.application import GFApplication
from gitfourchette.localization import *
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.qt import *
from gitfourchette.sshagent import SshAgent
from gitfourchette.toolbox import escape, stockIcon


class AskpassDialog(TextInputDialog):
    secret = Signal(str)

    def __init__(self, parent: QWidget | None, prompt: str):
        subtitle = ""

        title = _("Enter SSH credentials")

        # When connecting to an HTTPS remote with user/pass, the username is requested first.
        clearText = re.search(r"^Username(:| for )", prompt)

        builtInAgentPid = os.environ.get(SshAgent.EnvBuiltInAgentPid, "")
        if not clearText and builtInAgentPid:
            subtitle = _("{app}’s SSH agent (PID {pid}) will remember this credential "
                         "until you quit the application.", app=qAppName(), pid=builtInAgentPid)

        htmlPrompt = f"<html style='white-space: pre-wrap;'>{escape(prompt)}"

        super().__init__(parent, title, htmlPrompt, subtitle, multilineSubtitle=True)

        self.lineEdit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

        if not clearText:
            self.lineEdit.setEchoMode(QLineEdit.EchoMode.Password)
            self.echoModeAction = self.lineEdit.addAction(stockIcon("view-visible"), QLineEdit.ActionPosition.TrailingPosition)
            self.echoModeAction.setToolTip(_("Reveal passphrase"))
            self.echoModeAction.triggered.connect(self.onToggleEchoMode)

        self.finished.connect(self.onFinish)

    def onToggleEchoMode(self):
        passwordMode = self.lineEdit.echoMode() == QLineEdit.EchoMode.Password
        passwordMode = not passwordMode
        self.lineEdit.setEchoMode(QLineEdit.EchoMode.Password if passwordMode else QLineEdit.EchoMode.Normal)
        self.echoModeAction.setIcon(stockIcon("view-visible" if passwordMode else "view-hidden"))
        self.echoModeAction.setToolTip(_("Reveal passphrase") if passwordMode else _("Hide passphrase"))
        self.echoModeAction.setChecked(not passwordMode)

    def onFinish(self, result):
        if not result:
            return
        secret = self.lineEdit.text()
        self.secret.emit(secret)

    @classmethod
    def run(cls, prompt: str = ""):
        app = QApplication.instance()
        prompt = prompt or " ".join(app.arguments()[1:])
        dialog = AskpassDialog(None, prompt)
        dialog.rejected.connect(lambda: app.exit(1))
        dialog.secret.connect(print)
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
