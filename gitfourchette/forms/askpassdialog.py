# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os
import shlex
import sys
from pathlib import Path

from gitfourchette.application import GFApplication
from gitfourchette.localization import *
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.qt import *
from gitfourchette.toolbox import escape, stockIcon


class AskpassDialog(TextInputDialog):
    secret = Signal(str)

    def __init__(self, parent: QWidget | None, prompt: str):
        super().__init__(parent, _("Enter SSH credentials"), "<html>" + escape(prompt))

        self.lineEdit.setEchoMode(QLineEdit.EchoMode.Password)
        self.lineEdit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

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
    def run(cls):
        app = QApplication.instance()
        prompt = " ".join(app.arguments()[1:])
        dialog = AskpassDialog(None, prompt)
        dialog.rejected.connect(lambda: app.exit(1))
        dialog.secret.connect(print)
        dialog.show()
        return dialog

    @classmethod
    def environmentForChildProcess(cls):
        launcherScript = Path(qTempDir()) / "askpass.sh"

        if not launcherScript.exists():
            script = "#!/usr/bin/env bash\n"
            script += f"export {GFApplication.AskpassEnvKey}=1\n"

            if FLATPAK:
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
