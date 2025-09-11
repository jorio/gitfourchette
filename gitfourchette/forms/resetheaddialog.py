# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.ui_resetheaddialog import Ui_ResetHeadDialog
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *

DEFAULT_MODE = ResetMode.MIXED


class ResetHeadDialog(QDialog):
    activeMode: ResetMode

    def setActiveMode(self, mode: ResetMode):
        self.activeMode = mode
        okButton = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        okButton.setIcon(self.defaultOkIcon)
        okButton.setToolTip("")
        if mode == ResetMode.HARD:
            okButton.setIcon(stockIcon("achtung"))
            okButton.setToolTip(_("Hard reset: Destructive action!"))
        self.ui.recurseCheckBox.setEnabled(self.hasSubmodules and mode == ResetMode.HARD)

    def recurseSubmodules(self):
        checkBox = self.ui.recurseCheckBox
        return checkBox.isEnabled() and checkBox.isChecked()

    def __init__(self, oid: Oid, branchName: str, commitText: str, hasSubmodules: bool, parent: QWidget):
        super().__init__(parent)

        self.ui = Ui_ResetHeadDialog()
        self.ui.setupUi(self)

        self.hasSubmodules = hasSubmodules
        self.ui.recurseCheckBox.setVisible(hasSubmodules)
        self.ui.recurseCheckBox.setEnabled(hasSubmodules)

        okButton = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        self.defaultOkIcon = okButton.icon() or QIcon()

        self.modeButtons = {
            ResetMode.SOFT: self.ui.softButton,
            ResetMode.MIXED: self.ui.mixedButton,
            ResetMode.HARD: self.ui.hardButton,
        }
        self.modeLabels = {
            ResetMode.SOFT: self.ui.softHelp,
            ResetMode.MIXED: self.ui.mixedHelp,
            ResetMode.HARD: self.ui.hardHelp,
        }

        fontMetrics = self.modeButtons[ResetMode.SOFT].fontMetrics()
        spaceWidth = fontMetrics.horizontalAdvance(" " * 100) / 100
        desiredWidth = fontMetrics.horizontalAdvance("MixedWW")

        for mode, button in self.modeButtons.items():
            label = self.modeLabels[mode]
            formatWidgetText(label, commit=lquo(shortHash(oid)))
            tweakWidgetFont(label, 88)

            button.toggled.connect(lambda checked, m=mode: self.setActiveMode(m))

            # Pad checkbox text with spaces to enlarge clickable zone (hacky)
            missingWidth = desiredWidth - fontMetrics.horizontalAdvance(button.text())
            padding = " " * max(0, int(missingWidth / spaceWidth))
            button.setText(button.text() + padding)

        self.activeMode = DEFAULT_MODE
        self.modeButtons[DEFAULT_MODE].setChecked(True)

        title = _("Reset {0} to {1}", lquoe(branchName), lquo(shortHash(oid)))
        self.setWindowTitle(title)

        summary, _dummy = messageSummary(commitText)
        commitText = _("Commit {0}:", shortHash(oid)) + " " + tquo(summary)
        convertToBrandedDialog(self, subtitleText=commitText)
