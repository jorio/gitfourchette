# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import os.path
from contextlib import suppress

from pytestqt.qtbot import QtBot

from gitfourchette import settings
from gitfourchette.forms.aboutdialog import AboutDialog
from gitfourchette.forms.commitdialog import CommitDialog
from gitfourchette.forms.prefsdialog import PrefsDialog
from gitfourchette.forms.processdialog import ProcessDialog
from gitfourchette.forms.reposettingsdialog import RepoSettingsDialog
from gitfourchette.forms.repostub import RepoStub
from gitfourchette.forms.textinputdialog import TextInputDialog
from gitfourchette.graphview.commitlogmodel import SpecialRow, CommitLogModel
from gitfourchette.ipc.ipcprotocol import GFIpcProtocol
from gitfourchette.nav import NavLocator
from gitfourchette.prefsfile import PrefsFile
from gitfourchette.repowidget import RepoWidget
from gitfourchette.settings import Session
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from .util import *


def bringUpRepoSettings(rw):
    node = rw.sidebar.findNodeByKind(SidebarItem.WorkdirHeader)
    triggerMenuAction(rw.sidebar.makeNodeMenu(node), "repo.+settings")
    return findQDialog(rw, "repo.+settings", t=RepoSettingsDialog)


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
    unbornIndex = rw.sidebar.nodeToFilterIndex(unbornNode)
    assert re.search(r"branch.+will be created", unbornIndex.data(Qt.ItemDataRole.ToolTipRole), re.I)

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
    qmb = findQMessageBox(mainWindow, r"are you sure.+valoche3000.+isn.t empty")
    acceptButton = next(b for b in qmb.buttons() if findTextInWidget(b, "create repo here"))
    acceptButton.click()

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

    nestedPath = Path(wd, "valoche3000")
    nestedPath.mkdir(parents=True)

    # 1. Open parent repo
    triggerMenuAction(mainWindow.menuBar(), "file/new repo")
    acceptQFileDialog(mainWindow, "new repo", nestedPath)
    qmb = findQMessageBox(mainWindow, "TestGitRepository.+parent folder.+within.+existing repo")
    button = next(b for b in qmb.buttons() if findTextInWidget(b, "open"))
    button.click()

    rw = mainWindow.currentRepoWidget()
    assert Path(rw.repo.workdir).resolve() == Path(wd).resolve()

    mainWindow.closeAllTabs()

    # 2. Create nested repo
    triggerMenuAction(mainWindow.menuBar(), "file/new repo")
    acceptQFileDialog(mainWindow, "new repo", nestedPath)
    qmb = findQMessageBox(mainWindow, "TestGitRepository.+parent folder.+within.+existing repo")
    button = next(b for b in qmb.buttons() if findTextInWidget(b, "create"))
    button.click()

    rw = mainWindow.currentRepoWidget()
    assert Path(rw.repo.workdir).resolve() == nestedPath.resolve()


