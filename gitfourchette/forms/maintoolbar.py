# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from contextlib import suppress

from gitfourchette import settings
from gitfourchette import tasks
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.repowidget import RepoWidget
from gitfourchette.tasks import TaskBook
from gitfourchette.toolbox import *


class MainToolBar(QToolBar):
    openDialog = Signal()
    openPrefs = Signal()
    reveal = Signal()
    openTerminal = Signal()
    pull = Signal()
    push = Signal()

    observed: RepoWidget | None

    backAction: QAction
    forwardAction: QAction
    recentAction: QAction

    def __init__(self, parent: QWidget):
        super().__init__(englishTitleCase(_("Show toolbar")), parent)

        self.observed = None

        self.setObjectName("GFToolbar")
        self.setMovable(False)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.onCustomContextMenuRequested)

        self.visibilityChanged.connect(self.onVisibilityChanged)
        self.toolButtonStyleChanged.connect(self.onToolButtonStyleChanged)
        self.iconSizeChanged.connect(self.onIconSizeChanged)

        self.backAction = TaskBook.toolbarAction(self, tasks.JumpBack).toQAction(self)
        self.forwardAction = TaskBook.toolbarAction(self, tasks.JumpForward).toQAction(self)

        self.workdirAction = TaskBook.toolbarAction(self, tasks.JumpToUncommittedChanges).toQAction(self)
        self.headAction = TaskBook.toolbarAction(self, tasks.JumpToHEAD).toQAction(self)

        self.recentAction = ActionDef(
            _("Open…"), self.openDialog, icon="git-folder",
            shortcuts=QKeySequence.StandardKey.Open,
            tip=_("Open a Git repo on your machine")
        ).toQAction(self)

        defs = [
            self.backAction,
            self.forwardAction,
            self.workdirAction,
            self.headAction,
            ActionDef.SEPARATOR,

            TaskBook.toolbarAction(self, tasks.NewStash),
            TaskBook.toolbarAction(self, tasks.NewBranchFromHead),
            ActionDef.SEPARATOR,
            TaskBook.toolbarAction(self, tasks.FetchRemotes),
            TaskBook.toolbarAction(self, tasks.PullBranch),
            TaskBook.toolbarAction(self, tasks.PushBranch),
            ActionDef.SPACER,

            ActionDef(_("Terminal"), self.openTerminal, icon="terminal",
                      shortcuts=GlobalShortcuts.openTerminal,
                      tip=_("Open a terminal in the repo")),

            ActionDef(_("Reveal"), self.reveal, icon="reveal",
                      shortcuts=GlobalShortcuts.openRepoFolder,
                      tip=_("Open repo folder in file manager")),

            self.recentAction,

            ActionDef.SEPARATOR,

            ActionDef(_("Settings"), self.openPrefs, icon="git-settings",
                      shortcuts=QKeySequence.StandardKey.Preferences,
                      tip=_("Configure {app}", app=qAppName())),
        ]
        ActionDef.addToQToolBar(self, *defs)

        self.recentAction.setIconVisibleInMenu(True)
        recentButton = self.widgetForAction(self.recentAction)
        assert isinstance(recentButton, QToolButton)
        recentButton.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)

        self.setToolButtonStyle(settings.prefs.toolBarButtonStyle)
        self.setIconSize(QSize(settings.prefs.toolBarIconSize, settings.prefs.toolBarIconSize))

        self.updateNavButtons()

    def setToolButtonStyle(self, style: Qt.ToolButtonStyle):
        # Resolve style
        if style == Qt.ToolButtonStyle.ToolButtonFollowStyle:
            styleHint = QApplication.style().styleHint(QStyle.StyleHint.SH_ToolButtonStyle)
            style = Qt.ToolButtonStyle(styleHint)

        super().setToolButtonStyle(style)

        # Hide back/forward button text with ToolButtonTextBesideIcon
        if style != Qt.ToolButtonStyle.ToolButtonTextOnly:
            for navAction in (self.backAction, self.forwardAction):
                navButton: QToolButton = self.widgetForAction(navAction)
                navButton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

    def onCustomContextMenuRequested(self, localPoint: QPoint):
        globalPoint = self.mapToGlobal(localPoint)

        def textPositionAction(name, style):
            return ActionDef(name,
                             callback=lambda: self.setToolButtonStyle(style),
                             checkState=1 if self.toolButtonStyle() == style else -1,
                             radioGroup="TextPosition")

        def iconSizeAction(name, size):
            return ActionDef(name,
                             callback=lambda: self.setIconSize(QSize(size, size)),
                             checkState=1 if self.iconSize().width() == size else -1,
                             radioGroup="IconSize")

        menu = ActionDef.makeQMenu(self, [
            self.toggleViewAction(),

            ActionDef.SEPARATOR,

            ActionDef(
                _("Text Position"),
                submenu=[
                    textPositionAction(_("Icons Only"), Qt.ToolButtonStyle.ToolButtonIconOnly),
                    textPositionAction(_("Text Only"), Qt.ToolButtonStyle.ToolButtonTextOnly),
                    textPositionAction(_("Text Alongside Icons"), Qt.ToolButtonStyle.ToolButtonTextBesideIcon),
                    textPositionAction(_("Text Under Icons"), Qt.ToolButtonStyle.ToolButtonTextUnderIcon),
                ]
            ),

            ActionDef(
                _("Icon Size"),
                submenu=[
                    iconSizeAction(_("Small"), 16),
                    iconSizeAction(_("Medium"), 20),
                    iconSizeAction(_("Large"), 24),
                    iconSizeAction(_("Huge"), 32),
                ]
            ),
        ])

        menu.exec(globalPoint)

    def onVisibilityChanged(self, visible: bool):
        # self.window().setUnifiedTitleAndToolBarOnMac(visible)
        if visible == settings.prefs.showToolBar:
            return
        settings.prefs.showToolBar = visible
        settings.prefs.setDirty()

    def onToolButtonStyleChanged(self, style: Qt.ToolButtonStyle):
        if style == settings.prefs.toolBarButtonStyle:
            return
        settings.prefs.toolBarButtonStyle = style
        settings.prefs.setDirty()

    def onIconSizeChanged(self, size: QSize):
        w = size.width()
        if w == settings.prefs.toolBarIconSize:
            return
        settings.prefs.toolBarIconSize = w
        settings.prefs.setDirty()

    def observeRepoWidget(self, rw: RepoWidget | None):
        if rw is self.observed:
            return

        if self.observed is not None:
            with suppress(RuntimeError, TypeError):
                self.observed.historyChanged.disconnect(self.updateNavButtons)

        self.observed = rw

        if rw is not None:
            rw.historyChanged.connect(self.updateNavButtons)

        self.updateNavButtons()

    def updateNavButtons(self):
        rw = self.observed
        if rw is None:
            self.backAction.setEnabled(False)
            self.forwardAction.setEnabled(False)
        else:
            self.backAction.setEnabled(rw.navHistory.canGoBack())
            self.forwardAction.setEnabled(rw.navHistory.canGoForward())
