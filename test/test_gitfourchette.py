# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os.path
from contextlib import suppress

import pytest
from pytestqt.qtbot import QtBot

from gitfourchette.forms.processdialog import ProcessDialog
from gitfourchette.gitdriver import GitDriver
from .util import *

from gitfourchette.application import GFApplication
from gitfourchette.forms.aboutdialog import AboutDialog
from gitfourchette.forms.commitdialog import CommitDialog
from gitfourchette.forms.donateprompt import DonatePrompt
from gitfourchette.forms.reposettingsdialog import RepoSettingsDialog
from gitfourchette.forms.repostub import RepoStub
from gitfourchette.graphview.commitlogmodel import SpecialRow
from gitfourchette.mainwindow import MainWindow
from gitfourchette.nav import NavLocator, NavContext
from gitfourchette.settings import Session
from gitfourchette.sidebar.sidebarmodel import SidebarItem


def bringUpRepoSettings(rw):
    node = rw.sidebar.findNodeByKind(SidebarItem.WorkdirHeader)
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "repo.+settings")
    dlg: RepoSettingsDialog = findQDialog(rw, "repo.+settings")
    return dlg


def testEmptyRepo(tempDir, mainWindow):
    wd = unpackRepo(tempDir, "TestEmptyRepository")
    assert mainWindow.openRepo(wd)
    assert mainWindow.tabs.count() == 1
    mainWindow.closeCurrentTab()  # mustn't crash
    assert mainWindow.tabs.count() == 0


