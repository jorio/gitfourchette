# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *


class QSignalConnectContext:
    def __init__(self, signal: SignalInstance, slot):
        self.signal = signal
        self.slot = slot

    def __enter__(self):
        self.connection = self.signal.connect(self.slot)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.signal.disconnect(self.connection)
