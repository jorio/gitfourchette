# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os
import textwrap

import pytest

from gitfourchette.forms.clonedialog import CloneDialog
from gitfourchette.mainwindow import NoRepoWidgetError, MainWindow
from gitfourchette.nav import NavLocator
from .util import *


def _dragAndDrop(target: MainWindow, payload: QMimeData, expectedHint: str,
                 shouldAcceptEnter=True, shouldAcceptDrop=True, ):
    app = QApplication.instance()
    dropZone = target.dropZone

    pos = QPointF(target.width() // 2, target.height() // 2)

    assert not dropZone.isVisible()
    assert not dropZone.message

    dragEnterEvent = QDragEnterEvent(pos.toPoint(), Qt.DropAction.MoveAction, payload, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    accepted = app.sendEvent(target, dragEnterEvent)
    assert accepted  # DragEnter is always accepted so that we show a pointer
    QTest.qWait(1)  # Give some time for drop zone paint event (for coverage)

    if not expectedHint and not shouldAcceptDrop:
        assert not dropZone.isVisible()
        return

    assert dropZone.isVisible()
    assert re.search(expectedHint, dropZone.message, re.I)

    # TODO: test leave event....
    # dragLeaveEvent = QDragLeaveEvent()
    # accepted = app.sendEvent(target, dragLeaveEvent)
    # assert accepted
    # QTest.qWait(1)
    # assert not dropZone.isVisible()
    #
    # dragEnterEvent = QDragEnterEvent(pos.toPoint(), Qt.DropAction.MoveAction, payload, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    # accepted = app.sendEvent(target, dragEnterEvent)
    # assert accepted  # DragEnter is always accepted so that we show a pointer
    # QTest.qWait(1)  # Give some time for drop zone paint event (for coverage)

    dropEvent = QDropEvent(pos, Qt.DropAction.MoveAction, payload, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    accepted = app.sendEvent(target, dropEvent)
    assert accepted == shouldAcceptDrop
    QTest.qWait(1)


@pytest.mark.parametrize("mimePayload", ["text", "url"])
def testDropRepoDirOnMainWindow(tempDir, mainWindow, mimePayload):
    wd = unpackRepo(tempDir)

    path = wd
    mime = QMimeData()
    if mimePayload == "url":
        mime.setUrls([QUrl.fromLocalFile(path)])
    else:
        mime.setText(path)

    assert mainWindow.tabs.count() == 0
    with pytest.raises(NoRepoWidgetError):
        mainWindow.currentRepoWidget()

    _dragAndDrop(mainWindow, mime, "drop here to open repo")

    assert mainWindow.tabs.count() == 1
    assert os.path.normpath(mainWindow.currentRepoWidget().repo.workdir) == os.path.normpath(wd)


@pytest.mark.parametrize("mimePayload", ["text", "url"])
def testDropNonRepoDirOnMainWindow(tempDir, mainWindow, mimePayload):
    assert mainWindow.tabs.count() == 0
    with pytest.raises(NoRepoWidgetError):
        mainWindow.currentRepoWidget()

    path = tempDir.name
    mime = QMimeData()
    if mimePayload == "url":
        mime.setUrls([QUrl.fromLocalFile(path)])
    else:
        mime.setText(path)

    _dragAndDrop(mainWindow, mime, "isn.t in a git repo", shouldAcceptDrop=False)

    assert mainWindow.tabs.count() == 0


@pytest.mark.parametrize("mimePayload", ["text", "url"])
def testDropPatchOnMainWindow(tempDir, mainWindow, mimePayload):
    patchData = textwrap.dedent("""\
        diff --git a/newempty.txt b/newempty.txt
        new file mode 100644
        index 0000000..e69de29
        --- /dev/null
        +++ b/newempty.txt
    """)
    patchPath = f"{tempDir.name}/newempty.patch"
    writeFile(patchPath, patchData)

    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    assert qlvGetRowData(rw.diffArea.dirtyFiles) == []

    mime = QMimeData()
    if mimePayload == "url":
        mime.setUrls([QUrl.fromLocalFile(patchPath)])
    else:
        mime.setText(patchPath)

    _dragAndDrop(mainWindow, mime, r"apply patch.+newempty\.patch")
    acceptQMessageBox(mainWindow, "apply patch file")

    assert qlvGetRowData(rw.diffArea.dirtyFiles) == ["newempty.txt"]
    assert NavLocator.inUnstaged("newempty.txt").isSimilarEnoughTo(rw.navLocator)
    assert rw.diffArea.specialDiffView.isVisible()
    assert "new empty file" in rw.diffArea.specialDiffView.toPlainText().lower()


@pytest.mark.parametrize("mimePayload", ["url", "text", "sloppytext", "sshtext"])
def testDropUrlOnMainWindow(mainWindow, mimePayload):
    assert mainWindow.tabs.count() == 0
    with pytest.raises(NoRepoWidgetError):
        mainWindow.currentRepoWidget()

    httpsAddress = "https://github.com/jorio/bugdom"
    sshAddress = "git@github.com:jorio/bugdom.git"
    mime = QMimeData()
    if mimePayload == "url":
        mime.setUrls([QUrl(httpsAddress)])
    elif mimePayload == "text":
        mime.setText(httpsAddress)
    elif mimePayload == "sloppytext":
        mime.setText("  " + httpsAddress + "  ")
    elif mimePayload == "sshtext":
        mime.setText(sshAddress)
    else:
        raise NotImplementedError()

    _dragAndDrop(mainWindow, mime, "drop here to clone")

    cloneDialog: CloneDialog = findQDialog(mainWindow, "clone")
    assert cloneDialog is not None
    assert cloneDialog.url in [httpsAddress, sshAddress]

    cloneDialog.reject()


def testDropRandomTextOnMainWindow(mainWindow):
    assert mainWindow.tabs.count() == 0
    with pytest.raises(NoRepoWidgetError):
        mainWindow.currentRepoWidget()

    mime = QMimeData()
    mime.setText("blah blah blah")

    # No-op
    _dragAndDrop(mainWindow, mime, "", shouldAcceptEnter=False, shouldAcceptDrop=False)


@pytest.mark.parametrize("mimePayload", ["text", "url"])
def testDropFileWithinRepoOnMainWindow(tempDir, mainWindow, mimePayload):
    wd = unpackRepo(tempDir)
    mainWindow.openRepo(wd)

    path = f"{wd}/c/c1.txt"
    mime = QMimeData()

    if mimePayload == "url":
        mime.setUrls([QUrl.fromLocalFile(path)])
    else:
        mime.setText(path)

    _dragAndDrop(mainWindow, mime, r"drop here to blame.+c1\.txt")
    blameWindow = findWindow(r"blame.+c1\.txt")
    blameWindow.close()
