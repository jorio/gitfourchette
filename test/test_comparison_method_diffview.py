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

from gitfourchette import settings
from gitfourchette.nav import NavLocator
from gitfourchette.qt import QAction
from gitfourchette.settings import ComparisonMethod
from gitfourchette.syntax import LexJobCache
from .util import *


@pytest.fixture(autouse=True)
def _restore_comparison_method_after_test():
    previous = settings.prefs.comparisonMethod
    settings.prefs.comparisonMethod = ComparisonMethod.Strict
    yield
    settings.prefs.comparisonMethod = previous


def _commit_text_file(wd: str, relpath: str, contents: str):
    with RepoContext(wd) as repo:
        writeFile(f"{wd}{relpath}", contents)
        repo.index.add_all([relpath])
        repo.create_commit_on_head(f"add {relpath}", TEST_SIGNATURE, TEST_SIGNATURE)


def _set_worktree_text(wd: str, relpath: str, contents: str):
    writeFile(f"{wd}{relpath}", contents)


def _wait_unified_diff_visible(rw):
    def ready():
        if rw.diffArea.diffStack.currentIndex() != 0:
            return False
        text = rw.diffView.toPlainText()
        return "@@" in text and text.strip() != ""

    waitUntilTrue(ready, timeout=8000)


def _wait_no_change_special_visible(rw):
    def ready():
        if rw.diffArea.diffStack.currentIndex() != 1:
            return False
        return findTextInWidget(rw.specialDiffView, r"didn.t change") is not None

    waitUntilTrue(ready, timeout=8000)


def _apply_comparison_method_and_refresh(mainWindow, method: ComparisonMethod):
    mainWindow.onAcceptPrefsDialog({"comparisonMethod": method})


def _apply_comparison_method_via_reload_current_patch(rw, method: ComparisonMethod):
    """Same as prefs dialog for comparisonMethod, but exercises Jump-only reload path."""
    settings.prefs.comparisonMethod = method
    settings.prefs.write()
    LexJobCache.clear()
    rw.reloadCurrentPatchForPrefs(full_repo_refresh=False)
    rw.taskRunner.joinWorkerThread()


def _comparison_method_action(rw, method: ComparisonMethod) -> QAction:
    name = f"diffHeaderComparisonMethod_{method.name}"
    action = rw.diffArea.findChild(QAction, name)
    assert action is not None, f"missing comparison menu action {name}"
    return action


def _select_comparison_method(rw, method: ComparisonMethod):
    # Trigger menu action directly; offscreen tests may not hit-test the tool button.
    _comparison_method_action(rw, method).trigger()


@pytest.mark.parametrize(
    ("method", "expect_unified_diff"),
    [
        (ComparisonMethod.Strict, True),
        (ComparisonMethod.IgnoreCrAtEol, True),
        (ComparisonMethod.IgnoreCrAtEolAndSpaceChange, False),
        (ComparisonMethod.IgnoreCrAtEolAndAllSpace, False),
    ],
    ids=["strict", "ignore_eol", "ignore_eol_space_change", "ignore_eol_all_space"],
)
def test_comparison_method_tabs_vs_spaces_in_diffview(
        tempDir, mainWindow, method, expect_unified_diff):
    wd = unpackRepo(tempDir)
    relpath = "comp_tabs_spaces.txt"
    _commit_text_file(wd, relpath, "a\tb\n")
    _set_worktree_text(wd, relpath, "a    b\n")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(relpath), check=True)
    _wait_unified_diff_visible(rw)

    _apply_comparison_method_and_refresh(mainWindow, method)
    if expect_unified_diff:
        _wait_unified_diff_visible(rw)
    else:
        _wait_no_change_special_visible(rw)


