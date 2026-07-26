# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import dataclasses
import enum
import filecmp
import logging
import shutil
from typing import ClassVar

from gitfourchette import settings
from gitfourchette.gitdriver import GitConflict
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *
from gitfourchette.exttools.toolprocess import ToolProcess

logger = logging.getLogger(__name__)


class MergeDriver(QObject):
    class State(enum.IntEnum):
        Idle = 0
        Busy = 1
        Fail = 2
        Ready = 3

    @dataclasses.dataclass
    class MergeFiles:
        ours: str
        theirs: str
        ancestor: str
        scratch: str
        target: str

    _ongoingMerges: ClassVar[list[MergeDriver]] = []
    _mergeCounter: ClassVar[int] = 0

    statusChange = Signal()

    conflict: GitConflict
    paths: MergeFiles
    process: QProcess | None
    processName: str
    state: State
    debrief: str

    def __init__(self, parent: QObject, conflict: GitConflict, paths: MergeFiles):
        super().__init__(parent)

        logger.info(f"Initialize MergeDriver: {conflict}")
        self.conflict = conflict
        self.paths = paths
        self.process = None
        self.processName = "?"
        self.state = MergeDriver.State.Idle
        self.debrief = ""

        assert conflict.ours, "MergeDriver requires an 'ours' side"
        assert conflict.theirs, "MergeDriver requires a 'theirs' side"

        # Keep track of this merge
        MergeDriver._mergeCounter += 1
        MergeDriver._ongoingMerges.append(self)
        self.destroyed.connect(lambda: MergeDriver._forget(self))

    def deleteNow(self):
        MergeDriver._forget(self)
        # TODO: Terminate process?
        self.deleteLater()

    def startProcess(self, reopenWorkInProgress=False):
        paths = self.paths
        tokens = {
            "$B": paths.scratch if reopenWorkInProgress else paths.ancestor,
            "$L": paths.ours,
            "$R": paths.theirs,
            "$M": paths.scratch,
        }
        parentWidget = findParentWidget(self)
        self.process = ToolProcess.startProcess(parentWidget, ToolProcess.PrefKeyMergeTool, replacements=tokens, positional=[])
        if not self.process:
            return
        self.processName = settings.getMergeToolName()
        self.process.errorOccurred.connect(self.onMergeProcessError)
        self.process.finished.connect(self.onMergeProcessFinished)
        self.state = MergeDriver.State.Busy
        self.debrief = ""

    def onMergeProcessError(self, error: QProcess.ProcessError):
        logger.warning(f"Merge tool error {error}")

        self.state = MergeDriver.State.Fail

        if error == QProcess.ProcessError.FailedToStart:
            self.debrief = _("{0} failed to start.", tquo(self.processName))
        else:
            errorName = str(error) if PYQT5 else error.name
            self.debrief = _("{0} ran into error {1}.", tquo(self.processName), errorName)

        self.flush()

    def onMergeProcessFinished(self, exitCode: int, exitStatus: QProcess.ExitStatus):
        if (exitCode != 0
                or exitStatus == QProcess.ExitStatus.CrashExit
                or filecmp.cmp(self.paths.scratch, self.paths.target)):
            informalPid = self.process.processId() if self.process else '???'
            logger.warning(f"Merge tool PID {informalPid} finished with code {exitCode}, {exitStatus}")
            self.state = MergeDriver.State.Fail
            self.debrief = _("{0} didn’t complete the merge.", tquo(self.processName))
            self.debrief += "\n" + _("Exit code: {0}.", exitCode)
        else:
            self.state = MergeDriver.State.Ready
            self.debrief = ""

        self.flush()

    def flush(self):
        if self.process is not None:
            self.process.deleteLater()
            self.process = None
        self.statusChange.emit()

    def copyScratchToTarget(self):
        shutil.copyfile(self.paths.scratch, self.paths.target)

    @classmethod
    def findOngoingMerge(cls, conflict: GitConflict) -> MergeDriver | None:
        return next((m for m in cls._ongoingMerges if m.conflict == conflict), None)

    @classmethod
    def _forget(cls, deadMerge: MergeDriver):
        cls._ongoingMerges = [x for x in cls._ongoingMerges if x is not deadMerge]
