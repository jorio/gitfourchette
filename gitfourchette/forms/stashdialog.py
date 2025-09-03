# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.ui_stashdialog import Ui_StashDialog
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *

# In a stash, changes from the index and the worktree are combined.
# Use the order of the keys in this dictionary to find out which status
# will "win out" in a stash for any given file.
# The order of the keys is significant! Last key takes precedence.
# (NB: Dict key order is stable since Python 3.7)
statusPrecedence = {
    FileStatus.INDEX_MODIFIED: 'm',
    FileStatus.INDEX_RENAMED: 'r',
    FileStatus.INDEX_DELETED: 'd',
    FileStatus.INDEX_TYPECHANGE: 't',
    FileStatus.WT_MODIFIED: 'm',
    # INDEX_NEW takes precedence over WT_MODIFIED: if you stage a new file
    # and then modify it, it will appear as a new file in the stash.
    FileStatus.INDEX_NEW: 'a',
    # Other WT flags take precedence over INDEX flags.
    FileStatus.WT_NEW: 'a',
    FileStatus.WT_RENAMED: 'r',
    FileStatus.WT_DELETED: 'd',
    FileStatus.WT_TYPECHANGE: 't',
}


class StashDialog(QDialog):
    def __init__(
            self,
            repoStatus: dict[str, int],
            preTicked: list[str],
            parent: QWidget):
        super().__init__(parent)

        self.ui = Ui_StashDialog()
        self.ui.setupUi(self)
        self.ui.fileList.setVerticalScrollMode(settings.prefs.listViewScrollMode)
        self.ui.keepCheckBox.setToolTip("<p>" + self.ui.keepCheckBox.toolTip())
        self.ui.indexAndWtWarning.setVisible(False)
        self.ui.indexAndWtWarning.setText("\u26a0 " + self.ui.indexAndWtWarning.text())
        tweakWidgetFont(self.ui.fileList, 95)

        for label in (self.ui.willStashLabel, self.ui.indexAndWtWarning):
            tweakWidgetFont(label, 90)

        okButton = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        okButton.setShortcut("Ctrl+Return")

        buttonCaptions = [_("Stash && Reset Changes"), _("Stash && Keep Changes")]
        helpCaptions = [
            _("&Include these files in the stash, then reset them to their unmodified state:"),
            _("&Include these files in the stash:")]
        self.ui.keepCheckBox.clicked.connect(lambda keep: okButton.setText(buttonCaptions[keep]))
        self.ui.keepCheckBox.clicked.connect(lambda keep: self.ui.willStashLabel.setText(helpCaptions[keep]))

        self.ui.fileList.setUniformItemSizes(True)
        scrollTo = None
        for filePath, fileStatus in repoStatus.items():
            prefix = ""
            if (fileStatus & FileStatus_INDEX_MASK) and (fileStatus & FileStatus_WT_MASK):
                self.ui.indexAndWtWarning.setVisible(True)
                prefix = "\u26a0 "

            listItem = QListWidgetItem(prefix + filePath, self.ui.fileList)
            listItem.setSizeHint(QSize(100, 16))
            listItem.setData(Qt.ItemDataRole.UserRole, filePath)
            if not preTicked or filePath in preTicked:
                listItem.setCheckState(Qt.CheckState.Checked)
                if not scrollTo:
                    scrollTo = listItem
            else:
                listItem.setCheckState(Qt.CheckState.Unchecked)

            # Pick an icon that reflects(ish) the future status of the file in the stash
            strongestLetter = ''
            for flag, iconLetter in statusPrecedence.items():
                if fileStatus & flag:
                    strongestLetter = iconLetter
            if strongestLetter:
                icon = stockIcon(f"status_{strongestLetter}")
                listItem.setIcon(icon)

            self.ui.fileList.addItem(listItem)

        # Prime checkbox signal connections
        self.ui.keepCheckBox.click()
        self.ui.keepCheckBox.click()

        convertToBrandedDialog(self)
        self.ui.messageEdit.setFocus()

        # Make sure at least one ticked item is visible
        if scrollTo:
            self.ui.fileList.scrollToItem(scrollTo, hint=QAbstractItemView.ScrollHint.EnsureVisible)

    def tickedPaths(self) -> list[str]:
        paths = []

        for i in range(self.ui.fileList.count()):
            listItem = self.ui.fileList.item(i)
            if listItem.checkState() != Qt.CheckState.Unchecked:
                path = listItem.data(Qt.ItemDataRole.UserRole)
                paths.append(path)

        return paths
