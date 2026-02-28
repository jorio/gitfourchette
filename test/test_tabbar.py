# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.repostub import RepoStub
from gitfourchette.repowidget import RepoWidget
from gitfourchette.settings import TabBarClick
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
    from gitfourchette import settings

    wd = unpackRepo(tempDir)
    settings.history.setRepoNickname(wd, "ridiculously_long_" * 16)

    mainWindow.resize(640, 480)  # make sure it's narrow enough for overflow

    mainWindow.openRepo(wd)
    QTest.qWait(1)
    assert not mainWindow.tabs.overflowButton.isVisible()

    mainWindow.onAcceptPrefsDialog({"autoHideTabs": True})
    QTest.qWait(1)
    assert not mainWindow.tabs.overflowButton.isVisible()


@pytest.mark.parametrize("click", ["middle", "double"])
@pytest.mark.parametrize("action", TabBarClick)
def testTabSpecialClick(tempDir, mainWindow, click, action):
    mainWindow.onAcceptPrefsDialog({f"{click}ClickTabBar": action})

    if action == "terminal":
        editorPath = getTestDataPath("editor-shim.py")
        scratchPath = f"{tempDir.name}/scratch file.txt"
        mainWindow.onAcceptPrefsDialog({"terminal": f'"{editorPath}" "{scratchPath}" "hello world" $COMMAND'})

    wd0 = unpackRepo(tempDir, renameTo="repo0")
    wd1 = unpackRepo(tempDir, renameTo="repo1")

    mainWindow._openRepo(wd0, foreground=True)  # RepoWidget
    mainWindow._openRepo(wd1, foreground=False)  # RepoStub
    assert isinstance(mainWindow.tabs.widget(0), RepoWidget)
    assert isinstance(mainWindow.tabs.widget(1), RepoStub)

    tabBar = mainWindow.tabs.tabs
    assert tabBar.count() == 2

    for tabIndex in range(tabBar.count() - 1, -1, -1):
        tab = mainWindow.tabs.widget(tabIndex)
        pos = tabBar.tabRect(tabIndex).center()
        wd = tab.workdir

        with MockDesktopServicesContext() as services:
            mouseSpecialClick(tabBar, click, pos=pos)
            QTest.qWait(0)

        assert bool(services.urls) == (action == "folder")

        if action == TabBarClick.Nothing:
            pass
        elif action == TabBarClick.Close:
            assert not any(Path(wd).samefile(tab.workdir) for tab in mainWindow.tabs.widgets())
        elif action == TabBarClick.Folder:
            assert Path(wd).samefile(services.lastUrlAsLocalFile())
        elif action == TabBarClick.Terminal:
            scratchText = readTextFile(scratchPath, timeout=30000, unlink=True)
            assert "hello world" in scratchText
            assert "terminal" in scratchText
        else:
            raise NotImplementedError(f"unknown action {action}")

    assert tabBar.count() == (0 if action == "close" else 2)