@pytest.mark.parametrize("method", ["specialdiff", "graphcm"])
@pytest.mark.parametrize("action", ["load up to", "load full", "change threshold"])
def testTruncatedHistory(tempDir, mainWindow, method, action):
    bottomCommit = Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1")

    GFApplication.applyPrefs(maxCommits=5)
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    assert rw.graphView.clFilter.rowCount() == 7  # 1 Workdir, 5 Commits, 1 Truncated

    # Search bar shouldn't be able to reach bottom commit
    triggerMenuAction(mainWindow.menuBar(), "edit/find")
    waitUntilTrue(rw.graphView.searchBar.lineEdit.hasFocus)
    QTest.keyClicks(rw.graphView.searchBar.lineEdit, "first c/c1, no parent")
    waitUntilTrue(rw.graphView.searchBar.isRed)
    QTest.keyClick(rw.graphView.searchBar.lineEdit, Qt.Key.Key_Return)
    QTest.qWait(0)  # Mac compat
    dismissToolTip("no results.+truncated")
    rw.graphView.searchBar.ui.closeButton.click()

    # Bottom commit contents must still be able to be shown despite not being in the graph
    rw.jump(NavLocator.inCommit(bottomCommit, "c/c1.txt"), check=True)
    assert rw.diffBanner.isVisible()
    assert re.search("commit.+n.t shown in the graph", rw.diffBanner.label.text(), re.I)
    assert not rw.graphView.selectedIndexes()

    # Jump to truncated history row
    truncatedHistoryLocator = NavLocator.inSpecial(SpecialRow.TruncatedHistory)
    rw.jump(truncatedHistoryLocator, check=True)
    assert rw.graphView.currentRowKind == SpecialRow.TruncatedHistory
    assert rw.graphView.selectedIndexes()

    assert rw.specialDiffView.isVisible()
    assert findTextInWidget(rw.specialDiffView, "truncated")

    # Trigger action to load more commits
    if method == "specialdiff":
        qteClickLink(rw.specialDiffView, action)
    elif method == "graphcm":
        triggerContextMenuAction(rw.graphView.viewport(), action)
    else:
        raise NotImplementedError()

    # Change the threshold
    if action == "change threshold":
        prefsDialog = findQDialog(mainWindow, "settings")
        maxCommits = prefsDialog.findChild(QWidget, "prefctl_maxCommits")
        waitUntilTrue(maxCommits.hasFocus)
        maxCommits.setValue(0)
        assert maxCommits.text() == "\u221E", "infinity symbol"
        prefsDialog.accept()
        acceptQMessageBox(mainWindow, "new setting.+take effect.+until you reload")

    # Heads up! RepoWidget changes after a full reload
    rw = mainWindow.currentRepoWidget()
    assert rw.graphView.clFilter.rowCount() > 7

    # Truncated history row must be gone.
    assert rw.graphView.clModel._extraRow == SpecialRow.Invalid

    # Bottom commit should work now
    rw.jump(NavLocator.inCommit(bottomCommit, "c/c1.txt"), check=True)
    assert rw.graphView.selectedIndexes()
    assert not rw.diffBanner.isVisible()


@pytest.mark.parametrize("dedicatedNicknameDialog", [True, False])
def testRepoNickname(tempDir, mainWindow, dedicatedNicknameDialog):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    def nicknameUi() -> tuple[QDialog, QLineEdit]:
        if dedicatedNicknameDialog:
            triggerContextMenuAction(mainWindow.tabs.tabs, "rename")
            dlg = findQDialog(mainWindow, "nickname", t=TextInputDialog)
            return dlg, dlg.lineEdit
        else:
            dlg = bringUpRepoSettings(rw)
            return dlg, dlg.ui.nicknameEdit

    assert "TestGitRepository" in mainWindow.windowTitle()
    assert "TestGitRepository" in mainWindow.tabs.tabs.tabText(mainWindow.tabs.currentIndex())
    assert findMenuAction(mainWindow.menuBar(), "file/recent/TestGitRepository")

    # Rename to "coolrepo"
    dlg, lineEdit = nicknameUi()
    assert lineEdit.text() == ""
    lineEdit.setText("coolrepo")
    dlg.accept()

    assert "TestGitRepository" not in mainWindow.windowTitle()
    assert "coolrepo" in mainWindow.windowTitle()
    assert "coolrepo" in mainWindow.tabs.tabs.tabText(mainWindow.tabs.currentIndex())
    assert "coolrepo" == rw.sidebar.findNodeByKind(SidebarItem.WorkdirHeader).displayName
    recentAction = findMenuAction(mainWindow.menuBar(), "file/recent/coolrepo")
    assert "TestGitRepository" in recentAction.text()

    # Reset to default name
    dlg, lineEdit = nicknameUi()
    assert lineEdit.text() == "coolrepo"
    assert lineEdit.isClearButtonEnabled()
    lineEdit.clear()
    dlg.accept()

    assert "TestGitRepository" in mainWindow.windowTitle()
    assert "TestGitRepository" == rw.sidebar.findNodeByKind(SidebarItem.WorkdirHeader).displayName


