# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.ui_newbranchdialog import Ui_NewBranchDialog
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class NewBranchDialog(QDialog):
    def __init__(
            self,
            initialName: str,
            target: str,
            targetSubtitle: str,
            upstreams: list[str],
            reservedNames: list[str],
            allowSwitching: bool,
            parent=None):

        super().__init__(parent)

        self.ui = Ui_NewBranchDialog()
        self.ui.setupUi(self)

        self.ui.nameEdit.setText(initialName)
        self.acceptButton.setText(_("&Create"))

        self.ui.upstreamComboBox.addItems(upstreams)

        # hack to trickle down initial 'toggled' signal to combobox
        self.ui.upstreamCheckBox.setChecked(True)
        self.ui.upstreamCheckBox.setChecked(False)

        if not upstreams:
            self.ui.upstreamCheckBox.setChecked(False)
            self.ui.upstreamCheckBox.setVisible(False)
            self.ui.upstreamComboBox.setVisible(False)

        if not allowSwitching:
            switchCheckBox = self.ui.switchToBranchCheckBox
            switchCheckBox.setEnabled(False)
            switchCheckBox.setChecked(False)
            switchCheckBox.setText(switchCheckBox.text() + "\n" + _("(blocked by conflicts)"))
            self.ui.recurseSubmodulesCheckBox.setChecked(False)

        nameTaken = _("This name is already taken by another local branch.")
        validator = ValidatorMultiplexer(self)
        validator.setGatedWidgets(self.acceptButton)
        validator.connectInput(self.ui.nameEdit, lambda name: nameValidationMessage(name, reservedNames, nameTaken))
        validator.run()

        convertToBrandedDialog(self, _("New branch"),
                               _("Commit at tip:") + " " + target + "\n" + tquo(targetSubtitle))

        self.ui.nameEdit.setFocus()
        self.ui.nameEdit.selectAll()
        self.preSelectLeaf(self.ui.nameEdit)

    @property
    def acceptButton(self):
        return self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)

    @staticmethod
    def preSelectLeaf(nameEdit: QLineEdit):
        """
        Pre-select leaf name (e.g. in "folder/leaf" select only "leaf")
        """
        text = nameEdit.text()
        try:
            afterSlash = text.rindex("/") + 1
            nameEdit.setSelection(afterSlash, len(text) - afterSlash)
        except ValueError:
            pass
