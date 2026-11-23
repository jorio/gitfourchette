# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import re
from pathlib import Path

from gitfourchette.forms.ui_registersubmoduledialog import Ui_RegisterSubmoduleDialog
from gitfourchette.localization import *
from gitfourchette.porcelain import submodule_gitdir_conflict
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class RegisterSubmoduleDialog(QDialog):
    def __init__(
            self,
            workdirPath: str,
            superprojectName: str,
            remotes: dict[str, str],
            absorb: bool,
            reservedNames: set[str],
            modulesDir: str,
            parent):
        super().__init__(parent)
        ui = Ui_RegisterSubmoduleDialog()
        ui.setupUi(self)
        self.ui = ui
        self.reservedNames = reservedNames
        self.modulesDir = modulesDir

        for k, v in remotes.items():
            ui.remoteComboBox.addItemWithPreview(k, v, v)

        ui.pathValue.setText(workdirPath)
        ui.nameEdit.setText(workdirPath)
        ui.nameEdit.addAction(stockIcon("git-submodule"), QLineEdit.ActionPosition.LeadingPosition)
        self.resetNameAction = ui.nameEdit.addAction(stockIcon("SP_LineEditClearButton"), QLineEdit.ActionPosition.TrailingPosition)
        self.resetNameAction.setVisible(False)
        self.resetNameAction.setToolTip(_("Reset to default name"))
        self.resetNameAction.triggered.connect(lambda: ui.nameEdit.setText(workdirPath))
        ui.nameEdit.textChanged.connect(lambda name: self.resetNameAction.setVisible(name != workdirPath))

        if absorb:
            formatWidgetText(ui.absorbExplainer, sub=lquoe(workdirPath), super=lquoe(superprojectName))
            self.okButton.setText(_("Absorb submodule"))
            self.setWindowTitle(_("Absorb submodule"))
        else:
            ui.absorbExplainer.hide()
            self.okButton.setText(_("Register submodule"))
            self.setWindowTitle(_("Register submodule"))

        validator = ValidatorMultiplexer(self)
        validator.setGatedWidgets(self.okButton)
        validator.connectInput(self.ui.nameEdit, self.validateSubmoduleName)
        validator.run()

    @property
    def remoteUrl(self) -> str:
        return self.ui.remoteComboBox.currentData(Qt.ItemDataRole.UserRole)

    @property
    def customName(self):
        return self.ui.nameEdit.text()

    @property
    def okButton(self):
        return self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)

    def validateSubmoduleName(self, name: str):
        if not name.strip():
            return _("Cannot be empty.")
        elif name in self.reservedNames:
            return _("This name is already taken by another submodule.")
        elif ".." in re.split(r"[/\\]", name):  # Like Git's check_submodule_name
            return _("Git doesn’t accept {0} in a submodule name.", hquo(".."))

        conflict = submodule_gitdir_conflict(self.modulesDir, name)
        if not conflict:
            return ""
        elif Path(conflict) == Path(f"{self.modulesDir}/{name}"):  # The directory itself, not a parent
            return _("Git already has a directory for this name, for example left over from a removed submodule.")
        else:
            return _("Git would put its repository inside another submodule’s.")