def testRepoNicknameBackgroundTab(tempDir, mainWindow):
    wd1 = unpackRepo(tempDir, renameTo="repo1")
    wd2 = unpackRepo(tempDir, renameTo="repo2")
    mainWindow._openRepo(wd1, foreground=False)
    mainWindow.openRepo(wd2)

    assert mainWindow.tabs.currentIndex() == 1
    assert isinstance(mainWindow.tabs.widget(0), RepoStub)
    assert isinstance(mainWindow.tabs.widget(1), RepoWidget)

    triggerContextMenuAction(mainWindow.tabs.tabs, "rename")
    dlg = findQDialog(mainWindow, "nickname", t=TextInputDialog)
    assert "repo1" in dlg.lineEdit.placeholderText()
    dlg.lineEdit.setText("backgroundrepo")
    dlg.accept()

    assert "backgroundrepo" in mainWindow.tabs.tabs.tabText(0)
    mainWindow.tabs.setCurrentIndex(0)
    assert "backgroundrepo" in mainWindow.windowTitle()


def testTabNameDisambiguationByParentFolders(tempDir, mainWindow):
    """Test that tab names are disambiguated by parent folders."""
    wd1 = unpackRepo(tempDir, renameTo="tmprepo1")
    wd2 = unpackRepo(tempDir, renameTo="tmprepo2")

    # Create two repos in different parent folders
    path1 = os.path.join(tempDir.name, "a", "repo")
    path2 = os.path.join(tempDir.name, "b", "repo")
    os.makedirs(os.path.dirname(path1), exist_ok=True)
    os.makedirs(os.path.dirname(path2), exist_ok=True)
    shutil.move(os.path.normpath(wd1), path1)
    shutil.move(os.path.normpath(wd2), path2)

    mainWindow.openRepo(path1)
    mainWindow.openRepo(path2)

    # Tab names should be "a/repo" and "b/repo" (adjusted for OS separator)
    tabBar = mainWindow.tabs.tabs
    assert tabBar.tabText(0) == os.path.join("a", "repo")
    assert tabBar.tabText(1) == os.path.join("b", "repo")


def testTabNameDisambiguationFallbackToMiddleEllipsis(tempDir, mainWindow):
    """If parent folders differ only far from the repo, elide the middle of the path."""
    wd1 = unpackRepo(tempDir, renameTo="tmprepo1")
    wd2 = unpackRepo(tempDir, renameTo="tmprepo2")

    # Create two repos in different parent folders. Two levels above are identical (x, y).
    path1 = os.path.join(tempDir.name, "a", "x", "y", "repo")
    path2 = os.path.join(tempDir.name, "b", "x", "y", "repo")
    os.makedirs(os.path.dirname(path1), exist_ok=True)
    os.makedirs(os.path.dirname(path2), exist_ok=True)
    shutil.move(os.path.normpath(wd1), path1)
    shutil.move(os.path.normpath(wd2), path2)

    mainWindow.openRepo(path1)
    mainWindow.openRepo(path2)

    tabBar = mainWindow.tabs.tabs
    ellipsis = "…"
    assert tabBar.tabText(0) == os.path.join("a", ellipsis, "repo")
    assert tabBar.tabText(1) == os.path.join("b", ellipsis, "repo")


def testTabNameDisambiguationRevertsOnClose(tempDir, mainWindow):
    """Closing one of two disambiguated tabs reverts the other to the repo name."""
    wd1 = unpackRepo(tempDir, renameTo="tmprepo1")
    wd2 = unpackRepo(tempDir, renameTo="tmprepo2")

    path1 = os.path.join(tempDir.name, "a", "repo")
    path2 = os.path.join(tempDir.name, "b", "repo")
    os.makedirs(os.path.dirname(path1), exist_ok=True)
    os.makedirs(os.path.dirname(path2), exist_ok=True)
    shutil.move(os.path.normpath(wd1), path1)
    shutil.move(os.path.normpath(wd2), path2)

    mainWindow.openRepo(path1)
    mainWindow.openRepo(path2)

    tabBar = mainWindow.tabs.tabs
    assert tabBar.tabText(0) == os.path.join("a", "repo")
    assert tabBar.tabText(1) == os.path.join("b", "repo")

    mainWindow.closeTab(0)
    assert mainWindow.tabs.count() == 1
    assert tabBar.tabText(0) == "repo"


