# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.ui_checkoutcommitdialog import Ui_CheckoutCommitDialog
from gitfourchette.localization import *
from gitfourchette.porcelain import Oid
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class CheckoutCommitDialog(QDialog):
    def __init__(
            self,
            oid: Oid,
            refs: list[str],
            anySubmodules: bool,
            parent=None):

        super().__init__(parent)

        ui = Ui_CheckoutCommitDialog()
        self.ui = ui
        self.ui.setupUi(self)

        self.setWindowTitle(_("Check out commit {0}", shortHash(oid)))

        ok = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        ui.detachedHeadRadioButton.clicked.connect(lambda: ok.setText(_("Detach HEAD")))
        ui.detachedHeadRadioButton.clicked.connect(lambda: ok.setIcon(stockIcon("git-head-detached")))
        ui.switchToLocalBranchRadioButton.clicked.connect(lambda: ok.setText(_("Switch Branch")))
        ui.switchToLocalBranchRadioButton.clicked.connect(lambda: ok.setIcon(stockIcon("git-branch")))
        ui.createBranchRadioButton.clicked.connect(lambda: ok.setText(_("Create Branch…")))
        ui.createBranchRadioButton.clicked.connect(lambda: ok.setIcon(stockIcon("vcs-branch-new")))
        if refs:
            ui.switchToLocalBranchComboBox.addItems(refs)
            ui.switchToLocalBranchRadioButton.click()
        else:
            ui.detachedHeadRadioButton.click()
            ui.switchToLocalBranchComboBox.setVisible(False)
            ui.switchToLocalBranchRadioButton.setVisible(False)

        if not anySubmodules:
            ui.recurseSubmodulesSpacer.setVisible(False)
            ui.recurseSubmodulesGroupBox.setVisible(False)

        ui.createBranchRadioButton.toggled.connect(lambda t: ui.recurseSubmodulesGroupBox.setEnabled(not t))

