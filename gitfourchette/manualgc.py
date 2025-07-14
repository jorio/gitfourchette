# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Qt objects should always be collected on the main thread. However, Python's
automatic garbage collector may kick in at any time, including on a background
thread - possibly causing Qt to crash.

Import this module to turn off automatic GC and call gcHint() to collect the
garbage at opportune times.
"""

import gc
import logging

from gitfourchette.appconsts import APP_DEBUG
from gitfourchette.toolbox import onAppThread as _onAppThread

_logger = logging.getLogger(__name__)

gc.disable()


if APP_DEBUG:
    def checkNoGcOnBackgroundThreads(phase, _info):
        if phase == 'start' and not _onAppThread():
            _logger.warning("!!!DANGER!!! Garbage collection on non-UI thread!")

    gc.callbacks.append(checkNoGcOnBackgroundThreads)


def gcHint():
    assert _onAppThread(), "garbage collection should only occur on the UI thread"

    for gen, c, t in zip(range(3), gc.get_count(), gc.get_threshold(), strict=True):
        if c <= t:
            _logger.debug(f"GC gen {gen}: {c}/{t}, stop")
            break
        num = gc.collect(gen)
        _logger.debug(f"GC gen {gen}: {c}/{t}, {num}")
