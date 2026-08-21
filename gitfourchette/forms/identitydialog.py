# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.signatureform import SignatureForm
from gitfourchette.forms.ui_identitydialog import Ui_IdentityDialog
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class IdentityDialog(QDialog):
    def __init__(
            self,
            firstRun: bool,
            initialName: str,
            initialEmail: str,
            configPath: str,
            repoHasLocalIdentity: bool,
            parent: QWidget
    ):
        super().__init__(parent)

        ui = Ui_IdentityDialog()
        ui.setupUi(self)
        self.ui = ui

        formatWidgetText(ui.configPathLabel, lquo(compactPath(configPath)))
        ui.warningLabel.setVisible(repoHasLocalIdentity)

        # Initialize with global identity values (if any)
        ui.nameEdit.setText(initialName)
        ui.emailEdit.setText(initialEmail)

        validator = ValidatorMultiplexer(self)
        validator.setGatedWidgets(ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok))
        validator.connectInput(ui.nameEdit, SignatureForm.validateInput)
        validator.connectInput(ui.emailEdit, SignatureForm.validateInput)
        validator.run(silenceEmptyWarnings=True)

        subtitle = _("This information will be embedded in the commits and tags that you create on this machine.")
        if firstRun:
            subtitle = _("Before editing this repository, please set up your identity for Git.") + " " + subtitle

        convertToBrandedDialog(self, subtitleText=subtitle, multilineSubtitle=True)
        packDialog(self, lockHeight=True)

    def identity(self) -> tuple[str, str]:
        name = self.ui.nameEdit.text()
        email = self.ui.emailEdit.text()
        return name, email
