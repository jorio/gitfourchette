# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import argparse
import dataclasses
import os
import sys

from typing import TypeVar

from gitfourchette import jsonfriendly
from gitfourchette.qt import *


class GFIpcProtocol:
    FastTimeout = 5_000 if not CI_TESTMODE else 20_000  # timeout for "instantaneous" client/server comms
    UserTimeout = -1  # timeout when waiting for user input
    MaxPayloadSize = 4096

    @dataclasses.dataclass
    class Handshake:
        args: list[str]
        env: dict[str, str] = dataclasses.field(default_factory=dict)

    @dataclasses.dataclass
    class Response:
        print: str = ""
        abort: str = ""

    _THandshakeResponse = TypeVar("_THandshakeResponse", bound=Handshake | Response)

    @classmethod
    def writeMessage(cls, socket: QLocalSocket, payloadObj: Handshake | Response) -> int:
        """
        Serialize a message over the socket.
        """

        payloadJson = jsonfriendly.toJson(payloadObj)
        payloadBytes = payloadJson.encode("utf-8", errors="replace")
        assert len(payloadBytes) <= cls.MaxPayloadSize
        writeResult = socket.write(payloadBytes)
        assert writeResult == len(payloadBytes)
        return writeResult

    @classmethod
    def respondAndBail(cls, socket: QLocalSocket, print: str = "", abort: str = "") -> None:
        response = GFIpcProtocol.Response(print, abort)
        cls.writeMessage(socket, response)
        socket.disconnectFromServer()

        if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            socket.waitForDisconnected(GFIpcProtocol.FastTimeout)

    @classmethod
    def readMessage(cls, socket: QLocalSocket, t: type[_THandshakeResponse]) -> _THandshakeResponse:
        """
        Deserialize a dict from the socket.
        May raise TimeoutError if the message couldn't be read in due time,
        or TypeError/ValueError if the payload doesn't honor protocol.
        """

        assert socket.bytesAvailable() > 0, "did you forget to wait for readyRead?"
        assert socket.state() == QLocalSocket.LocalSocketState.ConnectedState

        payloadBytes = socket.read(cls.MaxPayloadSize)
        if PYSIDE6:  # PySide6 returns a QByteArray
            payloadBytes = bytes(payloadBytes)
        assert isinstance(payloadBytes, bytes)

        payloadObj, version = jsonfriendly.fromJson(payloadBytes, t)

        if version != APP_VERSION:
            raise ValueError(f"incompatible protocol version '{version}' (expected: '{APP_VERSION}')")

        return payloadObj

    @classmethod
    def simpleBlockingClient(
            cls,
            socketPath: str,
            handshakeObj: Handshake,
            fastTimeout: int = FastTimeout,
            responseTimeout: int = UserTimeout,
            parent=None,
    ) -> Response:
        """
        Connect to a server, send a handshake, get the response, disconnect.
        Return the response dataclass.
        WARNING: This blocks the main thread, so don't use this if the UI is running.
        """

        socket = QLocalSocket(parent)
        socket.connectToServer(socketPath)

        try:
            if not socket.waitForConnected(fastTimeout):
                raise TimeoutError(f"{fastTimeout}ms timeout connecting - {socket.errorString()} - {socket.state()!r}")

            # Write handshake, but don't waitForBytesWritten, we'll await the response directly
            cls.writeMessage(socket, handshakeObj)

            if not socket.waitForReadyRead(responseTimeout):
                raise TimeoutError(f"{responseTimeout}ms timeout server response - {socket.errorString()} - {socket.state()!r}")

            responseObj = cls.readMessage(socket, t=GFIpcProtocol.Response)
        finally:
            socket.disconnectFromServer()
            socket.deleteLater()

        if responseObj.print:
            print(responseObj.print, flush=True)

        if responseObj.abort:
            print(responseObj.abort, file=sys.stderr)
            sys.exit(1)

        return responseObj

    @classmethod
    def clientMain(cls):
        parser = argparse.ArgumentParser()
        parser.add_argument("--askpass", action="store_true")
        parser.add_argument("socket")
        parser.add_argument("forward", nargs="*",
                            help="forward arguments, typically askpass")
        args = parser.parse_args()

        handshakeObj = GFIpcProtocol.Handshake(args.forward)

        if args.askpass:
            for var in ["SSH_ASKPASS_PROMPT", "SSH_AUTH_SOCK", "SSH_AGENT_PID"]:
                handshakeObj.env[var] = os.environ.get(var, "")

        return cls.simpleBlockingClient(args.socket, handshakeObj)


# Required for PyInstaller app bundle
def main():
    GFIpcProtocol.clientMain()


if __name__ == '__main__':
    main()
