# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.nav import NavLocator
from gitfourchette.settings import WhitespaceMode
from .util import *


def whitespaceOnlyChangesDetected(rw):
    return (rw.specialDiffView.isVisible()
            and findTextInWidget(rw.specialDiffView, r"whitespace changes ignored"))


@pytest.mark.parametrize(
    ("textA", "textB", "ignoredWith"),
    [
        (
            "a\tb\n",
            "a    c\n",
            [],
        ),
        (
            "a\tb\n",
            "a    b\n",
            [WhitespaceMode.IgnoreAll, WhitespaceMode.IgnoreChange],
        ),
        (
            "a b c\n",
            "a  b  c\n",
            [WhitespaceMode.IgnoreAll, WhitespaceMode.IgnoreChange],
        ),
        (
            "a bc\n",
            "a b c\n",
            [WhitespaceMode.IgnoreAll],
        ),
        (
            "a b c\n",
            "\ta b c\n",
            [WhitespaceMode.IgnoreAll],
        ),
        (
            "hello world\n",
            "hello   world\r\n",
            [WhitespaceMode.IgnoreAll, WhitespaceMode.IgnoreChange],
        ),
        (
            "hello world\n",
            "hello world\r\n",
            [WhitespaceMode.IgnoreAll, WhitespaceMode.IgnoreChange, WhitespaceMode.IgnoreCrAtEol],
        ),
    ]
)
def testDiffWhitespaceModes(tempDir, mainWindow, textA, textB, ignoredWith):
    wd = unpackRepo(tempDir)

    with RepoContext(wd) as repo:
        writeFile(f"{wd}/hello.txt", textA)
        repo.index.add("hello.txt")
        repo.create_commit_on_head("hello", TEST_SIGNATURE, TEST_SIGNATURE)
    writeFile(f"{wd}/hello.txt", textB)

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("hello.txt"), check=True)

    effectivelyIgnored = []

    for strategy in WhitespaceMode:
        mainWindow.onAcceptPrefsDialog({"whitespaceMode": strategy})

        if whitespaceOnlyChangesDetected(rw):
            effectivelyIgnored.append(strategy)

    assert sorted(effectivelyIgnored) == sorted(ignoredWith)


def testDiffWhitespaceModeButton(tempDir, mainWindow):
    """
    Changing comparison via reloadCurrentPatchForPrefs (Jump.invoke) must refresh
    the visible patch without selecting another file.
    """

    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/master.txt", "\tOn master\nOn master\n")

    rw = mainWindow.openRepo(wd)
    rw.jump(NavLocator.inUnstaged("master.txt"), check=True)

    menu = rw.diffArea.diffButtons.whitespaceModeButton.menu()
    assert findMenuAction(menu, "do not ignore").isChecked()

    triggerMenuAction(menu, "ignore all whitespace")
    assert whitespaceOnlyChangesDetected(rw)
    assert findMenuAction(menu, "ignore all whitespace").isChecked()

    triggerMenuAction(menu, "do not ignore")
    assert rw.diffView.isVisible()
    assert findMenuAction(menu, "do not ignore").isChecked()