def testChangedFilesShownAtStart(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    touchFile(F"{wd}/SomeNewFile.txt")
    rw = mainWindow.openRepo(wd)

    assert rw.graphView.model().rowCount() > 5
    assert rw.dirtyFiles.isVisibleTo(rw)
    assert rw.stagedFiles.isVisibleTo(rw)
    assert not rw.committedFiles.isVisibleTo(rw)
    assert qlvGetRowData(rw.dirtyFiles) == ["SomeNewFile.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []


def testDisplayAllNestedUntrackedFiles(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    os.mkdir(F"{wd}/N")
    touchFile(F"{wd}/N/tata.txt")
    touchFile(F"{wd}/N/toto.txt")
    touchFile(F"{wd}/N/tutu.txt")
    rw = mainWindow.openRepo(wd)
    assert qlvGetRowData(rw.dirtyFiles) == ["N/tata.txt", "N/toto.txt", "N/tutu.txt"]
    assert qlvGetRowData(rw.stagedFiles) == []


@pytest.mark.skipif(WINDOWS, reason="Windows blocks external processes from touching the repo while we have a handle on it")
def testUnloadRepoWhenFolderGoesMissing(tempDir, mainWindow, qtbot: QtBot):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    rw.repoModel.prefs.draftCommitMessage = "some bogus change to prevent prefs to be written"
    rw.repoModel.prefs.write(force=True)
    assert os.path.isfile(f"{wd}/.git/{APP_SYSTEM_NAME}.json")

    oldName = os.path.normpath(wd)
    newName = oldName + "-2"
    os.rename(oldName, newName)

    rw.refreshRepo()
    assert not rw.isVisible()

    stub: RepoStub = mainWindow.tabs.currentWidget()
    assert isinstance(stub, RepoStub)
    assert stub.ui.promptPage.isVisible()
    assert re.search(r"folder.+missing", stub.ui.promptReadyLabel.text(), re.I)

    # Make sure we're not writing the prefs to a ghost directory structure upon exiting
    assert not os.path.isfile(f"{wd}/.git/{APP_SYSTEM_NAME}.json")

    # Try to reload - this causes a GitError.
    # Normally, RepoTaskRunner re-raises the exception, causing qtbot to fail the unit test.
    # In this specific case, don't let qtbot fail the test because of it.
    with qtbot.captureExceptions() as uncaughtExceptions:
        stub.ui.promptLoadButton.click()
        assert len(uncaughtExceptions) == 1
        assert "repository not found" in str(uncaughtExceptions[0]).lower()
        rejectQMessageBox(mainWindow, "repository not found")
    assert stub.ui.promptPage.isVisible()  # RepoStub still visible

    # Move back then try to reload
    os.rename(newName, oldName)
    stub.ui.promptLoadButton.click()
    assert not stub.isVisible()
    rw = mainWindow.currentRepoWidget()
    assert os.path.samefile(wd, rw.workdir)


def testNewRepo(tempDir, mainWindow):
    triggerMenuAction(mainWindow.menuBar(), "file/new repo")

    path = os.path.realpath(tempDir.name + "/valoche3000")
    os.makedirs(path)

    acceptQFileDialog(mainWindow, "new repo", path)

    rw = mainWindow.currentRepoWidget()
    assert path == os.path.normpath(rw.repo.workdir)

    assert rw.navLocator.context.isWorkdir()

    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.LocalBranch)
    unbornNode = rw.sidebar.findNodeByKind(SidebarItem.UnbornHead)
    unbornNodeIndex = unbornNode.createIndex(rw.sidebar.sidebarModel)
    assert re.search(r"branch.+will be created", unbornNodeIndex.data(Qt.ItemDataRole.ToolTipRole), re.I)

    rw.diffArea.commitButton.click()
    acceptQMessageBox(rw, "empty commit")
    commitDialog: CommitDialog = findQDialog(rw, "commit")
    commitDialog.ui.summaryEditor.setText("initial commit")
    commitDialog.accept()

    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.UnbornHead)
    assert rw.sidebar.findNodeByKind(SidebarItem.LocalBranch)


def testNewRepoFromExistingSources(tempDir, mainWindow):
    path = os.path.realpath(tempDir.name + "/valoche3000")
    os.makedirs(path)
    writeFile(f"{path}/existing.txt", "file was here before repo inited\n")

    triggerMenuAction(mainWindow.menuBar(), "file/new repo")

    acceptQFileDialog(mainWindow, "new repo", path)
    acceptQMessageBox(mainWindow, r"are you sure.+valoche3000.+isn.t empty")

    rw = mainWindow.currentRepoWidget()
    rw.jump(NavLocator.inUnstaged("existing.txt"))
    assert "file was here before repo inited" in rw.diffView.toPlainText()


@pytest.mark.skipif(WINDOWS, reason="TODO: Windows quirks")
def testNewRepoAtExistingRepo(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    triggerMenuAction(mainWindow.menuBar(), "file/new repo")
    acceptQFileDialog(mainWindow, "new repo", wd)
    acceptQMessageBox(mainWindow, "already exists")
    assert wd == mainWindow.currentRepoWidget().repo.workdir


def testNewNestedRepo(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    path = wd + "/valoche3000"
    os.makedirs(path)

    triggerMenuAction(mainWindow.menuBar(), "file/new repo")
    acceptQFileDialog(mainWindow, "new repo", path)
    acceptQMessageBox(mainWindow, "TestGitRepository.+parent folder.+within.+existing repo")


@pytest.mark.parametrize("method", ["specialdiff", "graphcm"])
def testTruncatedHistory(tempDir, mainWindow, method):
    bottomCommit = Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1")

    mainWindow.onAcceptPrefsDialog({"maxCommits": 5})
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    QTest.qWait(1)
    assert rw.graphView.clFilter.rowCount() == 7  # 1 Workdir, 5 Commits, 1 Truncated

    # Search bar shouldn't be able to reach bottom commit
    triggerMenuAction(mainWindow.menuBar(), "edit/find")
    QTest.qWait(0)
    assert rw.graphView.searchBar.lineEdit.hasFocus()
    QTest.keyClicks(rw.graphView.searchBar.lineEdit, "first c/c1, no parent")
    QTest.qWait(0)
    assert rw.graphView.searchBar.isRed()
    QTest.keyPress(rw.graphView.searchBar.lineEdit, Qt.Key.Key_Return)
    QTest.qWait(0)
    acceptQMessageBox(rw, "not found.+truncated")
    rw.graphView.searchBar.ui.closeButton.click()

    # Bottom commit contents must be able to be displayed
    rw.jump(NavLocator.inCommit(bottomCommit, "c/c1.txt"), check=True)
    assert rw.diffBanner.isVisible()
    assert re.search("commit.+n.t shown in the graph", rw.diffBanner.label.text(), re.I)
    assert not rw.graphView.selectedIndexes()

    # Jump to truncated history row
    truncatedHistoryLocator = NavLocator(NavContext.SPECIAL, path=str(SpecialRow.TruncatedHistory))
    rw.jump(truncatedHistoryLocator, check=True)
    assert rw.graphView.currentRowKind == SpecialRow.TruncatedHistory
    assert rw.graphView.selectedIndexes()

    assert rw.specialDiffView.isVisible()
    assert "truncated" in rw.specialDiffView.toPlainText().lower()

    # Click "change threshold"
    if method == "specialdiff":
        qteClickLink(rw.specialDiffView, "change.+threshold")
    elif method == "graphcm":
        triggerContextMenuAction(rw.graphView.viewport(), "change.+threshold")
    if not OFFSCREEN:
        QTest.qWait(100)  # Non-offscreen needs this nudge
    prefsDialog = findQDialog(mainWindow, "settings")
    QTest.qWait(0)
    assert prefsDialog.findChild(QWidget, "prefctl_maxCommits").hasFocus()
    prefsDialog.reject()

    # Load full commit history
    if method == "specialdiff":
        qteClickLink(rw.specialDiffView, "load full")
    elif method == "graphcm":
        triggerContextMenuAction(rw.graphView.viewport(), "load full")
    # Heads up! RepoWidget changes after a full reload
    rw = mainWindow.currentRepoWidget()
    assert rw.graphView.clFilter.rowCount() > 7

    # Truncated history row must be gone.
    assert rw.graphView.clModel._extraRow == SpecialRow.Invalid

    # Bottom commit should work now
    rw.jump(NavLocator.inCommit(bottomCommit, "c/c1.txt"), check=True)
    assert rw.graphView.selectedIndexes()
    assert not rw.diffBanner.isVisible()


def testRepoNickname(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    assert "TestGitRepository" in mainWindow.windowTitle()
    assert "TestGitRepository" in mainWindow.tabs.tabs.tabText(mainWindow.tabs.currentIndex())
    assert findMenuAction(mainWindow.menuBar(), "file/recent/TestGitRepository")

    # Rename to "coolrepo"
    dlg = bringUpRepoSettings(rw)
    assert dlg.ui.nicknameEdit.text() == ""
    dlg.ui.nicknameEdit.setText("coolrepo")
    dlg.accept()

    assert "TestGitRepository" not in mainWindow.windowTitle()
    assert "coolrepo" in mainWindow.windowTitle()
    assert "coolrepo" in mainWindow.tabs.tabs.tabText(mainWindow.tabs.currentIndex())
    recentAction = findMenuAction(mainWindow.menuBar(), "file/recent/coolrepo")
    assert recentAction
    assert recentAction is findMenuAction(mainWindow.menuBar(), "file/recent/TestGitRepository")

    # Reset to default name
    dlg = bringUpRepoSettings(rw)
    assert dlg.ui.nicknameEdit.text() == "coolrepo"
    assert dlg.ui.nicknameEdit.isClearButtonEnabled()
    dlg.ui.nicknameEdit.clear()
    dlg.accept()
    assert "TestGitRepository" in mainWindow.windowTitle()


@pytest.mark.parametrize("name", ["Zhack Sheerack", ""])
@pytest.mark.parametrize("email", ["chichi@example.com", ""])
def testCustomRepoIdentity(tempDir, mainWindow, name, email):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    dlg = bringUpRepoSettings(rw)
    nameEdit = dlg.ui.nameEdit
    emailEdit = dlg.ui.emailEdit
    okButton = dlg.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)

    assert not dlg.ui.localIdentityCheckBox.isChecked()
    for edit, value in {nameEdit: TEST_SIGNATURE.name, emailEdit: TEST_SIGNATURE.email}.items():
        assert not edit.isEnabled()
        assert not edit.text()
        assert value in edit.placeholderText()

    dlg.ui.localIdentityCheckBox.setChecked(True)
    assert nameEdit.isEnabled()
    assert emailEdit.isEnabled()

    # Test validation of illegal input
    for edit in [nameEdit, emailEdit]:
        assert okButton.isEnabled()
        edit.setText("<")
        assert not okButton.isEnabled()
        edit.clear()

    # Set name/email to given parameters
    nameEdit.setText(name)
    emailEdit.setText(email)

    dlg.accept()

    rw.diffArea.commitButton.click()
    acceptQMessageBox(rw, "empty commit")
    commitDialog: CommitDialog = rw.findChild(CommitDialog)
    commitDialog.ui.summaryEditor.setText("hello")
    commitDialog.accept()

    headCommit = rw.repo.head_commit
    assert headCommit.author.name == (name or TEST_SIGNATURE.name)
    assert headCommit.author.email == (email or TEST_SIGNATURE.email)
    assert headCommit.committer.name == headCommit.author.name
    assert headCommit.committer.email == headCommit.author.email


@pytest.mark.notParallelizableOnWindows
@pytest.mark.parametrize("withGC", [True, False])
@pytest.mark.skipif(WINDOWS, reason="TODO: teardown errors on Windows")
def testCloseManyReposInQuickSuccession(tempDir, mainWindow, taskThread, withGC):
    # Simulate user holding down Ctrl+W with a fast key repeat rate.
    # PrimeRepo should be interrupted without crashing!
    # TODO: For exhaustiveness we should make a large repo with tens of thousands of commits
    #       to simulate interrupting the walker loop in PrimeRepo.

    numTabs = 50
    sesh = Session()
    for i in range(numTabs):
        wd = unpackRepo(tempDir, renameTo=f"RepoCopy{i:04}")
        sesh.tabs.append(wd)

    mainWindow.restoreSession(sesh)

    for _dummy in range(numTabs):
        i = 0
        mainWindow.closeTab(i, finalTab=withGC)
        QTest.qWait(1)  # Simulate some delay as if key-repeating Ctrl+W


@pytest.mark.skipif(MACOS, reason="this feature is disabled on macOS")
def testAutoHideMenuBar(mainWindow):
    menuBar: QMenuBar = mainWindow.menuBar()
    assert menuBar.isVisible()
    assert menuBar.height() != 0

    # Hide menu bar
    mainWindow.onAcceptPrefsDialog({"showMenuBar": False})
    acceptQMessageBox(mainWindow, "menu bar.+hidden")
    assert menuBar.height() == 0

    QTest.keyClick(mainWindow, Qt.Key.Key_Alt)
    QTest.qWait(0)
    assert menuBar.height() != 0

    QTest.keyClick(mainWindow, Qt.Key.Key_Alt)
    QTest.qWait(0)
    assert menuBar.height() == 0

    QTest.keyPress(menuBar, Qt.Key.Key_F, Qt.KeyboardModifier.AltModifier)
    QTest.qWait(0)
    fileMenu: QMenu = menuBar.findChild(QMenu, "MWMainMenuFile")
    assert menuBar.height() != 0
    assert fileMenu.title() == "&File"
    assert fileMenu.isVisibleTo(menuBar)
    QTest.keyRelease(fileMenu, Qt.Key.Key_F, Qt.KeyboardModifier.AltModifier)
    QTest.qWait(0)
    assert menuBar.height() != 0

    QTest.keyClick(fileMenu, Qt.Key.Key_Escape)
    QTest.qWait(0)
    assert not fileMenu.isVisible()
    assert menuBar.height() == 0

    # Restore menu bar
    mainWindow.onAcceptPrefsDialog({"showMenuBar": True})
    QTest.qWait(0)
    assert menuBar.height() != 0


def testAboutDialog(mainWindow):
    app = QApplication.instance()

    def hover(widget: QWidget, localPoint: QPointF) -> bool:
        globalPoint = widget.mapToGlobal(localPoint.toPoint() if QT5 else localPoint)
        event = QMouseEvent(QMouseEvent.Type.MouseMove, localPoint, globalPoint,
                            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        return app.sendEvent(widget, event)

    triggerMenuAction(mainWindow.menuBar(), "help/about")
    dlg: AboutDialog = findQDialog(mainWindow, "about")
    waitUntilTrue(dlg.isActiveWindow)

    header = dlg.ui.header
    header.selectedText()
    hoverPoint = QPointF(12, header.height() - 16)

    # Test UrlToolTip
    assert hover(header, hoverPoint)
    waitUntilTrue(QToolTip.isVisible)
    assert QToolTip.text() == "https://gitfourchette.org"

    # Cover code path where linkHovered changes tooltip contents instantaneously
    QToolTip.showText(QPoint_zero, "TEST!")
    assert hover(header, hoverPoint + QPointF(0, 100))  # move mouse out of label
    assert hover(header, hoverPoint)  # move mouse back in label
    waitUntilTrue(lambda: QToolTip.text() == "https://gitfourchette.org")

    dlg.accept()


def testAllTaskNamesTranslated(mainWindow):
    from gitfourchette import tasks
    for key, type in vars(tasks).items():
        with suppress(TypeError):
            if (issubclass(type, tasks.RepoTask)
                    and type is not tasks.RepoTask
                    and type not in tasks.TaskBook.names):
                raise AssertionError(f"Missing task name translation for {key}")


def testDonatePrompt(mainWindow):
    from gitfourchette import settings
    app = GFApplication.instance()

    now = QDateTime.currentDateTime().toSecsSinceEpoch()
    secondsInADay = 60 * 60 * 24

    class Session:
        numSessions = 0

        def __init__(self, begin=True, end=True):
            self.begin = begin
            self.end = end

        def __enter__(self) -> MainWindow:
            if self.begin:
                app.mainWindow = None
                app.beginSession()
                QTest.qWait(1)
            window = app.mainWindow
            assert window is not None
            Session.numSessions += 1
            window.setWindowTitle(f"(DonatePrompt session {Session.numSessions})")
            return window

        def __exit__(self, exc_type, exc_val, exc_tb):
            if self.end:
                # Essentially a condensed version of the mainWindow fixture's cleanup code.
                app.mainWindow.close()
                app.mainWindow.deleteLater()
                waitUntilTrue(lambda: not app.mainWindow)
                app.endSession(clearTempDir=False)

    def daysToNextPrompt() -> int:
        return (settings.prefs.donatePrompt - now) // secondsInADay

    def schedulePromptInThePast():
        settings.prefs.donatePrompt = now - 1
        settings.prefs.write(True)

    # Launch many sessions in the same day - Donate prompt mustn't show up
    for i in range(15):
        # Don't schedule the prompt before hitting 10 launches
        assert 0 == settings.prefs.donatePrompt

        with Session(begin=i != 0) as mainWindow:
            assert not mainWindow.findChild(DonatePrompt)

    # Tenth launch should schedule donate prompt to appear in 60 days
    assert 59 <= daysToNextPrompt() <= 61

    # Force prompt to appear at the next launch for this test
    schedulePromptInThePast()

    # Make a bogus session. A dialog is vying for our attention so the donate prompt shouldn't get in the way
    bogusSesh = settings.Session()
    bogusSesh.tabs = [qTempDir() + "/---this-path-should-not-exist---"]
    bogusSesh.write(True)
    with Session() as mainWindow:
        acceptQMessageBox(mainWindow, "session couldn.t be restored")
        assert not mainWindow.findChild(DonatePrompt)

    # Intercept prompt and click "never show again"
    with Session() as mainWindow:
        donate: DonatePrompt = mainWindow.findChild(DonatePrompt)
        donate.ui.byeButton.click()
    with Session() as mainWindow:
        assert not mainWindow.findChild(DonatePrompt)
        assert settings.prefs.donatePrompt < 0  # permanently disabled

    # Force prompt to appear at the next launch again
    schedulePromptInThePast()

    # Intercept prompt and click "remind me in 3 months"
    with Session() as mainWindow:
        donate: DonatePrompt = mainWindow.findChild(DonatePrompt)
        donate.ui.postponeButton.click()
    assert 89 <= daysToNextPrompt() <= 91

    # Force prompt to appear at the next launch again
    schedulePromptInThePast()

    # Intercept prompt and click "donate"
    with Session() as mainWindow, MockDesktopServicesContext() as services:
        assert not services.urls
        donate: DonatePrompt = mainWindow.findChild(DonatePrompt)
        donate.ui.donateButton.click()
        QTest.qWait(1500)
        assert len(services.urls) == 1
        assert services.urls[0].toString() == "https://ko-fi.com/jorio"

    # Prompt must not show up again
    with Session(end=False) as mainWindow:
        assert not mainWindow.findChild(DonatePrompt)
        assert settings.prefs.donatePrompt < 0  # permanently disabled


def testRestoreSession(tempDir, mainWindow):
    app = GFApplication.instance()

    for i in range(10):
        wd = unpackRepo(tempDir, renameTo=f"RepoCopy{i:04}")
        rw = mainWindow.openRepo(wd)
        QTest.qWait(1)

    assert mainWindow.tabs.count() == 10
    mainWindow.tabs.setCurrentIndex(5)

    rw = mainWindow.currentRepoWidget()
    assert rw.repo.repo_name() == "RepoCopy0005"

    # Collapse something in sidebar
    originNode = rw.sidebar.findNodeByKind(SidebarItem.Remote)
    originIndex = originNode.createIndex(rw.sidebar.sidebarModel)
    assert rw.sidebar.isExpanded(originIndex)
    rw.sidebar.collapse(originNode.createIndex(rw.sidebar.sidebarModel))
    assert not rw.sidebar.isExpanded(originIndex)

    # Hide something in sidebar
    rw.toggleHideRefPattern("refs/heads/no-parent")

    # End this session
    originalWindow = mainWindow
    originalWindow.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    originalWindow.close()
    app.endSession(clearTempDir=False)
    app.mainWindow = None
    QTest.qWait(0)

    # Make one of the repos inaccessible
    shutil.rmtree(f"{tempDir.name}/RepoCopy0003")

    # ----------------------------------------------
    # Begin new session

    app.beginSession()
    mainWindow2: MainWindow = waitUntilTrue(lambda: app.mainWindow)

    # We've lost one of the repos
    acceptQMessageBox(mainWindow2, r"session could.?n.t be restored.+RepoCopy0003")
    assert mainWindow2.tabs.count() == 9

    # Should restore to same tab
    rw = mainWindow2.currentRepoWidget()
    assert rw.repo.repo_name() == "RepoCopy0005"

    # Make sure origin node is still collapsed
    originNode = rw.sidebar.findNodeByKind(SidebarItem.Remote)
    originIndex = originNode.createIndex(rw.sidebar.sidebarModel)
    assert not rw.sidebar.isExpanded(originIndex)

    # Make sure hidden branch is still hidden
    hiddenBranchNode = rw.sidebar.findNodeByRef("refs/heads/no-parent")
    assert rw.sidebar.sidebarModel.isExplicitlyHidden(hiddenBranchNode)

    # Clean up
    mainWindow2.close()
    mainWindow2.deleteLater()
    waitUntilTrue(lambda: not app.mainWindow)

    # Let fixture delete original window
    app.mainWindow = originalWindow


def testCommandLinePaths(tempDir, mainWindow):
    wd1 = unpackRepo(tempDir, renameTo="wd1")
    wd2 = unpackRepo(tempDir, renameTo="wd2")
    app = GFApplication.instance()

    # End default unit test session so we can start a new one with fake command line paths
    originalWindow = mainWindow
    originalWindow.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)  # Let fixture delete original MainWindow
    originalWindow.close()
    app.endSession(clearTempDir=False)
    app.mainWindow = None

    # Begin new session
    app.commandLinePaths = [
        wd1 + "/c/c1.txt",  # Any file within the repo should work
        wd2,
        wd1,  # Should count as duplicate of the first tab
    ]
    app.beginSession()
    QTest.qWait(1)
    mainWindow = app.mainWindow
    assert mainWindow is not originalWindow

    # Check that we opened the correct repos
    assert mainWindow.tabs.count() == 2  # Two distinct repos were opened
    assert mainWindow.tabs.currentIndex() == 0  # The last path that was passed was within the first repo
    assert mainWindow.tabs.widget(0).workdir == os.path.realpath(wd1)
    assert mainWindow.tabs.widget(1).workdir == os.path.realpath(wd2)

    # Clean up
    mainWindow.close()
    mainWindow.deleteLater()
    waitUntilTrue(lambda: not app.mainWindow)

    # Let fixture delete original window
    app.mainWindow = originalWindow


def testMaximizeDiffArea(tempDir, mainWindow):
    wd1 = unpackRepo(tempDir, renameTo="Repo1")
    wd2 = unpackRepo(tempDir, renameTo="Repo2")
    rw1 = mainWindow.openRepo(wd1)
    rw2 = mainWindow.openRepo(wd2)

    assert mainWindow.tabs.currentWidget() is rw2
    assert rw2.centralSplitter.sizes()[0] != 0
    assert not rw2.diffArea.contextHeader.maximizeButton.isChecked()

    # Maximize rw2's diffArea
    rw2.diffArea.contextHeader.maximizeButton.click()
    assert rw2.diffArea.contextHeader.maximizeButton.isChecked()
    assert rw2.centralSplitter.sizes()[0] == 0

    # Switch to rw1, diffArea must be maximized
    mainWindow.tabs.setCurrentIndex(0)
    assert mainWindow.tabs.currentWidget() is rw1
    assert rw1.diffArea.contextHeader.maximizeButton.isChecked()
    assert rw1.centralSplitter.sizes()[0] == 0

    # De-maximize rw1's diffArea
    rw1.diffArea.contextHeader.maximizeButton.click()
    assert not rw1.diffArea.contextHeader.maximizeButton.isChecked()
    assert rw1.centralSplitter.sizes()[0] > 0

    # Switch to rw2, diffArea must not be maximized
    mainWindow.tabs.setCurrentIndex(1)
    assert mainWindow.tabs.currentWidget() is rw2
    assert not rw2.diffArea.contextHeader.maximizeButton.isChecked()
    assert rw2.centralSplitter.sizes()[0] > 0


def testConfigFileScrubbing(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    configPath = f"{wd}/.git/config"

    assert b'[branch "master"]' in readFile(configPath)
    with open(configPath, "a") as configFile:
        configFile.write('[branch "master"]\n')  # add duplicate section
        configFile.write('[branch "scrubme"]\n')  # add vestigial section
    assert b'[branch "scrubme"]' in readFile(configPath)

    rw = mainWindow.openRepo(wd)

    for (renameFrom, renameTo) in ("master", "scrubme"), ("scrubme", "hello"):
        node = rw.sidebar.findNodeByRef(f"refs/heads/{renameFrom}")
        menu = rw.sidebar.makeNodeMenu(node)
        triggerMenuAction(menu, "rename")
        dlg = findQDialog(rw, "rename.+branch")
        dlg.findChild(QLineEdit).setText(renameTo)
        dlg.accept()

    assert b'[branch "master"]' not in readFile(configPath)
    assert b'[branch "scrubme"]' not in readFile(configPath)


# This used to fail in multithread mode only, hence taskThread
def testHideSelectedBranch(tempDir, mainWindow, taskThread):
    wd = unpackRepo(tempDir)
    with RepoContext(wd) as repo:
        masterId = repo.branches.local['master'].target
        detachedId = Oid(hex='ce112d052bcf42442aa8563f1e2b7a8aabbf4d17')
        repo.checkout_commit(detachedId)

    mainWindow.openRepo(wd)
    rw = waitForRepoWidget(mainWindow)

    # Select branch 'master'...
    rw.selectRef('refs/heads/master')
    waitUntilTrue(lambda: not rw.taskRunner.isBusy())
    assert rw.diffView.currentLocator.commit == masterId

    # ...and hide it. DiffView shouldn't show master anymore.
    rw.toggleHideRefPattern('refs/heads/master')
    waitUntilTrue(lambda: not rw.taskRunner.isBusy())
    assert masterId in rw.repoModel.hiddenCommits

    assert rw.navLocator.commit != masterId
    assert rw.navLocator.commit == rw.diffArea.contextHeader.locator.commit
    assert str(masterId)[:7] not in rw.diffArea.diffHeader.text()
    assert str(rw.navLocator.commit)[:7] in rw.diffArea.diffHeader.text()


def testOpenWorktreeSubdirectoryOfBareRepo(tempDir, mainWindow):
    referenceWd = unpackRepo(tempDir)
    barePath = makeBareCopy(referenceWd, "", False)

    worktreePath = f"{barePath}/MyCoolWorktree"
    GitDriver.runSync("worktree", "add", worktreePath,  directory=barePath, strict=True)
    writeFile(f"{worktreePath}/hello.txt", "hello")

    rw = mainWindow.openRepo(worktreePath)
    assert NavLocator.inUnstaged("hello.txt").isSimilarEnoughTo(rw.navLocator)


@pytest.mark.skipif(MACOS, reason="TODO: macOS quirks")
@pytest.mark.skipif(WINDOWS, reason="TODO: Windows quirks")
def testCloseParentOfExternalProcess(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(Oid(hex="7f822839a2fe9760f386cbbbcb3f92c5fe81def7"), "b/b2.txt"))

    editorPath = getTestDataPath("pause.py")
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"

    mainWindow.onAcceptPrefsDialog({"externalDiff": f'"{editorPath}" "{scratchPath}" $L $R'})
    triggerContextMenuAction(rw.committedFiles.viewport(), "open diff in pause")
    assert readFile(scratchPath, 1000).decode().strip() == "about to sleep"
    mainWindow.closeAllTabs()
    pause(3)
    assert readFile(scratchPath).decode().strip() == "about to sleep"


# TODO: Teardown fails on Windows, which is a symptom of a minor leak that
#  affects all platforms. The partially-initialized RepoWidget holds onto file
#  handles in the repo (making teardown fail on Windows). For now, we can't
#  delete the zombie RepoWidget because its cleanup routine would destroy the
#  task runner, which is shared with RepoStub. This task runner will be needed
#  again if the user tries to reload the repo from RepoStub.
@pytest.mark.skipif(WINDOWS, reason="TODO: tricky teardown, see comment")
def testFailedToStartGitProcess(tempDir, mainWindow, taskThread):
    mainWindow.onAcceptPrefsDialog({
        "gitPath": "/tmp/supposedly-a-git-executable-but-it-doesnt-exist"
    })

    wd = unpackRepo(tempDir)

    repoStub = mainWindow.openRepo(wd)
    assert isinstance(repoStub, RepoStub)

    waitUntilTrue(lambda: repoStub.ui.promptPage.isVisible())

    if FLATPAK:
        # flatpak-spawn always starts successfully, so the errorOccurred callback won't run.
        # Instead, look for return code 127 from /usr/bin/env.
        assert findTextInWidget(repoStub.ui.promptReadyLabel, "code.+127")
        acceptQMessageBox(mainWindow, "code 127")
    else:
        assert findTextInWidget(repoStub.ui.promptReadyLabel, "couldn.t start git")
        acceptQMessageBox(mainWindow, "couldn.t start git")


@pytest.mark.notParallelizableOnWindows
@pytest.mark.parametrize("needSigkill", [False, True])
def testGitProcessStuck(tempDir, mainWindow, taskThread, needSigkill):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/master.txt", "stage me")

    mainWindow.openRepo(wd)
    rw = waitForRepoWidget(mainWindow)
    waitUntilTrue(lambda: not rw.taskRunner.isBusy())

    with DelayGitCommandContext(block=needSigkill):
        rw.diffArea.stageButton.click()
        processDialog = waitForQDialog(rw, "stage files", timeout=1000, t=ProcessDialog)

    waitUntilTrue(lambda: findTextInWidget(processDialog.statusForm.ui.statusLabel, r"delaying.+git.+for.+seconds"))
    assert findTextInWidget(processDialog.statusForm.ui.titleLabel, "git add")

    assert findTextInWidget(processDialog.abortButton, "abort")
    processDialog.abortButton.click()

    if needSigkill:
        waitUntilTrue(lambda: findTextInWidget(processDialog.abortButton, "SIGKILL"), timeout=250)
        processDialog.abortButton.click()

    waitUntilTrue(processDialog.isHidden, timeout=1000)

    code = "SIGKILL" if needSigkill else "SIGTERM"
    waitForQMessageBox(rw, r"git.+exited.+with code.+" + code).reject()
