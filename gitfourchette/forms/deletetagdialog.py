# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.newtagdialog import populateRemoteComboBox
from gitfourchette.forms.ui_deletetagdialog import Ui_DeleteTagDialog
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class DeleteTagDialog(QDialog):
    def __init__(
            self,
            tagName: str,
            target: str,
            targetSubtitle: str,
            remotes: list[str],
            parent=None):

        super().__init__(parent)

        self.ui = Ui_DeleteTagDialog()
        self.ui.setupUi(self)

        formatWidgetText(self.ui.label, bquo(tagName))

        okButton = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        okButton.setIcon(stockIcon("SP_DialogDiscardButton"))
        okCaptions = [_("&Delete Locally"), _("&Delete Locally && Remotely")]
        self.ui.pushCheckBox.toggled.connect(lambda push: okButton.setText(okCaptions[push]))

        populateRemoteComboBox(self.ui.remoteComboBox, remotes)

        # Prime enabled state
        self.ui.pushCheckBox.click()
        self.ui.pushCheckBox.click()
        if not remotes:
            self.ui.pushCheckBox.setChecked(False)
            self.ui.pushCheckBox.setEnabled(False)

        convertToBrandedDialog(
            self,
            _("Delete tag {0}", tquo(tagName)),
            _("Tagged commit: {0}", target) + " – " + tquo(targetSubtitle))

        self.resize(max(512, self.width()), self.height())
