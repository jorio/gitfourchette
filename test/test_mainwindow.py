# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os

import pytest

from gitfourchette.forms.clonedialog import CloneDialog
from gitfourchette.mainwindow import NoRepoWidgetError
from gitfourchette.nav import NavContext
from .util import *


def testOpenDialog(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    triggerMenuAction(mainWindow.menuBar(), "file/open repo")
    acceptQFileDialog(mainWindow, "open", wd)
    rw = mainWindow.currentRepoWidget()
    assert os.path.samefile(wd, rw.workdir)


@pytest.mark.parametrize("mimePayload", ["text", "url"])
def testDropDirectoryOntoMainWindowOpensRepository(tempDir, mainWindow, mimePayload):
    wd = unpackRepo(tempDir)

    mime = QMimeData()
    if mimePayload == "url":
        wdUrl = QUrl.fromLocalFile(wd)
        mime.setUrls([wdUrl])
    else:
        mime.setText(wd)

    assert mainWindow.tabs.count() == 0
    with pytest.raises(NoRepoWidgetError):
        mainWindow.currentRepoWidget()

    pos = QPointF(mainWindow.width()//2, mainWindow.height()//2)
    dropEvent = QDropEvent(pos, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    dropEvent.acceptProposedAction()
    mainWindow.dropEvent(dropEvent)

    assert mainWindow.tabs.count() == 1
    assert os.path.normpath(mainWindow.currentRepoWidget().repo.workdir) == os.path.normpath(wd)


@pytest.mark.parametrize("mimePayload", ["url", "text", "sloppytext"])
def testDropUrlOntoMainWindowBringsUpCloneDialog(mainWindow, mimePayload):
    assert mainWindow.tabs.count() == 0
    with pytest.raises(NoRepoWidgetError):
        mainWindow.currentRepoWidget()

    address = "https://github.com/jorio/bugdom"
    mime = QMimeData()
    if mimePayload == "url":
        wdUrl = QUrl(address)
        mime.setUrls([wdUrl])
    elif mimePayload == "text":
        mime.setText(address)
    elif mimePayload == "sloppytext":
        mime.setText("  " + address + "  ")

    pos = QPointF(mainWindow.width()//2, mainWindow.height()//2)
    dropEvent = QDropEvent(pos, Qt.DropAction.MoveAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    dropEvent.acceptProposedAction()
    mainWindow.dropEvent(dropEvent)

    cloneDialog: CloneDialog = findQDialog(mainWindow, "clone")
    assert cloneDialog is not None
    assert cloneDialog.url == address

    cloneDialog.reject()


def testOpenSameRepoTwice(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    rw1 = mainWindow.openRepo(wd)
    assert mainWindow.tabs.count() == 1
    assert mainWindow.currentRepoWidget() == rw1

    rw2 = mainWindow.openRepo(wd)  # exact same workdir path
    assert mainWindow.tabs.count() == 1  # don't create a new tab
    assert mainWindow.currentRepoWidget() == rw2

    rw3 = mainWindow.openRepo(wd + os.path.sep)  # trailing slash
    assert mainWindow.tabs.count() == 1  # don't create a new tab
    assert mainWindow.currentRepoWidget() == rw3

    rw4 = mainWindow.openRepo(os.path.join(wd, "master.txt"), exactMatch=False)  # some file within workdir
    assert mainWindow.tabs.count() == 1  # don't create a new tab
    assert mainWindow.currentRepoWidget() == rw4


def testFileListFocusPolicy(tempDir, mainWindow):
    wd = unpackRepo(tempDir, renameTo="repo1")
    writeFile(f"{wd}/untracked.txt", "hello")

    rw = mainWindow.openRepo(wd)

    # GraphView -> TAB -> DirtyFiles
    rw.graphView.setFocus()
    QTest.keyClick(rw, Qt.Key.Key_Tab)
    assert rw.diffArea.dirtyFiles.hasFocus()

    # DirtyFiles -> TAB -> Skip over empty StagedFiles -> DiffView
    QTest.keyClick(rw, Qt.Key.Key_Tab)
    assert rw.diffArea.diffView.hasFocus()

    # DiffView -> Shift+TAB -> Back to DirtyFiles
    QTest.keyClick(rw, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    assert rw.diffArea.dirtyFiles.hasFocus()

    # Back to DirtyFiles via menu action
    triggerMenuAction(mainWindow.menuBar(), "view/focus.+file")
    assert rw.diffArea.dirtyFiles.hasFocus()

    # Stage the file; DirtyFiles becomes empty but it still has focus
    qlvClickNthRow(rw.diffArea.dirtyFiles, 0)
    QTest.keyClick(rw.diffArea.dirtyFiles, Qt.Key.Key_Return)
    assert rw.diffArea.dirtyFiles.isEmpty()
    assert rw.diffArea.dirtyFiles.hasFocus()

    # Menu action goes to StagedFiles now because it's not empty
    triggerMenuAction(mainWindow.menuBar(), "view/focus.+file")
    assert rw.diffArea.stagedFiles.hasFocus()

    # StagedFiles -> Shift+TAB -> Skip over empty DirtyFiles -> GraphView
    QTest.keyClick(rw, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    assert rw.graphView.hasFocus()

    # GraphView -> TAB -> Skip over empty DirtyFiles -> StagedFiles
    QTest.keyClick(rw, Qt.Key.Key_Tab)
    assert rw.diffArea.stagedFiles.hasFocus()


def testMainWindowMenuItems(tempDir, mainWindow):
    wd1 = unpackRepo(tempDir, renameTo="repo1")
    wd2 = unpackRepo(tempDir, renameTo="repo2")
    writeFile(f"{wd1}/untracked.txt", "hello")

    rw2 = mainWindow.openRepo(wd2)
    rw1 = mainWindow.openRepo(wd1)

    triggerMenuAction(mainWindow.menuBar(), "view/focus.+log")
    assert rw1.graphView.hasFocus()

    triggerMenuAction(mainWindow.menuBar(), "view/go to head")
    assert rw1.graphView.hasFocus()
    assert rw1.navLocator.commit == Oid(hex='c9ed7bf12c73de26422b7c5a44d74cfce5a8993b')

    triggerMenuAction(mainWindow.menuBar(), "view/working directory")
    assert rw1.graphView.hasFocus()
    assert rw1.navLocator.context == NavContext.UNSTAGED

    triggerMenuAction(mainWindow.menuBar(), "view/focus.+code")
    assert rw1.diffArea.diffView.hasFocus()
    triggerMenuAction(mainWindow.menuBar(), "view/focus.+file")
    assert rw1.diffArea.dirtyFiles.hasFocus()
    triggerMenuAction(mainWindow.menuBar(), "view/focus.+log")
    assert rw1.graphView.hasFocus()
    triggerMenuAction(mainWindow.menuBar(), "view/focus.+sidebar")
    assert rw1.sidebar.hasFocus()
    triggerMenuAction(mainWindow.menuBar(), "view/show status")
    assert not mainWindow.statusBar().isVisible()

    if not MACOS:
        triggerMenuAction(mainWindow.menuBar(), "view/show menu")
        acceptQMessageBox(mainWindow, "menu.+is now hidden")
        assert mainWindow.menuBar().height() < 2
        triggerMenuAction(mainWindow.menuBar(), "view/show menu")
        QTest.qWait(0)
        assert mainWindow.menuBar().height() >= 2

        # In offscreen tests, accepting the QMB doesn't restore an active window, for some reason (as of Qt 6.7.2)
        mainWindow.activateWindow()

    triggerMenuAction(mainWindow.menuBar(), "view/next tab")
    assert mainWindow.currentRepoWidget() is rw2
    triggerMenuAction(mainWindow.menuBar(), "view/next tab")
    assert mainWindow.currentRepoWidget() is rw1
    triggerMenuAction(mainWindow.menuBar(), "view/previous tab")
    assert mainWindow.currentRepoWidget() is rw2
    triggerMenuAction(mainWindow.menuBar(), "view/previous tab")
    assert mainWindow.currentRepoWidget() is rw1

    triggerMenuAction(mainWindow.menuBar(), "file/close tab")
    assert mainWindow.currentRepoWidget() is rw2
    triggerMenuAction(mainWindow.menuBar(), "file/close tab")
    with pytest.raises(NoRepoWidgetError):
        mainWindow.currentRepoWidget()

    triggerMenuAction(mainWindow.menuBar(), "file/recent/repo2")
    assert os.path.samefile(mainWindow.currentRepoWidget().workdir, wd2)
    triggerMenuAction(mainWindow.menuBar(), "file/close tab")
    triggerMenuAction(mainWindow.menuBar(), "file/recent/clear")
    with pytest.raises(KeyError):
        findMenuAction(mainWindow.menuBar(), "file/recent/repo2")


def testRepoWidgetTabBarActions(tempDir, mainWindow, mockDesktopServices):
    """
    WARNING: THIS TEST MODIFIES THE SYSTEM'S CLIPBOARD.
    (No worries if you're running the tests offscreen.)
    """

    editorPath = getTestDataPath("editor-shim.py")
    scratchPath = f"{tempDir.name}/scratch file.txt"
    mainWindow.onAcceptPrefsDialog({"terminal": f'"{editorPath}" "{scratchPath}" $P'})

    # Open two repos to test background and foreground tab actions
    wd0 = unpackRepo(tempDir, renameTo="repo0")
    wd1 = unpackRepo(tempDir, renameTo="repo1")

    mainWindow.openRepo(wd0)
    mainWindow.openRepo(wd1)
    assert mainWindow.tabs.count() == 2

    for tabIndex, wd in enumerate([wd0, wd1]):
        wd = os.path.realpath(wd)

        tabRect = mainWindow.tabs.tabs.tabRect(tabIndex)
        clickPoint = tabRect.topLeft()
        mainWindow.tabs.tabs.customContextMenuRequested.emit(clickPoint)

        menu = findContextMenu(mainWindow)

        triggerMenuAction(menu, "copy repo path")
        assert QApplication.clipboard().text() == wd

        triggerMenuAction(menu, "open repo folder")
        assert mockDesktopServices.urls[-1] == QUrl.fromLocalFile(wd)

        triggerMenuAction(menu, "open terminal")
        assert wd == readFile(scratchPath, timeout=1000, unlink=True).decode().strip()

        menu.close()
