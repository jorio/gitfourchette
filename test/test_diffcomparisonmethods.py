# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Exercise Settings → Code → Comparison method against real `git diff` output
shown in the diff view (tabs vs spaces, run-length spaces, LF vs CRLF).
"""

import pytest

from gitfourchette.nav import NavLocator
from gitfourchette.settings import ComparisonMethod
from .util import *


def _commitTextFile(wd: str, relpath: str, contents: str):
    with RepoContext(wd) as repo:
        writeFile(f"{wd}{relpath}", contents)
        repo.index.add_all([relpath])
        repo.create_commit_on_head(f"add {relpath}", TEST_SIGNATURE, TEST_SIGNATURE)


def _setWorktreeText(wd: str, relpath: str, contents: str):
    writeFile(f"{wd}{relpath}", contents)


def _waitUnifiedDiffVisible(rw):
    assert rw.diffView.isVisible()
    assert rw.diffView.toPlainText().startswith("@@")


def _waitNoChangeSpecialVisible(rw):
    assert rw.specialDiffView.isVisible()
    assert findTextInWidget(rw.specialDiffView, r"whitespace changes ignored")


def _applyComparisonMethod(mainWindow, method: ComparisonMethod):
    mainWindow.onAcceptPrefsDialog({"comparisonMethod": method})


@pytest.mark.parametrize(
    ("method", "expectUnifiedDiff"),
    [
        (ComparisonMethod.Strict, True),
        (ComparisonMethod.IgnoreCrAtEol, True),
        (ComparisonMethod.IgnoreCrAtEolAndSpaceChange, False),
        (ComparisonMethod.IgnoreCrAtEolAndAllSpace, False),
    ],
    ids=["strict", "ignore_eol", "ignore_eol_space_change", "ignore_eol_all_space"],
)
def testComparisonMethodTabsVsSpacesInDiffView(
        tempDir, mainWindow, method, expectUnifiedDiff):
    wd = unpackRepo(tempDir)
    relpath = "comp_tabs_spaces.txt"
    _commitTextFile(wd, relpath, "a\tb\n")
    _setWorktreeText(wd, relpath, "a    b\n")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(relpath), check=True)
    _waitUnifiedDiffVisible(rw)

    _applyComparisonMethod(mainWindow, method)
    if expectUnifiedDiff:
        _waitUnifiedDiffVisible(rw)
    else:
        _waitNoChangeSpecialVisible(rw)


def testReloadCurrentPatchWhenSwitchingWhitespaceMode(tempDir, mainWindow):
    """
    Changing comparison via reloadCurrentPatchForPrefs (Jump.invoke) must refresh
    the visible patch without selecting another file.
    """
    wd = unpackRepo(tempDir)
    relpath = "comp_reload_patch.txt"
    _commitTextFile(wd, relpath, "a\tb\n")
    _setWorktreeText(wd, relpath, "a    b\n")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(relpath), check=True)
    _waitUnifiedDiffVisible(rw)

    _applyComparisonMethod(mainWindow, ComparisonMethod.IgnoreCrAtEolAndAllSpace)
    _waitNoChangeSpecialVisible(rw)

    _applyComparisonMethod(mainWindow, ComparisonMethod.Strict)
    _waitUnifiedDiffVisible(rw)


def testDiffHeaderWhitespaceMenuReloadPatch(tempDir, mainWindow):
    """Diff header comparison menu must trigger the same reload as prefs."""
    wd = unpackRepo(tempDir)
    relpath = "comp_header_buttons.txt"
    _commitTextFile(wd, relpath, "a\tb\n")
    _setWorktreeText(wd, relpath, "a    b\n")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(relpath), check=True)
    _waitUnifiedDiffVisible(rw)

    menu = rw.diffArea.diffButtons.diffMethodButton.menu()
    assert findMenuAction(menu, "recognize line endings and white space").isChecked()

    triggerMenuAction(menu, "ignore line ending.+and all white space")
    _waitNoChangeSpecialVisible(rw)
    assert findMenuAction(menu, "ignore line ending.+and all white space").isChecked()

    triggerMenuAction(menu, "recognize line endings and white space")
    _waitUnifiedDiffVisible(rw)
    assert findMenuAction(menu, "recognize line endings and white space").isChecked()


@pytest.mark.parametrize(
    ("method", "expectUnifiedDiff"),
    [
        (ComparisonMethod.Strict, True),
        (ComparisonMethod.IgnoreCrAtEol, True),
        (ComparisonMethod.IgnoreCrAtEolAndSpaceChange, False),
        (ComparisonMethod.IgnoreCrAtEolAndAllSpace, False),
    ],
    ids=["strict", "ignore_eol", "ignore_eol_space_change", "ignore_eol_all_space"],
)
def testComparisonMethodSpaceRunLengthInDiffview(
        tempDir, mainWindow, method, expectUnifiedDiff):
    wd = unpackRepo(tempDir)
    relpath = "comp_space_runs.txt"
    _commitTextFile(wd, relpath, "a b c\n")
    _setWorktreeText(wd, relpath, "a  b  c\n")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(relpath), check=True)
    _waitUnifiedDiffVisible(rw)

    _applyComparisonMethod(mainWindow, method)
    if expectUnifiedDiff:
        _waitUnifiedDiffVisible(rw)
    else:
        _waitNoChangeSpecialVisible(rw)


@pytest.mark.parametrize(
    ("method", "expectUnifiedDiff"),
    [
        (ComparisonMethod.Strict, True),
        (ComparisonMethod.IgnoreCrAtEol, False),
        (ComparisonMethod.IgnoreCrAtEolAndSpaceChange, False),
        (ComparisonMethod.IgnoreCrAtEolAndAllSpace, False),
    ],
    ids=["strict", "ignore_eol", "ignore_eol_space_change", "ignore_eol_all_space"],
)
def testComparisonMethodLfVsCrlfInDiffView(
        tempDir, mainWindow, method, expectUnifiedDiff):
    wd = unpackRepo(tempDir)
    if WINDOWS:
        with RepoContext(wd) as repo:
            repo.config["core.autocrlf"] = "false"

    relpath = "comp_eol.txt"
    _commitTextFile(wd, relpath, "hello\n")
    _setWorktreeText(wd, relpath, "hello\r\n")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(relpath), check=True)
    _waitUnifiedDiffVisible(rw)

    _applyComparisonMethod(mainWindow, method)
    if expectUnifiedDiff:
        _waitUnifiedDiffVisible(rw)
    else:
        _waitNoChangeSpecialVisible(rw)
