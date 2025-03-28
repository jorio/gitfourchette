# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------
import dataclasses

import pytest

from gitfourchette.nav import NavLocator
from .util import *


@pytest.fixture
def commandsScratchFile(tempDir, mainWindow):
    shim = getTestDataPath("editor-shim.py")
    scratch = qTempDir() + "/scratch.txt"
    wrapper = f"python3 {shim} {scratch}"

    mainWindow.onAcceptPrefsDialog({
        "terminal": "/bin/sh -c $COMMAND",
        "commands": f"""
            {wrapper} 'hello world'
            {wrapper} $COMMIT       # Print Selected Commit
            {wrapper} $HEAD         # Print HEAD
            {wrapper} $WORKDIR      # Print Workdir
            {wrapper} $SELBRANCH    # Print Selected Branch
            {wrapper} $CURBRANCH    # Print Current Branch
            {wrapper} $FILE         # Print File Path
            {wrapper} $FILEDIR      # Print File Directory
        """})

    QTest.qWait(0)
    return scratch


@dataclasses.dataclass
class TokenParams:
    menuName: str
    output: str = ""
    locator: NavLocator = NavLocator.Empty

    def __repr__(self):
        return self.menuName


def testUserCommandsMenuHiddenByDefault(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    _rw = mainWindow.openRepo(wd)

    with pytest.raises(KeyError):
        findMenuAction(mainWindow.menuBar(), "commands/edit commands")

    mainWindow.onAcceptPrefsDialog({"commands": "helloworld"})
    QTest.qWait(0)
    assert findMenuAction(mainWindow.menuBar(), "commands/helloworld")
    assert findMenuAction(mainWindow.menuBar(), "commands/edit commands")


def testUserCommand(tempDir, mainWindow, commandsScratchFile):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    action = findMenuAction(mainWindow.menuBar(), "commands/hello world")
    action.trigger()
    acceptQMessageBox(rw, "run this command in a terminal.+hello world")

    assert "hello world" == readTextFile(commandsScratchFile, 1000)


locOriginMaster = NavLocator.inCommit(Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0"), "a/a1")
locNoParent = NavLocator.inCommit(Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1"), "c/c1.txt")

@pytest.mark.parametrize("params",
    [
        TokenParams("Print Selected Commit", str(locOriginMaster.commit), locOriginMaster),
        TokenParams("Print Workdir", "/TestGitRepository"),
        TokenParams("Print HEAD", "c9ed7bf12c73de26422b7c5a44d74cfce5a8993b"),
        TokenParams("Print Current Branch", "refs/heads/master"),
        TokenParams("Print Selected Branch", "refs/heads/no-parent", locNoParent),
        TokenParams("Print File Path", "/TestGitRepository/a/a1$", locOriginMaster),
        TokenParams("Print File Directory", "/TestGitRepository/a$", locOriginMaster),
    ])
def testUserCommandTokens(tempDir, mainWindow, commandsScratchFile, params):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    if params.locator != NavLocator.Empty:
        rw.jump(params.locator, check=True)

    action = findMenuAction(mainWindow.menuBar(), "commands/" + params.menuName)
    action.trigger()
    acceptQMessageBox(rw, "run this command in a terminal.+shim.+")

    output = readTextFile(commandsScratchFile, 1000).strip()
    assert re.search(params.output, output)


@pytest.mark.parametrize(["menuName", "error"],
     [
         ("Print Selected Commit", "a commit must be selected"),
         ("Print Selected Branch", "a local branch must be selected"),
         ("Print File Path", "a file must be selected"),
         ("Print File Dir", "a file must be selected"),
     ])
def testUserCommandTokenPrerequisitesNotMet(tempDir, mainWindow, commandsScratchFile, menuName, error):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    action = findMenuAction(mainWindow.menuBar(), "commands/" + menuName)
    action.trigger()
    rejectQMessageBox(rw, "prerequisites for your command are not met.+" + error)
