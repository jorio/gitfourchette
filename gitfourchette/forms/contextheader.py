# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from collections.abc import Callable

from gitfourchette.application import GFApplication
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavContext
from gitfourchette.qt import *
from gitfourchette.tasks import *
from gitfourchette.toolbox import *

PERMANENT_PROPERTY = "permanent"


class ContextHeader(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("ContextHeader")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)

        self.locator = NavLocator()
        self.buttons = []

        layout = QHBoxLayout(self)

        self.mainLabel = QElidedLabel(self)

        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.mainLabel)

        self.maximizeButton = self.addButton(_("Maximize"), permanent=True)
        self.maximizeButton.setIcon(stockIcon("maximize"))
        self.maximizeButton.setToolTip(_("Maximize the diff area and hide the commit graph"))
        self.maximizeButton.setCheckable(True)

        self.restyle()
        GFApplication.instance().restyle.connect(self.restyle)

    def restyle(self):
        bg = mutedTextColorHex(self, .07)
        fg = mutedTextColorHex(self, .8)
        self.setStyleSheet(f"ContextHeader {{ background-color: {bg}; }}  ContextHeader QLabel {{ color: {fg}; }}")

    def addButton(self, text: str, callback: Callable | None = None, permanent=False) -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        button.setProperty(PERMANENT_PROPERTY, "true" if permanent else "")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAutoRaise(True)
        self.buttons.append(button)

        if callback is not None:
            button.clicked.connect(callback)

        layout: QHBoxLayout = self.layout()
        layout.insertWidget(1, button)

        button.setMaximumHeight(20)

        return button

    def clearButtons(self):
        for i in range(len(self.buttons) - 1, -1, -1):
            button = self.buttons[i]
            if not button.property(PERMANENT_PROPERTY):
                button.hide()
                button.deleteLater()
                del self.buttons[i]

    @DisableWidgetUpdatesContext.methodDecorator
    def setContext(self, locator: NavLocator, commitMessage: str = "", isStash=False):
        self.clearButtons()

        self.locator = locator

        if locator.context == NavContext.COMMITTED:
            kind = _p("noun", "Stash") if isStash else _p("noun", "Commit")
            summary, _continued = messageSummary(commitMessage)
            self.mainLabel.setText(f"{kind} {shortHash(locator.commit)} – {summary}")

            infoButton = self.addButton(_("Info"), lambda: GetCommitInfo.invoke(self, self.locator.commit))
            infoButton.setToolTip(_("Show details about this commit") if not isStash
                                  else _("Show details about this stash"))

            if isStash:
                dropButton = self.addButton(_("Delete"), lambda: DropStash.invoke(self, locator.commit))
                dropButton.setToolTip(_("Delete this stash"))

                applyButton = self.addButton(_("Apply"), lambda: ApplyStash.invoke(self, locator.commit))
                applyButton.setToolTip(_("Apply this stash"))

        elif locator.context.isWorkdir():
            self.mainLabel.setText(_("Working Directory"))
        else:
            # Special context (e.g. history truncated)
            self.mainLabel.setText(" ")
