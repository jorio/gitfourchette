# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.ui_newtagdialog import Ui_NewTagDialog
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


def populateRemoteComboBox(comboBox: QComboBox, remotes: list[str]):
    assert 0 == comboBox.count()
    if not remotes:
        comboBox.addItem(_("No Remotes"))
    else:
        comboBox.addItem(_("All Remotes"), userData="*")
        comboBox.insertSeparator(1)
        for remote in remotes:
            comboBox.addItem(remote, userData=remote)


class NewTagDialog(QDialog):
    def __init__(
            self,
            target: str,
            targetSubtitle: str,
            reservedNames: list[str],
            remotes: list[str],
            parent=None):

        super().__init__(parent)

        self.ui = Ui_NewTagDialog()
        self.ui.setupUi(self)

        self.reservedNames = reservedNames

        okButton = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        okButton.setIcon(stockIcon("git-tag"))
        okCaptions = [_("&Create"), _("&Create && Push")]
        self.ui.pushCheckBox.toggled.connect(lambda push: okButton.setText(okCaptions[push]))

        populateRemoteComboBox(self.ui.remoteComboBox, remotes)

        # Enable/disable OK button depending on input
        validator = ValidatorMultiplexer(self)
        validator.setGatedWidgets(okButton)
        validator.connectInput(self.ui.nameEdit, self.validateOK)
        validator.run(silenceEmptyWarnings=True)

        # Enable/disable 'Replace' checkbox depending on input
        validatorForce = ValidatorMultiplexer(self)
        validatorForce.setGatedWidgets(self.ui.forceCheckBox)
        validatorForce.connectInput(self.ui.nameEdit, self.validateForce, showError=False)
        validatorForce.run(silenceEmptyWarnings=True)

        self.ui.forceCheckBox.toggled.connect(validator.run)

        # Prime enabled state
        self.ui.pushCheckBox.click()
        self.ui.pushCheckBox.click()
        if not remotes:
            self.ui.pushCheckBox.setChecked(False)
            self.ui.pushCheckBox.setEnabled(False)

        convertToBrandedDialog(
            self,
            _("New tag on commit {0}", tquo(target)),
            tquo(targetSubtitle))

        self.resize(max(512, self.width()), self.height())

    def validateOK(self, name: str) -> str:
        nameTaken = _("This name is already taken by another tag.")

        reservedNames = self.reservedNames
        if self.ui.forceCheckBox.isEnabled() and self.ui.forceCheckBox.isChecked():
            reservedNames = []

        return nameValidationMessage(name, reservedNames, nameTaken)

    def validateForce(self, name: str) -> str:
        # The 'replace' checkbox will be DISABLED if the validation string
        # evaluates to False (as a bool)
        taken = name.lower() in (n.lower() for n in self.reservedNames)
        return "" if taken else "DISABLE_FORCE_CHECKBOX"
