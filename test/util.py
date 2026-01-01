# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os
import re
import shlex
import shutil
import sys
import tempfile
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import pygit2
import pytest

from gitfourchette.porcelain import *
from gitfourchette.toolbox import QPoint_zero, stripAccelerators, stripHtml
from . import *

TEST_SIGNATURE = Signature("Test Person", "toto@example.com", 1672600000, 0)

requiresNetwork = pytest.mark.skipif(
    os.environ.get("TESTNET", "0").lower() in {"0", ""},
    reason="Requires network - rerun with TESTNET=1 environment variable")

requiresFlatpak = pytest.mark.skipif(
    not FREEDESKTOP or (not FLATPAK and not shutil.which("flatpak")),
    reason="Requires flatpak")

requiresGpg = pytest.mark.skipif(
    not shutil.which("gpg"),
    reason="Requires gpg")

_T = TypeVar("_T")
_TInheritsQWidget = TypeVar("_TInheritsQWidget", bound=QWidget)
_TInheritsQDialog = TypeVar("_TInheritsQDialog", bound=QDialog)


def pause(seconds: int = 3):
    QTest.qWait(seconds * 1000)


def pauseDialog(message="Click OK to continue"):
    """
    Show a non-modal QMessageBox and pause the unit test until the message box
    is finished. Click OK to resume the test or Cancel to abort. This lets you
    explore the UI in the middle of a test.

    This function does nothing in offscreen mode. Make sure to remove calls to
    this function before committing a new test.
    """

    import sys
    import traceback

    if OFFSCREEN:
        warnings.warn("Did you forget to remove a pauseDialog call?")
        return

    stackLine = traceback.format_stack()[-2].splitlines()[0]

    qmb = QMessageBox(
        QMessageBox.Icon.NoIcon,
        "Unit test paused",
        f"Unit test paused from:\n{stackLine}\n{message}",
        buttons=QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
        parent=None)
    qmb.setWindowModality(Qt.WindowModality.NonModal)
    qmb.show()

    waitForSignal(qmb.finished, 1000 * 3600 * 24)

    if qmb.result() == QMessageBox.StandardButton.Cancel:
        sys.exit(1)


def pygit2OlderThan(version: str):
    try:
        pygit2_version_at_least(version)
        return False  # We have this version or newer
    except NotImplementedError:
        # Catch error instead of passing raise_error=False to silence the warning
        return True  # Our version is older


def getTestDataPath(name):
    path = Path(__file__).resolve().parent / "data"
    return str(path / name)


def delayCommand(*tokens: str, delay=5, block=False) -> str:
    delayTokens = ["python3", getTestDataPath("delay-cmd.py"), f"-d{delay}"]
    if block:
        delayTokens.append("--block")
    delayTokens.append("--")
    delayTokens.extend(tokens)
    return shlex.join(delayTokens)


class DelayGitCommandContext:
    def __init__(self, delay=5, block=False):
        from gitfourchette import settings
        rawCommand = settings.prefs.gitPath
        rawTokens = shlex.split(rawCommand, posix=True)
        self.oldCommand = rawCommand
        self.newCommand = delayCommand(*rawTokens, delay=delay, block=block)

    @property
    def mainWindow(self):
        from gitfourchette.application import GFApplication
        return GFApplication.instance().mainWindow

    def __enter__(self):
        # We'll change the git command in the prefs, which invalidates
        # GitDriver's cached version info. Some tasks need this version info
        # to prepare the actual git command they'll run. For testing purposes,
        # the version check ('git version') shouldn't put an additional delay
        # on the tasks, so we'll refresh the version cache manually.
        from gitfourchette.gitdriver import GitDriver
        rawVersionText = GitDriver.runSync("version")

        self.mainWindow.onAcceptPrefsDialog({"gitPath": self.newCommand})

        assert not GitDriver._cachedGitVersionValid
        GitDriver._cacheGitVersion(rawVersionText)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.mainWindow.onAcceptPrefsDialog({"gitPath": self.oldCommand})


def clearSessionwideIdentity():
    config = pygit2.Config.get_global_config()
    toClear = {
        "user.name": TEST_SIGNATURE.name,
        "user.email": TEST_SIGNATURE.email,
    }
    for key, expectedValue in toClear.items():
        assert config[key] == expectedValue
        del config[key]
        assert key not in config


