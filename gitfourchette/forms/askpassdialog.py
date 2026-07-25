# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.pycompat import *

import os
import re
import shlex
from enum import StrEnum
from pathlib import Path

from gitfourchette.localization import *
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.qt import *
from gitfourchette.sshagent import SshAgent
from gitfourchette.toolbox import escape, stockIcon, tquo, paragraphs, tweakWidgetFont, QHintButton

_ClearTextPromptPatterns = [
    # When connecting to an HTTPS remote with user/pass, the username is requested first.
    r"^Username(:| for )",

    # First time connecting to a host that's not in ~/.ssh/known_hosts
    r"Are you sure you want to continue connecting \(yes/no",

    # Follow-up question to the above
    r"Please type 'yes'"
]

_UnknownHostPrompt = "Are you sure you want to continue connecting (yes/no/[fingerprint])?"

_KeyFingerprintPattern = re.compile(r"key fingerprint is:? (.+?)\.?$", re.MULTILINE)


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
    promptKind: AskpassPrompt | str

    autoYesOnAcceptEmptyText: bool
    "Reply 'yes' if the dialog is accepted with an empty text input."

    def __init__(self, parent: QWidget | None, prompt: str):
        promptKind = os.environ.get("SSH_ASKPASS_PROMPT", AskpassPrompt.Entry)
        self.promptKind = promptKind

        prompt = prompt.strip()
        clearText = any(re.search(pattern, prompt) for pattern in _ClearTextPromptPatterns)

        # Detect "unknown host" message
        self.unknownHostFingerprint = ""
        if clearText and promptKind == AskpassPrompt.Entry and prompt.endswith(_UnknownHostPrompt):
            fingerprintMatch = _KeyFingerprintPattern.search(prompt)
            if fingerprintMatch:
                self.unknownHostFingerprint = fingerprintMatch.group(1)
                prompt = prompt.removesuffix(_UnknownHostPrompt).strip()

        self.autoYesOnAcceptEmptyText = bool(self.unknownHostFingerprint)

        if promptKind == AskpassPrompt.Confirm:
            title = _("SSH is asking for your confirmation")
        elif promptKind == AskpassPrompt.Message:
            title = _("Message from SSH")
        elif self.unknownHostFingerprint:
            title = _("Connecting to unknown SSH host")
        else:
            title = _("Enter SSH credentials")

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

        promptLines = escape(prompt).splitlines()
        if self.unknownHostFingerprint:
            promptLines.append("<b>" + _("To continue connecting, do you trust this key?"))
        htmlPrompt = paragraphs(*promptLines)

        super().__init__(
            parent, title, htmlPrompt, subtitle,
            multilineSubtitle=True, selectableLabel=True)

        if not clearText:
            self.lineEdit.setEchoMode(QLineEdit.EchoMode.Password)
            self.echoModeAction = self.lineEdit.addAction(stockIcon("view-visible"), QLineEdit.ActionPosition.TrailingPosition)
            self.echoModeAction.setToolTip(_("Reveal passphrase"))
            self.echoModeAction.triggered.connect(self.onToggleEchoMode)

        self.finished.connect(self.onFinish)

        if self.unknownHostFingerprint:
            self._setUpUnknownHostUi()
        elif promptKind == AskpassPrompt.Confirm:
            self.okButton.setText(_("Yes"))
            self.cancelButton.setText(_("No"))
            self.lineEdit.setVisible(False)
        elif promptKind == AskpassPrompt.Message:
            self.cancelButton.setVisible(False)
            self.lineEdit.setVisible(False)

    def _setUpUnknownHostUi(self):
        self.okButton.setText(_("Trust"))

        hintParts = [
            _("Check that the host’s key matches one you trust:"),
            "<ol><li><p>",
            _("Get the host’s fingerprint from a trusted source. "
              "(Do not use the one shown in this dialog!)"),
            "</p></li><li>",
            _("Paste the trusted fingerprint here. "
              "If it matches the host’s, you may trust this host and proceed."),
            "</p></li></ol>",
            _("This is safer than visually comparing fingerprints because it "
              "prevents “fuzzy fingerprint” attacks, where a malicious "
              "fingerprint is crafted to look like the real one."),
        ]

        checkbox = QCheckBox(_("&Verify fingerprint before trusting (optional)"))
        checkbox.setObjectName("VerifyFingerprintQCheckBox")
        checkbox.toggled.connect(self.onToggleFingerprintCheckbox)

        hint = QHintButton(toolTip="".join(hintParts))

        fingerprintWidget = QWidget()
        layout = QGridLayout(fingerprintWidget)
        layout.setContentsMargins(QMargins(0, 0, 0, 16))
        layout.addWidget(checkbox,      0, 0)
        layout.addWidget(hint,          0, 1)
        layout.addWidget(self.lineEdit, 1, 0, 1, 3)  # yank lineEdit out of its layout and into ours
        layout.setColumnStretch(2, 1)
        layout.setVerticalSpacing(0)
        tweakWidgetFont(fingerprintWidget, 80)

        self.setExtraWidget(fingerprintWidget)
        self.setValidator(self.validateFingerprint)

        # Prime unchecked state
        self.onToggleFingerprintCheckbox(True)
        self.onToggleFingerprintCheckbox(False)

    def onToggleEchoMode(self):
        passwordMode = self.lineEdit.echoMode() == QLineEdit.EchoMode.Password
        passwordMode = not passwordMode
        self.lineEdit.setEchoMode(QLineEdit.EchoMode.Password if passwordMode else QLineEdit.EchoMode.Normal)
        self.echoModeAction.setIcon(stockIcon("view-visible" if passwordMode else "view-hidden"))
        self.echoModeAction.setToolTip(_("Reveal passphrase") if passwordMode else _("Hide passphrase"))
        self.echoModeAction.setChecked(not passwordMode)

    def onToggleFingerprintCheckbox(self, checked: bool):
        self.lineEdit.setEnabled(checked)
        if checked:
            self.validator.successText = _("Both fingerprints match")
            self.lineEdit.setPlaceholderText(_("Enter fingerprint from trusted source"))
            if self.isVisible():
                self.lineEdit.setFocus()
        else:
            self.validator.successText = ""
            self.lineEdit.setPlaceholderText("")
            self.lineEdit.clear()
        self.validator.run(silenceEmptyWarnings=True)

    def validateFingerprint(self, s: str):
        if not self.lineEdit.isEnabled():
            return ""

        s = s.strip()
        if not s:
            return _("Cannot be empty.")
        if s != self.unknownHostFingerprint:
            return _("Fingerprint does not match.") + "\n" + self.unknownHostFingerprint
        return ""

    def onFinish(self, result: int):
        if not result:
            QApplication.instance().exit(1)
            return

        if self.promptKind == AskpassPrompt.Entry:
            secret = self.lineEdit.text()

            if not secret and self.autoYesOnAcceptEmptyText:
                secret = "yes"

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
    def environmentForChildProcess(cls, sandbox: bool):
        from gitfourchette.exttools.toolcommands import ToolCommands

        fileName = "askpass_sandboxed.sh" if sandbox else "askpass.sh"
        launcherScript = Path(qTempDir(), fileName)

        if not launcherScript.exists():
            tokens = ToolCommands.spawnNewInstance(__name__, sandbox=sandbox)

            # Discard stderr to avoid forwarding Qt error spam to ProcessDialog.
            script = ('#!/usr/bin/env bash\n'
                      f'exec {shlex.join(tokens)} "$@" 2>/dev/null\n')

            launcherScript.write_text(script, "utf-8")
            launcherScript.chmod(0o755)

        return {
            "SSH_ASKPASS": str(launcherScript),
            "SSH_ASKPASS_REQUIRE": "force",
        }


def main():
    from gitfourchette.application import GFApplication
    import sys
    app = GFApplication(sys.argv, barebones=True)
    _dontCollectMe = AskpassDialog.run()
    returnCode = app.exec()
    return sys.exit(returnCode)


if __name__ == "__main__":
    main()
