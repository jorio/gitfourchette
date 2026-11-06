# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import re
from enum import StrEnum
from pathlib import Path

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.ipc.ipcprotocol import GFIpcProtocol
from gitfourchette.localization import *
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.qt import *
from gitfourchette.toolbox import *

_ClearTextPromptPatterns = [
    # When connecting to an HTTPS remote with user/pass, the username is requested first.
    r"^Username(:| for )",

    # First time connecting to a host that's not in ~/.ssh/known_hosts
    r"Are you sure you want to continue connecting \(yes/no",

    # Follow-up question to the above
    r"Please type 'yes'"
]

_UnknownHostPrompt = "Are you sure you want to continue connecting (yes/no/[fingerprint])?"

# Git asks for HTTP(S) credentials through the askpass program too (SSH never says "for '")
_HttpCredentialPattern = re.compile(r"^(Username|Password) for '")

_KeyFingerprintPattern = re.compile(r"key fingerprint is:? (.+?)\.?$", re.MULTILINE)

# Used in verify fingerprint hint, to suggest searching for "(host) ssh fingerprint"
_CommonHostsPattern = re.compile(r"github|gitlab|codeberg", re.IGNORECASE)


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
    messageForClient = Signal(GFIpcProtocol.Response)

    promptKind: AskpassPrompt | str

    autoYesOnAcceptEmptyText: bool
    "Reply 'yes' if the dialog is accepted with an empty text input."

    def __init__(
            self,
            parent: QWidget | None,
            prompt: str,
            sshAskpassPrompt: str = "",
            sshAuthSock: str = "",
            sshAgentPid: str = "",
    ):
        promptKind = AskpassPrompt(sshAskpassPrompt)
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
        httpCredential = promptKind == AskpassPrompt.Entry and bool(_HttpCredentialPattern.match(prompt))

        if promptKind == AskpassPrompt.Confirm:
            title = _("SSH is asking for your confirmation")
        elif promptKind == AskpassPrompt.Message:
            title = _("Message from SSH")
        elif self.unknownHostFingerprint:
            title = _("Connecting to unknown SSH host")
        elif httpCredential:
            title = _("Enter Git credentials")
        else:
            title = _("Enter SSH credentials")

        subtitle = ""
        if httpCredential:
            if settings.prefs.isGitSandboxed():
                subtitle = _("{app}’s built-in Git can’t run credential helpers that need programs "
                             "from your system (like libsecret or gh). To use them, go to {where} "
                             "and switch to your system’s Git.",
                             app=qAppName(),
                             where=tquo(f'{_("Settings")} \u2192 {_p("Prefs", "Git Integration")}'))
        elif promptKind == AskpassPrompt.Entry and not clearText:
            ownAgent = GFApplication.instance().sshAgent

            if ownAgent and sshAgentPid == ownAgent.environment["SSH_AGENT_PID"]:
                subtitle = _("{app}’s ssh-agent will remember this credential "
                             "until you quit the application.", app=qAppName())
            elif Path(sshAuthSock).exists():
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
            self._setUpUnknownHostUi(prompt)
        elif promptKind == AskpassPrompt.Confirm:
            self.okButton.setText(_("Yes"))
            self.cancelButton.setText(_("No"))
            self.lineEdit.setVisible(False)
        elif promptKind == AskpassPrompt.Message:
            self.cancelButton.setVisible(False)
            self.lineEdit.setVisible(False)

        packDialog(self)

    def _setUpUnknownHostUi(self, prompt: str):
        self.okButton.setText(_("Trust"))

        hostTip = ""
        if hostMatch := _CommonHostsPattern.search(prompt):
            hostTip = _("(Tip: search for {0})", tquo(f"{hostMatch.group(0)} ssh fingerprint"))

        hintParts = [
            _("Check that the host’s key matches one you trust:"),
            "<ol><li><p>",
            _("Get the host’s fingerprint from a <b>trusted</b> source. "
              "Don’t use the one shown in this dialog!") + " " + hostTip,
            "</p></li><li>",
            _("Tick {0} and paste the trusted fingerprint. "
              "If it matches, you can safely trust this host.",
              tquo(stripAccelerators(_("&Verify")))),
            "</p></li></ol>",
            _("This is safer than visually comparing fingerprints because it "
              "prevents “fuzzy fingerprint” attacks, where a malicious "
              "fingerprint is crafted to look like the real one."),
        ]

        checkbox = QCheckBox(_("&Verify"))
        checkbox.setObjectName("VerifyFingerprintQCheckBox")
        checkbox.toggled.connect(self.onToggleFingerprintCheckBox)
        self.fingerprintCheckBox = checkbox

        hint = QHintButton(toolTip="".join(hintParts))

        fingerprintWidget = QWidget()
        layout = QHBoxLayout(fingerprintWidget)
        layout.setContentsMargins(QMargins(0, 0, 0, 16))
        layout.addWidget(checkbox)
        layout.addWidget(self.lineEdit)  # yank lineEdit out of its layout and into ours
        layout.addWidget(hint)
        layout.addStretch()
        checkbox.setMinimumHeight(28)
        layout.setStretch(1, 100)

        self.setExtraWidget(fingerprintWidget)
        self.setValidator(self.validateFingerprint)

        tweakWidgetFont(checkbox, 80)
        tweakWidgetFont(self.lineEdit, 80)

        # Prime unchecked state
        self.onToggleFingerprintCheckBox(True)
        self.onToggleFingerprintCheckBox(False)

    def onToggleEchoMode(self):
        passwordMode = self.lineEdit.echoMode() == QLineEdit.EchoMode.Password
        passwordMode = not passwordMode
        self.lineEdit.setEchoMode(QLineEdit.EchoMode.Password if passwordMode else QLineEdit.EchoMode.Normal)
        self.echoModeAction.setIcon(stockIcon("view-visible" if passwordMode else "view-hidden"))
        self.echoModeAction.setToolTip(_("Reveal passphrase") if passwordMode else _("Hide passphrase"))
        self.echoModeAction.setChecked(not passwordMode)

    def onToggleFingerprintCheckBox(self, checked: bool):
        self.lineEdit.setEnabled(checked)
        self.lineEdit.setVisible(checked)
        if checked:
            self.fingerprintCheckBox.setText(_("&Verify") + _(":"))
            self.validator.successText = _("Both fingerprints match")
            self.lineEdit.setPlaceholderText(_("Enter fingerprint from trusted source"))
            if self.isVisible():
                self.lineEdit.setFocus()
        else:
            self.fingerprintCheckBox.setText(_("&Verify fingerprint before trusting (optional)"))
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
        m = GFIpcProtocol.Response()

        if not result:  # canceled
            m.abort = _("You clicked the Cancel button.")
        elif self.promptKind == AskpassPrompt.Entry:
            secret = self.lineEdit.text()
            if not secret and self.autoYesOnAcceptEmptyText:
                secret = "yes"
            m.print = secret

        self.messageForClient.emit(m)
