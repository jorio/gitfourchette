# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import colors
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import stockIcon, tquo


class CommitHookButton(QToolButton):
    def __init__(self, parent):
        super().__init__(parent)

        self.willRunHooks = True
        self.hookNames = []  # must be filled in

        toggleAction = QAction(self)
        toggleAction.setText("...RUN HOOKS...")
        toggleAction.setCheckable(True)
        toggleAction.setChecked(self.willRunHooks)
        toggleAction.toggled.connect(lambda t: self.updateConfig(t))
        self.toggleAction = toggleAction

        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.addActions([toggleAction])
        self.updateConfig(self.willRunHooks)

    def setup(self, commitHooks: list[str]):
        if not commitHooks:
            self.setVisible(False)
            return
        self.hookNames = commitHooks
        self.updateConfig(self.willRunHooks)

        title = _n("Run {h} hook", "Run hooks {h}", len(self.hookNames), h=self.hooksString())
        self.toggleAction.setText(title)

    def hooksString(self):
        andJoin = " " + _("and") + " "
        return andJoin.join([tquo(hook) for hook in self.hookNames])

    def updateConfig(self, willRunHooks: bool):
        self.willRunHooks = willRunHooks

        if willRunHooks:
            tip = _n("Hook {h} will run.", "Hooks {h} will run.", n=len(self.hookNames), h=self.hooksString())
            icon = stockIcon("git-hook", f"gray={colors.olive.name()}")
        else:
            tip = _n("Bypassing {h} hook for this commit.", "Bypassing hooks {h} for this commit.", n=len(self.hookNames), h=self.hooksString())
            icon = stockIcon("git-hook-disabled")

        self.setIcon(icon)
        self.setToolTip(tip)

    def explicitNoVerify(self):
        return not self.willRunHooks