def testTabNameDisambiguationRespectsCustomNickname(tempDir, mainWindow):
    """Custom nicknames are kept even when multiple tabs share the same name."""
    from gitfourchette import settings

    wd1 = unpackRepo(tempDir, renameTo="tmprepo1")
    wd2 = unpackRepo(tempDir, renameTo="tmprepo2")

    path1 = os.path.realpath(os.path.join(tempDir.name, "a", "repo"))
    path2 = os.path.realpath(os.path.join(tempDir.name, "b", "repo"))
    os.makedirs(os.path.dirname(path1), exist_ok=True)
    os.makedirs(os.path.dirname(path2), exist_ok=True)
    shutil.move(os.path.normpath(wd1), path1)
    shutil.move(os.path.normpath(wd2), path2)

    settings.history.getRepo(path1).nickname = "myrepo"
    settings.history.getRepo(path2).nickname = "myrepo"

    mainWindow.openRepo(path1)
    mainWindow.openRepo(path2)

    tabBar = mainWindow.tabs.tabs
    assert tabBar.tabText(0) == "myrepo"
    assert tabBar.tabText(1) == "myrepo"


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
    GFApplication.applyPrefs(showMenuBar=False)
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
    GFApplication.applyPrefs(showMenuBar=True)
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

    with MockDesktopServicesContext(dlg) as services:
        donateButton = findWidgetWithText(dlg.ui.buttonBox.buttons(), "donate")
        donateButton.click()
        assert "ko-fi.com/jorio" in services.urls[-1].toString()

        guideButton = findWidgetWithText(dlg.ui.buttonBox.buttons(), "guide")
        guideButton.click()
        assert "gitfourchette.org/guide" in services.urls[-1].toString()

    dlg.accept()


def testWhatsNewFromHelpMenu(mainWindow):
    triggerMenuAction(mainWindow.menuBar(), rf"help/what.s new in v{APP_VERSION}")
    aboutDialog = findQDialog(mainWindow, "About", t=AboutDialog)
    tabs = aboutDialog.ui.tabWidget
    assert tabs.tabText(tabs.currentIndex()) == "News"
    assert findTextInWidget(tabs.currentWidget().findChild(QLabel), "first public release")
    aboutDialog.accept()


def testAllTaskNamesTranslated(mainWindow):
    from gitfourchette import tasks
    for key, type in vars(tasks).items():
        with suppress(TypeError):
            if (issubclass(type, tasks.RepoTask)
                    and type is not tasks.RepoTask
                    and type not in tasks.TaskBook.names):
                raise AssertionError(f"Missing task name translation for {key}")


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


