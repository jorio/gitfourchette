# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import os
from pathlib import Path

from gitfourchette.application import GFApplication
from gitfourchette.ipc.ipcprotocol import GFIpcProtocol
from gitfourchette.ipc.ipcserver import GFIpcServer
from gitfourchette.localization import *
from gitfourchette.qt import *

logger = logging.getLogger(__name__)


class SingleInstanceSocket(GFIpcServer):
    """
    Socket created in the user's app config directory. Used to activate an
    existing instance of the application instead of starting a new instance.
    """

    restoreSession = Signal(list)

    def __init__(self, parent):
        socketPath = self.singleInstanceSocketPath()

        # On the very first run, the app config directory may not exist yet.
        # QLocalServer doesn't create intermediate directories, so bind would
        # fail with "Name error" if we didn't create it beforehand.
        socketPath.parent.mkdir(parents=True, exist_ok=True)

        super().__init__(parent, singleShot=False, socketPath=str(socketPath))
        self.clientConnected.connect(self._newConnection)

    @classmethod
    def singleInstanceSocketPath(cls) -> Path:
        # Keep it short! Full path cannot exceed 104-1 chars on macOS
        fileName = "instance.sock"

        if APP_TESTMODE:
            configPath = qTempDir()
        else:
            configPath = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)

        path = Path(configPath, fileName)
        return path

    @classmethod
    def connectToExistingInstance(cls, paths: list[str]) -> bool:
        raiseSocketPath = cls.singleInstanceSocketPath()

        if not raiseSocketPath.is_socket():
            return False

        handshake = GFIpcProtocol.Handshake(paths)

        try:
            GFIpcProtocol.simpleBlockingClient(
                str(raiseSocketPath),
                handshake,
                responseTimeout=GFIpcProtocol.FastTimeout)
            return True
        except TimeoutError:
            return False

    def _newConnection(self, handshake: GFIpcProtocol.Handshake, socket: QLocalSocket):
        paths = handshake.args

        message = _("Switching to running instance {pid}. Pass {switch} to start a new instance.",
                    pid=f"(PID {os.getpid()})",
                    switch="--" + GFApplication.OptionNamesNewInstance[-1])

        GFIpcProtocol.respondAndBail(socket, print=message)
        self.restoreSession.emit(paths)