def unpackRepo(
        tempDir: tempfile.TemporaryDirectory | str,
        testRepoName="TestGitRepository",
        renameTo="",
) -> str:
    tempDirPath = tempDir if isinstance(tempDir, str) else tempDir.name

    path = f"{tempDirPath}/{testRepoName}"
    path = os.path.realpath(path)
    assert not os.path.exists(path)

    for ext in ".tar", ".zip":
        archivePath = getTestDataPath(f"{testRepoName}{ext}")
        if os.path.isfile(archivePath):
            shutil.unpack_archive(archivePath, os.path.dirname(path))
            assert os.path.isdir(path)
            break
    else:
        raise FileNotFoundError(f"can't find archive '{testRepoName}' in test data")

    if renameTo:
        path2 = f"{tempDirPath}/{renameTo}"
        shutil.move(path, path2)
        path = path2

    assert not path.endswith("/")
    path += "/"  # ease direct comparison with workdir path produced by libgit2 (it appends a slash)

    return path


def makeBareCopy(
        path: str,
        addAsRemote: str,
        preFetch: bool,
        barePath="",
        keepOldUpstream=False,
        deleteOtherRemotes=False
) -> str:
    if not barePath:
        basename = os.path.basename(os.path.normpath(path))  # normpath first, because basename may return an empty string if path ends with a slash
        barePath = f"{path}/../{basename}-bare-{addAsRemote}.git"  # create bare repo besides real repo in temporary directory
    barePath = os.path.normpath(barePath)

    shutil.copytree(F"{path}/.git", barePath)

    conf = GitConfig(F"{barePath}/config")
    conf['core.bare'] = True
    del conf

    if not addAsRemote:
        assert not preFetch, "requires addAsRemote"
        assert not keepOldUpstream, "requires addAsRemote"
        assert not deleteOtherRemotes, "requires addAsRemote"
        return barePath

    with RepoContext(path) as repo:
        remote = repo.remotes.create(addAsRemote, barePath)

        if preFetch:
            remote.fetch()
            if not keepOldUpstream:
                for localBranch in repo.branches.local:
                    repo.edit_upstream_branch(localBranch, f"{addAsRemote}/{localBranch}")
        else:
            assert not keepOldUpstream, "requires preFetch"

        if deleteOtherRemotes:
            assert not keepOldUpstream, "mutually exclusive"
            remoteNames = repo.listall_remotes_fast()[:]
            remoteNames.remove(addAsRemote)
            for remoteName in remoteNames:
                repo.delete_remote(remoteName)

    return barePath


def touchFile(path):
    open(path, 'a').close()

    # Also gotta do this for QFileSystemWatcher to pick up a change in a unit testing environment
    os.utime(path, (0, 0))


def writeFile(path, text):
    # Prevent accidental littering of current working directory
    assert os.path.isabs(path), "pass me an absolute path"

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))


def readFile(path, timeout=0, unlink=False):
    if timeout:
        waitUntilTrue(lambda: os.path.exists(path), timeout=timeout)

    with open(path, "rb") as f:
        data = f.read()

    if unlink:
        os.unlink(path)

    return data


def readTextFile(path, timeout=0, unlink=False):
    if timeout:
        waitUntilTrue(lambda: os.path.exists(path), timeout=timeout)

    with open(path, encoding="utf-8") as f:
        data = f.read()

    if unlink:
        os.unlink(path)

    return data


def fileHasUserExecutableBit(path: str) -> bool:
    mode = Path(path).lstat().st_mode
    return mode & 0o100 == 0o100


def qlvGetRowData(view: QListView, role=Qt.ItemDataRole.DisplayRole):
    model = view.model()
    data = []
    for row in range(model.rowCount()):
        index = model.index(row, 0)
        assert index.isValid()
        data.append(index.data(role))
    return data


def qlvFindRow(view: QListView, data: str, role=Qt.ItemDataRole.DisplayRole):
    model = view.model()
    for row in range(model.rowCount()):
        index = model.index(row, 0)
        assert index.isValid()
        if index.data(role) == data:
            return row
    raise IndexError(f"didn't find a row containing '{data}'")


