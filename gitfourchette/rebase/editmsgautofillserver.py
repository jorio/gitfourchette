# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
from pathlib import Path

from gitfourchette.ipc.ipcprotocol import GFIpcProtocol
from gitfourchette.ipc.ipcserver import GFIpcServer
from gitfourchette.qt import *
from gitfourchette.rebase.rebasemodel import RebaseInfo

logger = logging.getLogger(__name__)


class EditmsgAutoFillServer(GFIpcServer):
    """
    During an interactive rebase, automatically fills out .git/COMMIT_EDITMSG
    for commits that were reworded from our rebase dialog.

    Pass clientCommand() as the GIT_EDITOR environment variable to 'git rebase'.
    """

    def __init__(self, parent):
        # singleShot=False because a single 'git rebase -i' may call the editor
        # multiple times if there are several commits to reword.
        super().__init__(parent, singleShot=False)

        self.clientConnected.connect(self.onClientConnected)

    def onClientConnected(self, handshake: GFIpcProtocol.Handshake, socket: QLocalSocket):
        abortPayload = ""  # success

        try:
            assert len(handshake.args) == 1

            editmsgPath = Path(handshake.args[0])
            assert editmsgPath.name == "COMMIT_EDITMSG"

            rebaseInfo = RebaseInfo.parse(str(editmsgPath.parent))
            doneLast = rebaseInfo.doneSeq[-1]

            # If we stopped on a reword, dump the message
            if doneLast.op.isEditable() and doneLast.payload:
                editmsgPath.write_text(doneLast.payload, "utf-8")
            else:
                logger.debug(f"confirming verbatim commit message: {doneLast}")
        except Exception as ex:
            # Switch to non-graceful abort
            abortPayload = f"{self.__class__.__name__} failed: {ex.__class__.__name__}: {ex}"
        finally:
            # Always answer the client, otherwise 'git rebase' waits for it forever
            GFIpcProtocol.respondAndBail(socket, abort=abortPayload)
