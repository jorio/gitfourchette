from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *
from gitfourchette.forms.ui_resetheaddialog import Ui_ResetHeadDialog


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
            okButton.setToolTip(self.tr("Hard reset: Destructive action!"))
            self.ui.recurseCheckBox.setEnabled(True)
        else:
            self.ui.recurseCheckBox.setEnabled(False)

    def recurseSubmodules(self):
        checkBox = self.ui.recurseCheckBox
        return checkBox.isEnabled() and checkBox.isChecked()

    def __init__(self, oid: Oid, branchName: str, commitText: str, hasSubmodules: bool, parent: QWidget):
        super().__init__(parent)

        self.ui = Ui_ResetHeadDialog()
        self.ui.setupUi(self)

        self.ui.recurseCheckBox.setVisible(hasSubmodules)

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

        title = self.tr("Reset {0} to {1}").format(lquoe(branchName), lquo(shortHash(oid)))
        self.setWindowTitle(title)

        summary, _ = messageSummary(commitText)
        commitText = self.tr("Commit {0}:").format(shortHash(oid)) + " " + tquo(summary)
        convertToBrandedDialog(self, subtitleText=commitText)