def qlvClickNthRow(view: QListView, n: int):
    index = view.model().index(n, 0)
    assert index.isValid()
    view.scrollTo(index)
    rect = view.visualRect(index)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    return index.data(Qt.ItemDataRole.DisplayRole)


def qlvGetSelection(view: QListView, role=Qt.ItemDataRole.DisplayRole):
    data = []
    for index in view.selectedIndexes():
        assert index.isValid()
        data.append(index.data(role))
    return data


def findMenuAction(menu: QMenu | QMenuBar, pattern: str) -> QAction:
    def stripAmps(s: str):
        return s.replace("&", "")

    patternParts = pattern.split("/")

    for submenuPattern in patternParts[:-1]:
        for submenu in menu.children():
            if (isinstance(submenu, QAction)
                    and submenu.menu()
                    and re.search(submenuPattern, stripAmps(submenu.text()), re.I)):
                menu = submenu.menu()
                break
            elif (isinstance(submenu, QMenu)
                  and re.search(submenuPattern, stripAmps(submenu.title()), re.I)):
                menu = submenu
                break
        else:
            raise KeyError(f"didn't find menu '{pattern}' (failed pattern part: '{submenuPattern}')")

    assert isinstance(menu, QMenu)
    for action in menu.actions():
        actionText = re.sub(r"&([A-Za-z])", r"\1", action.text())
        if re.search(patternParts[-1], actionText, re.IGNORECASE):
            return action
    raise KeyError(f"didn't find menu item '{pattern}' in menu")


def triggerMenuAction(menu: QMenu | QMenuBar, pattern: str):
    action = findMenuAction(menu, pattern)
    assert action is not None, f"did not find menu action matching \"{pattern}\""
    assert action.isEnabled(), f"menu action is disabled: \"{pattern}\""
    action.trigger()


def triggerContextMenuAction(widget: QWidget, pattern: str):
    menu = summonContextMenu(widget)
    triggerMenuAction(menu, pattern)
    try:
        menu.close()
    except RuntimeError:
        pass


def qteFind(qte: QTextEdit, pattern: str, plainText=False):
    assert isinstance(qte, QTextEdit)
    if plainText:
        match = re.search(pattern, qte.toPlainText(), re.I | re.M | re.DOTALL)
        found = bool(match)
    else:
        # qte.find() starts searching at current cursor position, so reset cursor to top of document
        textCursor = qte.textCursor()
        textCursor.setPosition(0)
        qte.setTextCursor(textCursor)

        regex = QRegularExpression(pattern, QRegularExpression.PatternOption.CaseInsensitiveOption | QRegularExpression.PatternOption.MultilineOption | QRegularExpression.PatternOption.DotMatchesEverythingOption)
        found = qte.find(regex)

    if not found:
        raise KeyError(f"did not find pattern in QTextEdit: '{pattern}'")

    return found


def qteClickLink(qte: QTextEdit, pattern: str):
    foundLink = qteFind(qte, pattern)
    assert foundLink
    # TODO: Generate an actual click event, not a key press
    qte.setFocus()
    QTest.keyPress(qte, Qt.Key.Key_Enter)


def qteBlockPoint(qte: QTextEdit, blockNo: int, atEnd=False) -> QPoint:
    b = qte.document().firstBlock()
    for _ in range(blockNo):
        b = b.next()
    p = b.position()
    cursor = qte.textCursor()
    cursor.setPosition(p)
    if atEnd:
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
    return qte.cursorRect(cursor).topLeft()


def qteClickBlock(qte: QTextEdit, block1: int):
    point1 = qteBlockPoint(qte, block1)
    QTest.mouseClick(qte.viewport(), Qt.MouseButton.LeftButton, pos=point1)


def qteSelectBlocks(qte: QTextEdit, block1: int, block2: int):
    # Clear selection first
    cursor = qte.textCursor()
    cursor.clearSelection()
    qte.setTextCursor(cursor)

    point1 = qteBlockPoint(qte, block1, atEnd=block1 > block2)
    point2 = qteBlockPoint(qte, block2, atEnd=block1 <= block2)

    QTest.mousePress(qte.viewport(), Qt.MouseButton.LeftButton, pos=point1)
    QTest.mouseMove(qte.viewport(), pos=point2)
    QTest.mouseRelease(qte.viewport(), Qt.MouseButton.LeftButton, pos=point2)


