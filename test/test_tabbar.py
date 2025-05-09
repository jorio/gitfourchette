# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os.path

from .util import *


def testTabOverflow(tempDir, mainWindow):
    numRepos = 10
    tabWidget = mainWindow.tabs
    tabBar = mainWindow.tabs.tabs

    for i in range(numRepos):
        wd = unpackRepo(tempDir, renameTo=f"RepoCopy{i:04}")
        mainWindow.openRepo(wd)
        QTest.qWait(1)

        if i <= 2:  # assume no overflow when there are few repos
            assert not tabWidget.overflowGradient.isVisible()
            assert not tabWidget.overflowButton.isVisible()

    mainWindow.resize(640, 480)  # make sure it's narrow enough for overflow
    QTest.qWait(1)

    assert tabWidget.currentIndex() == numRepos - 1
    assert tabWidget.overflowGradient.isVisible()
    assert tabWidget.overflowButton.isVisible()

    # Scroll
    assert not tabBar.visibleRegion().contains(tabBar.tabRect(0))
    assert tabBar.visibleRegion().contains(tabBar.tabRect(numRepos-1))
    for _dummy in range(16):
        postMouseWheelEvent(tabBar, 120)
        QTest.qWait(0)
    assert tabBar.visibleRegion().contains(tabBar.tabRect(0))
    assert not tabBar.visibleRegion().contains(tabBar.tabRect(numRepos-1))

    # Test overflow menu
    mainWindow.tabs.overflowButton.click()
    menu: QMenu = mainWindow.findChild(QMenu, "QTW2OverflowMenu")
    triggerMenuAction(menu, "RepoCopy0002")
    menu.close()
    assert mainWindow.tabs.currentIndex() == 2


def testTabOverflowSingleTab(tempDir, mainWindow):
    mainWindow.resize(640, 480)  # make sure it's narrow enough for overflow

    # Don't set a super long name for Windows (max path length restriction)
    wd = unpackRepo(tempDir, renameTo="W" * 128)
    mainWindow.openRepo(wd)
    QTest.qWait(1)
    assert not mainWindow.tabs.overflowButton.isVisible()

    mainWindow.onAcceptPrefsDialog({"autoHideTabs": True})
    QTest.qWait(1)
    assert not mainWindow.tabs.overflowButton.isVisible()


def testMiddleClickToCloseTab(tempDir, mainWindow, mockDesktopServices):
    wd0 = unpackRepo(tempDir, renameTo="repo0")
    wd1 = unpackRepo(tempDir, renameTo="repo1")

    mainWindow.openRepo(wd0)
    mainWindow.openRepo(wd1)
    QTest.qWait(1)
    assert mainWindow.tabs.count() == 2

    for _dummy in range(2):
        tabBar = mainWindow.tabs.tabs
        tabRect = tabBar.tabRect(0)
        QTest.mouseClick(tabBar, Qt.MouseButton.MiddleButton, pos=tabRect.center())
        QTest.qWait(0)

    assert mainWindow.tabs.count() == 0


def testDoubleClickTabOpensWorkdir(tempDir, mainWindow, mockDesktopServices):
    wd0 = unpackRepo(tempDir, renameTo="repo0")
    wd1 = unpackRepo(tempDir, renameTo="repo1")

    mainWindow.openRepo(wd0)
    mainWindow.openRepo(wd1)
    assert mainWindow.tabs.count() == 2

    for tabIndex, wd in enumerate([wd0, wd1]):
        wd = os.path.realpath(wd)

        tabBar = mainWindow.tabs.tabs
        tabRect = tabBar.tabRect(tabIndex)

        QTest.mouseDClick(tabBar, Qt.MouseButton.LeftButton, pos=tabRect.center())
        QTest.mouseRelease(tabBar, Qt.MouseButton.LeftButton, pos=tabRect.center())
        QTest.qWait(0)
        assert mockDesktopServices.urls[-1] == QUrl.fromLocalFile(wd)
