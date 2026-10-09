# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import json
import shlex
import sys
from collections.abc import Iterator

import pytest

from gitfourchette import settings
from gitfourchette.sidebar.sidebarmodel import SidebarItem
from gitfourchette.sshagent import SshAgent
from gitfourchette.tasks import RepoTask, RepoTaskRunner
from .util import *


class SupportingWidget(QLabel):
    cleanup = Signal()

    def __init__(self):
        super().__init__(None)

        self.setContentsMargins(32, 32, 32, 32)
        self.setText("<h3>Supporting widget for RepoTaskRunner")

        self.taskRunner = RepoTaskRunner(self)
        self.cleanup.connect(self.taskRunner.prepareForDeletion)

    def closeEvent(self, event):
        self.cleanup.emit()
        super().closeEvent(event)


@pytest.fixture
def taskRunner(qapp) -> Iterator[RepoTaskRunner]:
    widget = SupportingWidget()
    widget.show()
    assert not widget.taskRunner.isBusy()
    yield widget.taskRunner
    widget.deleteLater()


def testTaskKilled(taskRunner):
    parentWidget: QWidget = taskRunner.parent()

    class HelloA(RepoTask):
        def flow(self):
            yield from self.flowConfirm("HelloA-1")
            yield from self.flowConfirm("HelloA-2")

    HelloA.invoke(taskRunner)
    taskRunner.killCurrentTask()
    acceptQMessageBox(parentWidget, "HelloA-1")
    with pytest.raises(KeyError):
        acceptQMessageBox(parentWidget, "HelloA-2")


def testTaskKillOtherTask(taskRunner):
    parentWidget: QWidget = taskRunner.parent()

    class HelloA(RepoTask):
        def flow(self):
            yield from self.flowConfirm("HelloA-1")
            yield from self.flowConfirm("HelloA-2")

    class HelloB(RepoTask):
        def canKill(self, task: RepoTask) -> bool:
            return isinstance(task, HelloA)

        def flow(self):
            yield from self.flowConfirm("HelloB")

    HelloA.invoke(taskRunner)
    HelloB.invoke(taskRunner)

    acceptQMessageBox(parentWidget, "HelloA-1")
    acceptQMessageBox(parentWidget, "HelloB")


def testTaskQueueing(taskRunner):
    parentWidget: QWidget = taskRunner.parent()

    class HelloA(RepoTask):
        def flow(self):
            yield from self.flowConfirm("HelloA")

    class HelloB(RepoTask):
        def flow(self):
            yield from self.flowConfirm("HelloB")

    class HelloC(RepoTask):
        def flow(self):
            yield from self.flowConfirm("HelloC")

    HelloA.invoke(taskRunner)

    # Can only queue a single task at once - HelloC will override HelloB
    HelloB.invoke(taskRunner)
    HelloC.invoke(taskRunner)

    acceptQMessageBox(parentWidget, "HelloA")
    acceptQMessageBox(parentWidget, "HelloC")


