# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.graphview.commitlogdelegate import CommitLogDelegate
from gitfourchette.localization import *
from gitfourchette.qt import *


class BlameScrubberDelegate(CommitLogDelegate):
    def isBold(self, index):
        return False

    def paintPrivate(self, painter, option, rect, oid, toolTips):
        pass

    def uncommittedChangesMessage(self) -> str:
        return _("Uncommitted Changes in Working Directory")
