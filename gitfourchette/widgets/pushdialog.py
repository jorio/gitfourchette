from gitfourchette import log
from gitfourchette import porcelain
from gitfourchette.qt import *
from gitfourchette.remotelink import RemoteLink
from gitfourchette.util import QSignalBlockerContext
from gitfourchette.util import addComboBoxItem, stockIcon
from gitfourchette.widgets.brandeddialog import convertToBrandedDialog
from gitfourchette.widgets.ui_pushdialog import Ui_PushDialog
from gitfourchette.workqueue import WorkQueue
from html import escape
import enum
import pygit2


class ERemoteItem(enum.Enum):
    ExistingRef = enum.auto()
    NewRef = enum.auto()


def generateUniqueBranchNameOnRemote(repo: pygit2.Repository, remoteName: str, seedBranchName: str):
    """ Generate a name that doesn't clash with any existing branches on the remote """

    i = 1
    newBranchName = seedBranchName
    allRemoteBranches = list(repo.branches.remote)

    while F"{remoteName}/{newBranchName}" in allRemoteBranches:
        i += 1
        newBranchName = F"{seedBranchName}-{i}"

    return newBranchName


class PushDialog(QDialog):
    pushSuccessful = Signal()

    def onPickLocalBranch(self, index: int):
        localBranch = self.currentLocalBranch

        if localBranch.upstream:
            self.ui.trackingLabel.setText(F"tracking “{localBranch.upstream.shorthand}”")
        else:
            self.ui.trackingLabel.setText(F"non-tracking")

        if self.trackedBranchIndex >= 0:
            self.ui.remoteBranchEdit.setCurrentIndex(self.trackedBranchIndex)
        else:
            self.ui.remoteBranchEdit.setCurrentIndex(self.fallbackAutoNewIndex)

    def onPickRemoteBranch(self, index: int):
        localBranch = self.currentLocalBranch

        remoteItem, remoteData = self.ui.remoteBranchEdit.currentData()

        if remoteItem != ERemoteItem.ExistingRef:
            newRBN = generateUniqueBranchNameOnRemote(self.repo, remoteData, localBranch.branch_name)
            self.ui.remoteBranchOptionsStack.setCurrentWidget(self.ui.customRemoteBranchNamePage)
            self.ui.customRemoteBranchNameEdit.setText(newRBN)
            self.ui.customRemoteBranchNameEdit.setFocus(Qt.TabFocusReason)
        else:
            self.ui.remoteBranchOptionsStack.setCurrentWidget(self.ui.forcePushPage)

    @property
    def currentLocalBranchName(self) -> str:
        return self.ui.localBranchEdit.currentData()

    @property
    def currentLocalBranch(self) -> pygit2.Branch:
        return self.repo.branches.local[self.currentLocalBranchName]

    @property
    def forcePush(self) -> bool:
        remoteItem, _ = self.ui.remoteBranchEdit.currentData()
        return remoteItem == ERemoteItem.ExistingRef and self.ui.forcePushCheckBox.isChecked()

    @property
    def currentRemoteName(self):
        remoteItem, remoteData = self.ui.remoteBranchEdit.currentData()

        if remoteItem == ERemoteItem.ExistingRef:
            rbr: pygit2.Branch = remoteData
            return rbr.remote_name
        elif remoteItem == ERemoteItem.NewRef:
            return remoteData
        else:
            raise NotImplementedError()

    @property
    def currentRemoteBranchName(self) -> str:
        data = self.ui.remoteBranchEdit.currentData()
        if data is None:
            return ""
        remoteItem, remoteData = self.ui.remoteBranchEdit.currentData()

        if remoteItem == ERemoteItem.ExistingRef:
            rbr: pygit2.Branch = remoteData
            return rbr.shorthand.removeprefix(rbr.remote_name + "/")
        elif remoteItem == ERemoteItem.NewRef:
            return self.ui.customRemoteBranchNameEdit.text()
        else:
            raise NotImplementedError()

    @property
    def revspec(self):
        prefix = "+" if self.forcePush else ""
        return F"{prefix}refs/heads/{self.currentLocalBranchName}:refs/heads/{self.currentRemoteBranchName}"

    def fillRemoteComboBox(self):
        self.fallbackAutoNewIndex = 0
        self.trackedBranchIndex = -1
        comboBox = self.ui.remoteBranchEdit

        with QSignalBlockerContext(comboBox):
            comboBox.clear()
            firstRemote = True

            for remoteName, remoteBranches in porcelain.getRemoteBranchNames(self.repo).items():
                if not remoteBranches:
                    continue
                if not firstRemote:
                    comboBox.insertSeparator(comboBox.count())

                for remoteBranch in remoteBranches:
                    identifier = F"{remoteName}/{remoteBranch}"
                    br = self.repo.branches.remote[identifier]
                    font = None

                    if br == self.currentLocalBranch.upstream:
                        caption = F"{identifier} [tracked]"
                        self.trackedBranchIndex = comboBox.count()
                        icon = stockIcon(QStyle.StandardPixmap.SP_DirHomeIcon)
                        font = QFont()
                        font.setBold(True)
                    else:
                        icon = stockIcon("vcs-branch")
                        caption = identifier

                    payload = (ERemoteItem.ExistingRef, br)

                    comboBox.addItem(icon, caption, payload)

                    if font:
                        comboBox.setItemData(comboBox.count()-1, font, Qt.ItemDataRole.FontRole)
                    comboBox.setItemData(comboBox.count()-1, self.repo.remotes[remoteName].url, Qt.ItemDataRole.ToolTipRole)

                if firstRemote:
                    self.fallbackAutoNewIndex = comboBox.count()
                comboBox.addItem(stockIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder), F"New remote branch: {remoteName}/...", (ERemoteItem.NewRef, remoteName))

                firstRemote = False

    def __init__(self, repo: pygit2.Repository, branch: pygit2.Branch, parent: QWidget):
        super().__init__(parent)
        self.repo = repo

        self.fallbackAutoNewIndex = 0
        self.trackedBranchIndex = -1
        self.pushInProgress = False

        self.ui = Ui_PushDialog()
        self.ui.setupUi(self)

        self.cloneButton: QPushButton = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        self.cloneButton.setText("&Push")
        self.cloneButton.setIcon(stockIcon("vcs-push"))
        self.cloneButton.clicked.connect(self.onPushClicked)

        pickBranchIndex = 0

        for lbName in repo.branches.local:
            i = addComboBoxItem(self.ui.localBranchEdit, lbName, lbName)
            if branch.shorthand == lbName:
                pickBranchIndex = i
        self.ui.localBranchEdit.setCurrentIndex(pickBranchIndex)

        self.ui.localBranchEdit.currentIndexChanged.connect(self.fillRemoteComboBox)
        self.ui.localBranchEdit.currentIndexChanged.connect(self.onPickLocalBranch)
        self.ui.remoteBranchEdit.currentIndexChanged.connect(self.onPickRemoteBranch)

        # Force the indexchanged signal to fire so the callbacks are guaranteed to run even if pickBranchIndex is 0.
        self.ui.localBranchEdit.currentIndexChanged.emit(pickBranchIndex)

        convertToBrandedDialog(self)

        #self.setMaximumHeight(self.height())
        self.setWindowModality(Qt.WindowModality.WindowModal)

    def enableInputs(self, on: bool):
        for w in [self.ui.remoteBranchEdit, self.ui.localBranchEdit, self.ui.customRemoteBranchNameEdit, self.ui.forcePushCheckBox]:
            w.setEnabled(on)

    def onPushClicked(self):
        remote = self.repo.remotes[self.currentRemoteName]
        log.info("PushDialog", self.revspec, remote.name)
        link = RemoteLink()

        self.ui.statusForm.initProgress(F"Contacting remote host...")
        link.signals.message.connect(self.ui.statusForm.setProgressMessage)
        link.signals.progress.connect(self.ui.statusForm.setProgressValue)

        def work():
            remote.push([self.revspec], callbacks=link)

        def then(_):
            self.pushInProgress = False
            self.pushSuccessful.emit()
            self.accept()
            pass

        def onError(exc: BaseException):
            QApplication.beep()
            QApplication.alert(self, 500)
            self.pushInProgress = False
            self.enableInputs(True)
            self.ui.statusForm.setBlurb(F"<b>{type(exc).__name__}:</b> {escape(str(exc))}")

        self.pushInProgress = True
        self.enableInputs(False)

        wq = WorkQueue(self)
        wq.put(work, then, "Pushing", errorCallback=onError)
