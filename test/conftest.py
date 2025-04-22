# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

from pytestqt.qtbot import QtBot
from typing import TYPE_CHECKING
import pygit2
import pytest
import tempfile
import os

from gitfourchette.application import GFApplication

if TYPE_CHECKING:
    # For '-> MainWindow' type annotation, without pulling in MainWindow in the actual fixture
    from gitfourchette.mainwindow import MainWindow


def setUpGitConfigSearchPaths(prefix=""):
    # Don't let unit tests access host system's git config
    levels = [
        pygit2.enums.ConfigLevel.GLOBAL,
        pygit2.enums.ConfigLevel.XDG,
        pygit2.enums.ConfigLevel.SYSTEM,
        pygit2.enums.ConfigLevel.PROGRAMDATA,
    ]
    for level in levels:
        if prefix:
            path = f"{prefix}_{level.name}"
        else:
            path = ""
        pygit2.settings.search_path[level] = path


@pytest.fixture(scope='session', autouse=True)
def maskHostGitConfig():
    setUpGitConfigSearchPaths("")


@pytest.fixture(scope="session")
def qapp_args():
    mainPyPath = os.path.join(os.path.dirname(__file__), "..", "gitfourchette", "__main__.py")
    mainPyPath = os.path.normpath(mainPyPath)
    return [mainPyPath, "--test-mode", "--no-threads", "--debug"]


@pytest.fixture(scope="session")
def qapp_cls():
    yield GFApplication


@pytest.fixture
def tempDir() -> tempfile.TemporaryDirectory:
    td = tempfile.TemporaryDirectory(prefix="gitfourchettetest-")
    yield td
    td.cleanup()


@pytest.fixture
def mainWindow(request, qtbot: QtBot) -> MainWindow:
    from gitfourchette import settings, qt, trash, porcelain, tasks
    from .util import TEST_SIGNATURE, waitUntilTrue

    # Turn on test mode: Prevent loading/saving prefs; disable multithreaded work queue
    assert settings.TEST_MODE
    assert tasks.RepoTaskRunner.ForceSerial

    failCount = request.session.testsfailed

    # Prevent unit tests from reading actual user settings.
    # (The prefs and the trash should use a temp folder with TEST_MODE,
    # so this is just an extra safety precaution.)
    qt.QStandardPaths.setTestModeEnabled(True)

    # Prepare app instance
    app = GFApplication.instance()
    app.beginSession(bootUi=False)

    # Prepare session-wide git config with a fallback signature.
    setUpGitConfigSearchPaths(os.path.join(app.tempDir.path(), "MaskedGitConfig"))
    globalGitConfig = porcelain.GitConfigHelper.ensure_file(porcelain.GitConfigLevel.GLOBAL)
    globalGitConfig["user.name"] = TEST_SIGNATURE.name
    globalGitConfig["user.email"] = TEST_SIGNATURE.email

    # Boot the UI
    assert app.mainWindow is None
    app.bootUi()

    # Run the test...
    assert app.mainWindow is not None  # help out code analysis a bit
    yield app.mainWindow

    # Look for any unclosed dialogs after the test
    leakedDialog = ""
    for dialog in app.mainWindow.findChildren(qt.QDialog):
        if dialog.isVisible():
            leakedDialog = dialog.windowTitle()
            break

    # Kill the main window
    app.mainWindow.close()
    app.mainWindow.deleteLater()

    # Wait for main window to die
    waitUntilTrue(lambda: not app.mainWindow)

    # Clear temp trash after this test
    trash.Trash.instance().clear()

    # Clean up the app without destroying it completely.
    # This will reset the temp settings folder.
    app.endSession()

    # Skip cleanup asserts if the test itself failed
    if request.session.testsfailed > failCount:
        return

    # Die here if any dialogs are still visible after the unit test
    assert not leakedDialog, f"Unit test has leaked dialog: '{leakedDialog}'"

    from gitfourchette.exttools.mergedriver import MergeDriver
    assert not MergeDriver._ongoingMerges, "Unit test has leaked MergeDriver objects"


@pytest.fixture
def mockDesktopServices():
    """
    Use this fixture to intercept calls to QDesktopServices.openUrl() in unit tests.
    """
    from gitfourchette import qt

    protocols = ["http", "https", "file"]

    class MockDesktopServices(qt.QObject):
        urlSlot = qt.Signal(qt.QUrl)
        urls: list[qt.QUrl]

        def __init__(self, parent=None):
            super().__init__(parent)
            self.urlSlot.connect(self.recordUrl)
            self.urls = []

        def recordUrl(self, url: qt.QUrl):
            self.urls.append(url)

    handler = MockDesktopServices()

    for protocol in protocols:
        qt.QDesktopServices.setUrlHandler(protocol, handler, "urlSlot")

    yield handler

    for protocol in protocols:
        qt.QDesktopServices.unsetUrlHandler(protocol)


@pytest.fixture
def taskThread():
    """ In this unit test, run RepoTasks in a separate thread """
    from gitfourchette import tasks
    assert tasks.RepoTaskRunner.ForceSerial
    tasks.RepoTaskRunner.ForceSerial = False
    yield
    tasks.RepoTaskRunner.ForceSerial = True
