# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from pathlib import Path

from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import QFilePickerCheckBox, PersistentFileDialog, paragraphs


class KeyFilePickerCheckBox(QFilePickerCheckBox):
    DefaultSshDir = "~/.ssh"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        filePickerTip = paragraphs(
            _("{app} normally uses public/private keys in {path} to authenticate you with remote servers.",
              app=qAppName(), path=KeyFilePickerCheckBox.DefaultSshDir),
            _("Tick this box if you want to access this remote with a custom key."))
        self.checkBox.setToolTip(filePickerTip)

    def fileDialog(self):
        sshDir = Path(KeyFilePickerCheckBox.DefaultSshDir).expanduser()
        fallbackPath = str(sshDir) if sshDir.exists() else ""

        prompt = _("Select public key file for this remote")
        publicKeyFilter = _("Public key file") + " (*.pub)"
        return PersistentFileDialog.openFile(self, "KeyFile", prompt, filter=publicKeyFilter, fallbackPath=fallbackPath)

    def validatePath(self, path: str):
        if not path:
            return ""

        p = Path(path)

        if not p.is_file():
            return _("File not found.")

        if path.endswith(".pub"):
            privateKey = p.with_suffix("")
            if not privateKey.is_file():
                return _("Accompanying private key not found.")
        else:
            privateKey = p
            if not privateKey.with_suffix(".pub").is_file():
                return _("Accompanying public key not found.")

        return ""

    def privateKeyPath(self):
        return self.path().removesuffix(".pub")