def test_reload_current_patch_when_switching_whitespace_mode(tempDir, mainWindow):
    """
    Changing comparison via reloadCurrentPatchForPrefs (Jump.invoke) must refresh
    the visible patch without selecting another file.
    """
    wd = unpackRepo(tempDir)
    relpath = "comp_reload_patch.txt"
    _commit_text_file(wd, relpath, "a\tb\n")
    _set_worktree_text(wd, relpath, "a    b\n")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(relpath), check=True)
    _wait_unified_diff_visible(rw)

    _apply_comparison_method_via_reload_current_patch(rw, ComparisonMethod.IgnoreCrAtEolAndAllSpace)
    _wait_no_change_special_visible(rw)

    _apply_comparison_method_via_reload_current_patch(rw, ComparisonMethod.Strict)
    _wait_unified_diff_visible(rw)


def test_diff_header_whitespace_menu_reload_patch(tempDir, mainWindow):
    """Diff header comparison menu must trigger the same reload as prefs."""
    wd = unpackRepo(tempDir)
    relpath = "comp_header_buttons.txt"
    _commit_text_file(wd, relpath, "a\tb\n")
    _set_worktree_text(wd, relpath, "a    b\n")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(relpath), check=True)
    _wait_unified_diff_visible(rw)
    assert _comparison_method_action(rw, ComparisonMethod.Strict).isChecked()

    _select_comparison_method(rw, ComparisonMethod.IgnoreCrAtEolAndAllSpace)
    _wait_no_change_special_visible(rw)
    assert _comparison_method_action(rw, ComparisonMethod.IgnoreCrAtEolAndAllSpace).isChecked()

    _select_comparison_method(rw, ComparisonMethod.Strict)
    _wait_unified_diff_visible(rw)
    assert _comparison_method_action(rw, ComparisonMethod.Strict).isChecked()


@pytest.mark.parametrize(
    ("method", "expect_unified_diff"),
    [
        (ComparisonMethod.Strict, True),
        (ComparisonMethod.IgnoreCrAtEol, True),
        (ComparisonMethod.IgnoreCrAtEolAndSpaceChange, False),
        (ComparisonMethod.IgnoreCrAtEolAndAllSpace, False),
    ],
    ids=["strict", "ignore_eol", "ignore_eol_space_change", "ignore_eol_all_space"],
)
def test_comparison_method_space_run_length_in_diffview(
        tempDir, mainWindow, method, expect_unified_diff):
    wd = unpackRepo(tempDir)
    relpath = "comp_space_runs.txt"
    _commit_text_file(wd, relpath, "a b c\n")
    _set_worktree_text(wd, relpath, "a  b  c\n")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(relpath), check=True)
    _wait_unified_diff_visible(rw)

    _apply_comparison_method_and_refresh(mainWindow, method)
    if expect_unified_diff:
        _wait_unified_diff_visible(rw)
    else:
        _wait_no_change_special_visible(rw)


@pytest.mark.parametrize(
    ("method", "expect_unified_diff"),
    [
        (ComparisonMethod.Strict, True),
        (ComparisonMethod.IgnoreCrAtEol, False),
        (ComparisonMethod.IgnoreCrAtEolAndSpaceChange, False),
        (ComparisonMethod.IgnoreCrAtEolAndAllSpace, False),
    ],
    ids=["strict", "ignore_eol", "ignore_eol_space_change", "ignore_eol_all_space"],
)
def test_comparison_method_lf_vs_crlf_in_diffview(
        tempDir, mainWindow, method, expect_unified_diff):
    wd = unpackRepo(tempDir)
    if WINDOWS:
        with RepoContext(wd) as repo:
            repo.config["core.autocrlf"] = "false"

    relpath = "comp_eol.txt"
    _commit_text_file(wd, relpath, "hello\n")
    _set_worktree_text(wd, relpath, "hello\r\n")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged(relpath), check=True)
    _wait_unified_diff_visible(rw)

    _apply_comparison_method_and_refresh(mainWindow, method)
    if expect_unified_diff:
        _wait_unified_diff_visible(rw)
    else:
        _wait_no_change_special_visible(rw)
