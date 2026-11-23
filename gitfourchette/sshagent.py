# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.gitdriver import GitDriver
from gitfourchette.porcelain import GitConfigHelper
from gitfourchette.qt import *

logger = logging.getLogger(__name__)


class WindowsOpenSshError(Exception):
    """
    Git is set up to use OpenSSH for Windows, which can't use our ssh-agent.
    """


class SshAgent(QProcess):
    environment: dict[str, str]
    sandboxed: bool

    def __init__(self, parent: QObject, sandbox: bool = False):
        super().__init__(parent)
        self.setObjectName("SshAgent")

        program = "ssh-agent"

        if FLATPAK and sandbox:
            program = ToolCommands.FlatpakSandboxedCommandPrefix + program
            self.sandboxed = True
        else:
            self.sandboxed = False

        if WINDOWS:
            if self.isWindowsOpenSsh(GitConfigHelper.get_default_value("core.sshCommand")):
                raise WindowsOpenSshError()
            program = self.gitForWindowsProgram()

        tokens = [program, "-c", "-D"]
        process = self
        process.setProgram(tokens[0])
        process.setArguments(tokens[1:])
        ToolCommands.wrapFlatpakCommand(process)
        process.start()
        if not process.waitForStarted():
            raise RuntimeError("ssh-agent did not start")
        process.waitForReadyRead()

        output = process.readAll().data().decode("utf-8", errors="replace")

        pidMatch = re.search(r"Agent pid (.+);", output, re.IGNORECASE)
        sockMatch = re.search(r"setenv SSH_AUTH_SOCK (.+);", output)
        if not sockMatch or not pidMatch:
            raise ValueError("didn't find SSH_AUTH_SOCK or agent PID")

        # It's tempting to get the PID via QProcess instead of parsing stdout,
        # but remember that we may be launching ssh-agent via flatpak-spawn
        # (which has a separate PID).
        sshAgentPid = pidMatch.group(1)
        sshAuthSock = sockMatch.group(1)

        self.environment = {
            "SSH_AUTH_SOCK": sshAuthSock,
            "SSH_AGENT_PID": sshAgentPid,
        }

        logger.info(f"ssh-agent started on PID {sshAgentPid} ({sshAuthSock})")

    @staticmethod
    def gitForWindowsProgram() -> str:
        """
        Find the ssh-agent that ships with Git for Windows.

        Git runs its own ssh from the directory of its POSIX shell, and that ssh
        can only talk to the ssh-agent next to it. The ssh-agent on PATH is
        usually Windows' own, which only runs as a service.
        """
        shellPath = GitDriver.runSync("var", "GIT_SHELL_PATH", strict=True).strip()
        return str(Path(shellPath).with_name("ssh-agent.exe"))

    @staticmethod
    def isWindowsOpenSsh(sshCommand: str) -> bool:
        """
        Tell whether this command runs OpenSSH for Windows (the one that ships
        with Windows, or Win32-OpenSSH), which can't use Git's ssh-agent.
        """
        tokens = ToolCommands.splitCommandTokens(sshCommand)

        # Git runs a bare name like 'ssh' from its own directory, so only a path
        # can lead to another ssh
        if not tokens or not os.path.dirname(tokens[0]):
            return False

        # ssh -V prints its version to stderr, not stdout. Don't use runSync()
        # here: it only returns stdout.
        process = QProcess()
        process.setProgram(tokens[0])
        process.setArguments(tokens[1:] + ["-V"])
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.start()
        process.waitForFinished()

        output = process.readAll().data().decode(errors="replace")
        return "OpenSSH_for_Windows" in output

    def isSandboxed(self) -> bool:
        return self.sandboxed

    def askToExit(self, msec: int = 500):
        """
        Run 'ssh-agent -k', which sends SIGTERM to the agent so that it removes
        its socket as it exits.
        """
        process = QProcess(self)
        process.setProgram(self.program())
        process.setArguments(["-k"])
        ToolCommands.setQProcessEnvironment(process, self.environment)
        process.start()
        process.waitForFinished(msec)

    def stopAndWait(self, msec: int = 500):
        if self.state() != QProcess.ProcessState.Running:
            return

        # On Windows, terminate() can't stop a console program, and kill()
        # would leave the agent's socket behind.
        terminate = self.askToExit if WINDOWS else self.terminate

        for stop, name in (terminate, "SIGTERM"), (self.kill, "SIGKILL"):
            stop()
            if self.waitForFinished(msec):
                logger.info(f"ssh-agent stopped ({name})")
                break
            logger.warning(f"ssh-agent didn't respond to {name} after {msec} ms")
