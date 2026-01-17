# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.nav import NavLocator
from .util import *


def testOpenFileInQDesktopServices(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0"), "a/a1"), check=True)
    menu = summonContextMenu(rw.committedFiles.viewport())

    with MockDesktopServicesContext() as services:
        triggerMenuAction(menu, "open file in/working copy")

        url = services.urls[-1]
        assert url.isLocalFile()
        assert Path(url.toLocalFile()) == Path(wd, "a/a1")


def testTerminal(tempDir, mainWindow):
    shim = getTestDataPath("editor-shim.py")
    scratch = f"{tempDir.name}/terminal scratch file.txt"
    mainWindow.onAcceptPrefsDialog({"terminal": f"'{shim}' '{scratch}' 'hello world' $COMMAND"})

    wd = unpackRepo(tempDir)
    _rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/terminal")
    scratchText = readTextFile(scratch, 5000)
    scratchLines = scratchText.splitlines()
    assert scratchLines[0] == "hello world"
    assert scratchLines[1].endswith(".sh")  # launcher script

    launcherScript = Path(scratchLines[1]).read_text("utf-8")
    assert f"WORKDIR={Path(wd)}" in launcherScript \
        or f"WORKDIR='{Path(wd)}'" in launcherScript


def testTerminalNotConfiguredYet(tempDir, mainWindow):
    mainWindow.onAcceptPrefsDialog({"terminal": ""})

    wd = unpackRepo(tempDir)
    _rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/terminal")
    acceptQMessageBox(mainWindow, "terminal.+isn.t configured")
    findQDialog(mainWindow, "settings").reject()


def testTerminalPlaceholderTokenMissing(tempDir, mainWindow):
    shim = getTestDataPath("editor-shim.py")
    scratch = f"{tempDir.name}/terminal scratch file.txt"
    mainWindow.onAcceptPrefsDialog({"terminal": f"'{shim}' '{scratch}' 'hello world'"})

    wd = unpackRepo(tempDir)
    _rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/terminal")
    qmb = findQMessageBox(mainWindow, "missing placeholder:.+COMMAND")
    editButton = next(b for b in qmb.buttons() if "edit command" in b.text().lower())
    editButton.click()
    findQDialog(mainWindow, "settings").reject()


@pytest.mark.skipif(QT5, reason="Qt 5 (deprecated) is finicky with this test, but Qt 6 is fine")
@pytest.mark.skipif(MACOS and not OFFSCREEN, reason="macOS+non offscreen is finicky with this test")
def testTerminalCommandNotFound(tempDir, mainWindow):
    shim = getTestDataPath("editor-shim.py")
    scratch = f"{tempDir.name}/terminal scratch file.txt"

    wd = unpackRepo(tempDir)
    _rw = mainWindow.openRepo(wd)

    # First, set the editor to an incorrect command to go through the "locate" code path
    mainWindow.onAcceptPrefsDialog({"terminal": f"'{shim}-BOGUSCOMMAND' '{scratch}' 'hello world' $COMMAND"})
    triggerMenuAction(mainWindow.menuBar(), "repo/terminal")

    qmb = waitForQMessageBox(mainWindow, "couldn.t start.+editor-shim.+terminal")
    locateButton: QPushButton = qmb.button(QMessageBox.StandardButton.Open)
    assert "locate" in locateButton.text().casefold()
    locateButton.click()

    # Set correct command; this must retain the arguments from the incorrect command
    acceptQFileDialog(mainWindow, "where is.+editor-shim", shim)

    triggerMenuAction(mainWindow.menuBar(), "repo/terminal")
    scratchText = readTextFile(scratch, 5000)
    scratchLines = scratchText.splitlines()
    assert scratchLines[0] == "hello world"
    assert scratchLines[1].endswith(".sh")
