# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.qt import *
from gitfourchette.settings import ComparisonMethod
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables

_ComparisonMethodIconTable = {
    ComparisonMethod.Strict: "diff-whitespace-strict",
    ComparisonMethod.IgnoreCrAtEol: "diff-whitespace-ignore-eol",
    ComparisonMethod.IgnoreCrAtEolAndSpaceChange: "diff-whitespace-ignore-space-change",
    ComparisonMethod.IgnoreCrAtEolAndAllSpace: "diff-whitespace-ignore-all-space",
}


class DiffButtons(QWidget):
    def __init__(self, parent):
        super().__init__(parent)

        self.diffMethodActions: dict[ComparisonMethod, QAction] = {}

        self.wordWrapButton = self._makeWordWrapButton()
        self.marksButton = self._makeMarksButton()
        self.diffMethodButton = self._makeDiffMethodButton()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 2, 0)
        layout.setSpacing(2)
        for button in self.buttons:
            layout.addWidget(button)

    @property
    def buttons(self):
        return self.wordWrapButton, self.marksButton, self.diffMethodButton

    # -------------------------------------------------------------------------
    # Constructor helpers

    def _makeWordWrapButton(self):
        button = QToolButton(self)
        button.setCheckable(True)
        button.setIcon(stockIcon("format-text-wrap"))
        button.setToolTip(TrTables.prefKey("wordWrap"))
        button.toggled.connect(self.onWordWrapToggled)
        return button

    def _makeMarksButton(self):
        button = QToolButton(self)
        button.setCheckable(True)
        button.setIcon(stockIcon("paragraph"))
        button.setToolTip(TrTables.prefKey("showFormattingMarks"))
        button.toggled.connect(self.onMarksToggled)
        return button

    def _makeDiffMethodButton(self):
        menu = QMenu(self)

        actionGroup = QActionGroup(menu)
        actionGroup.setExclusive(True)

        for method in ComparisonMethod:
            label = escamp(TrTables.enum(method))
            action = QAction(label)
            action.setIcon(stockIcon(_ComparisonMethodIconTable[method]))
            action.triggered.connect(lambda _dummy, m=method: self.onDiffMethodChosen(m))
            action.setActionGroup(actionGroup)
            action.setCheckable(True)
            menu.addAction(action)
            self.diffMethodActions[method] = action

        button = QToolButton(self)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        return button

    # -------------------------------------------------------------------------
    # Sync with preferences

    def refreshPrefs(self):
        with QSignalBlockerContext(
                self.wordWrapButton,
                self.marksButton,
                *self.diffMethodActions.values(),
        ):
            self.wordWrapButton.setChecked(settings.prefs.wordWrap)
            self.marksButton.setChecked(settings.prefs.showFormattingMarks)

            method = settings.prefs.comparisonMethod
            for m, action in self.diffMethodActions.items():
                action.setChecked(m == method)
            action = self.diffMethodActions[method]

            toolTip = stripAccelerators(action.text())
            self.diffMethodButton.setIcon(action.icon())
            self.diffMethodButton.setToolTip(toolTip)

    # -------------------------------------------------------------------------
    # Button callbacks

    def onWordWrapToggled(self, checked: bool):
        if settings.prefs.wordWrap == checked:
            return
        settings.prefs.wordWrap = checked
        settings.prefs.write()
        GFApplication.instance().prefsChanged.emit(["wordWrap"])

    def onMarksToggled(self, checked: bool):
        if settings.prefs.showFormattingMarks == checked:
            return
        settings.prefs.showFormattingMarks = checked
        settings.prefs.write()
        GFApplication.instance().prefsChanged.emit(["showFormattingMarks"])

    def onDiffMethodChosen(self, method: settings.ComparisonMethod):
        if settings.prefs.comparisonMethod == method:
            return
        settings.prefs.comparisonMethod = method
        settings.prefs.write()

        GFApplication.instance().prefsChanged.emit(["comparisonMethod"])

        # Trigger a reload of the patch
        # TODO: This is inelegant, but it does the job for now. Ideally prefsChanged would suffice?
        GFApplication.instance().mainWindow.onAcceptPrefsDialog({"comparisonMethod": method})
