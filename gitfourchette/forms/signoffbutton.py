# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import colors
from gitfourchette.localization import _
from gitfourchette.qt import *
from gitfourchette.toolbox import *

_SOB = "Signed-off-by"


class SignoffButton(QToolButton):
    def __init__(self, parent):
        super().__init__(parent)

        self.willSignoff = False

        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        toggleAction = QAction(self)
        toggleAction.setText(_("Add {0} to commit message", tquo(_SOB)))
        toggleAction.setCheckable(True)
        toggleAction.toggled.connect(lambda t: self.updateConfig(t))

        self.addActions([toggleAction])
        self.updateConfig(self.willSignoff)

    def updateConfig(self, willSignoff: bool):
        self.willSignoff = willSignoff

        lines = []

        if willSignoff:
            lines.append(_("A {0} trailer by the committer will be added "
                           "at the end of the commit message.", tquo(f"<b>{_SOB}</b>")))
        else:
            lines.append(_("{0} will <b>not</b> be added to the commit message.", tquo(_SOB)))

        tip = "<html style='white-space: pre-wrap;'>" + paragraphs(lines)

        if willSignoff:
            icon = stockIcon("git-signoff", f"gray={colors.olive.name()}")
        else:
            icon = stockIcon("git-signoff-disabled")

        self.setIcon(icon)
        self.setToolTip(tip)

    def explicitSign(self):
        return self.willSignoff

    def explicitNoSign(self):
        return not self.willSignoff
