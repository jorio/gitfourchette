# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import stockIcon


class QHintButton(QToolButton):
    def __init__(self, parent=None, toolTip="", iconKey="hint"):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoRaise(True)
        self.setText(_("Help"))
        self.setIcon(stockIcon(iconKey))
        self.setToolTip(toolTip)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self.connectClicked()

    def connectClicked(self):
        self.clicked.connect(lambda _: QToolTip.showText(QCursor.pos(), self.toolTip(), self))
