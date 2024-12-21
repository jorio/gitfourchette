# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.ui_remotedialog import Ui_RemoteDialog
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class RemoteDialog(QDialog):
    def __init__(self, editExistingRemote: bool, name: str, url: str, customKeyFile: str,
                 existingRemotes: list[str], parent: QWidget):

        super().__init__(parent)

        self.ui = Ui_RemoteDialog()
        self.ui.setupUi(self)
        okButton = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)

        self.ui.urlEdit.setText(url)
        self.ui.nameEdit.setText(name)
        self.existingRemotes = existingRemotes

        # Set up key file picker
        self.ui.keyFilePicker.makeFixedHeight()
        self.ui.keyFilePicker.setPath(customKeyFile)
        self.ui.keyFilePicker.checkBox.setChecked(bool(customKeyFile))

        # Set up input validator
        nameTaken = _p("NameValidationError", "This name is already taken by another remote.")
        cannotBeEmpty = _p("NameValidationError", "Cannot be empty.")
        validator = ValidatorMultiplexer(self)
        validator.setGatedWidgets(okButton)
        validator.connectInput(self.ui.nameEdit, lambda s: nameValidationMessage(s, existingRemotes, nameTaken))
        validator.connectInput(self.ui.urlEdit, lambda s: cannotBeEmpty if not s.strip() else "")

        # Different behavior if editing existing remote or creating a new one
        if editExistingRemote:
            # Edit existing remote
            title = _("Edit remote {0}", hquoe(name))
            self.setWindowTitle(_("Edit remote"))
            okButton.setText(_("Save"))
            self.ui.fetchAfterAddCheckBox.setVisible(False)
            # Don't touch name automatically on existing remotes
            self.allowAutoFillName = False
        else:
            # Create new remote
            title = _("Add remote")
            self.setWindowTitle(_("Add remote"))
            okButton.setText(_("Add"))
            self.ui.fetchAfterAddCheckBox.setVisible(True)
            # Autofill name on new remotes
            self.allowAutoFillName = True
            self.ui.urlEdit.textChanged.connect(self.onUrlChangedAutoFillName)
            self.ui.nameEdit.textChanged.connect(self.onNameChanged)
            # Automatically paste URL in clipboard
            if not url:
                url = guessRemoteUrlFromText(QApplication.clipboard().text())
                self.ui.urlEdit.setText(url)
                self.ui.urlEdit.setFocus()

        # Connect protocol button to URL editor
        self.ui.protocolButton.connectTo(self.ui.urlEdit)

        convertToBrandedDialog(self, title)
        self.resize(max(self.width(), 600), self.height())

        # Run input callback
        validator.run(silenceEmptyWarnings=True)

    @property
    def privateKeyFilePath(self):
        return self.ui.keyFilePicker.privateKeyPath()

    def onNameChanged(self, name: str):
        # Allow autofilling name again if user has erased it
        self.allowAutoFillName = name == ""

    def onUrlChangedAutoFillName(self, url: str):
        if not self.allowAutoFillName:
            return

        url = url.strip()
        host, path = splitRemoteUrl(url)

        # Sanitize host
        for c in " ?/\\*~<>|:":
            host = host.replace(c, "_")

        # Clean up common host names (git.(...).org)
        host = host.removeprefix("www.")
        host = host.removeprefix("git.")
        for tld in (".com", ".org", ".net"):
            if host.endswith(tld):
                host = host.removesuffix(tld)
                break

        host = withUniqueSuffix(host, self.existingRemotes)
        self.ui.nameEdit.setText(host)
        self.allowAutoFillName = True  # re-enable this since we got this far
