# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import gc
import os
import re
import shlex
import shutil
import tempfile
import warnings
import zipfile
from collections.abc import Callable
from contextlib import contextmanager
from os import PathLike
from pathlib import Path
from typing import Literal
from collections.abc import Iterable

import pygit2
import pytest

from gitfourchette.application import GFApplication
from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.porcelain import *
from gitfourchette.tasks import RepoTaskRunner
from gitfourchette.toolbox import QPoint_zero, stripAccelerators, stripHtml
from . import *

TEST_SIGNATURE = Signature("Test Person", "toto@example.com", 1672600000, 0)

HAS_LFS = bool(shutil.which("git-lfs"))
HAS_GPG = bool(shutil.which("gpg"))

# Mac CI can be very slow to start processes
DEFAULT_TIMEOUT = 5_000 if not CI_TESTMODE else 20_000
TOOLTIP_TIMEOUT = 3_000

requiresNetwork = pytest.mark.skipif(
    os.environ.get("TESTNET", "") in {"0", ""},
    reason="Requires network (test.py --with-network)")

requiresFlatpak = pytest.mark.skipif(
    not FLATPAK,
    reason="Requires flatpak")

requiresLfs = pytest.mark.skipif(
    not HAS_LFS,
    reason="Requires git-lfs")

requiresGpg = pytest.mark.skipif(
    not HAS_GPG,
    reason="Requires gpg")

requiresFuse = pytest.mark.skipif(
    os.environ.get("TESTFUSE", "") in {"0", ""},
    reason="Requires FUSE (test.py --with-fuse)")

requiresSymlinks = pytest.mark.skipif(
    WINDOWS,
    reason="no symlinks on Windows")

requiresFileModes = pytest.mark.skipif(
    WINDOWS,
    reason="no file modes on Windows")


def pause(seconds: float = 1.0):
    """
    Pause the current test.
    """
    QTest.qWait(int(seconds * 1000))


def visualPause(seconds: float = 1.0):
    """
    Pause the current test in visual mode only (non-offscreen).
    """
    if not OFFSCREEN:
        pause(seconds)


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


def pygit2OlderThan(version: str) -> bool:
    return not pygit2_min_version(version)


def getTestDataPath(name: str):
    dataDir = Path(__file__).resolve().parent / "data"
    path = dataDir / name

    if not WINDOWS and path.suffix == ".sh":
        assert path.stat().st_mode & 0o100, f"file is not exectuable: {path}"

    return str(path)


def getShimCommand(name: str, *args: str, flatpakSandbox=False) -> str:
    path = Path(getTestDataPath("shims/" + name))
    assert path.suffix == ".py", path
    assert path.is_file()

    if WINDOWS:
        prefix = ["PYTHON3.EXE"]
    elif FLATPAK and flatpakSandbox:
        prefix = [ToolCommands.FlatpakSandboxedCommandPrefix + "python"]
    else:
        assert path.stat().st_mode & 0o100, f"file is not executable: {path}"
        prefix = []

    tokens = prefix + [str(path), *args]
    return shlex.join(tokens)


def delayCommand(*tokens: str, delay=5, block=False) -> str:
    tokens = ["delay.py", f"-d{delay}", "--", *tokens]
    if block:
        tokens.insert(1, "-b")
    return getShimCommand(*tokens, flatpakSandbox=True)


class DelayGitCommandContext:
    def __init__(self, delay=5, block=False):
        from gitfourchette import settings

        rawCommand = settings.prefs.gitPath
        rawTokens = ToolCommands.splitCommandTokens(rawCommand)

        if FLATPAK:
            # Unpack full flatpak-compatible command
            dummyProcess = QProcess(None)
            dummyProcess.setProgram(rawTokens[0])
            dummyProcess.setArguments(rawTokens[1:])
            dummyProcess.setWorkingDirectory("")
            ToolCommands.wrapFlatpakCommand(dummyProcess)
            rawTokens = [dummyProcess.program()] + dummyProcess.arguments()
            dummyProcess.deleteLater()

        self.oldCommand = rawCommand
        self.newCommand = delayCommand(*rawTokens, delay=delay, block=block)

    def __enter__(self):
        # We'll change the git command in the prefs, which invalidates
        # GitDriver's cached version info. Some tasks need this version info
        # to prepare the actual git command they'll run. For testing purposes,
        # the version check ('git version') shouldn't put an additional delay
        # on the tasks, so we'll refresh the version cache manually.
        from gitfourchette.gitdriver import GitDriver
        rawVersionText = GitDriver.runSync("version")

        GFApplication.applyPrefs(gitPath=self.newCommand)

        assert not GitDriver._cachedGitVersionValid
        GitDriver._cacheGitVersion(rawVersionText)

    def __exit__(self, exc_type, exc_val, exc_tb):
        GFApplication.applyPrefs(gitPath=self.oldCommand)


