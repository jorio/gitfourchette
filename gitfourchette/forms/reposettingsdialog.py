# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.signatureform import SignatureForm
from gitfourchette.forms.ui_reposettingsdialog import Ui_RepoSettingsDialog
from gitfourchette.localization import *
from gitfourchette.porcelain import Repo, GitConfigHelper
from gitfourchette.qt import *
from gitfourchette.toolbox import *


def validateSigPart(x: str):
    if x == "":
        return ""
    return SignatureForm.validateInput(x)


class RepoSettingsDialog(QDialog):
    def __init__(self, repo: Repo, parent):
        super().__init__(parent)
        ui = Ui_RepoSettingsDialog()
        ui.setupUi(self)
        self.ui = ui

        self.setWindowTitle(self.windowTitle().format(repo=tquoe(settings.history.getRepoNickname(repo.workdir))))

        currentNickname = settings.history.getRepoNickname(repo.workdir, strict=True)
        ui.nicknameEdit.setText(currentNickname)
        ui.nicknameEdit.setToolTip("<p>" + ui.nicknameEdit.toolTip().format(app=qAppName()))
        ui.nicknameLabel.setToolTip(ui.nicknameEdit.toolTip())

        localName, localEmail = repo.get_local_identity()
        useLocalIdentity = bool(localName or localEmail)

        globalName, globalEmail, globalIdentityLevel = GitConfigHelper.global_identity()
        for text, edit in [(globalName, ui.nameEdit), (globalEmail, ui.emailEdit)]:
            if text:
                text += " <" + _p("RepoSettingsDialog", "from global config") + ">"
            else:
                text = "<" + _p("RepoSettingsDialog", "global git identity not configured") + ">"
            edit.setPlaceholderText(text)

        self.localNameBackup = localName
        self.localEmailBackup = localEmail

        validator = ValidatorMultiplexer(self)
        validator.setGatedWidgets(ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok))
        validator.connectInput(ui.nameEdit, validateSigPart)
        validator.connectInput(ui.emailEdit, validateSigPart)
        self.validator = validator

        ui.localIdentityCheckBox.checkStateChanged.connect(self.onLocalIdentityCheckStateChanged)
        ui.localIdentityCheckBox.setChecked(not useLocalIdentity)  # hack to trigger enablement
        ui.localIdentityCheckBox.setChecked(useLocalIdentity)

        validator.run()

        convertToBrandedDialog(self, subtitleText=compactPath(repo.workdir))

    def onLocalIdentityCheckStateChanged(self, state: Qt.CheckState):
        if state == Qt.CheckState.Checked:
            self.ui.nameEdit.setText(self.localNameBackup)
            self.ui.emailEdit.setText(self.localEmailBackup)
        else:
            self.localNameBackup = self.ui.nameEdit.text()
            self.localEmailBackup = self.ui.emailEdit.text()
            self.ui.nameEdit.clear()
            self.ui.emailEdit.clear()
        self.validator.run()

    def localIdentity(self) -> tuple[str, str]:
        useLocalIdentity = self.ui.localIdentityCheckBox.isChecked()
        if useLocalIdentity:
            localName = self.ui.nameEdit.text()
            localEmail = self.ui.emailEdit.text()
        else:
            localName = ""
            localEmail = ""
        return localName, localEmail
