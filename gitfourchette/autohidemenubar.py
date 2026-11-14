# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import weakref

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.qt import *


class AutoHideMenuBar(QObject):
    def __init__(self, menuBar: QMenuBar):
        super().__init__(menuBar)

        self.setObjectName("AutoHideMenuBar")

        self.menuBar = menuBar
        self.defaultMaximumHeight = self.menuBar.maximumHeight()
        self.sticky = False

        self.hideScheduler = QTimer(self)
        self.hideScheduler.setInterval(0)
        self.hideScheduler.setSingleShot(True)
        self.hideScheduler.timeout.connect(self.doScheduledHide)

        self.menusConnected: list[weakref.ReferenceType[QMenu]] = []

        GFApplication.instance().prefsChanged.connect(self.refreshPrefs)
        self.refreshPrefs()

    def refreshPrefs(self):
        self.hideScheduler.stop()

        # Show the menu bar if auto-hide is turned off, OR if the sticky bit
        # was set as the prefs were reset. That way, if our specific setting
        # wasn't updated, the menu bar will stay put.
        self.showMenuBar(not self.enabled or self.sticky)

        # Reinstall signal connections regardless.
        self.reconnectToMenus()

        # Reset sticky bit if auto-hide is turned off, so that the menubar
        # gets hidden right away next time auto-hide is reenabled.
        if not self.enabled:
            self.sticky = False

    def reconnectToMenus(self):
        connect = self.enabled
        newConnections = []

        menu: QMenu
        for menu in self.menuBar.findChildren(QMenu, options=Qt.FindChildOption.FindDirectChildrenOnly):
            menuRef = weakref.ref(menu)
            wasConnected = menuRef in self.menusConnected

            if connect:
                if not wasConnected:
                    menu.aboutToShow.connect(self.onMenuAboutToShow)
                    menu.aboutToHide.connect(self.onMenuAboutToHide)
                newConnections.append(menuRef)
            elif wasConnected:
                menu.aboutToShow.disconnect(self.onMenuAboutToShow)
                menu.aboutToHide.disconnect(self.onMenuAboutToHide)

        self.menusConnected = newConnections

    @property
    def enabled(self):
        return not settings.prefs.showMenuBar

    @property
    def isHidden(self):
        return self.menuBar.maximumHeight() == 0

    def showMenuBar(self, show):
        if show:
            self.menuBar.setMaximumHeight(self.defaultMaximumHeight)
        else:
            self.menuBar.setMaximumHeight(0)

    def toggle(self):
        assert self.enabled, "did you forget to disconnect AutoHideMenuBar signals?"
        self.sticky = True
        self.showMenuBar(self.isHidden)

    def onMenuAboutToShow(self):
        assert self.enabled, "did you forget to disconnect AutoHideMenuBar signals?"
        self.hideScheduler.stop()
        if self.isHidden:
            self.showMenuBar(True)
            self.sticky = False

    def onMenuAboutToHide(self):
        assert self.enabled, "did you forget to disconnect AutoHideMenuBar signals?"
        self.hideScheduler.start()

    def doScheduledHide(self):
        assert self.enabled, "did you forget to disconnect AutoHideMenuBar signals?"
        if not self.isHidden and not self.sticky:
            self.showMenuBar(False)