class MockDesktopServicesContext(QObject):
    urlSlot = Signal(QUrl)

    urls: list[QUrl]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.protocols = ["http", "https", "file"]
        self.urls = []
        self.urlSlot.connect(self.recordUrl)

    def recordUrl(self, url: QUrl):
        self.urls.append(url)

    def lastUrlAsLocalFile(self) -> str:
        url = self.urls[-1]
        if not url.isLocalFile():
            raise ValueError(f"last URL isn't a local file: {url}")
        return url.toLocalFile()

    def __enter__(self):
        for protocol in self.protocols:
            QDesktopServices.setUrlHandler(protocol, self, "urlSlot")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for protocol in self.protocols:
            QDesktopServices.unsetUrlHandler(protocol)
        if self.parent() is None:
            self.deleteLater()


@contextmanager
def AsynchronousTaskContext(taskRunner: RepoTaskRunner, tearDown=True, tearDownTimeout=DEFAULT_TIMEOUT):
    """
    To make it easier to write unit tests, RepoTaskRunner runs synchronously in
    the test environment by default. Everything happens on the UI thread, making
    it easier to describe a deterministic chain of events in your tests.

    In the real world, however, RepoTaskRunner runs asynchronously (unless you
    start the application with --no-threads). Use this context manager if your
    test needs events to occur while RepoTaskRunner is busy.

    In this context, be careful to "wait" for conditions instead of assuming
    they flip instantaneously. For example, `findQDialog` assumes the dialog is
    available right now; in an async context, you should instead use
    `waitForQDialog` if the dialog is triggered by an asynchronous task.

    When the context manager exits, it waits for the task runner to finish any
    ongoing tasks (unless you disable `tearDown`).
    """

    assert not taskRunner.isBusy()
    assert taskRunner.forceSerial
    taskRunner.forceSerial = False

    assert not taskRunner.isBusy()

    try:
        yield
    finally:
        taskRunner.forceSerial = True
        if tearDown:
            waitUntilTrue(lambda: not taskRunner.isBusy(), timeout=tearDownTimeout)


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


class ZipFileFixModes(zipfile.ZipFile):
    """ ZipFile that correctly sets file modes on extraction. """
    def _extract_member(self, member, targetpath, pwd):
        if not isinstance(member, zipfile.ZipInfo):
            member = self.getinfo(member)
        path = super()._extract_member(member, targetpath, pwd)
        attr = member.external_attr >> 16
        if attr:
             os.chmod(path, attr)
        return path


def unpackRepo(
        tempDir: tempfile.TemporaryDirectory | str,
        testRepoName="TestGitRepository",
        renameTo="",
) -> str:
    tempDirPath = tempDir if isinstance(tempDir, str) else tempDir.name
    tempDirPath = Path(tempDirPath)
    tempDirPath = tempDirPath.resolve()

    path = Path(tempDirPath, testRepoName)
    assert not path.exists()

    zipPath = getTestDataPath(f"{testRepoName}.zip")
    ZipFileFixModes(zipPath).extractall(path.parent)
    assert path.is_dir()

    if renameTo:
        oldPath, path = path, Path(tempDirPath, renameTo)
        shutil.move(oldPath, path)

    if WINDOWS:
        with RepoContext(str(path)) as repo:
            repo.config["core.autocrlf"] = True

    assert not str(path).endswith("/")
    return str(path) + "/"  # ease direct comparison with workdir path produced by libgit2 (it appends a slash)


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

    assert not Path(path, ".git/objects/maintenance.lock").exists()
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
                    lb = repo.branches.local[localBranch]
                    rb = repo.branches.remote[f"{addAsRemote}/{localBranch}"]
                    lb.upstream = rb
        else:
            assert not keepOldUpstream, "requires preFetch"

        if deleteOtherRemotes:
            assert not keepOldUpstream, "mutually exclusive"
            remoteNames = repo.listall_remotes_fast()[:]
            remoteNames.remove(addAsRemote)
            for remoteName in remoteNames:
                repo.remotes.delete(remoteName)

    return barePath


