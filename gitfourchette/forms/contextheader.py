# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from collections.abc import Callable

from gitfourchette.application import GFApplication
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavContext
from gitfourchette.porcelain import Oid, NULL_OID
from gitfourchette.qt import *
from gitfourchette.tasks import *
from gitfourchette.toolbox import *


class ContextHeader(QFrame):
    PermanentButtonProperty = "permanent"
    CompareModeProperty = "compare"

    toggleMaximize = Signal()
    unpinCommit = Signal()

    locator: NavLocator
    buttons: list[QToolButton]

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
        self.maximizeButton.clicked.connect(self.toggleMaximize)

        self.restyle()
        GFApplication.instance().restyle.connect(self.restyle)

    def isCompareMode(self):
        return bool(self.property(ContextHeader.CompareModeProperty))

    def restyle(self):
        comparing = self.isCompareMode()

        if not comparing:
            bg = mutedTextColorHex(self, .07)
            fg = mutedTextColorHex(self, .8)
            self.setStyleSheet(f"ContextHeader {{ background-color: {bg}; }}  ContextHeader QLabel {{ color: {fg}; }}")
        else:
            self.setStyleSheet("* {}")

        for b in self.buttons:
            b.setAutoRaise(not comparing)

    def addButton(self, text: str, callback: Callable | Signal | None = None, permanent=False) -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        button.setProperty(ContextHeader.PermanentButtonProperty, "true" if permanent else "")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAutoRaise(not self.isCompareMode())
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
            if not button.property(ContextHeader.PermanentButtonProperty):
                button.hide()
                button.deleteLater()
                del self.buttons[i]

    @DisableWidgetUpdatesContext.methodDecorator
    def setContext(self, locator: NavLocator, commitMessage: str = "", isStash=False, pinnedCommit: Oid = NULL_OID):
        self.clearButtons()

        comparingPin = locator.context == NavContext.COMMITTED and pinnedCommit != NULL_OID

        self.locator = locator

        if locator.context == NavContext.COMMITTED:
            if not comparingPin:
                kind = _p("noun", "Stash") if isStash else _p("noun", "Commit")
                summary, _continued = messageSummary(commitMessage)
                mainText = f"{kind} {shortHash(locator.commit)} – {summary}"
            elif pinnedCommit == locator.commit:
                mainText = _("Commit {0} is pinned for comparison", shortHash(pinnedCommit))
            else:
                mainText = _("Comparing pinned commit {0} to {1}", "\u2022" + shortHash(pinnedCommit), shortHash(locator.commit))
            self.mainLabel.setText(mainText)

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

        if comparingPin:
            unpinButton = self.addButton(_("Unpin {0}", tquo(shortHash(pinnedCommit))), self.unpinCommit)
            unpinButton.setIcon(stockIcon("pin"))
            unpinButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        # Toggle 'compare' property
        if comparingPin != self.isCompareMode():
            self.setProperty(ContextHeader.CompareModeProperty, "true" if comparingPin else "")
            self.restyle()
