# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.localization import *
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class PassphraseDialog(TextInputDialog):
    passphraseReady = Signal(str, str)

    def __init__(self, parent: QWidget, keyfile: str):
        super().__init__(
            parent,
            _("Passphrase-protected key file"),
            _("Enter passphrase to use this key file:"),
            subtitle=escape(compactPath(keyfile)))

        self.keyfile = keyfile

        self.lineEdit.setEchoMode(QLineEdit.EchoMode.Password)

        rememberCheckBox = QCheckBox(_("Remember passphrase for this session"))
        rememberCheckBox.setChecked(settings.prefs.rememberPassphrases)
        rememberCheckBox.checkStateChanged.connect(self.onRememberCheckStateChanged)
        self.setExtraWidget(rememberCheckBox)
        self.rememberCheckBox = rememberCheckBox

        self.finished.connect(self.onFinish)

    def onRememberCheckStateChanged(self, state: Qt.CheckState):
        settings.prefs.rememberPassphrases = state == Qt.CheckState.Checked
        settings.prefs.setDirty()

    def onFinish(self, result):
        if result:
            secret = self.lineEdit.text()
            self.passphraseReady.emit(self.keyfile, secret)
        else:
            self.passphraseReady.emit("", "")