def touchFile(path):
    open(path, 'a').close()

    # Also gotta do this for QFileSystemWatcher to pick up a change in a unit testing environment
    os.utime(path, (0, 0))


def writeFile(path: str, text: str):
    pathObj = Path(path)

    # Prevent accidental littering of current working directory
    assert pathObj.is_absolute(), "pass me an absolute path"

    pathObj.parent.mkdir(parents=True, exist_ok=True)
    pathObj.write_text(text, "utf-8")


def readFile(path: str, unlink: bool = False) -> bytes:
    pathObj = Path(path)
    data = pathObj.read_bytes()

    if not unlink:
        pass
    elif not WINDOWS:
        pathObj.unlink()
    else:
        def tryUnlink():
            try:
                pathObj.unlink()
                return True
            except PermissionError as ex:  # typically still used by another process
                warnings.warn(f"postponing unlink because: {ex}")
                return False

        waitUntilTrue(tryUnlink)

    return data


def readTextFile(path: str, unlink: bool = False, convertCRLF: bool = True):
    data = readFile(path, unlink=unlink)
    text = data.decode("utf-8")
    if WINDOWS and convertCRLF:
        text = text.replace("\r\n", "\n")
    return text


def readOidFile(path: str) -> Oid:
    return Oid(hex=readTextFile(path).strip())


def waitForFile(path: str, timeout: int = DEFAULT_TIMEOUT):
    pathObj = Path(path)
    waitUntilTrue(lambda: pathObj.exists(), timeout=timeout)


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


def qlvVisualRect(view: QListView, n: int) -> QRect:
    index = view.model().index(n, 0)
    assert index.isValid()
    view.scrollTo(index)
    rect = view.visualRect(index)
    return rect


def qlvClickNthRow(
        view: QListView,
        n: int,
        modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
        doubleClick = False
):
    index = view.model().index(n, 0)
    assert index.isValid()
    view.scrollTo(index)
    rect = view.visualRect(index)
    mouseClick = QTest.mouseDClick if doubleClick else QTest.mouseClick
    mouseClick(view.viewport(), Qt.MouseButton.LeftButton, modifier, pos=rect.center())
    return index.data(Qt.ItemDataRole.DisplayRole)


def qlvGetSelection(view: QListView, role=Qt.ItemDataRole.DisplayRole):
    data = []
    for index in view.selectedIndexes():
        assert index.isValid()
        data.append(index.data(role))
    return data


def qlvSummonToolTip(listView: QListView, row: int, x: int = -16):
    # If passing in a negative x, summon tooltip from right edge of viewport
    if x < 0:
        x = listView.viewport().width() + x

    assert listView.uniformItemSizes(), "this function assumes uniform item heights"
    rowHeight = listView.sizeHintForRow(0)
    y = row * rowHeight + 2

    toolTipPoint = QPoint(x, y)
    toolTip = summonToolTip(listView.viewport(), toolTipPoint)
    return toolTip


def findMenuAction(menu: QMenu | QMenuBar, pattern: str) -> QAction:
    patternParts = pattern.split("/")
    findOptions = Qt.FindChildOption.FindDirectChildrenOnly

    for submenuPattern in patternParts[:-1]:
        submenus = [
            (m, m.title())
            for m in menu.findChildren(QMenu, options=findOptions)
        ]

        submenus.extend(
            (a.menu(), a.text())
            for a in menu.findChildren(QAction, options=findOptions)
            if a.menu() is not None
        )

        for submenu, title in submenus:
            title = stripAccelerators(title)
            if re.search(submenuPattern, title, re.IGNORECASE):
                menu = submenu
                break
        else:
            raise KeyError(f"didn't find menu '{pattern}' (failed pattern part: '{submenuPattern}')")

    assert isinstance(menu, QMenu)
    for action in menu.actions():
        actionText = stripAccelerators(action.text())
        if re.search(patternParts[-1], actionText, re.IGNORECASE):
            return action
    raise KeyError(f"didn't find menu item '{pattern}' in menu")


