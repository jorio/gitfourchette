# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Generator
from typing import TYPE_CHECKING

import pygit2
import pytest
from pytestqt.qtbot import QtBot

from gitfourchette.application import GFApplication

if TYPE_CHECKING:
    # For '-> MainWindow' type annotation, without pulling in MainWindow in the actual fixture
    from gitfourchette.mainwindow import MainWindow


def setUpGitConfigSearchPaths(prefix=""):
    """
    Prevent unit tests from accessing the host system's git config files.
    This modifies libgit2 search paths and GIT_CONFIG environment variables
    for vanilla git.
    """
    ConfigLevel = pygit2.enums.ConfigLevel

    levels = [
        ConfigLevel.GLOBAL,
        ConfigLevel.XDG,
        ConfigLevel.SYSTEM,
        ConfigLevel.PROGRAMDATA,
    ]

    for level in levels:
        if prefix:
            path = f"{prefix}_{level.name}"
        else:
            path = ""
        pygit2.settings.search_path[level] = path

    def vanillaGitConfigPath(level):
        path = pygit2.settings.search_path[level]
        if path:
            # When there are no valid config files in the search path, libgit2
            # will create a file named ".gitconfig" the first time it writes
            # a config object to disk
            path += "/.gitconfig"
        return path

    os.environ["GIT_CONFIG_SYSTEM"] = vanillaGitConfigPath(ConfigLevel.SYSTEM)
    os.environ["GIT_CONFIG_GLOBAL"] = vanillaGitConfigPath(ConfigLevel.GLOBAL)

    from gitfourchette.qt import INITIAL_ENVIRONMENT
    assert INITIAL_ENVIRONMENT.get("GIT_CONFIG_SYSTEM", None) != os.environ["GIT_CONFIG_SYSTEM"]
    assert INITIAL_ENVIRONMENT.get("GIT_CONFIG_GLOBAL", None) != os.environ["GIT_CONFIG_GLOBAL"]


@pytest.fixture(scope='session', autouse=True)
def maskHostGitConfig():
    setUpGitConfigSearchPaths("")


@pytest.fixture(scope='session', autouse=True)
def setUpLogging():
    rootLogger = logging.root
    rootLogger.setLevel(logging.DEBUG)

    yield

    # Chatty destructors may cause spam after pytest has wound down.
    # Work around https://github.com/pytest-dev/pytest/issues/5502
    for handler in rootLogger.handlers:
        rootLogger.removeHandler(handler)


@pytest.fixture(scope="session")
def qapp_args():
    mainPyPath = os.path.join(os.path.dirname(__file__), "..", "gitfourchette", "__main__.py")
    mainPyPath = os.path.normpath(mainPyPath)
    return [mainPyPath]


@pytest.fixture(scope="session")
def qapp_cls():
    yield GFApplication


@pytest.fixture
def tempDir() -> Generator[tempfile.TemporaryDirectory, None, None]:
    # When running as a Flatpak, we want to override the temp dir's location
    # to make it easier to send repository paths out of the sandbox.
    location = os.environ.get("GITFOURCHETTE_TEMPDIR", None)

    td = tempfile.TemporaryDirectory(prefix="gitfourchettetest-", dir=location)
    yield td
    td.cleanup()


@pytest.fixture
def mainWindow(request, qtbot: QtBot) -> Generator[MainWindow, None, None]:
    from gitfourchette import qt, trash, porcelain, tasks
    from gitfourchette.appconsts import APP_TESTMODE
    from .util import TEST_SIGNATURE, waitUntilTrue, getTestDataPath

    # Turn on test mode: Prevent loading/saving prefs; disable multithreaded work queue
    assert APP_TESTMODE
    assert tasks.RepoTaskRunner.ForceSerial

    failCount = request.session.testsfailed

    # Prevent unit tests from reading actual user settings.
    # (The prefs and the trash should use a temp folder with APP_TESTMODE,
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
    # Let vanilla git clone submodules from filesystem remotes (for offline tests)
    globalGitConfig["protocol.file.allow"] = "always"
    # Prevent OpenSSH from looking at host user's key files
    globalGitConfig["core.sshCommand"] = getTestDataPath("isolated-ssh.sh")

    # Boot the UI
    assert app.mainWindow is None
    app.bootUi()

    # Run the test...
    assert app.mainWindow is not None  # help out code analysis a bit
    waitUntilTrue(app.mainWindow.isActiveWindow)  # for non-offscreen tests
    yield app.mainWindow

    assert app.mainWindow is not None, "mainWindow vanished after the test"

    # Look for any unclosed dialogs after the test
    leakedWindows = []
    for dialog in app.mainWindow.findChildren(qt.QDialog):
        if dialog.isVisible():
            leakedWindows.append(dialog.windowTitle() + "(unclosed dialog)")

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

    # Purge leaked windows
    for window in app.topLevelWindows():
        if window.isVisible():
            leakedWindows.append(window.title() + "(top-level window)")
            window.deleteLater()

    # Skip cleanup asserts if the test itself failed
    if request.session.testsfailed > failCount:
        return

    # Die here if any windows are still visible after the unit test
    assert not leakedWindows, \
        f"Unit test has leaked {len(leakedWindows)} windows: {'; '.join(leakedWindows)}"

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
