# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from .util import *


def testTerminal(tempDir, mainWindow):
    scratch = f"{tempDir.name}/terminal scratch file.txt"
    shim = getShimCommand("editor.py", scratch, "hello world", "$COMMAND")
    GFApplication.applyPrefs(terminal=shim)

    wd = unpackRepo(tempDir)
    _rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/terminal")
    waitForFile(scratch)
    scratchText = readTextFile(scratch)
    scratchLines = scratchText.splitlines()
    assert scratchLines[0] == "hello world"
    assert scratchLines[1].endswith(".sh")  # launcher script

    launcherScript = Path(scratchLines[1]).read_text("utf-8")
    assert f"WORKDIR={Path(wd)}" in launcherScript \
        or f"WORKDIR='{Path(wd)}'" in launcherScript


def testTerminalNotConfiguredYet(tempDir, mainWindow):
    GFApplication.applyPrefs(terminal="")

    wd = unpackRepo(tempDir)
    _rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/terminal")
    acceptQMessageBox(mainWindow, "terminal.+isn.t configured")
    findQDialog(mainWindow, "settings").reject()


def testTerminalPlaceholderTokenMissing(tempDir, mainWindow):
    scratch = f"{tempDir.name}/terminal scratch file.txt"
    shim = getShimCommand("editor.py", scratch, "hello world")
    GFApplication.applyPrefs(terminal=shim)

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
    scratch = f"{tempDir.name}/terminal scratch file.txt"
    shim = getShimCommand("editor.py", scratch, "hello world", "$COMMAND")
    if WINDOWS:
        badShim = shim.replace("PYTHON3.EXE", "BOGUS_PROGRAM_DOES_NOT_EXIST")
    else:
        badShim = shim.replace("editor.py", "BOGUS.py")

    wd = unpackRepo(tempDir)
    _rw = mainWindow.openRepo(wd)

    # First, set the editor to an incorrect command to go through the "locate" code path
    GFApplication.applyPrefs(terminal=badShim)
    triggerMenuAction(mainWindow.menuBar(), "repo/terminal")

    qmb = waitForQMessageBox(mainWindow, "couldn.t start.+BOGUS.+terminal")
    locateButton: QPushButton = qmb.button(QMessageBox.StandardButton.Open)
    assert "locate" in locateButton.text().casefold()
    locateButton.click()

    # Set correct command; this must retain the arguments from the incorrect command
    acceptQFileDialog(mainWindow, "where is.+BOGUS",
                      getTestDataPath("shims/editor.py") if not WINDOWS else shutil.which("PYTHON3.EXE"))

    triggerMenuAction(mainWindow.menuBar(), "repo/terminal")
    waitForFile(scratch)
    scratchText = readTextFile(scratch)
    scratchLines = scratchText.splitlines()
    assert scratchLines[0] == "hello world"
    assert scratchLines[1].endswith(".sh")


@pytest.mark.skipif(WINDOWS, reason="teardown fails on Windows")
def testKickerScriptTamperProofing(tempDir, mainWindow, qtbot):
    scratch = f"{tempDir.name}/terminal scratch file.txt"
    shim = getShimCommand("editor.py", scratch, "$COMMAND")
    GFApplication.applyPrefs(terminal=shim)

    wd = unpackRepo(tempDir)
    _rw = mainWindow.openRepo(wd)

    triggerMenuAction(mainWindow.menuBar(), "repo/terminal")
    waitForFile(scratch)
    scratchText = readTextFile(scratch)
    scratchLines = scratchText.splitlines()

    scriptPath = Path(scratchLines[0])  # Kicker script
    assert scriptPath.suffix == ".sh"
    scriptPath.chmod(0o777)  # it was read-only
    scriptPath.write_text("# gotcha!")

    with qtbot.captureExceptions() as uncaughtExceptions:
        triggerMenuAction(mainWindow.menuBar(), "repo/terminal")
        assert len(uncaughtExceptions) == 1
        assert "internal file altered by another process" in str(uncaughtExceptions[-1]).lower()
