# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
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
            currentBranch: str,
            anySubmodules: bool,
            parent=None):

        super().__init__(parent)

        ui = Ui_CheckoutCommitDialog()
        self.ui = ui
        self.ui.setupUi(self)

        self.setWindowTitle(_("Check out commit {0}", shortHash(oid)))

        isDetachedHead = currentBranch == "HEAD"
        if isDetachedHead:
            ui.detachHeadRadioButton.setText(_("Move &detached HEAD here"))
        else:
            ui.resetHeadRadioButton.setText(_("&Reset the tip of branch {0} here…", lquo(currentBranch)))

        self.bindRadioToOkCaption(ui.detachHeadRadioButton, _("Detach HEAD"), "git-head-detached")
        self.bindRadioToOkCaption(ui.switchToLocalBranchRadioButton, _("Switch Branch"), "git-checkout")
        self.bindRadioToOkCaption(ui.resetHeadRadioButton, _("Reset {0}…", "HEAD" if isDetachedHead else lquoe(currentBranch)), "")
        self.bindRadioToOkCaption(ui.createBranchRadioButton, _("Create Branch…"), "git-branch")

        if refs:
            ui.switchToLocalBranchComboBox.addItems(refs)
            ui.switchToLocalBranchRadioButton.click()
        else:
            ui.detachHeadRadioButton.click()
            ui.switchToLocalBranchComboBox.setVisible(False)
            ui.switchToLocalBranchRadioButton.setVisible(False)

        if not anySubmodules:
            ui.recurseSubmodulesSpacer.setVisible(False)
            ui.recurseSubmodulesGroupBox.setVisible(False)

        for noRecurseRadio in [ui.createBranchRadioButton, ui.resetHeadRadioButton]:
            noRecurseRadio.toggled.connect(lambda t: ui.recurseSubmodulesGroupBox.setEnabled(not t))

    def bindRadioToOkCaption(self, radio: QRadioButton, okCaption: str, okIcon: str):
        def callback():
            ok = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
            ok.setText(okCaption)
            ok.setIcon(stockIcon(okIcon) if okIcon else QIcon())
        radio.clicked.connect(callback)
