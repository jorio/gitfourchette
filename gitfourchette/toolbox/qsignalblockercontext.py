# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import warnings
import weakref

from gitfourchette.qt import *


class QSignalBlockerContext:
    """
    Context manager wrapper around QSignalBlocker.
    """

    nestingLevels: dict[weakref.ReferenceType[QObject], int] = {}  # Map object id to nesting depth
    concurrentBlockers = 0

    def __init__(self, *objectsToBlock: QObject):
        self.objectsToBlock = [weakref.ref(o) for o in objectsToBlock]

    def __enter__(self):
        self.concurrentBlockers += 1

        for ref in self.objectsToBlock:
            o = ref()
            assert o is not None
            self.nestingLevels[ref] = self.nestingLevels.get(ref, 0) + 1
            if self.nestingLevels[ref] == 1:
                # Block signals if we're the first QSignalBlockerContext to refer to this object
                if o.signalsBlocked():  # pragma: no cover
                    warnings.warn(f"QSignalBlockerContext: object signals already blocked! {o}")
                o.blockSignals(True)

    def __exit__(self, excType, excValue, excTraceback):
        for ref in self.objectsToBlock:
            o = ref()
            if o is None:
                del self.nestingLevels[ref]
            else:
                self.nestingLevels[ref] -= 1
                assert self.nestingLevels[ref] >= 0
                # Unblock signals if we were holding last remaining reference to this object
                if self.nestingLevels[ref] == 0:
                    o.blockSignals(False)
                    del self.nestingLevels[ref]

        self.concurrentBlockers -= 1
        assert self.concurrentBlockers >= 0
        assert self.concurrentBlockers != 0 or not self.concurrentBlockers
