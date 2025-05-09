# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os.path
from contextlib import suppress

import pytest

from gitfourchette.application import GFApplication
from gitfourchette.forms.commitdialog import CommitDialog
from gitfourchette.forms.donateprompt import DonatePrompt
from gitfourchette.forms.reposettingsdialog import RepoSettingsDialog
from gitfourchette.forms.unloadedrepoplaceholder import UnloadedRepoPlaceholder
from gitfourchette.graphview.commitlogmodel import SpecialRow
from gitfourchette.mainwindow import MainWindow
from gitfourchette.nav import NavLocator, NavContext
from gitfourchette.settings import Session
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from .util import *


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
def testUnloadRepoWhenFolderGoesMissing(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    assert rw.isLoaded

    rw.repoModel.prefs.draftCommitMessage = "some bogus change to prevent prefs to be written"
    rw.repoModel.prefs.write(force=True)
    assert os.path.isfile(f"{wd}/.git/gitfourchette_testmode.json")

    os.rename(wd, os.path.normpath(wd) + "-2")

    mainWindow.currentRepoWidget().refreshRepo()
    assert not rw.isLoaded

    urp: UnloadedRepoPlaceholder = rw.placeholderWidget
    assert urp is not None
    assert isinstance(urp, UnloadedRepoPlaceholder)
    assert urp.isVisibleTo(rw)
    assert re.search(r"folder.+missing", urp.ui.label.text(), re.I)

    # Make sure we're not writing the prefs to a ghost directory structure upon exiting
    assert not os.path.isfile(f"{wd}/.git/gitfourchette_testmode.json")


def testSkipRenameDetection(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    with RepoContext(wd, write_index=True) as repo:
        os.rename(f"{wd}/a/a2.txt", f"{wd}/a/a2-renamed.txt")
        repo.index.remove("a/a2.txt")
        repo.index.add("a/a2-renamed.txt")
        for i in range(100):
            writeFile(f"{wd}/bogus{i:03}.txt", f"hello {i}\n")
            repo.index.add(f"bogus{i:03}.txt")
        oid = repo.create_commit_on_head("renamed a2.txt and added a ton of files")

    rw = mainWindow.openRepo(wd)
    assert rw.isLoaded
    assert not rw.diffBanner.isVisibleTo(rw)

    rw.jump(NavLocator.inCommit(oid))
    assert 102 == len(qlvGetRowData(rw.committedFiles))
    assert rw.diffBanner.isVisibleTo(rw)
    assert "rename" in rw.diffBanner.label.text().lower()

    assert "detect" in rw.diffBanner.buttons[-1].text().lower()
    rw.diffBanner.buttons[-1].click()

    assert 101 == len(qlvGetRowData(rw.committedFiles))
    assert rw.diffBanner.isVisibleTo(rw)
    print(rw.diffBanner.label.text())
    assert re.search(r"1 rename.* detected", rw.diffBanner.label.text(), re.I)

    rw.diffBanner.dismissButton.click()
    assert not rw.diffBanner.isVisibleTo(rw)


def testNewRepo(tempDir, mainWindow):
    triggerMenuAction(mainWindow.menuBar(), "file/new repo")

    path = os.path.realpath(tempDir.name + "/valoche3000")
    os.makedirs(path)

    acceptQFileDialog(mainWindow, "new repo", path)

    rw = mainWindow.currentRepoWidget()
    assert path == os.path.normpath(rw.repo.workdir)

    assert rw.uiReady
    assert rw.navLocator.context.isWorkdir()

    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.LocalBranch)
    unbornNode = rw.sidebar.findNodeByKind(SidebarItem.UnbornHead)
    unbornNodeIndex = unbornNode.createIndex(rw.sidebar.sidebarModel)
    assert re.search(r"branch.+will be created", unbornNodeIndex.data(Qt.ItemDataRole.ToolTipRole), re.I)
    # TODO: test that we honor "init.defaultBranch"...without touching user's git config

    rw.diffArea.commitButton.click()
    acceptQMessageBox(rw, "empty commit")
    commitDialog: CommitDialog = findQDialog(rw, "commit")
    commitDialog.ui.summaryEditor.setText("initial commit")
    commitDialog.accept()

    assert 0 == rw.sidebar.countNodesByKind(SidebarItem.UnbornHead)
    assert rw.sidebar.findNodeByKind(SidebarItem.LocalBranch)


def testNewRepoFromExistingSources(tempDir, mainWindow):
    triggerMenuAction(mainWindow.menuBar(), "file/new repo")

    path = os.path.realpath(tempDir.name + "/valoche3000")
    os.makedirs(path)
    writeFile(f"{path}/existing.txt", "file was here before repo inited\n")

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
    assert 7 == rw.graphView.clFilter.rowCount()

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
    rw.jump(NavLocator.inCommit(bottomCommit))
    assert rw.navLocator.commit == bottomCommit
    assert rw.diffBanner.isVisibleTo(rw)
    assert re.search("commit.+n.t shown in the graph", rw.diffBanner.label.text(), re.I)
    assert not rw.graphView.selectedIndexes()

    # Jump to truncated history row
    loc = NavLocator(NavContext.SPECIAL, path=str(SpecialRow.TruncatedHistory))
    rw.jump(loc)
    assert loc.isSimilarEnoughTo(rw.navLocator)
    assert rw.graphView.currentRowKind == SpecialRow.TruncatedHistory
    assert rw.graphView.selectedIndexes()

    assert rw.specialDiffView.isVisibleTo(rw)
    assert "truncated" in rw.specialDiffView.toPlainText().lower()

    # Click "change threshold"
    if method == "specialdiff":
        qteClickLink(rw.specialDiffView, "change.+threshold")
    elif method == "graphcm":
        triggerContextMenuAction(rw.graphView.viewport(), "change.+threshold")
    prefsDialog = findQDialog(mainWindow, "settings")
    QTest.qWait(0)
    assert prefsDialog.findChild(QWidget, "prefctl_maxCommits").hasFocus()
    prefsDialog.reject()

    # Load full commit history
    if method == "specialdiff":
        qteClickLink(rw.specialDiffView, "load full")
    elif method == "graphcm":
        triggerContextMenuAction(rw.graphView.viewport(), "load full")
    assert 7 < rw.graphView.clFilter.rowCount()

    # Truncated history row must be gone
    with pytest.raises(ValueError):
        rw.jump(loc)
    rejectQMessageBox(mainWindow, "navigate in repo")  # dismiss error message

    # Bottom commit should work now
    rw.jump(NavLocator.inCommit(bottomCommit))
    assert rw.navLocator.commit == bottomCommit
    assert rw.graphView.selectedIndexes()
    assert not rw.diffBanner.isVisibleTo(rw)


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

    dlg.accept()


def testCloseManyReposInQuickSuccession(tempDir, mainWindow, taskThread):
    # Simulate user holding down Ctrl+W with a fast key repeat rate.
    # PrimeRepo should be interrupted without crashing!
    # TODO: For exhaustiveness we should make a large repo with tens of thousands of commits
    #       to simulate interrupting the walker loop in PrimeRepo.

    numTabs = 15
    sesh = Session()
    for i in range(numTabs):
        wd = unpackRepo(tempDir, renameTo=f"RepoCopy{i:04}")
        sesh.tabs.append(wd)

    mainWindow.restoreSession(sesh)

    for _dummy in range(numTabs):
        mainWindow.closeTab(0)
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
    fileMenu: QMenu = menuBar.findChild(QMenu, "MWMainMenu0")
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
    triggerMenuAction(mainWindow.menuBar(), "help/about")
    dlg = findQDialog(mainWindow, "about")
    dlg.accept()


def testAllTaskNamesTranslated(mainWindow):
    from gitfourchette import tasks
    for key, type in vars(tasks).items():
        with suppress(TypeError):
            if (issubclass(type, tasks.RepoTask)
                    and type is not tasks.RepoTask
                    and type not in tasks.TaskBook.names):
                raise AssertionError(f"Missing task name translation for {key}")


def testDonatePrompt(mainWindow, mockDesktopServices):
    from gitfourchette import settings
    app = GFApplication.instance()

    now = QDateTime.currentDateTime().toSecsSinceEpoch()
    secondsInADay = 60 * 60 * 24

    class Session:
        def __init__(self, begin=True, end=True):
            self.begin = begin
            self.end = end

        def __enter__(self) -> MainWindow:
            if self.begin:
                app.mainWindow = None
                app.beginSession()
                QTest.qWait(1)
            assert app.mainWindow is not None
            return app.mainWindow

        def __exit__(self, exc_type, exc_val, exc_tb):
            if self.end:
                app.mainWindow.close()
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

        with Session(begin=i != 0):
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
    with Session(end=False) as mainWindow:
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
    with Session() as mainWindow:
        assert not mockDesktopServices.urls
        donate: DonatePrompt = mainWindow.findChild(DonatePrompt)
        donate.ui.donateButton.click()
        QTest.qWait(1500)
        assert len(mockDesktopServices.urls) == 1
        assert mockDesktopServices.urls[0].toString() == "https://ko-fi.com/jorio"

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
    mainWindow.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    mainWindow.close()
    app.endSession(clearTempDir=False)

    # Make one of the repos inaccessible
    shutil.rmtree(f"{tempDir.name}/RepoCopy0003")

    # ----------------------------------------------
    # Begin new session

    app.mainWindow = None
    app.beginSession()
    QTest.qWait(1)
    mainWindow2: MainWindow = app.mainWindow

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

    mainWindow2.close()
    mainWindow2.deleteLater()


def testCommandLinePaths(tempDir, mainWindow):
    wd1 = unpackRepo(tempDir, renameTo="wd1")
    wd2 = unpackRepo(tempDir, renameTo="wd2")
    app = GFApplication.instance()

    # End default unit test session so we can start a new one with fake command line paths
    mainWindow.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)  # Let fixture delete original MainWindow
    mainWindow.close()
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

    # Check that we opened the correct repos
    assert mainWindow.tabs.count() == 2  # Two distinct repos were opened
    assert mainWindow.tabs.currentIndex() == 0  # The last path that was passed was within the first repo
    assert mainWindow.tabs.widget(0).workdir == os.path.realpath(wd1)
    assert mainWindow.tabs.widget(1).workdir == os.path.realpath(wd2)

    # Clean up
    mainWindow.close()
    mainWindow.deleteLater()


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

    rw = mainWindow.openRepo(wd)
    rw.repoTaskRunner.waitUntilReady()

    # Select branch 'master'...
    rw.selectRef('refs/heads/master')
    rw.repoTaskRunner.waitUntilReady()
    assert rw.diffView.currentLocator.commit == masterId

    # ...and hide it. DiffView shouldn't show master anymore.
    rw.toggleHideRefPattern('refs/heads/master')
    rw.repoTaskRunner.waitUntilReady()
    assert masterId in rw.repoModel.hiddenCommits

    assert rw.navLocator.commit != masterId
    assert rw.navLocator.commit == rw.diffArea.contextHeader.locator.commit
    assert str(masterId)[:7] not in rw.diffArea.diffHeader.text()
    assert str(rw.navLocator.commit)[:7] in rw.diffArea.diffHeader.text()


@pytest.mark.skipif(MACOS, reason="TODO: macOS quirks")
def testCloseParentOfExternalProcess(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inCommit(Oid(hex="7f822839a2fe9760f386cbbbcb3f92c5fe81def7"), "b/b2.txt"))

    editorPath = getTestDataPath("pause.py")
    scratchPath = f"{tempDir.name}/external editor scratch file.txt"

    mainWindow.onAcceptPrefsDialog({"externalDiff": f'python3 "{editorPath}" "{scratchPath}" $L $R'})
    triggerContextMenuAction(rw.committedFiles.viewport(), "open diff in python3")
    assert readFile(scratchPath, 1000).decode().strip() == "about to sleep"
    mainWindow.closeAllTabs()
    pause(3)
    assert readFile(scratchPath).decode().strip() == "about to sleep"