def triggerMenuAction(menu: QMenu | QMenuBar, pattern: str):
    action = findMenuAction(menu, pattern)
    assert action is not None, f"did not find menu action matching \"{pattern}\""
    assert action.isEnabled(), f"menu action is disabled: \"{pattern}\""
    action.trigger()


def triggerContextMenuAction(widget: QWidget, pattern: str, point: QPoint = QPoint_zero):
    menu = summonContextMenu(widget, point)
    triggerMenuAction(menu, pattern)
    try:
        menu.close()
    except RuntimeError:
        pass


def qlabelClickLink(label: QLabel, pattern: str):
    doc = QTextDocument(None)
    try:
        doc.setHtml(label.text())
        block = doc.firstBlock()

        while block.isValid():
            for fragment in block.fragments():
                fmt = fragment.charFormat()
                if not fmt.isAnchor():
                    continue
                href = fmt.anchorHref()
                if not href:
                    continue
                if re.search(pattern, fragment.text(), re.IGNORECASE | re.MULTILINE | re.DOTALL):
                    label.linkActivated.emit(href)
                    return
            block = block.next()

        raise KeyError(f"did not find link pattern in QLabel: '{pattern}'")
    finally:
        doc.deleteLater()


def qteFind(qte: QTextEdit | QPlainTextEdit, pattern: str, plainText=False):
    assert isinstance(qte, (QTextEdit, QPlainTextEdit))
    if plainText:
        match = re.search(pattern, qte.toPlainText(), re.IGNORECASE | re.MULTILINE | re.DOTALL)
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


def findWindow[T: QWidget](
        pattern: str,
        t: type[T] = QWidget
) -> T:
    widget: QWidget
    for widget in QApplication.topLevelWidgets():
        if not widget.isEnabled() or widget.isHidden():
            continue
        if not isinstance(widget, t):
            continue
        if re.search(pattern, widget.windowTitle(), re.IGNORECASE):
            return widget

    raise KeyError(f"did not find widget window matching \"{pattern}\"")


def findQDialog[T: QDialog](
        parent: QWidget,
        pattern: str,
        t: type[T] = QDialog
) -> T:
    dlg: QDialog
    for dlg in parent.findChildren(t):
        if not dlg.isEnabled() or dlg.isHidden():
            continue
        if re.search(pattern, dlg.windowTitle(), re.IGNORECASE):
            return dlg

    raise KeyError(f"did not find qdialog matching \"{pattern}\"")


def waitForQDialog[T: QDialog](
        parent: QWidget,
        pattern: str,
        timeout: int = DEFAULT_TIMEOUT,
        t: type[T] = QDialog
) -> T:
    def tryFind():
        try:
            return findQDialog(parent, pattern, t)
        except KeyError:
            return None
    return waitUntilTrue(tryFind, timeout=timeout)


def releaseRepoHandles():
    """Windows compat: Flush deferred deletes and GC so repo models let go of their file handles."""
    app = GFApplication.instance()
    for _i in range(100):
        assert QThread.currentThread().loopLevel() == 0
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QTest.qWait(0)
        if 0 == gc.collect():
            break
    else:
        warnings.warn("GC loop")


def waitUntilTrue[T](
        callback: Callable[[], T],
        timeout: int = DEFAULT_TIMEOUT,
        interval: int = 100,
) -> T:
    assert isinstance(callback, Callable), "did you forget passing a lambda or function?"
    assert timeout >= interval
    deadline = QDeadlineTimer(timeout)
    while not deadline.hasExpired():
        result = callback()
        if result:
            return result
        QTest.qWait(interval)
    raise TimeoutError(f"retry failed after {timeout} ms timeout")


