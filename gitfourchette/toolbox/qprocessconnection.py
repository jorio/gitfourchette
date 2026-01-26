# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from contextlib import suppress

from gitfourchette.qt import *


class QProcessConnection(QObject):
    """
    Emits processLost when a QProcess stops running or fails to start outright.
    """
    processLost = Signal()

    process: QProcess | None

    def __init__(self, parent):
        super().__init__(parent)
        self.process = None

    def __bool__(self):
        return self.process is not None

    def track(self, process: QProcess):
        assert process is not self.process, "reconnecting to same process"

        self.stopTracking()
        assert self.process is None

        self.process = process
        process.errorOccurred.connect(self.stopTracking)
        process.finished.connect(self.stopTracking)

    def stopTracking(self):
        process = self.process

        if process is not None:
            with suppress(TypeError, RuntimeError):
                process.finished.disconnect(self.stopTracking)
            with suppress(TypeError, RuntimeError):
                process.errorOccurred.disconnect(self.stopTracking)
            self.processLost.emit()

        self.process = None
        return process