def testTaskQueueingAbortedByClosedParent(taskRunner, taskThread):
    parentWidget: QWidget = taskRunner.parent()

    class HelloA(RepoTask):
        def flow(self):
            waitMillis = 3_000
            sleepUnit = 100
            for _dummy in range(waitMillis // sleepUnit):
                print("Waiting...", _dummy)
                yield from self.flowEnterWorkerThread()
                QThread.msleep(sleepUnit)
            yield from self.flowEnterUiThread()
            yield from self.flowConfirm("this should not appear A")

    class HelloB(RepoTask):
        def flow(self):
            yield from self.flowConfirm("this should not appear B")

    # Start HelloA, wait for background thread to start
    assert not taskRunner._workerThread.isRunning()
    HelloA.invoke(taskRunner)
    waitUntilTrue(taskRunner._workerThread.isRunning)

    # Enqueue HelloB
    HelloB.invoke(taskRunner)

    # While HelloA is still running and HelloB is pending, close the widget
    parentWidget.close()

    # Wait for task runner to wind down
    waitUntilTrue(lambda: not taskRunner.isBusy())
    assert not parentWidget.isVisible()

    # Make sure BOTH tasks were properly interrupted
    with pytest.raises(KeyError):
       acceptQMessageBox(parentWidget, "this should not appear")


# -----------------------------------------------------------------------------
# SSH options passed to vanilla git by RepoTask.createGitProcess

FAKE_AGENT_ENV = {
    "SSH_AUTH_SOCK": "/gftest/fake-agent.sock",
    "SSH_AGENT_PID": "424242",
    SshAgent.EnvBuiltInAgentPid: "424242",
}


class FakeSshAgent:
    """ Stand-in for GFApplication.sshAgent that doesn't spawn a real ssh-agent. """

    def __init__(self):
        self.environment = dict(FAKE_AGENT_ENV)

    def isSandboxed(self):
        return False

    def stopAndWait(self, msec=500):
        pass

    def deleteLater(self):
        pass


def makeSshTask(rw=None, parent=None) -> RepoTask:
    task = RepoTask(parent or rw)
    if rw is not None:
        task.setRepoModel(rw.repoModel)
    return task


def gitSshCommandTokens(process: QProcess) -> list[str]:
    env = process.processEnvironment()
    assert env.contains("GIT_SSH_COMMAND")
    return shlex.split(env.value("GIT_SSH_COMMAND"))


def testCreateGitProcessNoSshOptions(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    assert not rw.repoModel.prefs.customKeyFile
    assert not settings.prefs.ownSshAgent

    process = makeSshTask(rw).createGitProcess("fetch")
    env = process.processEnvironment()
    assert env.value("LC_ALL") == "C.UTF-8"
    # GIT_SSH_COMMAND must not be overridden if there are no custom SSH options
    assert env.value("GIT_SSH_COMMAND", "") == os.environ.get("GIT_SSH_COMMAND", "")
    assert Path(process.workingDirectory()) == Path(wd)


def testCreateGitProcessCustomKeyFromRepoPrefs(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    keyPath = str(Path(tempDir.name, "my key"))
    rw.repoModel.prefs.customKeyFile = keyPath

    # The user's custom core.sshCommand must be preserved, including its arguments
    rw.repo.config["core.sshCommand"] = "my-ssh --gftest-flag 'quoted arg'"

    process = makeSshTask(rw).createGitProcess("fetch")
    assert gitSshCommandTokens(process) == [
        "my-ssh", "--gftest-flag", "quoted arg",
        "-i", keyPath, "-o", "IdentitiesOnly=yes"]


def testCreateGitProcessExplicitCustomKeyOverridesRepoPrefs(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.repoModel.prefs.customKeyFile = "/gftest/repo-key"
    rw.repo.config["core.sshCommand"] = "my-ssh"

    process = makeSshTask(rw).createGitProcess("fetch", customKey="/gftest/explicit-key")
    assert gitSshCommandTokens(process) == [
        "my-ssh", "-i", "/gftest/explicit-key", "-o", "IdentitiesOnly=yes"]


def testCreateGitProcessCustomKeyDefaultSshCommand(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.repoModel.prefs.customKeyFile = "/gftest/key"

    # Blank out core.sshCommand (masking the test suite's global config)
    rw.repo.config["core.sshCommand"] = ""

    process = makeSshTask(rw).createGitProcess("fetch")
    assert gitSshCommandTokens(process) == [
        "/usr/bin/ssh", "-i", "/gftest/key", "-o", "IdentitiesOnly=yes"]


def testCreateGitProcessCustomKeyWithoutRepo(tempDir, mainWindow):
    # E.g. cloning: there's no repo yet, so core.sshCommand comes from the global config
    from gitfourchette.porcelain import GitConfigHelper

    globalSshCommand = GitConfigHelper.get_default_value("core.sshCommand")
    assert globalSshCommand  # set up by conftest (isolated-ssh)

    task = makeSshTask(parent=mainWindow)
    assert task.repo is None
    process = task.createGitProcess("clone", customKey="/gftest/key", workdir=tempDir.name)
    assert gitSshCommandTokens(process) == [
        *ToolCommands.splitCommandTokens(globalSshCommand),
        "-i", "/gftest/key", "-o", "IdentitiesOnly=yes"]
    assert Path(process.workingDirectory()) == Path(tempDir.name)


def testCreateGitProcessBuiltInSshAgent(tempDir, mainWindow, monkeypatch):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.repo.config["core.sshCommand"] = "my-ssh -v"

    monkeypatch.setattr(settings.prefs, "ownSshAgent", True)
    monkeypatch.setattr(GFApplication.instance(), "sshAgent", FakeSshAgent())

    # Agent only
    process = makeSshTask(rw).createGitProcess("fetch")
    env = process.processEnvironment()
    for key, value in FAKE_AGENT_ENV.items():
        assert env.value(key) == value
    assert gitSshCommandTokens(process) == ["my-ssh", "-v", "-o", "AddKeysToAgent=yes"]

    # Agent + custom key file
    rw.repoModel.prefs.customKeyFile = "/gftest/key"
    process = makeSshTask(rw).createGitProcess("fetch")
    assert process.processEnvironment().value("SSH_AUTH_SOCK") == FAKE_AGENT_ENV["SSH_AUTH_SOCK"]
    assert gitSshCommandTokens(process) == [
        "my-ssh", "-v",
        "-o", "AddKeysToAgent=yes",
        "-i", "/gftest/key", "-o", "IdentitiesOnly=yes"]


def testCreateGitProcessBuiltInSshAgentNotRunning(tempDir, mainWindow, monkeypatch):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    # Pref is on, but the agent couldn't be started
    monkeypatch.setattr(settings.prefs, "ownSshAgent", True)
    monkeypatch.setattr(GFApplication.instance(), "sshAgent", None)

    process = makeSshTask(rw).createGitProcess("fetch")
    env = process.processEnvironment()
    assert env.value("GIT_SSH_COMMAND", "") == os.environ.get("GIT_SSH_COMMAND", "")
    assert env.value("SSH_AUTH_SOCK", "") == os.environ.get("SSH_AUTH_SOCK", "")


@pytest.mark.skipif(not shutil.which("ssh-agent"), reason="Requires ssh-agent")
@pytest.mark.skipif(FLATPAK, reason="Not testing sandboxed ssh-agent")
def testCreateGitProcessRealSshAgent(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)
    rw.repo.config["core.sshCommand"] = "my-ssh"

    app = GFApplication.instance()
    app.applyPrefs(ownSshAgent=True)
    assert app.sshAgent is not None

    try:
        process = makeSshTask(rw).createGitProcess("fetch")
        env = process.processEnvironment()
        assert env.value("SSH_AUTH_SOCK") == app.sshAgent.environment["SSH_AUTH_SOCK"]
        assert env.value("SSH_AGENT_PID") == app.sshAgent.environment["SSH_AGENT_PID"]
        assert gitSshCommandTokens(process) == ["my-ssh", "-o", "AddKeysToAgent=yes"]
    finally:
        app.applyPrefs(ownSshAgent=False)
    assert app.sshAgent is None


SSH_SHIM_SOURCE = """\
import json, os, sys
with open(sys.argv[1], "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": sys.argv[2:], "SSH_AUTH_SOCK": os.environ.get("SSH_AUTH_SOCK", "")}) + "\\n")
sys.stderr.write("gftest ssh shim: connection refused\\n")
sys.exit(255)
"""


@pytest.mark.skipif(FLATPAK, reason="Host python shim may not be reachable from sandboxed git")
def testFetchPassesSshOptionsToCustomSshCommand(tempDir, mainWindow, monkeypatch):
    """
    End-to-end: run a real 'git fetch' against an ssh:// remote, with
    core.sshCommand pointing to a shim that dumps its arguments instead of
    connecting anywhere.
    """
    wd = unpackRepo(tempDir)
    shimPath = Path(tempDir.name, "ssh-shim.py")
    dumpPath = Path(tempDir.name, "ssh-shim-dump.jsonl")
    writeFile(str(shimPath), SSH_SHIM_SOURCE)

    sshCommand = shlex.join([
        Path(sys.executable).as_posix(), shimPath.as_posix(), dumpPath.as_posix(), "--gftest-custom-flag"])
    keyPath = Path(tempDir.name, "keyfile").as_posix()

    with RepoContext(wd) as repo:
        repo.config["core.sshCommand"] = sshCommand
        repo.remotes.set_url("origin", "ssh://gftest@gftest-host.invalid/fake/repo.git")

    rw = mainWindow.openRepo(wd)
    rw.repoModel.prefs.customKeyFile = keyPath
    monkeypatch.setattr(settings.prefs, "ownSshAgent", True)
    monkeypatch.setattr(GFApplication.instance(), "sshAgent", FakeSshAgent())

    node = rw.sidebar.findNode(lambda n: n.kind == SidebarItem.Remote and n.data == "origin")
    menu = rw.sidebar.makeNodeMenu(node)
    triggerMenuAction(menu, "fetch")

    waitUntilTrue(lambda: not rw.taskRunner.isBusy())
    acceptQMessageBox(rw, "gftest ssh shim: connection refused")

    # Git may probe the ssh variant with '-G' first; look at the actual connection attempt.
    invocations = [json.loads(line) for line in dumpPath.read_text("utf-8").splitlines()]
    connectAttempts = [i for i in invocations if any("gftest-host.invalid" in a for a in i["argv"])]
    assert connectAttempts
    for invocation in connectAttempts:
        argv = invocation["argv"]
        assert argv[:7] == [
            "--gftest-custom-flag",
            "-o", "AddKeysToAgent=yes",
            "-i", keyPath, "-o", "IdentitiesOnly=yes"]
        assert invocation["SSH_AUTH_SOCK"] == FAKE_AGENT_ENV["SSH_AUTH_SOCK"]