def waitForSignal(
        signal: SignalInstance,
        timeout: int = DEFAULT_TIMEOUT,
        disconnect=True
):
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
        haystack = f"{qmb.windowTitle()}\n{qmb.text()}\n{qmb.informativeText()}"
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


def acceptQMessageBox(parent: QWidget, textPattern: str,
                      click=QMessageBox.StandardButton.NoButton):
    """
    In offscreen mode, be aware that closing a QMessageBox doesn't restore the
    previously active window, thereby sending the application to the background
    via a QEvent::ApplicationStateChange.
    """
    qmb = findQMessageBox(parent, textPattern)

    if click:
        # Explicitly accept by clicking a button
        button = qmb.button(click)
        button.click()
    else:
        # Generic accept
        qmb.accept()


def rejectQMessageBox(parent: QWidget, textPattern: str):
    """
    In offscreen mode, be aware that closing a QMessageBox doesn't restore the
    previously active window, thereby sending the application to the background
    via a QEvent::ApplicationStateChange.
    """
    findQMessageBox(parent, textPattern).reject()


def acceptQFileDialog(parent: QWidget, textPattern: str, path: str | PathLike, useSuggestedName=False):
    qfd = findQDialog(parent, textPattern, QFileDialog)

    # qfd.selectFile() is finicky when QLineEdit has focus - https://stackoverflow.com/a/53886678
    assert qfd.focusWidget()
    assert isinstance(qfd.focusWidget(), QLineEdit)
    qfd.focusWidget().clearFocus()
    QTest.qWait(0)

    if useSuggestedName:
        suggestedName = Path(qfd.selectedFiles()[0]).name
        path = Path(path, suggestedName)
    path = Path(path).resolve()

    qfd.selectFile(str(path))

    if MACOS and not OFFSCREEN and path.is_dir():
        qfd.selectFile(str(path) + "/")

    qfd.accept()
    return str(path)


def findChildWithText[TInheritsQWidget: QWidget](
        parent: QWidget,
        pattern: str,
        t: type[TInheritsQWidget]
) -> TInheritsQWidget:
    for widget in parent.findChildren(t):
        if findTextInWidget(widget, pattern):
            return widget
    raise KeyError(f"did not find {t} \"{pattern}\"")


def findTextInWidget(
        widget: QAction | QLabel | QAbstractButton | QStatusBar | QComboBox | QTextEdit | QPlainTextEdit,
        pattern: str
) -> re.Match[str] | None:
    if isinstance(widget, QStatusBar):
        text = widget.currentMessage()
    elif isinstance(widget, QComboBox):
        text = widget.currentText()
    elif isinstance(widget, (QTextEdit, QPlainTextEdit)):
        text = widget.toPlainText()
    else:
        text = widget.text()
    if "<" not in text:  # unlikely to be HTML
        text = stripAccelerators(text)
    else:
        text = stripHtml(text)
    return re.search(pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)


def findWidgetWithText[T: QWidget](widgets: Iterable[T], pattern: str) -> T:
    return next(w for w in widgets if findTextInWidget(w, pattern))


def mouseSpecialClick(widget: QWidget, clickType: Literal["middle", "double"], pos: QPoint = QPoint_zero):
    if clickType == "middle":
        QTest.mouseClick(widget, Qt.MouseButton.MiddleButton, pos=pos)
    elif clickType == "double":
        QTest.mouseDClick(widget, Qt.MouseButton.LeftButton, pos=pos)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=pos)
    else:
        raise NotImplementedError(f"unknown special click type {clickType}")


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


