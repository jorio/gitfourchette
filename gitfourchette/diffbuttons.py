# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from typing import Any

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.settings import WhitespaceMode
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables


class DiffButtons(QWidget):
    def __init__(self, parent):
        super().__init__(parent)

        self.diffMethodActions: dict[WhitespaceMode, QAction] = {}

        self.contextButton = self._makeContextLinesButton()
        self.wordWrapButton = self._makeToggle("diff-wrap", "wordWrap")
        self.marksButton = self._makeToggle("diff-show-whitespace", "showFormattingMarks")
        self.whitespaceModeButton = self._makeWhitespaceDiffButton()
        self.svgButton = self._makeToggle("diff-svg", "renderSvg")
        self.svgButton.setToolTip(_("SVG image preview"))

        self.buttons = [
            self.svgButton,
            self.contextButton,
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
        button = QToolButton(self)
        menu = QMenu(button)

        actionGroup = QActionGroup(menu)
        actionGroup.setExclusive(True)

        for mode in WhitespaceMode:
            label = escamp(TrTables.enum(mode))
            iconName = f"diff-whitespace-{mode or 'strict'}"
            action = QAction(stockIcon(iconName), label, button)
            action.triggered.connect(lambda _dummy, m=mode: self.setWhitespaceMode(m))
            action.setActionGroup(actionGroup)
            action.setCheckable(True)
            menu.addAction(action)
            self.diffMethodActions[mode] = action

        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

        # We'll "press" the button when the whitespace mode is anything but Strict.
        button.setCheckable(True)

        return button

    def _makeContextLinesButton(self):
        button = QToolButton(self)
        menu = QMenu(button)

        actionGroup = QActionGroup(menu)
        actionGroup.setExclusive(True)

        container = QWidget()
        layout = QHBoxLayout(container)

        spinbox = QSpinBox()
        spinbox.setRange(0, 32)  # TODO: couple with PrefsDialog bounds
        spinbox.valueChanged.connect(self.setContextLines)
        spinbox.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)

        t1, t2 = _("Show up to # context lines").split("#")
        layout.addWidget(QLabel(t1))
        layout.addWidget(spinbox)
        layout.addWidget(QLabel(t2))

        def aboutToShowContextLinesMenu():
            spinbox.setValue(settings.prefs.contextLines)
            spinbox.setFocus()
            spinbox.selectAll()

        widgetAction = QWidgetAction(menu)
        widgetAction.setDefaultWidget(container)
        menu.addAction(widgetAction)
        menu.aboutToShow.connect(aboutToShowContextLinesMenu)

        button.setToolTip(_("Context lines"))
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setText(_("Context"))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        return button

    def _makeToggle(self, icon: str, prefKey: str):
        button = QToolButton(self)
        button.setCheckable(True)
        button.setIcon(stockIcon(icon))
        button.setToolTip(TrTables.prefKey(prefKey))
        button.toggled.connect(lambda checked: self.setPref(prefKey, checked))
        return button

    # -------------------------------------------------------------------------
    # Sync with preferences

    def refreshPrefs(self):
        with QSignalBlockerContext(
                *self.buttons,
                *self.diffMethodActions.values(),
        ):
            self.wordWrapButton.setChecked(settings.prefs.wordWrap)
            self.marksButton.setChecked(settings.prefs.showFormattingMarks)
            self.contextButton.setIcon(stockIcon("diff-context-lines", f"$TEXT$={settings.prefs.contextLines}"))

            mode = settings.prefs.whitespaceMode
            for m, action in self.diffMethodActions.items():
                action.setChecked(m == mode)
            action = self.diffMethodActions[mode]

            toolTip = stripAccelerators(action.text())
            self.whitespaceModeButton.setIcon(action.icon())
            self.whitespaceModeButton.setToolTip(toolTip)

            # "Press" the button when the mode is anything but Strict.
            self.whitespaceModeButton.setChecked(mode != WhitespaceMode.Strict)

            self.svgButton.setChecked(settings.prefs.renderSvg)

    # -------------------------------------------------------------------------
    # Button callbacks

    @classmethod
    def setPref(cls, prefKey: str, newValue: Any):
        if getattr(settings.prefs, prefKey) == newValue:
            return

        setattr(settings.prefs, prefKey, newValue)
        settings.prefs.write()
        GFApplication.instance().prefsChanged.emit([prefKey])

        if prefKey in {"whitespaceMode", "contextLines", "renderSvg"}:
            # Trigger a reload of the patch
            # TODO: This is inelegant, but it does the job for now. Ideally prefsChanged would suffice?
            GFApplication.instance().mainWindow.onAcceptPrefsDialog({prefKey: newValue})

    def setWhitespaceMode(self, mode: WhitespaceMode):
        self.setPref("whitespaceMode", mode)

    def setContextLines(self, n: int):
        self.setPref("contextLines", n)
