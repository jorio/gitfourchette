# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.ui_pushdialog import Ui_PushDialog
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import RepoModel
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)


class PushDialog(QDialog):
    abortRequested = Signal()

    def onPickLocalBranch(self):
        localBranch = self.currentLocalBranch

        if localBranch.upstream:
            self.ui.trackingLabel.setText(_("tracking {0}", lquo(localBranch.upstream.shorthand)))
        else:
            self.ui.trackingLabel.setText(_("non-tracking"))

        remoteIndex = self.getUpstreamIndex(localBranch.upstream.shorthand if localBranch.upstream else "")
        self.ui.remoteBranchEdit.setCurrentIndex(remoteIndex)
        self.onPickRemoteBranch(remoteIndex)
        self.updateTrackCheckBox()

        self.remoteBranchNameValidator.run()

    def onPickRemoteBranch(self, index: int):
        remoteName = self.currentRemoteName
        remoteTooltip = self.ui.remoteBranchEdit.itemData(index, Qt.ItemDataRole.ToolTipRole)

        if self.willPushToNewBranch:
            reservedNames = self.reservedRemoteBranchNames[remoteName]
            remoteBranchName = withUniqueSuffix(self.currentLocalBranchName, reservedNames)
            self.ui.remoteNameLabel.setText(f"\u21AA {remoteName}/")
            self.ui.remoteNameLabel.setToolTip(remoteTooltip)
            self.ui.newRemoteBranchStackedWidget.setCurrentIndex(0)
            self.ui.newRemoteBranchNameEdit.setText(remoteBranchName)
            self.ui.newRemoteBranchNameEdit.setFocus(Qt.FocusReason.TabFocusReason)
        else:
            self.ui.newRemoteBranchStackedWidget.setCurrentIndex(1)
            self.ui.remoteBranchEdit.setFocus(Qt.FocusReason.TabFocusReason)

        self.ui.remoteBranchEdit.setToolTip(remoteTooltip)
        self.updateTrackCheckBox()

        self.remoteBranchNameValidator.run()

    def updateTrackCheckBox(self, resetCheckedState=True):
        localBranch = self.currentLocalBranch
        lbName = localBranch.shorthand
        rbName = self.currentRemoteBranchFullName
        lbUpstream = localBranch.upstream.shorthand if localBranch.upstream else "???"

        lbName = hquoe(lbName)
        rbName = hquoe(rbName)
        lbUpstream = hquoe(lbUpstream)

        hasUpstream = bool(localBranch.upstream)
        isTrackingHomeBranch = hasUpstream and localBranch.upstream.shorthand == self.currentRemoteBranchFullName

        if not resetCheckedState:
            willTrack = self.ui.trackCheckBox.isChecked()
        else:
            willTrack = self.willPushToNewBranch or isTrackingHomeBranch

        if not hasUpstream and willTrack:
            text = _("{0} will track {1}.", lbName, rbName)
        elif not hasUpstream and not willTrack:
            text = _("{0} currently does not track any remote branch.", lbName)
        elif isTrackingHomeBranch:
            text = _("{0} already tracks remote branch {1}.", lbName, lbUpstream)
        elif willTrack:
            text = _("{0} will track {1} instead of {2}.", lbName, rbName, lbUpstream)
        else:
            text = _("{0} currently tracks {1}.", lbName, lbUpstream)

        self.ui.trackingLabel.setWordWrap(True)
        self.ui.trackingLabel.setText("<small>" + text + "</small>")
        self.ui.trackingLabel.setContentsMargins(20, 0, 0, 0)
        self.ui.trackingLabel.setEnabled(not isTrackingHomeBranch)
        self.ui.trackCheckBox.setEnabled(not isTrackingHomeBranch)
        self.setOkButtonText()

        if resetCheckedState:
            with QSignalBlockerContext(self.ui.trackCheckBox):
                self.ui.trackCheckBox.setChecked(willTrack)

    @property
    def repo(self) -> Repo:
        return self.repoModel.repo

    @property
    def currentLocalBranchName(self) -> str:
        return self.ui.localBranchEdit.currentData()

    @property
    def currentLocalBranch(self) -> Branch:
        return self.repo.branches.local[self.currentLocalBranchName]

    @property
    def willForcePush(self) -> bool:
        return not self.willPushToNewBranch and self.ui.forcePushCheckBox.isChecked()

    @property
    def willPushToNewBranch(self) -> bool:
        data = self.ui.remoteBranchEdit.currentData()
        assert isinstance(data, str)
        return data.endswith("/")

    @property
    def currentRemoteName(self):
        data = self.ui.remoteBranchEdit.currentData()
        assert isinstance(data, str)
        remoteName, _branchName = split_remote_branch_shorthand(data)
        return remoteName

    @property
    def currentRemoteBranchName(self) -> str:
        if self.willPushToNewBranch:
            return self.ui.newRemoteBranchNameEdit.text()
        else:
            data = self.ui.remoteBranchEdit.currentData()
            assert isinstance(data, str)
            _remoteName, branchName = split_remote_branch_shorthand(data)
            return branchName

    @property
    def currentRemoteBranchFullName(self) -> str:
        return self.currentRemoteName + "/" + self.currentRemoteBranchName

    def refspec(self, withForcePrefix=True):
        prefix = "+" if withForcePrefix and self.willForcePush else ""
        lbn = self.currentLocalBranchName
        rbn = self.currentRemoteBranchName
        return f"{prefix}refs/heads/{lbn}:refs/heads/{rbn}"

    def getUpstreamIndex(self, upstream: str):
        comboBox = self.ui.remoteBranchEdit

        # Find the upstream as-is
        index = comboBox.findData(upstream)
        if index >= 0:
            return index

        # Fall back to "New branch" item for last used remote in this repo
        fallbackRemote = self.repoModel.prefs.getShadowUpstream(self.currentLocalBranchName)
        index = comboBox.findData(fallbackRemote)
        if index >= 0:
            return index

        # Just find the first "New branch" item
        for index in range(comboBox.count()):
            data = comboBox.itemData(index)
            if data.endswith("/"):
                return index

        return -1

    def fillRemoteComboBox(self):
        comboBox = self.ui.remoteBranchEdit
        currentLocalBranch = self.currentLocalBranch
        currentUpstream = currentLocalBranch.upstream.shorthand if currentLocalBranch.upstream else ""

        branchIcon = stockIcon("vcs-branch")
        newBranchIcon = stockIcon("SP_FileDialogNewFolder")
        boldFont = QFont(comboBox.font())
        boldFont.setBold(True)

        with QSignalBlockerContext(comboBox):
            comboBox.clear()

            for remoteName, branchNames in self.repo.listall_remote_branches(value_style="shorthand").items():
                if comboBox.count() != 0:
                    comboBox.insertSeparator(comboBox.count())

                remoteUrl = self.repo.remotes[remoteName].url
                for shorthand in branchNames:
                    isTracked = shorthand == currentUpstream
                    caption = shorthand
                    if isTracked:
                        caption += " " + _("[tracked]")
                    index = comboBox.count()
                    comboBox.addItem(branchIcon, caption, shorthand)
                    comboBox.setItemData(index, boldFont if isTracked else None, Qt.ItemDataRole.FontRole)
                    comboBox.setItemData(index, remoteUrl, Qt.ItemDataRole.ToolTipRole)

                newBranchPayload = remoteName + "/"
                newBranchCaption = _("New remote branch on {0}", lquo(remoteName))
                comboBox.addItem(newBranchIcon, newBranchCaption, newBranchPayload)
                comboBox.setItemData(comboBox.count()-1, remoteUrl, Qt.ItemDataRole.ToolTipRole)

    def __init__(self, repoModel: RepoModel, branch: Branch, parent: QWidget):
        super().__init__(parent)
        repo = repoModel.repo
        self.repoModel = repoModel
        self.reservedRemoteBranchNames = repo.listall_remote_branches()
        self.widgetsWereEnabled = []

        self.ui = Ui_PushDialog()
        self.ui.setupUi(self)
        self.ui.trackingLabel.setMinimumHeight(self.ui.trackingLabel.height())
        self.ui.trackingLabel.setMaximumHeight(self.ui.trackingLabel.height())

        self.startOperationButton: QPushButton = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        self.startOperationButton.setText(_("&Push"))
        self.startOperationButton.setIcon(stockIcon("git-push"))

        lbComboBox = self.ui.localBranchEdit
        for lbName in sorted(repo.branches.local, key=naturalSort):
            lbComboBox.addItem(lbName, lbName)
        lbComboBox.setCurrentIndex(lbComboBox.findData(branch.shorthand))

        self.ui.localBranchEdit.activated.connect(self.fillRemoteComboBox)
        self.ui.localBranchEdit.activated.connect(self.onPickLocalBranch)
        self.ui.remoteBranchEdit.activated.connect(self.onPickRemoteBranch)
        self.ui.newRemoteBranchNameEdit.textEdited.connect(lambda text: self.updateTrackCheckBox(False))
        self.ui.trackCheckBox.toggled.connect(lambda: self.updateTrackCheckBox(False))

        self.remoteBranchNameValidator = ValidatorMultiplexer(self)
        self.remoteBranchNameValidator.setGatedWidgets(self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok))
        self.remoteBranchNameValidator.connectInput(self.ui.newRemoteBranchNameEdit, self.validateCustomRemoteBranchName)
        # don't prime the validator!

        # Set up comboboxes (act as if we picked the current branch in localBranchEdit)
        self.fillRemoteComboBox()
        self.onPickLocalBranch()

        self.ui.forcePushCheckBox.clicked.connect(self.setOkButtonText)

        self.ui.forcePushCheckBox.setText(self.ui.forcePushCheckBox.text() + " " + _("(with lease)"))

        self.setOkButtonText()

        convertToBrandedDialog(self)

        self.setWindowModality(Qt.WindowModality.WindowModal)

    def okButton(self) -> QPushButton:
        return self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)

    def cancelButton(self) -> QPushButton:
        return self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Cancel)

    def setOkButtonText(self):
        icon = "git-push"
        tip = ""

        if self.willForcePush:
            text = _("Force &push")
            icon = "achtung"
            tip = _("Force push: Destructive action!")
        elif self.willPushToNewBranch:
            text = _("&Push new branch")
        else:
            text = _("&Push")

        okButton = self.okButton()
        okButton.setText(text)
        okButton.setIcon(stockIcon(icon))
        okButton.setToolTip(tip)

    def validateCustomRemoteBranchName(self, name: str):
        if not self.ui.newRemoteBranchNameEdit.isVisibleTo(self):
            return ""

        reservedNames = self.reservedRemoteBranchNames.get(self.currentRemoteName, [])

        return nameValidationMessage(name, reservedNames,
                                     _("This name is already taken by another branch on this remote."))

    def isBusy(self) -> bool:
        return len(self.widgetsWereEnabled) > 0

    def setBusy(self, busy: bool):
        widgets = [self.ui.remoteBranchEdit,
                   self.ui.localBranchEdit,
                   self.ui.newRemoteBranchNameEdit,
                   self.ui.forcePushCheckBox,
                   self.ui.trackCheckBox,
                   self.startOperationButton]

        if busy:
            # Remember which widgets were disabled already
            self.widgetsWereEnabled = [w.isEnabled() for w in widgets]
            for w in widgets:
                w.setEnabled(False)
        else:
            for w, enableW in zip(widgets, self.widgetsWereEnabled, strict=True):
                w.setEnabled(enableW)
            self.widgetsWereEnabled.clear()

    def reject(self):
        if self.isBusy():
            self.ui.statusForm.setProgressMessage(_("Canceling…"))
            self.ui.statusForm.setProgressValue(0, 0)
            self.abortRequested.emit()
        else:
            super().reject()

    def saveShadowUpstream(self):
        branch = self.currentLocalBranch
        if branch.upstream:
            self.repoModel.prefs.setShadowUpstream(branch.branch_name, "")
        else:
            self.repoModel.prefs.setShadowUpstream(branch.branch_name, self.currentRemoteBranchFullName)