def testHideSelectedBranch(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    shell("git checkout ce112d0", wd)

    rw = mainWindow.openRepo(wd)
    masterId = rw.repo.branches.local['master'].target

    # Select branch 'master'...
    rw.selectRef('refs/heads/master')
    assert rw.navLocator.commit == masterId
    assert not rw.diffArea.diffBanner.isVisible()

    # ...and hide it.
    rw.toggleHideRefPattern('refs/heads/master')
    assert masterId in rw.repoModel.hiddenCommits

    # Still showing the commit at the tip of master
    assert rw.navLocator.commit == masterId
    # The banner should say that it's hidden
    assert rw.diffArea.diffBanner.isVisible()
    assert findTextInWidget(rw.diffArea.diffBanner.label, "part of a hidden branch")
    assert rw.navLocator.commit == rw.diffArea.contextHeader.locator.commit
    # It's not selected in GraphView anymore
    assert not rw.graphView.selectedIndexes()  # no selection in graph

    # Unhide 'master'
    rw.toggleHideRefPattern('refs/heads/master')
    assert masterId not in rw.repoModel.hiddenCommits

    # Still showing the commit at the tip of master
    assert rw.navLocator.commit == masterId
    # GraphView selection restored
    assert len(rw.graphView.selectedIndexes()) == 1
    graphIndex = rw.graphView.selectedIndexes()[0]
    assert graphIndex.data(CommitLogModel.Role.Oid) == masterId
    # Not a hidden commit anymore
    assert not rw.diffArea.diffBanner.isVisible()


def testOpenWorktreeSubdirectoryOfBareRepo(tempDir, mainWindow):
    referenceWd = unpackRepo(tempDir)
    barePath = makeBareCopy(referenceWd, "", False)

    worktreePath = f"{barePath}/MyCoolWorktree"
    shell(f"git worktree add {worktreePath}", barePath)
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

    GFApplication.applyPrefs(externalDiff=f'"{editorPath}" "{scratchPath}" $L $R')
    triggerContextMenuAction(rw.committedFiles.viewport(), "open diff in pause")
    waitForFile(scratchPath)
    assert readTextFile(scratchPath).strip() == "about to sleep"
    mainWindow.closeAllTabs()
    pause(3)
    assert readTextFile(scratchPath).strip() == "about to sleep"


# TODO: Teardown fails on Windows, which is a symptom of a minor leak that
#  affects all platforms. The partially-initialized RepoWidget holds onto file
#  handles in the repo (making teardown fail on Windows). For now, we can't
#  delete the zombie RepoWidget because its cleanup routine would destroy the
#  task runner, which is shared with RepoStub. This task runner will be needed
#  again if the user tries to reload the repo from RepoStub.
@pytest.mark.skipif(WINDOWS, reason="TODO: tricky teardown, see comment")
def testFailedToStartGitProcess(tempDir, mainWindow, taskThread):
    GFApplication.applyPrefs(gitPath="/tmp/supposedly-a-git-executable-but-it-doesnt-exist")

    wd = unpackRepo(tempDir)

    repoStub = mainWindow.openRepo(wd)
    assert isinstance(repoStub, RepoStub)

    waitUntilTrue(lambda: repoStub.ui.promptPage.isVisible())

    if FLATPAK:
        # flatpak-spawn always starts successfully, so the errorOccurred callback won't run.
        # Instead, look for return code 127 from /usr/bin/env.
        assert findTextInWidget(repoStub.ui.promptReadyLabel, "code.+127")
        qmb = findQMessageBox(mainWindow, "code 127")
    else:
        assert findTextInWidget(repoStub.ui.promptReadyLabel, "couldn.t start git")
        qmb = findQMessageBox(mainWindow, "couldn.t start git")

    # The message box should suggest changing the Git executable
    setUpButton = findChildWithText(qmb, "change git", t=QPushButton)
    setUpButton.click()

    # Make sure the gitPath field has focus in PrefsDialog
    prefsDialog = findQDialog(mainWindow, "settings", t=PrefsDialog)
    gitPathControl = prefsDialog.findChild(QWidget, "prefctl_gitPath")
    waitUntilTrue(gitPathControl.hasFocus)
    prefsDialog.close()


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

    delayPattern = "delaying.+git.+for.+seconds"
    if FLATPAK:
        delayPattern = "delaying.+flatpak-spawn.+for.+seconds"

    waitUntilTrue(lambda: findTextInWidget(processDialog.statusForm.ui.statusLabel, delayPattern))
    assert findTextInWidget(processDialog.statusForm.ui.titleLabel, "git add")

    assert findTextInWidget(processDialog.abortButton, "abort")
    processDialog.abortButton.click()

    if needSigkill:
        waitUntilTrue(lambda: findTextInWidget(processDialog.abortButton, "SIGKILL"), timeout=250)
        processDialog.abortButton.click()

    waitUntilTrue(processDialog.isHidden)

    code = "SIGKILL" if needSigkill else "SIGTERM"
    waitForQMessageBox(rw, r"git.+exited.+with code.+" + code).reject()


def testAccumulateTaskEffectBitsUntilRefreshComplete(tempDir, mainWindow, taskThread):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/file1.txt", "stage me...")
    writeFile(f"{wd}/file2.txt", "...then jump here")

    mainWindow.openRepo(wd)
    rw = waitForRepoWidget(mainWindow)
    waitUntilTrue(lambda: not rw.taskRunner.isBusy())

    with DelayGitCommandContext(delay=1):
        # Stage file1.txt
        assert 2 == len(qlvGetRowData(rw.dirtyFiles))
        qlvClickNthRow(rw.dirtyFiles, 0)
        rw.diffArea.stageButton.click()

        # Wait for post-refresh task to start
        assert "StageFiles" in repr(rw.taskRunner.currentTask)
        waitUntilTrue(lambda: "StageFiles" not in repr(rw.taskRunner.currentTask))

        # While refreshing, the dirty box still shows 2 files.
        # Interrupt the refresh task to jump to file2.txt.
        assert 2 == len(qlvGetRowData(rw.dirtyFiles))
        qlvClickNthRow(rw.dirtyFiles, 1)

        # Wait for dust to settle
        waitUntilTrue(lambda: not rw.taskRunner.isBusy(), timeout=20_000)

        assert 1 == len(qlvGetRowData(rw.dirtyFiles))
        assert 1 == len(qlvGetRowData(rw.stagedFiles))


def testAccumulateTaskEffectBitsUntilRefreshAbortedManually(tempDir, mainWindow, taskThread):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/file1.txt", "stage me...")

    mainWindow.openRepo(wd)
    rw = waitForRepoWidget(mainWindow)
    waitUntilTrue(lambda: not rw.taskRunner.isBusy())

    with DelayGitCommandContext(delay=1):
        # Stage file1.txt
        assert 1 == len(qlvGetRowData(rw.dirtyFiles))
        qlvClickNthRow(rw.dirtyFiles, 0)
        rw.diffArea.stageButton.click()

        # Wait for post-refresh task to start
        assert "StageFiles" in repr(rw.taskRunner.currentTask)
        waitUntilTrue(lambda: "StageFiles" not in repr(rw.taskRunner.currentTask))
        assert "RefreshRepo" in repr(rw.taskRunner.currentTask)

        # Abort the refresh task manually
        findQDialog(rw, "", t=ProcessDialog).abortButton.click()
        waitForQMessageBox(rw, "git command exited with code").accept()

        # file1.txt still appears dirty because we've aborted the refresh task
        assert 1 == len(qlvGetRowData(rw.dirtyFiles))
        waitUntilTrue(lambda: not rw.taskRunner.isBusy())


def testDiffHeader(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/empty.txt", "")
    writeFile(f"{wd}/hello.txt", "hello")

    rw = mainWindow.openRepo(wd)

    # Switch back and forth between a text diff (hello.txt) and a special diff
    # (empty.txt) to ensure that the header text is updated even when reloading
    # the diff is not necessary.
    for _i in range(2):
        rw.jump(NavLocator.inUnstaged("empty.txt"), check=True)
        assert rw.diffArea.specialDiffView.isVisible()
        assert findTextInWidget(rw.diffArea.diffHeader, "empty.txt")

        rw.jump(NavLocator.inUnstaged("hello.txt"), check=True)
        assert rw.diffArea.diffView.isVisible()
        assert findTextInWidget(rw.diffArea.diffHeader, "hello.txt")


def testPrefsFileGenericAliases(tempDir, mainWindow):
    assert settings.prefs.dontShowAgain == []
    settings.prefs.dontShowAgain.append("NoFastForwardNecessary")
    settings.prefs.setDirty()
    settings.prefs.write()
    settings.prefs.reset()
    settings.prefs.load()
    assert settings.prefs.dontShowAgain == ["NoFastForwardNecessary"]

    assert settings.history.cloneHistory == []
    assert not settings.history.getRepoNickname("/tmp/hello", strict=True)
    settings.history.cloneHistory.append("https://github.com/jorio/gitfourchette")
    settings.history.getRepo("/tmp/hello").nickname = "HelloWorld"
    settings.history.setDirty()
    settings.history.write()
    settings.history.reset()
    settings.history.load()
    assert settings.history.cloneHistory == ["https://github.com/jorio/gitfourchette"]
    assert settings.history.getRepoNickname("/tmp/hello", strict=True) == "HelloWorld"


def testPrefsFileDontTouchPrivateFields(tempDir, mainWindow):
    @dataclasses.dataclass
    class TestPrefs(PrefsFile):
        _filename = "testprefs.json"

        hello: str = ""
        _dontOverwriteMe: str = ""

    p = TestPrefs()
    p.hello = "hello world"
    p._dontOverwriteMe = "whatever"
    p.setDirty()
    p.write()
    del p

    p = TestPrefs()
    p._dontOverwriteMe = "keep this"
    p.load()
    assert p.hello == "hello world"
    assert p._dontOverwriteMe == "keep this"


def testWindowSizeUnaffectedByLongRepoNames(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    assert not settings.history.repos
    settings.history.getRepo(wd).nickname = "extremely long name " * 200

    desiredSize = QSize(800, 600)
    mainWindow.resize(desiredSize)
    assert mainWindow.size() == desiredSize

    mainWindow.openRepo(wd)
    assert mainWindow.size() == desiredSize


def testSshAgentSandboxingMatchesGit(tempDir, mainWindow):
    app = GFApplication.instance()
    app.applyPrefs(ownSshAgent=True)

    if not FLATPAK:
        assert not settings.prefs.isGitSandboxed()
        assert not app.sshAgent.isSandboxed()
        return

    app.applyPrefs(gitPath="flatpak:/app/bin/git")
    assert settings.prefs.isGitSandboxed()
    assert app.sshAgent.isSandboxed()

    # Resetting just ssh-agent should preserve correct sandboxed state
    app.applyPrefs(ownSshAgent=False)
    assert app.sshAgent is None
    app.applyPrefs(ownSshAgent=True)
    assert app.sshAgent.isSandboxed()

    # Changing the git program setting should reset ssh-agent's sandboxed state
    app.applyPrefs(gitPath="/usr/bin/git")
    assert not settings.prefs.isGitSandboxed()
    assert not app.sshAgent.isSandboxed()


def testRaiseExistingInstance(tempDir, mainWindow):
    socketPath = GFApplication.instance().singleInstanceSocket.socketPath

    wd = unpackRepo(tempDir)
    handshake = GFIpcProtocol.Handshake(args=[wd])

    socket = QLocalSocket()
    socket.connected.connect(lambda: GFIpcProtocol.writeMessage(socket, handshake))

    assert mainWindow.tabs.count() == 0

    socket.connectToServer(socketPath)
    waitUntilTrue(lambda: mainWindow.tabs.count() == 1)
    assert os.path.samefile(wd, mainWindow.currentRepoWidget().workdir)


def testSingleInstanceSocketCreatesConfigDir(tempDir, mainWindow, monkeypatch):
    from gitfourchette.ipc.singleinstancesocket import SingleInstanceSocket

    # Simulate the very first run, where the app config directory doesn't exist yet
    socketPath = Path(tempDir.name, "missingdir", "instance.sock")
    assert not socketPath.parent.exists()

    monkeypatch.setattr(
        SingleInstanceSocket, "singleInstanceSocketPath",
        classmethod(lambda cls: socketPath))

    server = SingleInstanceSocket(mainWindow)
    try:
        assert socketPath.is_socket()
    finally:
        server.close()
        server.deleteLater()