def qteSyntaxColor(textEdit: QTextEdit, line: int):
    document = textEdit.document()
    block = document.findBlockByLineNumber(line)
    formatRange = block.layout().formats()[0]
    return formatRange.format.foreground().color()


def qcbSetIndex(qcb: QComboBox, pattern: str):
    i = qcb.findText(pattern, Qt.MatchFlag.MatchRegularExpression)
    assert i >= 0
    qcb.setCurrentIndex(i)
    qcb.activated.emit(i)
    return i


def findWindow(
        pattern: str,
        t: type[_TInheritsQWidget] = QWidget
) -> _TInheritsQWidget:
    widget: QWidget
    for widget in QApplication.topLevelWidgets():
        if not widget.isEnabled() or widget.isHidden():
            continue
        if not isinstance(widget, t):
            continue
        if re.search(pattern, widget.windowTitle(), re.IGNORECASE):
            return widget

    raise KeyError(f"did not find widget window matching \"{pattern}\"")


def findQDialog(
        parent: QWidget,
        pattern: str,
        t: type[_TInheritsQDialog] = QDialog
) -> _TInheritsQDialog:
    dlg: QDialog
    for dlg in parent.findChildren(t):
        if not dlg.isEnabled() or dlg.isHidden():
            continue
        if re.search(pattern, dlg.windowTitle(), re.IGNORECASE):
            return dlg

    raise KeyError(f"did not find qdialog matching \"{pattern}\"")


def waitForQDialog(
        parent: QWidget,
        pattern: str,
        timeout: int = 5000,
        t: type[_TInheritsQDialog] = QDialog
) -> _TInheritsQDialog:
    def tryFind():
        try:
            return findQDialog(parent, pattern, t)
        except KeyError:
            return None
    return waitUntilTrue(tryFind, timeout=timeout)


def waitUntilTrue(
        callback: Callable[[], _T],
        timeout: int = 5000,
        interval: int = 100,
) -> _T:
    assert timeout >= interval
    deadline = QDeadlineTimer(timeout)
    while not deadline.hasExpired():
        result = callback()
        if result:
            return result
        QTest.qWait(interval)
    raise TimeoutError(f"retry failed after {timeout} ms timeout")


def waitForSignal(signal: SignalInstance, timeout=5000, disconnect=True):
    loop = QEventLoop()

    signal.connect(loop.quit)

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout)

    loop.exec()
    timedOut = not timer.isActive()
    timer.stop()

    if disconnect:
        try:
            signal.disconnect(loop.quit)
        except (TypeError, RuntimeError):  # pragma: no cover
            pass

    loop.deleteLater()
    timer.deleteLater()

    if timedOut:
        raise TimeoutError("waitForSignal timed out")


def waitForRepoWidget(mainWindow):
    from gitfourchette.repowidget import RepoWidget
    from gitfourchette.mainwindow import NoRepoWidgetError

    def attempt() -> RepoWidget | None:
        try:
            return mainWindow.currentRepoWidget()
        except NoRepoWidgetError:
            return None

    rw = waitUntilTrue(attempt)
    assert isinstance(rw, RepoWidget)

    waitUntilTrue(lambda: not rw.taskRunner.isBusy())
    return rw


def findQMessageBox(parent: QWidget, textPattern: str) -> QMessageBox:
    numBoxesFound = 0
    haystack = ""
    for qmb in parent.findChildren(QMessageBox):
        if not qmb.isVisibleTo(parent):  # skip zombie QMBs
            continue
        numBoxesFound += 1
        haystack = "\n".join([qmb.windowTitle(), qmb.text(), qmb.informativeText()])
        haystack = stripHtml(haystack)
        if re.search(textPattern, haystack, re.IGNORECASE | re.DOTALL):
            return qmb

    raise KeyError(f"did not find \"{textPattern}\" among {numBoxesFound} QMessageBoxes. Last haystack is: {haystack}")


def waitForQMessageBox(parent: QWidget, pattern: str) -> QMessageBox:
    def tryFind():
        try:
            return findQMessageBox(parent, pattern)
        except KeyError:
            return None
    return waitUntilTrue(tryFind)


