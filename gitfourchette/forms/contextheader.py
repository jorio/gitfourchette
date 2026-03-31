# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from collections.abc import Callable

from gitfourchette import colors
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

        self.mainLabel = QLabel(self)
        self.spacerItem = QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 0, 0)
        layout.addWidget(self.mainLabel)
        layout.addSpacerItem(self.spacerItem)

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

    def addButton(
            self,
            text: str,
            callback: Callable | None = None,
            permanent: bool = False,
            stickToLabel: bool = False,
    ) -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        button.setProperty(PERMANENT_PROPERTY, "true" if permanent else "")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAutoRaise(True)
        button.setMaximumHeight(20)
        self.buttons.append(button)

        if callback is not None:
            button.clicked.connect(callback)

        layout: QHBoxLayout = self.layout()
        insertionIndex = layout.indexOf(self.spacerItem)
        if not stickToLabel:
            insertionIndex += 1
        layout.insertWidget(insertionIndex, button)

        return button

    def clearButtons(self):
        for i in range(len(self.buttons) - 1, -1, -1):
            button = self.buttons[i]
            if not button.property(PERMANENT_PROPERTY):
                button.hide()
                button.deleteLater()
                del self.buttons[i]

    @DisableWidgetUpdatesContext.methodDecorator
    def setContext(
            self,
            locator: NavLocator,
            commitMessage: str = "",
            isStash=False,
    ):
        self.clearButtons()

        self.locator = locator

        fromCommitId = locator.comparedCommit()

        introStyle = "font-weight: 500;"
        mainText = " "

        if fromCommitId is not None:
            mainText = (
                "<span style='{introStyle}'>{intro}{colon}</span> "
                "<span style='color: {red}; font-weight: bold;'>A: </span> {a} \u2192 "
                "<span style='color: {blue}; font-weight: bold;'>B: </span> {b}"
            ).format(introStyle=introStyle, intro=_("Comparing commits"), colon=_(":"),
                     red=colors.red.name(), blue=colors.blue.name(),
                     a=shortHash(fromCommitId), b=shortHash(locator.commit))

            swapButton = self.addButton(
                _("Swap A/B"),
                lambda: Jump.invoke(self, locator.swapComparison()),
                stickToLabel=True)

            swapButton.setToolTip(_("Swap the “old” and “new” sides in the commit comparison"))

        elif locator.selectedCommits:
            pass

        elif locator.context == NavContext.COMMITTED:
            kind = _p("noun", "Stash") if isStash else _p("noun", "Commit")
            summary, _continued = messageSummary(commitMessage)
            mainText = "<span style='{introStyle}'>{intro} {hash}{colon}</span> {summary}".format(
                introStyle=introStyle, intro=kind, hash=shortHash(locator.commit), colon=_(":"), summary=escape(summary))

            infoButton = self.addButton(_("Info"), lambda: GetCommitInfo.invoke(self, self.locator.commit))
            infoButton.setToolTip(_("Show details about this commit") if not isStash
                                  else _("Show details about this stash"))

            if isStash:
                dropButton = self.addButton(_("Delete"), lambda: DropStash.invoke(self, locator.commit))
                dropButton.setToolTip(_("Delete this stash"))

                applyButton = self.addButton(_("Apply"), lambda: ApplyStash.invoke(self, locator.commit))
                applyButton.setToolTip(_("Apply this stash"))

        elif locator.context.isWorkdir():
            mainText = _("Working Directory")

        self.mainLabel.setText(mainText)
