# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import re

from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.qt import *

logger = logging.getLogger(__name__)


class SshAgent(QProcess):
    environment: dict[str, str]

    def __init__(self, parent: QObject, sandbox: bool = False):
        super().__init__(parent)

        program = "ssh-agent"

        if FLATPAK and sandbox:
            program = ToolCommands.FlatpakSandboxedCommandPrefix + program

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

        pidMatch = re.search(r"Agent pid (.+);", output, re.I)
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
