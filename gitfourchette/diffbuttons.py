# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.qt import *
from gitfourchette.settings import WhitespaceMode
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables

_WhitespaceDiffIconTable = {
    WhitespaceMode.Strict: "diff-whitespace-strict",
    WhitespaceMode.IgnoreChange: "diff-whitespace-ignore-space-change",
    WhitespaceMode.IgnoreAll: "diff-whitespace-ignore-all-space",
    WhitespaceMode.IgnoreCrAtEol: "diff-whitespace-ignore-eol",
}


class DiffButtons(QWidget):
    def __init__(self, parent):
        super().__init__(parent)

        self.diffMethodActions: dict[WhitespaceMode, QAction] = {}

        self.wordWrapButton = self._makeToggle("format-text-wrap", "wordWrap")
        self.marksButton = self._makeToggle("paragraph", "showFormattingMarks")
        self.whitespaceModeButton = self._makeWhitespaceDiffButton()

        self.buttons = [
            self.wordWrapButton,
            self.marksButton,
            self.whitespaceModeButton,
        ]

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 2, 0)
        layout.setSpacing(2)
        for button in self.buttons:
            layout.addWidget(button)

    # -------------------------------------------------------------------------
    # Constructor helpers

    def _makeWhitespaceDiffButton(self):
        menu = QMenu(self)

        actionGroup = QActionGroup(menu)
        actionGroup.setExclusive(True)

        for mode in WhitespaceMode:
            label = escamp(TrTables.enum(mode))
            action = QAction(label)
            action.setIcon(stockIcon(_WhitespaceDiffIconTable[mode]))
            action.triggered.connect(lambda _dummy, m=mode: self.setWhitespaceMode(m))
            action.setActionGroup(actionGroup)
            action.setCheckable(True)
            menu.addAction(action)
            self.diffMethodActions[mode] = action

        button = QToolButton(self)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        # We'll "press" the button when the whitespace mode is anything but Strict.
        button.setCheckable(True)

        return button

    def _makeToggle(self, icon: str, prefKey: str):
        button = QToolButton(self)
        button.setCheckable(True)
        button.setIcon(stockIcon(icon))
        button.setToolTip(TrTables.prefKey(prefKey))
        button.toggled.connect(lambda checked: self.onGenericToggle(prefKey, checked))
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

            mode = settings.prefs.whitespaceMode
            for m, action in self.diffMethodActions.items():
                action.setChecked(m == mode)
            action = self.diffMethodActions[mode]

            toolTip = stripAccelerators(action.text())
            self.whitespaceModeButton.setIcon(action.icon())
            self.whitespaceModeButton.setToolTip(toolTip)

            # "Press" the button when the mode is anything but Strict.
            self.whitespaceModeButton.setChecked(mode != WhitespaceMode.Strict)

    # -------------------------------------------------------------------------
    # Button callbacks

    @classmethod
    def onGenericToggle(cls, prefKey: str, checked: bool):
        if getattr(settings.prefs, prefKey) == checked:
            return
        setattr(settings.prefs, prefKey, checked)
        settings.prefs.write()
        GFApplication.instance().prefsChanged.emit([prefKey])

    def setWhitespaceMode(self, mode: WhitespaceMode):
        if settings.prefs.whitespaceMode == mode:
            return

        settings.prefs.whitespaceMode = mode
        settings.prefs.write()

        GFApplication.instance().prefsChanged.emit(["whitespaceMode"])

        # Trigger a reload of the patch
        # TODO: This is inelegant, but it does the job for now. Ideally prefsChanged would suffice?
        GFApplication.instance().mainWindow.onAcceptPrefsDialog({"whitespaceMode": mode})
