# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import functools
import sys
import threading
from collections.abc import Callable


def calledFromQThread(f: Callable):  # pragma: no cover
    """
    Add this decorator to functions that are called from within a QThread
    so pytest-cov can trace them correctly.
    """
    # Adapted from https://github.com/nedbat/coveragepy/issues/686#issuecomment-634932753

    if "coverage" not in sys.modules:
        return f

    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        sys.settrace(threading._trace_hook)  # type: ignore[attr-defined]
        return f(*args, **kwargs)

    return wrapped