def summonContextMenu(target: QWidget, localPoint=QPoint_zero) -> QMenu:
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
    if qIsWayland() and not OFFSCREEN:
        warnings.warn("*** ON WAYLAND, THIS TEST SHOULD RUN IN OFFSCREEN MODE. ***")

    # Sometimes, especially on Windows, a tooltip may remain from wherever the
    # mouse happened to be. Just discard it.
    if QToolTip.isVisible():
        QToolTip.hideText()
        waitUntilTrue(lambda: not QToolTip.isVisible(), timeout=TOOLTIP_TIMEOUT)

    # Help out macOS
    target.activateWindow()
    waitUntilTrue(lambda: target.window().isActiveWindow())

    # Move the cursor so that context-sensitive tooltips still work.
    # NOTE: DOES NOT WORK ON WAYLAND because they disallow moving the pointer,
    # but offscreen tests will still work fine.
    QCursor.setPos(target.mapToGlobal(localPoint))
    QTest.qWait(0)  # Note: on macOS/offscreen, this may cause the tooltip to appear immediately

    # QTest.mouseMove doesn't trigger the tooltip in offscreen tests,
    # so post a QHelpEvent instead.
    helpEvent = QHelpEvent(QEvent.Type.ToolTip, localPoint, target.mapToGlobal(localPoint))
    QApplication.instance().postEvent(target, helpEvent)

    waitUntilTrue(QToolTip.isVisible, timeout=TOOLTIP_TIMEOUT)
    text = QToolTip.text()

    QToolTip.hideText()
    waitUntilTrue(lambda: not QToolTip.isVisible(), timeout=TOOLTIP_TIMEOUT)  # may need some time to fade out

    return text


def dismissToolTip(pattern: str):
    assert QToolTip.isVisible()
    assert re.search(pattern, QToolTip.text(), re.IGNORECASE)
    QToolTip.hideText()
    waitUntilTrue(lambda: not QToolTip.isVisible())


def shell(script: str, directory: str, authorSig=TEST_SIGNATURE, committerSig=TEST_SIGNATURE):
    from gitfourchette.toolbox.gitutils import signatureEnvironmentVariables

    env = {}

    # Sanitize author/committer
    if authorSig is not None:
        env.update(signatureEnvironmentVariables(authorSig, "AUTHOR"))
    if committerSig is not None:
        env.update(signatureEnvironmentVariables(committerSig, "COMMITTER"))

    # Make sure we're forwarding the correct git config directories
    assert os.environ.get("GIT_CONFIG_GLOBAL", ""), "fixture didn't set GIT_CONFIG_GLOBAL"
    assert os.environ.get("GIT_CONFIG_SYSTEM", ""), "fixture didn't set GIT_CONFIG_SYSTEM"

    lines = [
        "#!/usr/bin/env bash",
        "set -eu",
    ]
    lines.extend(f"export {k}={shlex.quote(v)}" for k, v in env.items())
    lines.append(script)

    scriptPath = Path(qTempDir(), "scenario.sh")
    scriptPath.write_text("\n".join(lines))
    scriptPath.chmod(0o700)
    scriptPath = str(scriptPath)

    # Run script inside Flatpak sandbox, not via flatpak-spawn
    # (this will inherit anything set in os.environ)
    if FLATPAK:
        scriptPath = ToolCommands.FlatpakSandboxedCommandPrefix + scriptPath

    scriptCommand = [scriptPath]

    # On Windows, we can't execute the .sh directly, so prepend with bash.exe.
    if WINDOWS:
        bash = os.environ.get("TESTWINDOWSBASH", "")

        if not bash:
            message = ("\n*** Can't find bash.exe. Please do one of the following:"
                       "\n*** - run test.py under Git Bash,"
                       "\n*** - or, use `test.py --bash=<path to bash.exe>`,"
                       "\n*** - or, set the TESTWINDOWSBASH environment variable.")
            warnings.warn(message)
            pytest.exit(message, returncode=1)

        scriptCommand = [bash, "-l"] + scriptCommand

    ToolCommands.runSync(*scriptCommand, directory=directory, strict=True)


class CallSpy:
    completeCalls: int

    def __init__(self, monkeypatch, obj, attr: str):
        self.completeCalls = 0
        func = getattr(obj, attr)

        def proxy(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            finally:
                self.completeCalls += 1

        monkeypatch.setattr(obj, attr, proxy)

    def __bool__(self):
        return self.completeCalls >= 1


def injectFunctionPrefix(monkeypatch, obj, attr, prefix):
    func = getattr(obj, attr)
    calls = 0

    def wrapped(*args, **kwargs):
        nonlocal calls
        assert calls == 0, "injected code called more than once"
        calls += 1
        prefix()
        return func(*args, **kwargs)

    monkeypatch.setattr(obj, attr, wrapped)
