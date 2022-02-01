import porcelain
from allqt import *
from util import labelQuote, addComboBoxItem
import pygit2

from widgets import brandeddialog


class TrackedBranchDialog(QDialog):
    newTrackingBranchName: str

    def __init__(self, repo: pygit2.Repository, localBranchName: str, parent):
        super().__init__(parent)

        self.setWindowTitle(F"Edit Tracked Branch")

        buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

        localBranch: pygit2.Branch = repo.branches.local[localBranchName]
        trackedBranch: pygit2.Branch = localBranch.upstream

        comboBox = QComboBox(self)
        self.comboBox = comboBox

        self.newTrackedBranchName = None
        if trackedBranch:
            self.newTrackedBranchName = trackedBranch.shorthand

        addComboBoxItem(comboBox, "[don’t track any remote branch]", userData=None, isCurrent=not trackedBranch)

        for remoteName, remoteBranches in porcelain.getRemoteBranchNames(repo).items():
            if not remoteBranches:
                continue
            comboBox.insertSeparator(comboBox.count())
            #remotePrefix = F"refs/remotes/{remote.name}/"
            #remoteRefNames = (n for n in repo.listall_references() if n.startswith(remotePrefix))
            for remoteBranch in remoteBranches:
                addComboBoxItem(
                    comboBox,
                    F"{remoteName}/{remoteBranch}",
                    userData=F"{remoteName}/{remoteBranch}",
                    isCurrent=trackedBranch and trackedBranch.name == F"refs/remotes/{remoteName}/{remoteBranch}")

        comboBox.currentIndexChanged.connect(
            lambda index: self.onChangeNewRemoteBranchName(comboBox.itemData(index, role=Qt.UserRole)))

        explainer = F"<p>Local branch <b>{labelQuote(localBranch.shorthand)}</b> currently "
        if trackedBranch:
            explainer += F"tracks remote branch <b>{labelQuote(trackedBranch.shorthand)}</b>."
        else:
            explainer += "does <b>not</b> track a remote branch."
        explainer += "</p><p>Pick a new remote branch to track:</p>"
        explainerLabel = QLabel(explainer)
        explainerLabel.setWordWrap(True)

        explainerLabel.setMinimumHeight(explainerLabel.fontMetrics().height()*4)

        layout = QVBoxLayout()
        layout.addWidget(explainerLabel)
        layout.addWidget(comboBox)
        layout.addWidget(QLabel("<small>If you can’t find the remote branch you want, "
                                "try fetching the remote first.</small>"))
        layout.addWidget(buttonBox)

        brandeddialog.makeBrandedDialog(self, layout, F"Set branch tracked by “{localBranch.shorthand}”")

        self.setModal(True)
        self.resize(512, 128)
        self.setMaximumHeight(self.height())

    def onChangeNewRemoteBranchName(self, remoteBranchName):
        self.newTrackedBranchName = remoteBranchName
