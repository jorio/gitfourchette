# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import re
import traceback
import urllib.parse
from contextlib import suppress
from pathlib import Path

import pygit2
from pygit2.enums import RepositoryOpenFlag

from gitfourchette import settings
from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.ui_clonedialog import Ui_CloneDialog
from gitfourchette.localization import *
from gitfourchette.porcelain import Repo, pygit2_version_at_least
from gitfourchette.qt import *
from gitfourchette.remotelink import RemoteLink
from gitfourchette.repoprefs import RepoPrefs
from gitfourchette.tasks import RepoTask, RepoTaskRunner
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables


def _projectNameFromUrl(url: str) -> str:
    url = url.strip()
    name = url.rsplit("/", 1)[-1].removesuffix(".git")
    name = urllib.parse.unquote(name)
    # Sanitize name
    for c in " ?/\\*~<>|:":
        name = name.replace(c, "_")
    return name


class CloneDialog(QDialog):
    cloneSuccessful = Signal(str)
    aboutToReject = Signal()

    urlEditUserDataClearHistory = "CLEAR_HISTORY"

    def __init__(self, initialUrl: str, parent: QWidget):
        super().__init__(parent)

        if not initialUrl:
            initialUrl = guessRemoteUrlFromText(QApplication.clipboard().text())

        self.taskRunner = RepoTaskRunner(self)

        self.ui = Ui_CloneDialog()
        self.ui.setupUi(self)

        self.initUrlComboBox()
        self.ui.urlEdit.activated.connect(self.onUrlActivated)

        self.ui.browseButton.setIcon(stockIcon("SP_DialogOpenButton"))
        self.ui.browseButton.clicked.connect(self.browse)

        self.setDefaultCloneLocationAction = QAction("(SET)")
        self.setDefaultCloneLocationAction.triggered.connect(lambda: self.setDefaultCloneLocationPref(self.pathParentDir))
        self.clearDefaultCloneLocationAction = QAction(stockIcon("edit-clear-history"), _("Reset default clone location"))
        self.clearDefaultCloneLocationAction.triggered.connect(lambda: self.setDefaultCloneLocationPref(""))
        self.ui.browseButton.setMenu(ActionDef.makeQMenu(
            self.ui.browseButton, [self.setDefaultCloneLocationAction, self.clearDefaultCloneLocationAction]))
        self.updateDefaultCloneLocationAction()  # prime default clone path actions
        self.ui.pathEdit.textChanged.connect(self.updateDefaultCloneLocationAction)

        self.cloneButton: QPushButton = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        self.cloneButton.setText(_("C&lone"))
        self.cloneButton.setIcon(QIcon.fromTheme("download"))
        self.cloneButton.clicked.connect(self.onCloneClicked)

        self.cancelButton: QPushButton = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Cancel)
        self.cancelButton.setAutoDefault(False)

        self.ui.statusForm.setBlurb(_("Hit {0} when ready.", tquo(self.cloneButton.text().replace("&", ""))))

        self.ui.shallowCloneDepthSpinBox.valueChanged.connect(self.onShallowCloneDepthChanged)
        self.ui.shallowCloneCheckBox.stateChanged.connect(self.onShallowCloneCheckBoxStateChanged)
        self.ui.shallowCloneCheckBox.setMinimumHeight(max(self.ui.shallowCloneCheckBox.height(), self.ui.shallowCloneDepthSpinBox.height()))  # prevent jumping around
        self.onShallowCloneCheckBoxStateChanged(self.ui.shallowCloneCheckBox.checkState())

        convertToBrandedDialog(self)

        self.ui.urlEdit.editTextChanged.connect(self.autoFillDownloadPath)
        self.ui.urlEdit.setCurrentIndex(-1)  # prevent "Clear History" from installing its icon
        self.ui.urlEdit.setCurrentText(initialUrl)
        self.ui.urlEdit.setFocus()

        # Connect protocol button to URL editor
        self.ui.protocolButton.connectTo(self.ui.urlEdit.lineEdit())

        validator = ValidatorMultiplexer(self)
        validator.setGatedWidgets(self.cloneButton)
        validator.connectInput(self.ui.urlEdit.lineEdit(), self.validateUrl)
        validator.connectInput(self.ui.pathEdit, self.validatePath)
        validator.run(silenceEmptyWarnings=True)

        if not pygit2_version_at_least("1.15.1", False):
            self.ui.recurseSubmodulesCheckBox.setChecked(False)
            self.ui.recurseSubmodulesCheckBox.setEnabled(False)
            self.ui.recurseSubmodulesCheckBox.setText("Recursing into submodules requires pygit2 1.15.1+")

    def validateUrl(self, url):
        if not url:
            return _("Please fill in this field.")
        return ""

    def validatePath(self, _ignored: str) -> str:
        path = self.path
        path = Path(path)
        if not path.is_absolute():
            return _("Please enter an absolute path.")
        if path.is_file():
            return _("There’s already a file at this path.")
        if path.is_dir():
            with suppress(StopIteration):
                next(path.iterdir())  # raises StopIteration if directory is not empty
                return _("This directory isn’t empty.")
        return ""

    def autoFillDownloadPath(self, url):
        # Get standard download location
        downloadPath = Path(settings.prefs.resolveDefaultCloneLocation())

        # Don't overwrite if user has set a custom path
        currentPath = self.ui.pathEdit.text()
        if currentPath and Path(currentPath).parent != downloadPath:
            return

        # Extract project name; clear target path if blank
        projectName = _projectNameFromUrl(url)
        if not projectName or projectName in [".", ".."]:
            self.ui.pathEdit.setText("")
            return

        # Append differentiating number if this path already exists
        projectName = withUniqueSuffix(projectName, lambda x: (downloadPath / x).exists())

        # Set target path to <downloadPath>/<projectName>
        target = downloadPath / projectName
        assert not target.exists()

        self.ui.pathEdit.setText(str(target))

    def updateDefaultCloneLocationAction(self):
        self.clearDefaultCloneLocationAction.setEnabled(settings.prefs.defaultCloneLocation != "")

        location = self.pathParentDir
        action = self.setDefaultCloneLocationAction

        if self.validatePath(self.path):  # truthy if validation error
            action.setText(_("Set current location as default clone location"))
            action.setEnabled(False)
            return

        display = lquoe(compactPath(location))
        if location == settings.prefs.resolveDefaultCloneLocation():
            action.setEnabled(False)
            action.setText(_("{0} is the default clone location", display))
        else:
            action.setEnabled(True)
            action.setText(_("Set {0} as default clone location", display))

    def setDefaultCloneLocationPref(self, location: str):
        settings.prefs.defaultCloneLocation = location
        settings.prefs.setDirty()
        self.updateDefaultCloneLocationAction()

    def initUrlComboBox(self):
        urlEdit = self.ui.urlEdit
        urlEdit.clear()

        if settings.history.cloneHistory:
            for url in settings.history.cloneHistory:
                urlEdit.addItem(url)
            urlEdit.insertSeparator(urlEdit.count())

        urlEdit.addItem(stockIcon("edit-clear-history"), _("Clear history"), CloneDialog.urlEditUserDataClearHistory)

        # "Clear history" is added even if the history is empty, so that the
        # QComboBox's arrow button - which cannot be hidden - still pops up
        # something when clicked, as the user might expect.
        if not settings.history.cloneHistory:
            clearItem: QStandardItem = urlEdit.model().item(urlEdit.count()-1)
            clearItem.setFlags(clearItem.flags() & ~Qt.ItemFlag.ItemIsEnabled)

        self.ui.urlEdit.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)

    def onUrlActivated(self, index: int):
        itemData = self.ui.urlEdit.itemData(index, Qt.ItemDataRole.UserRole)
        if itemData == CloneDialog.urlEditUserDataClearHistory:
            settings.history.clearCloneHistory()
            settings.history.write()
            self.initUrlComboBox()

    @DisableWidgetUpdatesContext.methodDecorator
    def onShallowCloneCheckBoxStateChanged(self, state):
        isChecked = state not in [0, Qt.CheckState.Unchecked]
        if isChecked:
            self.onShallowCloneDepthChanged(self.ui.shallowCloneDepthSpinBox.value())
        else:
            self.ui.shallowCloneCheckBox.setText(_("&Shallow clone"))
        self.ui.shallowCloneDepthSpinBox.setVisible(isChecked)
        self.ui.shallowCloneSuffix.setVisible(isChecked)

    def onShallowCloneDepthChanged(self, depth: int):
        # Re-translate text for correct plural form
        text = _n("&Shallow clone: Fetch up to {n} commit per branch",
                  "&Shallow clone: Fetch up to {n} commits per branch", depth)
        parts = re.split(r"\b\d(?:.*\d)?\b", text, maxsplit=1)
        assert len(parts) >= 2
        self.ui.shallowCloneCheckBox.setText(parts[0].strip())
        self.ui.shallowCloneSuffix.setText(parts[1].strip())

    def reject(self):
        # Emit "aboutToReject" before destroying the dialog so TaskRunner has time to wrap up.
        self.aboutToReject.emit()
        self.taskRunner.killCurrentTask()
        self.taskRunner.joinZombieTask()
        super().reject()  # destroys the dialog then emits the "rejected" signal

    @property
    def url(self):
        return self.ui.urlEdit.currentText().strip()

    @property
    def path(self):
        text = self.ui.pathEdit.text().strip()
        path = Path(text)
        with suppress(RuntimeError):
            path = path.expanduser()
        return str(path)

    @property
    def pathParentDir(self):
        return str(Path(self.path).parent)

    def browse(self):
        existingPath = Path(self.path) if self.path else None

        if existingPath:
            initialName = existingPath.name
        else:
            initialName = _projectNameFromUrl(self.url)

        qfd = PersistentFileDialog.saveFile(self, "NewRepo", _("Clone repository into"), initialName)

        # Rationale for omitting directory-related options that appear to make sense at first glance:
        # - FileMode.Directory: forces user to hit "new folder" to enter the name of the repo
        # - Options.ShowDirsOnly: KDE Plasma 6's native dialog forces user to hit "new folder" when this flag is set
        qfd.setOption(QFileDialog.Option.DontConfirmOverwrite, True)  # we'll show our own warning if the file already exists
        qfd.setOption(QFileDialog.Option.HideNameFilterDetails, True)  # not sure Qt honors this...

        qfd.setLabelText(QFileDialog.DialogLabel.FileName, self.ui.pathLabel.text())  # "Clone into:"
        qfd.setLabelText(QFileDialog.DialogLabel.Accept, _("Clone here"))

        if existingPath:
            qfd.setDirectory(str(existingPath.parent))

        qfd.fileSelected.connect(lambda path: self.ui.pathEdit.setText(str(Path(path))))
        qfd.show()

    def enableInputs(self, enable):
        grayable = [
            self.ui.urlLabel,
            self.ui.urlEdit,
            self.ui.pathLabel,
            self.ui.pathEdit,
            self.ui.browseButton,
            self.ui.optionsLabel,
            self.ui.recurseSubmodulesCheckBox,
            self.ui.shallowCloneCheckBox,
            self.ui.shallowCloneDepthSpinBox,
            self.ui.shallowCloneSuffix,
            self.ui.keyFilePicker,
            self.cloneButton
        ]
        for widget in grayable:
            widget.setEnabled(enable)

    def onCloneClicked(self):
        depth = 0
        privKeyPath = self.ui.keyFilePicker.privateKeyPath()
        recursive = self.ui.recurseSubmodulesCheckBox.isChecked()

        if self.ui.shallowCloneCheckBox.isChecked():
            depth = self.ui.shallowCloneDepthSpinBox.value()

        self.ui.statusForm.initProgress(_("Contacting remote host…"))
        self.taskRunner.put(CloneTask(self), url=self.url, path=self.path, depth=depth, privKeyPath=privKeyPath, recursive=recursive)

    def onUrlProtocolChanged(self, newUrl: str):
        # This pushes the new text to the QLineEdit's undo stack (whereas setText clears the undo stack).
        self.ui.urlEdit.lineEdit().selectAll()
        self.ui.urlEdit.lineEdit().insert(newUrl)


