# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import shlex
import uuid
from pathlib import Path

from gitfourchette import settings
from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.ipc.ipcprotocol import GFIpcProtocol
from gitfourchette.qt import *

logger = logging.getLogger(__name__)


class GFIpcServer(QLocalServer):
    clientConnected = Signal(GFIpcProtocol.Handshake, QLocalSocket)
    _globalSocketCounter = 0

    socketPath: str

    def __init__(
            self,
            parent: QObject,
            singleShot: bool,
            startNow: bool = True,
            socketPath: str = "",
    ):
        super().__init__(parent)

        self.singleShot = singleShot
        self.socketNumber = GFIpcServer._globalSocketCounter
        GFIpcServer._globalSocketCounter += 1

        if not socketPath:
            if WINDOWS:
                socketPath = f"{APP_SYSTEM_NAME}-{uuid.uuid4()}"
            else:
                socketPath = str(Path(qTempDir(), f"ipc{self.socketNumber}.sock"))
        if len(socketPath) >= 104:  # pragma: no cover
            logger.warning(f"very long socket path may fail on some platforms: {socketPath}")
        self.socketPath = socketPath

        self.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.setMaxPendingConnections(1)
        self.newConnection.connect(self.onNewConnection)

        if startNow:
            isListening = self.listenOnSocketPath()
            logger.debug(f"IPC server listening on {self.socketPath}: {isListening} -- {self.errorString()} -- {self.fullServerName()}")
            assert isListening, self.errorString()

    def listenOnSocketPath(self) -> bool:
        return self.listen(self.socketPath)

    def onNewConnection(self):
        socket = self.nextPendingConnection()
        assert socket is not None
        logger.debug(f"New connection on {socket.fullServerName()} [{socket.serverName()}]")
        assert socket.isValid()
        assert socket.isOpen()

        # Single-shot server: Stop listening for any additional connections
        if self.singleShot:
            self.close()

        # Get handshake from client
        socket.readyRead.connect(lambda: self.onReadyReadGetHandshakeFromClient(socket))

    def onReadyReadGetHandshakeFromClient(self, socket: QLocalSocket):
        try:
            payload = GFIpcProtocol.readMessage(socket, GFIpcProtocol.Handshake)
        except (TypeError, ValueError) as ex:
            logger.warning(f"Did not get client handshake: {ex}")
            socket.close()
            return

        logger.debug(f"Got client handshake: {payload}")
        self.clientConnected.emit(payload, socket)

    def clientCommand(self, askpass: bool = False) -> str:
        """
        Return a command starting an IPC client that connects to this server.
        """

        sandbox = settings.prefs.isGitSandboxed()
        infix1 = f"ask{self.socketNumber}" if askpass else ""
        infix2 = "s" if sandbox else ""
        fileName = f"ipc{infix1}{infix2}.sh"
        launcherScript = Path(qTempDir(), fileName)

        # Generate kicker script
        if not ToolCommands.untamperedScriptExists(launcherScript):
            tokens, env = ToolCommands.spawnNewInstance(GFIpcProtocol.__module__, sandbox=sandbox)

            # Askpass: embed socket path inside script
            if askpass:
                tokens += ["--askpass", self.socketPath, "--"]

            scriptText = "\n".join([
                "#!/usr/bin/env bash",
                *(f"export {shlex.quote(k + '=' + v)}" for k, v in env.items()),
                f'exec {shlex.join(tokens)} "$@"',
                "",
            ])

            ToolCommands.writeTamperProofScript(launcherScript, scriptText)

        if askpass:
            # Askpass must be a single token without any arguments
            return str(launcherScript)
        else:
            # Non-askpass: pass socket path on command line
            return shlex.join([str(launcherScript), self.socketPath])
