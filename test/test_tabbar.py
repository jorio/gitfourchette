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

    GFApplication.applyPrefs(autoHideTabs=True)
    QTest.qWait(1)
    assert not mainWindow.tabs.overflowButton.isVisible()


@pytest.mark.parametrize("click", ["middle", "double"])
@pytest.mark.parametrize("action", TabBarClick)
def testTabSpecialClick(tempDir, mainWindow, click, action):
    GFApplication.applyPrefs(**{f"{click}ClickTabBar": action})

    if action == "terminal":
        editorPath = getTestDataPath("editor-shim.py")
        scratchPath = f"{tempDir.name}/scratch file.txt"
        GFApplication.applyPrefs(terminal=f'"{editorPath}" "{scratchPath}" "hello world" $COMMAND')

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
            waitForFile(scratchPath)
            scratchText = readTextFile(scratchPath, unlink=True)
            assert "hello world" in scratchText
            assert "terminal" in scratchText
        else:
            raise NotImplementedError(f"unknown action {action}")

    assert tabBar.count() == (0 if action == "close" else 2)


def testBackgroundTabRequestsAttention(tempDir, mainWindow):
    from gitfourchette.tasks import SwitchBranch
    from gitfourchette.toolbox.qtabwidget2 import QTabWidget2

    wd0 = unpackRepo(tempDir, renameTo="repo0")
    wd1 = unpackRepo(tempDir, renameTo="repo1")

    rw0 = mainWindow.openRepo(wd0)
    rw1 = mainWindow.openRepo(wd1)
    assert isinstance(rw0, RepoWidget)
    assert isinstance(rw1, RepoWidget)

    tabWidget = mainWindow.tabs
    tabBar = tabWidget.tabs
    assert tabWidget.currentIndex() == 1
    assert not rw0.isVisible()
    assert tabBar.tabIcon(0).isNull()
    assert not rw0.property(QTabWidget2.UrgentPropertyName)

    # Start a task that needs a dialog in the background tab.
    # The dialog can't be shown until the tab comes to the foreground,
    # so the background tab should request the user's attention.
    SwitchBranch.invoke(rw0, "no-parent")
    assert rw0.taskRunner.isBusy()
    assert rw0.property(QTabWidget2.UrgentPropertyName) == "true"
    assert not tabBar.tabIcon(0).isNull()
    assert tabBar.tabIcon(1).isNull()
    assert not any(dlg.isVisible() for dlg in rw0.findChildren(QDialog))

    # Requesting attention again for an urgent tab is a no-op
    tabWidget.requestAttention(0)
    assert rw0.property(QTabWidget2.UrgentPropertyName) == "true"

    # The current tab can't request attention
    tabWidget.requestAttention(1)
    assert not rw1.property(QTabWidget2.UrgentPropertyName)
    assert tabBar.tabIcon(1).isNull()

    # Out-of-bounds index is ignored
    tabWidget.requestAttention(2)

    # Bring the background tab to the foreground: urgent flag should go away
    # and the task should resume, showing its dialog.
    tabWidget.setCurrentIndex(0)
    assert not rw0.property(QTabWidget2.UrgentPropertyName)
    assert tabBar.tabIcon(0).isNull()

    rejectQMessageBox(rw0, "switch to.+no-parent")
    waitUntilTrue(lambda: not rw0.taskRunner.isBusy())
    assert rw0.repo.head_branch_shorthand == "master"


def testUnloadOtherTabs(tempDir, mainWindow):
    numRepos = 3
    for i in range(numRepos):
        wd = unpackRepo(tempDir, renameTo=f"repo{i}")
        mainWindow.openRepo(wd)

    tabWidget = mainWindow.tabs
    tabBar = tabWidget.tabs
    assert tabWidget.count() == numRepos
    assert all(isinstance(w, RepoWidget) for w in tabWidget.widgets())
    keptWidget = tabWidget.widget(1)
    keptWorkdir = keptWidget.workdir

    def getMenu(tabIndex: int) -> QMenu:
        return summonContextMenu(tabBar, tabBar.tabRect(tabIndex).center())

    menu = getMenu(1)
    assert findMenuAction(menu, "unload other tabs").isEnabled()
    triggerMenuAction(menu, "unload other tabs")
    menu.close()

    # The tab whose context menu we summoned should become current and remain loaded
    assert tabWidget.count() == numRepos
    assert tabWidget.currentIndex() == 1
    assert tabWidget.widget(1) is keptWidget
    assert isinstance(keptWidget, RepoWidget)
    assert keptWidget.workdir == keptWorkdir

    # The other tabs should be unloaded
    for i in [0, 2]:
        stub = tabWidget.widget(i)
        assert isinstance(stub, RepoStub)
        assert Path(stub.workdir).name == f"repo{i}"

    assert findTextInWidget(mainWindow.statusBar2, "2 background tabs unloaded")

    # There are no other loaded tabs now
    menu = getMenu(1)
    assert not findMenuAction(menu, "unload other tabs").isEnabled()
    menu.close()

    # Unloaded tabs shouldn't reload by themselves when they're brought to the foreground
    tabWidget.setCurrentIndex(0)
    QTest.qWait(1)
    stub = tabWidget.widget(0)
    assert isinstance(stub, RepoStub)
    assert stub.ui.promptPage.isVisible()

    # Load it back manually
    stub.ui.promptLoadButton.click()
    rw = waitForRepoWidget(mainWindow)
    assert Path(rw.workdir).name == "repo0"
