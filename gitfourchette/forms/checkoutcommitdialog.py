# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.ui_checkoutcommitdialog import Ui_CheckoutCommitDialog
from gitfourchette.localization import *
from gitfourchette.porcelain import Oid, RefPrefix
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

        localBranches = [r.removeprefix(RefPrefix.HEADS) for r in refs if r.startswith(RefPrefix.HEADS)]
        currentBranchIsHere = currentBranch in localBranches
        currentBranchIsOnlyLocalBranch = currentBranchIsHere and len(localBranches) == 1
        currentBranchIsOnlyRef = currentBranchIsHere and len(refs) == 1
        isDetachedHead = currentBranch == "HEAD"

        ui = Ui_CheckoutCommitDialog()
        self.ui = ui
        self.ui.setupUi(self)

        self.setWindowTitle(_("Check out commit {0}", shortHash(oid)))

        if isDetachedHead:
            ui.detachHeadRadioButton.setText(_("Move &detached HEAD here"))
        else:
            ui.resetHeadRadioButton.setText(_("&Reset the tip of branch {0} here…", lquo(currentBranch)))
            ui.mergeRadioButton.setText(_("&Merge into {0}…", lquo(currentBranch)))

        self.bindRadioToOkCaption(ui.detachHeadRadioButton, _("Detach HEAD"), "git-head-detached")
        self.bindRadioToOkCaption(ui.switchRadioButton, _("Switch Branch"), "git-checkout")
        self.bindRadioToOkCaption(ui.resetHeadRadioButton, _("Reset {0}…", "HEAD" if isDetachedHead else lquoe(currentBranch)), "")
        self.bindRadioToOkCaption(ui.mergeRadioButton, _("Merge…"), "git-merge")
        self.bindRadioToOkCaption(ui.createBranchRadioButton, _("Create Branch…"), "git-branch")

        # Determine if we can merge
        ui.mergeRadioButton.setEnabled(bool(refs) and not currentBranchIsOnlyRef)

        # Determine if we can switch to a local branch
        switchSuffix = ""
        if localBranches and not currentBranchIsOnlyLocalBranch:
            ui.switchRadioButton.click()

            branchChoices = [r for r in localBranches if r != currentBranch]
            ui.switchComboBox.addItems(branchChoices)

            # Single branch - remove combobox
            if len(branchChoices) == 1:
                switchSuffix = lquo(branchChoices[0])
        else:
            ui.detachHeadRadioButton.click()
            ui.switchRadioButton.setEnabled(False)

            if currentBranchIsOnlyLocalBranch:
                switchSuffix = _p("checkout: current branch name", "{0} (already checked out)", lquo(currentBranch))
            else:
                switchSuffix = _p("checkout: no branches available", "(none available here)")

        # If there's a suffix text for the switch radio button, hide the combobox
        if switchSuffix:
            ui.switchRadioButton.setText(ui.switchRadioButton.text() + " " + switchSuffix)
            ui.switchComboBox.setVisible(False)

        if not anySubmodules:
            ui.recurseSubmodulesSpacer.setVisible(False)
            ui.recurseSubmodulesGroupBox.setVisible(False)

        for noRecurseRadio in [ui.createBranchRadioButton, ui.resetHeadRadioButton, ui.mergeRadioButton]:
            noRecurseRadio.toggled.connect(lambda t: ui.recurseSubmodulesGroupBox.setEnabled(not t))

    def bindRadioToOkCaption(self, radio: QRadioButton, okCaption: str, okIcon: str):
        def callback():
            ok = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
            ok.setText(okCaption)
            ok.setIcon(stockIcon(okIcon) if okIcon else QIcon())
        radio.clicked.connect(callback)
