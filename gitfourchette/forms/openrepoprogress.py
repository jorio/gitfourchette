# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.ui_openrepoprogress import Ui_OpenRepoProgress
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class OpenRepoProgress(QWidget):
    def __init__(self, parent=None, name=""):
        super().__init__(parent)
        self.ui = Ui_OpenRepoProgress()
        self.ui.setupUi(self)

        abortIcon = stockIcon("SP_BrowserStop")

        self.ui.abortButton.setIcon(abortIcon)
        self.ui.abortButton.setEnabled(False)

        if name:
            self.initialMessage = _("Opening {0}…", tquo(name))
            self.ui.label.setText(self.initialMessage)
        else:
            self.initialMessage = self.ui.label.text()

    def reset(self):
        self.ui.retranslateUi(self)
        self.ui.label.setText(self.initialMessage)
        self.ui.progressBar.setRange(0, 100)
        self.ui.progressBar.setValue(0)