def acceptQMessageBox(parent: QWidget, textPattern: str):
    findQMessageBox(parent, textPattern).accept()
    parent.activateWindow()  # in offscreen tests, accepting the QMB doesn't restore an active window, for some reason (as of Qt 6.7.1)
    QTest.qWait(0)


def rejectQMessageBox(parent: QWidget, textPattern: str):
    findQMessageBox(parent, textPattern).reject()
    parent.activateWindow()  # in offscreen tests, accepting the QMB doesn't restore an active window, for some reason (as of Qt 6.7.1)
    QTest.qWait(0)


def acceptQFileDialog(parent: QWidget, textPattern: str, path: str, useSuggestedName=False):
    qfd = findQDialog(parent, textPattern, QFileDialog)

    # qfd.selectFile() is finicky when QLineEdit has focus - https://stackoverflow.com/a/53886678
    assert qfd.focusWidget()
    assert isinstance(qfd.focusWidget(), QLineEdit)
    qfd.focusWidget().clearFocus()
    QTest.qWait(0)

    if useSuggestedName:
        suggestedName = os.path.basename(qfd.selectedFiles()[0])
        path = os.path.join(path, suggestedName)
    path = os.path.normpath(path)

    qfd.selectFile(path)

    if MACOS and not OFFSCREEN and os.path.isdir(path):
        qfd.selectFile(path + "/")

    qfd.accept()
    return path


def findChildWithText(
        parent: QWidget,
        pattern: str,
        t: type[_TInheritsQWidget]
) -> _TInheritsQWidget:
    for widget in parent.findChildren(t):
        if findTextInWidget(widget, pattern):
            return widget
    raise KeyError(f"did not find {t} \"{pattern}\"")


def findTextInWidget(
        widget: QLabel | QAbstractButton | QStatusBar | QAction,
        pattern: str
) -> re.Match[str] | None:
    if isinstance(widget, QStatusBar):
        text = widget.currentMessage()
    else:
        text = widget.text()
    if "<" not in text:  # unlikely to be HTML
        text = stripAccelerators(text)
    return re.search(pattern, text, re.I | re.M)


def postMouseWheelEvent(target: QWidget, angleDelta: int, point=QPoint_zero, modifiers=Qt.KeyboardModifier.NoModifier):
    if QT5:
        point = QPoint(point)
    else:
        point = QPointF(point)

    fakeWheelEvent = QWheelEvent(
        point,
        target.mapToGlobal(point),
        QPoint(0, 0),
        QPoint(0, angleDelta),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        False)

    QApplication.instance().postEvent(target, fakeWheelEvent)


def summonContextMenu(target: QWidget, localPoint=QPoint_zero):
    def getVisibleContextMenu():
        for tlw in QApplication.topLevelWidgets():
            if isinstance(tlw, QMenu) and tlw.isVisible():
                return tlw
        return None

    # No context menu should be visible at the beginning
    assert not getVisibleContextMenu()

    QTest.qWait(0)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, localPoint, target.mapToGlobal(localPoint))
    QApplication.instance().postEvent(target, event)
    return waitUntilTrue(getVisibleContextMenu)


def summonToolTip(target: QWidget, localPoint=QPoint_zero):
    if WAYLAND and not OFFSCREEN:
        print("*** THIS TEST MUST BE RUN IN OFFSCREEN MODE IN WAYLAND.", file=sys.stderr)

    # Move the cursor so that context-sensitive tooltips still work.
    # NOTE: DOES NOT WORK ON WAYLAND because they disallow moving the pointer,
    # but offscreen tests will still work fine.
    QCursor.setPos(target.mapToGlobal(localPoint))

    # QTest.mouseMove doesn't trigger the tooltip in offscreen tests,
    # so post a QHelpEvent instead.
    assert not QToolTip.isVisible()
    helpEvent = QHelpEvent(QEvent.Type.ToolTip, localPoint, target.mapToGlobal(localPoint))
    QApplication.instance().postEvent(target, helpEvent)
    waitUntilTrue(QToolTip.isVisible, 300)
    text = QToolTip.text()
    QToolTip.hideText()
    waitUntilTrue(lambda: not QToolTip.isVisible())  # may need some time to fade out
    return text
