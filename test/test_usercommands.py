# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses

import pytest

from gitfourchette.nav import NavLocator
from gitfourchette.sidebar.sidebarmodel import SidebarItem, SidebarNode
from gitfourchette.usercommand import UserCommand
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

            {wrapper} $BADTOKEN         # Bad Token
            {wrapper} $COMMIT           # Sel Commit
            {wrapper} $FILE             # File Path
            {wrapper} $FILEDIR          # File Dir
            {wrapper} $FILEABS          # Abs File Path
            {wrapper} $FILEDIRABS       # Abs File Dir
            {wrapper} $HEAD             # HEA&D Commit
            {wrapper} $HEADBRANCH       # HEAD Branch
            {wrapper} $HEADUPSTREAM     # HEAD Upstream
            {wrapper} $REF              # Sel Ref
            {wrapper} $REMOTE           # Sel Remote
            {wrapper} $WORKDIR          # Workdir
            {wrapper} $COMMIT..$HEAD    # Diff Commit With HEAD
        """})

    QTest.qWait(0)
    return scratch


@dataclasses.dataclass
class TokenParams:
    menuName: str
    output: str = ""
    locator: NavLocator = NavLocator.Empty
    sidebarNode: tuple[SidebarItem, str] | None = None
    actionSource: str = "menu"

    def __repr__(self):
        return self.menuName + "," + self.actionSource

    @classmethod
    def parametrize(cls, argName: str, *ttp):
        ids = [repr(ttp) for ttp in ttp]
        return pytest.mark.parametrize(argName, ttp, ids=ids)


def testUserCommandsTokenDocumentation():
    docTable = UserCommand.tokenHelpTable()
    callbackPrefix = "eval"

    for token in docTable:
        tokenEnum = UserCommand.Token(token)
        assert hasattr(UserCommand, callbackPrefix + tokenEnum.name), f"{token} is documented but has no callback"

    for callbackName in dir(UserCommand):
        if not callbackName.startswith(callbackPrefix):
            continue
        tokenEnum = UserCommand.Token[callbackName.removeprefix(callbackPrefix)]
        assert tokenEnum in docTable, f"{callbackName} is not documented"


def testUserCommandsMenuHiddenByDefault(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    _rw = mainWindow.openRepo(wd)

    with pytest.raises(KeyError):
        findMenuAction(mainWindow.menuBar(), "commands/edit commands")

    mainWindow.onAcceptPrefsDialog({"commands": "helloworld"})
    QTest.qWait(0)
    assert findMenuAction(mainWindow.menuBar(), "commands/helloworld")
    assert findMenuAction(mainWindow.menuBar(), "commands/edit commands")


locOriginMaster = NavLocator.inCommit(Oid(hex="49322bb17d3acc9146f98c97d078513228bbf3c0"), "a/a1")
locNoParent = NavLocator.inCommit(Oid(hex="42e4e7c5e507e113ebbb7801b16b52cf867b7ce1"), "c/c1.txt")
locHead = NavLocator.inCommit(Oid(hex="c9ed7bf12c73de26422b7c5a44d74cfce5a8993b"), "c/c2-2.txt")


@TokenParams.parametrize(
    "params",

    TokenParams("hello world", "hello world"),

    TokenParams("sel commit", locOriginMaster.hash7, locOriginMaster),
    TokenParams("sel commit", locOriginMaster.hash7, locOriginMaster, actionSource="graphview"),

    TokenParams("workdir", "/TestGitRepository"),
    TokenParams("workdir", "/TestGitRepository", actionSource="graphview"),
    TokenParams("workdir", "/TestGitRepository", actionSource="sidebar"),

    TokenParams("head commit", locHead.hash7),
    TokenParams("head branch", "refs/heads/master"),
    TokenParams("head upstream", "refs/remotes/origin/master"),

    TokenParams("head commit", locHead.hash7, locHead, actionSource="sidebar"),
    TokenParams("head branch", "refs/heads/master", locHead, actionSource="sidebar"),

    TokenParams("sel ref", "refs/heads/no-parent", locNoParent),
    TokenParams("sel ref", "refs/heads/no-parent", locNoParent, actionSource="sidebar"),

    TokenParams("sel ref", "refs/remotes/origin/master", locOriginMaster),
    TokenParams("sel ref", "refs/remotes/origin/master", locOriginMaster, actionSource="sidebar"),

    TokenParams("file path", "^a/a1$", locOriginMaster),
    TokenParams("file dir", "^a$", locOriginMaster),
    TokenParams("abs file path", "/TestGitRepository/a/a1$", locOriginMaster),
    TokenParams("abs file dir", "/TestGitRepository/a$", locOriginMaster),

    TokenParams("file path", "^a/a1$", locOriginMaster, actionSource="filelist"),
    TokenParams("file dir", "^a$", locOriginMaster, actionSource="filelist"),
    TokenParams("abs file path", "/TestGitRepository/a/a1$", locOriginMaster, actionSource="filelist"),
    TokenParams("abs file dir", "/TestGitRepository/a$", locOriginMaster, actionSource="filelist"),

    TokenParams("sel remote", "^origin$", locOriginMaster),
    TokenParams("sel remote", "^origin$", locOriginMaster, actionSource="sidebar"),
    TokenParams("sel remote", "^origin$", sidebarNode=(SidebarItem.Remote, "origin")),
    TokenParams("sel remote", "^origin$", sidebarNode=(SidebarItem.Remote, "origin"), actionSource="sidebar"),

    TokenParams("diff commit with head", f"{locOriginMaster.hash7}..{locHead.hash7}", locOriginMaster),
    TokenParams("diff commit with head", f"{locOriginMaster.hash7}..{locHead.hash7}", locOriginMaster, actionSource="graphview"),
)
def testUserCommandTokens(tempDir, mainWindow, commandsScratchFile, params):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    if params.locator != NavLocator.Empty:
        rw.jump(params.locator, check=True)
        assert not params.sidebarNode, "define either a locator or a sidebar node, not both!"

    if params.sidebarNode:
        kind, data = params.sidebarNode
        node = rw.sidebar.findNode(lambda n: n.kind == kind and n.data == data)
        rw.sidebar.selectNode(node)

    if params.actionSource == "menu":
        menu = mainWindow.menuBar()
        action = findMenuAction(menu, "commands/" + params.menuName)
    elif params.actionSource == "graphview":
        menu = rw.graphView.makeContextMenu()
        action = findMenuAction(menu, "command: " + params.menuName)
    elif params.actionSource == "filelist":
        menu = rw.committedFiles.makeContextMenu()
        action = findMenuAction(menu, "command: " + params.menuName)
    elif params.actionSource == "sidebar":
        node = SidebarNode.fromIndex(rw.sidebar.selectedIndexes()[0])
        menu = rw.sidebar.makeNodeMenu(node)
        action = findMenuAction(menu, "command: " + params.menuName)
    else:
        raise NotImplementedError(f"unknown action source {params.actionSource}")

    action.trigger()
    acceptQMessageBox(rw, "run this command in a terminal.+shim.+")

    output = readTextFile(commandsScratchFile, 5000).strip()
    assert re.search(params.output, output)


@pytest.mark.parametrize(["scenario", "menuName", "error"], [
    ("",           "sel commit",       "a commit must be selected"),
    ("",           "sel ref",          "a ref.+must be selected"),
    ("",           "file path",        "a file must be selected"),
    ("",           "file dir",         "a file must be selected"),
    ("",           "abs file path",    "a file must be selected"),
    ("",           "abs file dir",     "a file must be selected"),
    ("",           "sel remote",       "a remote.+must be selected"),
    ("",           "bad token",        "unknown placeholder token.+BADTOKEN"),
    ("detach",     "head branch",      "head cannot be.+detached"),
    ("detach",     "head upstream",    "head cannot be.+detached"),
    ("unborn",     "head commit",      "head cannot be.+unborn"),
    ("unborn",     "head branch",      "head cannot be.+unborn"),
    ("unborn",     "head upstream",    "head cannot be.+unborn"),
    ("noupstream", "head upstream",    "current branch has no upstream"),
])
def testUserCommandTokenPrerequisitesNotMet(tempDir, mainWindow, commandsScratchFile, scenario, menuName, error):
    testRepoName = "TestGitRepository"
    if scenario == "unborn":
        testRepoName = "TestEmptyRepository"

    wd = unpackRepo(tempDir, testRepoName)

    with RepoContext(wd) as repo:
        if scenario == "noupstream":
            repo.edit_upstream_branch("master", "")
        elif scenario == "detach":
            repo.checkout_commit(locHead.commit)

    rw = mainWindow.openRepo(wd)

    action = findMenuAction(mainWindow.menuBar(), "commands/" + menuName)
    action.trigger()
    rejectQMessageBox(rw, "prerequisites for your command are not met.+" + error)


def testUserCommandWithoutConfirmation(tempDir, mainWindow, commandsScratchFile):
    mainWindow.openRepo(unpackRepo(tempDir))
    mainWindow.onAcceptPrefsDialog({"confirmRunCommand": False})

    triggerMenuAction(mainWindow.menuBar(), "commands/hello world")
    output = readTextFile(commandsScratchFile, 5000).strip()
    assert re.search(r"hello world", output)


@pytest.mark.skipif(MACOS, reason="no menu accelerator keys on macOS")
def testUserCommandAcceleratorKeys(tempDir, mainWindow, commandsScratchFile):
    wd = unpackRepo(tempDir)
    mainWindow.openRepo(wd)
    QTest.qWait(0)

    QTest.keySequence(mainWindow, "Alt+C")
    commandsMenu: QMenu = mainWindow.findChild(QMenu, "MWCommandsMenu")
    assert commandsMenu.isVisible()
    QTest.keySequence(commandsMenu, "Alt+D")  # For some reason, Alt+H doesn't work in offscreen tests

    acceptQMessageBox(mainWindow, "do you want to run this command in a terminal")

    output = readTextFile(commandsScratchFile, 5000).strip()
    assert re.search(locHead.hash7, output)
