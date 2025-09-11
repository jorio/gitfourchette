# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import colors
from gitfourchette.localization import _
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class GpgButton(QToolButton):
    def __init__(self, parent):
        super().__init__(parent)

        self.gpgFlag = False
        self.gpgKey = ""
        self.willSign = False

        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

    def setup(self, flag: bool, key: str):
        self.gpgFlag = flag
        self.gpgKey = key
        self.willSign = bool(flag and key)
        canSign = bool(key)

        # Less intrusive button if user hasn't set up their key
        self.setAutoRaise(not canSign)

        keyAction = QAction(self)
        if key:
            keyAction.setText(_("Signing key: {0}", escamp(key)))
        else:
            keyAction.setText(_("Signing key not configured ({0})", "user.signingKey"))

        keyAction.setEnabled(False)

        toggleAction = QAction(self)
        if canSign:
            toggleAction.setText(_("Enable &signing for this commit"))
        else:
            toggleAction.setText(_("This commit will not be signed."))
        toggleAction.setEnabled(canSign)
        toggleAction.setCheckable(canSign)
        toggleAction.setChecked(self.willSign)
        toggleAction.toggled.connect(lambda t: self.updateConfig(t))

        self.addActions([toggleAction, keyAction])

        self.updateConfig(self.willSign)

    def updateConfig(self, willSign: bool):
        self.willSign = willSign

        flag = self.gpgFlag
        key = self.gpgKey
        lines = []

        if willSign:
            lines.append(tagify(_("This commit [will be signed] with your key {yourkey} (configured in {keyconf})."), "<b>"))
        else:
            lines.append(_("This commit will not be signed."))

        if willSign:
            pass
        elif key:
            lines.append(_("Click this button to sign the commit with your key {yourkey} (configured in {keyconf})."))
        else:
            lines.append(_("Your signing key isn’t configured in {keyconf}."))

        if not key:
            pass
        elif flag:
            lines.append(_("This repository is configured to sign commits automatically ({flagconf})."))
        else:
            lines.append(_("Tip: You can configure {flagconf} if you want to sign every commit."))

        tip = "<html style='white-space: pre-wrap;'>" + paragraphs(lines).format(
            flagconf="<i>commit.gpgSign</i>", keyconf="<i>user.signingKey</i>", yourkey=escape(key))

        if willSign:
            icon = stockIcon("gpg-key", f"gray={colors.olive.name()}")
        else:
            icon = stockIcon("gpg-key-fail")

        self.setIcon(icon)
        self.setToolTip(tip)

    def explicitSign(self):
        return self.willSign

    def explicitNoSign(self):
        return not self.willSign
