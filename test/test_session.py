# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Test events scheduled at the start of a session. ("Session" here loosely means
a start/stop cycle.)
"""

import json
import os.path
from collections import defaultdict
from typing import ClassVar

from gitfourchette.application import GFApplication
from gitfourchette.forms.aboutdialog import AboutDialog
from gitfourchette.forms.donateprompt import DonatePrompt
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.forms.whatsnewbutton import WhatsNewButton
from gitfourchette.mainwindow import MainWindow
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from .util import *


class SessionContext:
    sessionCounter: ClassVar[dict[str, int]] = defaultdict(lambda: 0)

    def __init__(self, end=True, commandLinePaths: None | list[str] = None):
        self.tearDown = end
        self.commandLinePaths = commandLinePaths

    def __enter__(self) -> MainWindow:
        key = os.environ.get("PYTEST_CURRENT_TEST")
        count = SessionContext.sessionCounter[key]
        SessionContext.sessionCounter[key] += 1

        app = GFApplication.instance()
        if self.commandLinePaths:
            app.commandLinePaths = self.commandLinePaths[:]
        if app.mainWindow is None:
            app.beginSession()
            QTest.qWait(0)
        window = app.mainWindow
        assert window is not None
        window.setWindowTitle(f"({self.__class__.__name__}#{count})")
        return window

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.tearDown:
            return
        # Essentially a condensed version of the mainWindow fixture's cleanup code.
        app = GFApplication.instance()
        app.mainWindow.close()
        app.mainWindow.deleteLater()
        waitUntilTrue(lambda: not app.mainWindow)
        app.endSession(clearTempDir=False)
        assert app.mainWindow is None


@pytest.mark.skipif(WINDOWS, reason="TODO: Try again on Windows with https://github.com/jorio/gitfourchette/pull/160")
def testRestoreSession(tempDir, mainWindow):
    # ----------------------------------------------
    # Session 1

    with SessionContext() as window:
        for i in range(10):
            wd = unpackRepo(tempDir, renameTo=f"RepoCopy{i:04}")
            window.openRepo(wd)
            QTest.qWait(1)

        assert window.tabs.count() == 10
        window.tabs.setCurrentIndex(5)

        rw = window.currentRepoWidget()
        assert rw.repo.repo_name() == "RepoCopy0005"

        # Collapse something in sidebar
        originNode = rw.sidebar.findNodeByKind(SidebarItem.Remote)
        originIndex = rw.sidebar.nodeToFilterIndex(originNode)
        assert rw.sidebar.isExpanded(originIndex)
        rw.sidebar.collapse(originIndex)
        assert not rw.sidebar.isExpanded(originIndex)

        # Hide something in sidebar
        rw.toggleHideRefPattern("refs/heads/no-parent")

        # Set repo nickname
        triggerMenuAction(window.menuBar(), "repo/rename")
        tid = findQDialog(window, "nickname", t=TextInputDialog)
        tid.lineEdit.setText("Nickname0005")
        tid.accept()

    # ----------------------------------------------
    # Make one of the repos inaccessible

    shutil.rmtree(f"{tempDir.name}/RepoCopy0003")

    # ----------------------------------------------
    # Session 2

    with SessionContext(end=False) as window:
        # We've lost one of the repos
        acceptQMessageBox(window, r"session could.?n.t be restored.+RepoCopy0003")
        assert window.tabs.count() == 9

        # Should restore to same tab
        rw = window.currentRepoWidget()
        assert rw.repo.repo_name() == "RepoCopy0005"

        # Make sure origin node is still collapsed
        originNode = rw.sidebar.findNodeByKind(SidebarItem.Remote)
        originIndex = rw.sidebar.nodeToFilterIndex(originNode)
        assert not rw.sidebar.isExpanded(originIndex)

        # Make sure hidden branch is still hidden
        hiddenBranchNode = rw.sidebar.findNodeByRef("refs/heads/no-parent")
        assert rw.sidebar.sidebarModel.isExplicitlyHidden(hiddenBranchNode)

        # Make sure nickname still set
        assert window.tabs.tabs.tabText(window.tabs.currentIndex()) == "Nickname0005"


def testCommandLinePaths(tempDir, mainWindow):
    # End default unit test session so we can start a new one with fake command line paths
    with SessionContext():
        pass

    wd1 = unpackRepo(tempDir, renameTo="wd1")
    wd2 = unpackRepo(tempDir, renameTo="wd2")

    GFApplication.instance().commandLinePaths = [
        wd1 + "/c/c1.txt",  # Any file within the repo should work
        wd2,
        wd1,  # Should count as duplicate of the first tab
    ]

    with SessionContext(end=False) as window:
        # Check that we opened the correct repos
        assert window.tabs.count() == 2  # Two distinct repos were opened
        assert window.tabs.currentIndex() == 0  # The last path that was passed was within the first repo
        assert window.tabs.widget(0).workdir == os.path.realpath(wd1)
        assert window.tabs.widget(1).workdir == os.path.realpath(wd2)


def testDonatePrompt(mainWindow):
    from gitfourchette import settings

    now = QDateTime.currentDateTime().toSecsSinceEpoch()
    secondsInADay = 60 * 60 * 24

    def daysToNextPrompt() -> int:
        return (settings.prefs.donatePrompt - now) // secondsInADay

    def schedulePromptInThePast():
        settings.prefs.donatePrompt = now - 1
        settings.prefs.write(True)

    # Launch many sessions in the same day - Donate prompt mustn't show up
    for _dummy in range(15):
        # Don't schedule the prompt before hitting 10 launches
        assert 0 == settings.prefs.donatePrompt

        with SessionContext() as window:
            assert not window.findChild(DonatePrompt)

    # 15th launch should schedule donate prompt to appear in 60 days
    assert 59 <= daysToNextPrompt() <= 61

    # Force prompt to appear at the next launch for this test
    schedulePromptInThePast()

    # Make a bogus session. A dialog is vying for our attention so the donate prompt shouldn't get in the way
    bogusSesh = settings.Session()
    bogusSesh.tabs = [qTempDir() + "/---this-path-should-not-exist---"]
    bogusSesh.write(True)
    with SessionContext() as window:
        acceptQMessageBox(window, "session couldn.t be restored")
        assert not window.findChild(DonatePrompt)

    # Intercept prompt and click "never show again"
    with SessionContext() as window:
        donate: DonatePrompt = window.findChild(DonatePrompt)
        donate.ui.byeButton.click()
    with SessionContext() as window:
        assert not window.findChild(DonatePrompt)
        assert settings.prefs.donatePrompt < 0  # permanently disabled

    # Force prompt to appear at the next launch again
    schedulePromptInThePast()

    # Intercept prompt and click "remind me in 3 months"
    with SessionContext() as window:
        donate: DonatePrompt = window.findChild(DonatePrompt)
        donate.ui.postponeButton.click()
    assert 89 <= daysToNextPrompt() <= 91

    # Force prompt to appear at the next launch again
    schedulePromptInThePast()

    # Intercept prompt and click "donate"
    with SessionContext() as window, MockDesktopServicesContext() as services:
        assert not services.urls
        donate: DonatePrompt = window.findChild(DonatePrompt)
        donate.ui.donateButton.click()
        QTest.qWait(1500)
        assert len(services.urls) == 1
        assert services.urls[0].toString() == "https://ko-fi.com/jorio"

    # Prompt must not show up again
    with SessionContext(end=False) as window:
        assert not window.findChild(DonatePrompt)
        assert settings.prefs.donatePrompt < 0  # permanently disabled


def testWhatsNewNotificationAfterUpgrade(mainWindow):
    from gitfourchette import settings

    # One bogus session just to get any pref writing out of the way
    with SessionContext() as window:
        assert not window.statusBar().findChild(WhatsNewButton)
        settings.prefs.maxCommits += 1
        settings.prefs.setDirty()

    def setPreviousVersion(version="1.10.0"):
        pathStr = settings.history._getFullPath(False)
        assert pathStr
        path = Path(pathStr)
        jsonObj = json.loads(path.read_text(encoding="utf-8"))
        assert jsonObj["_version"] == APP_VERSION
        jsonObj["_version"] = version
        path.write_text(json.dumps(jsonObj), encoding="utf-8")

    # -------------------------------------------------------------------------
    # Notification must show up at most once after an upgrade

    setPreviousVersion()

    with SessionContext() as window:
        whatsNewButton = window.statusBar().findChild(WhatsNewButton)
        assert whatsNewButton.isVisible()
        assert findTextInWidget(whatsNewButton, rf"updated to v{APP_VERSION}")
    with SessionContext() as window:
        assert not window.statusBar().findChild(WhatsNewButton)

    # -------------------------------------------------------------------------
    # Test Changelog

    setPreviousVersion()

    with SessionContext() as window:
        whatsNewButton = window.statusBar().findChild(WhatsNewButton)
        triggerMenuAction(whatsNewButton.menu(), rf"what.s new in v{APP_VERSION}")
        aboutDialog = findQDialog(window, "About", t=AboutDialog)
        tabs = aboutDialog.ui.tabWidget
        assert tabs.tabText(tabs.currentIndex()) == "News"
        assert findTextInWidget(tabs.currentWidget().findChild(QLabel), "first public release")
        aboutDialog.accept()
        QTest.qWait(0)

        # Dismiss it
        whatsNewButton = window.statusBar().findChild(WhatsNewButton)
        triggerMenuAction(whatsNewButton.menu(), r"dismiss")
        QTest.qWait(0)
        assert not window.statusBar().findChild(WhatsNewButton)

    with SessionContext() as window:
        assert not window.statusBar().findChild(WhatsNewButton)

    # -------------------------------------------------------------------------
    # Test "Don't show again"

    setPreviousVersion()

    with SessionContext(end=False) as window:
        whatsNewButton = window.statusBar().findChild(WhatsNewButton)
        triggerMenuAction(whatsNewButton.menu(), r"show.+next update")
        triggerMenuAction(whatsNewButton.menu(), r"dismiss")
        QTest.qWait(0)
        assert not window.statusBar().findChild(WhatsNewButton)

    with SessionContext() as window:
        assert not window.statusBar().findChild(WhatsNewButton)

    setPreviousVersion()

    with SessionContext() as window:
        assert not window.statusBar().findChild(WhatsNewButton)

    # -------------------------------------------------------------------------
    # One bogus session to let mainWindow fixture clean up

    with SessionContext(end=False):
        pass
