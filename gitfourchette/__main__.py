# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import signal
import sys

from gitfourchette.qt import *


def excepthook(exctype, value, tb):
    sys.__excepthook__(exctype, value, tb)  # run default excepthook

    from gitfourchette.toolbox import excMessageBox
    excMessageBox(value, printExc=False)


def main():
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.WARNING,
        format='%(levelname).1s %(asctime)s %(filename)-16s | %(message)s',
        datefmt="%H:%M:%S")
    logging.captureWarnings(True)

    # inject our own exception hook to show an error dialog in case of unhandled exceptions
    # (note that this may get overridden when running under a debugger)
    sys.excepthook = excepthook

    # Initialize the application
    from gitfourchette.application import GFApplication
    app = GFApplication(sys.argv, __file__)

    # Quit app cleanly on Ctrl+C (all repos and associated file handles will be freed)
    def onSigint(*_dummy):
        # Deferring the quit to the next event loop gives the application
        # some time to wrap up the session.
        QTimer.singleShot(0, app.quit)
    signal.signal(signal.SIGINT, onSigint)

    # Force Python interpreter to run every now and then so it can run the Ctrl+C signal handler
    # (Otherwise the app won't actually die until the window regains focus, see https://stackoverflow.com/q/4938723)
    if __debug__:
        timer = QTimer()
        timer.start(300)
        timer.timeout.connect(lambda: None)

    app.beginSession()

    # Keep the app running
    returnCode = app.exec()
    sys.exit(returnCode)


if __name__ == "__main__":
    main()