class CloneTask(RepoTask):
    """
    Even though we don't have a Repository yet, this is a RepoTask so we can
    easily run the clone operation in a background thread.
    """

    stickyStatus = Signal(str)

    def __init__(self, dialog: CloneDialog):
        super().__init__(dialog)
        self.cloneDialog = dialog
        self.remoteLink = RemoteLink(self)
        self.remoteLink.message.connect(dialog.ui.statusForm.setProgressMessage)
        self.remoteLink.progress.connect(dialog.ui.statusForm.setProgressValue)
        self.stickyStatus.connect(dialog.ui.statusGroupBox.setTitle)

    def abort(self):
        self.remoteLink.raiseAbortFlag()

    def flow(self, url: str, path: str, depth: int, privKeyPath: str, recursive: bool):
        dialog = self.cloneDialog
        dialog.enableInputs(False)
        dialog.aboutToReject.connect(self.remoteLink.raiseAbortFlag)

        # Enter worker thread
        yield from self.flowEnterWorkerThread()

        # Set private key
        # (This requires passing resetParams=False to remoteContext())
        if privKeyPath:
            self.remoteLink.forceCustomKeyFile(privKeyPath)

        # Clone the repo
        self.stickyStatus.emit(_("Cloning…"))
        with self.remoteLink.remoteContext(url, resetParams=False):
            repo = pygit2.clone_repository(url, path, callbacks=self.remoteLink, depth=depth)

        # Convert to our extended Repo class
        repo = Repo(repo.workdir, RepositoryOpenFlag.NO_SEARCH)

        # Store custom key (if any) in cloned repo config
        if privKeyPath:
            RepoPrefs.setRemoteKeyFileForRepo(repo, repo.remotes[0].name, privKeyPath)

        # Recurse into submodules
        if recursive:
            self.recurseIntoSubmodules(repo, depth=depth)

        # Done, back to UI thread
        yield from self.flowEnterUiThread()
        settings.history.addCloneUrl(url)
        settings.history.setDirty()
        dialog.cloneSuccessful.emit(path)
        dialog.accept()

    def recurseIntoSubmodules(self, repo: Repo, depth: int):
        for i, submodule in enumerate(repo.recurse_submodules(), 1):
            stickyStatus = _("Initializing submodule {0}: {1}…", i, lquoe(submodule.name))
            self.stickyStatus.emit(stickyStatus)

            with self.remoteLink.remoteContext(submodule.url or ""):
                submodule.update(init=True, callbacks=self.remoteLink, depth=depth)

    def onError(self, exc: BaseException):
        traceback.print_exception(exc.__class__, exc, exc.__traceback__)
        dialog = self.cloneDialog
        QApplication.beep()
        QApplication.alert(dialog, 500)
        dialog.enableInputs(True)
        dialog.ui.statusForm.setBlurb(f"<span style='white-space: pre;'><b>{TrTables.exceptionName(exc)}:</b> {escape(str(exc))}")
