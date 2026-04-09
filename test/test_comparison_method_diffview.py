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
from gitfourchette.settings import ComparisonMethod
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
