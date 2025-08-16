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
    def __init__(self, parent: QObject):
        super().__init__(parent)
        process = self

        tokens = ["ssh-agent", "-c", "-D"]
        if FLATPAK:
            tokens = ToolCommands.wrapFlatpakSpawn(tokens, detached=False)

        process.setProgram(tokens[0])
        process.setArguments(tokens[1:])
        process.start()
        if not process.waitForStarted():
            raise RuntimeError("ssh-agent did not start")
        process.waitForReadyRead()
        output = process.readAll().data().decode("utf-8", errors="replace")
        match = re.match(r"setenv SSH_AUTH_SOCK (.+);", output)
        if not match:
            raise ValueError("didn't find SSH_AUTH_SOCK")
        sshAuthSock = match.group(1)
        self.sshAuthSock = sshAuthSock

        logger.info(f"ssh-agent started ({sshAuthSock})")

    def environment(self):
        return {
            "SSH_AGENT_PID": str(self.processId()),
            "SSH_AUTH_SOCK": self.sshAuthSock,
        }
