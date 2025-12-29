# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import enum
import filecmp
import logging
import os
import shutil

from gitfourchette import settings
from gitfourchette.gitdriver import GitConflict
from gitfourchette.localization import *
from gitfourchette.porcelain import Repo
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

    _ongoingMerges: list[MergeDriver] = []
    _mergeCounter: int = 0

    statusChange = Signal()

    conflict: GitConflict
    process: QProcess | None
    processName: str
    state: State
    debrief: str

    def __init__(self, parent: QObject, repo: Repo, conflict: GitConflict):
        super().__init__(parent)

        logger.info(f"Initialize MergeDriver: {conflict}")
        self.conflict = conflict
        self.process = None
        self.processName = "?"
        self.state = MergeDriver.State.Idle
        self.debrief = ""

        assert conflict.ours, "MergeDriver requires an 'ours' side"
        assert conflict.theirs, "MergeDriver requires a 'theirs' side"

        # Keep a reference to mergeDir so the temporary directory doesn't vanish
        self.mergeDir = QTemporaryDir(os.path.join(qTempDir(), "merge"))
        # self.mergeDir = tempfile.TemporaryDirectory(dir=qTempDir(), prefix="merge-", ignore_cleanup_errors=True)
        # mergeDirPath = self.mergeDir.name
        MergeDriver._mergeCounter += 1
        mergeDirPath = self.mergeDir.path()

        # Dump OURS and THEIRS blobs into the temporary directory
        self.oursPath = conflict.ours.dump(repo, mergeDirPath, "[OURS]")
        self.theirsPath = conflict.theirs.dump(repo, mergeDirPath, "[THEIRS]")

        oursPath = conflict.ours.path
        baseName = os.path.basename(oursPath)
        self.targetPath = repo.in_workdir(oursPath)
        self.relativeTargetPath = oursPath

        if conflict.ancestor:
            # Dump ANCESTOR blob into the temporary directory
            self.ancestorPath = conflict.ancestor.dump(repo, mergeDirPath, "[ANCESTOR]")
        else:
            # There's no ancestor! Some merge tools can fake a 3-way merge without
            # an ancestor (e.g. PyCharm), but others won't (e.g. VS Code).
            # To make sure we get a 3-way merge, copy our current workdir file as
            # the fake ANCESTOR file. It should contain chevron conflict markers
            # (<<<<<<< >>>>>>>) which should trigger conflicts between OURS and
            # THEIRS in the merge tool.
            self.ancestorPath = os.path.join(mergeDirPath, f"[NO-ANCESTOR]{baseName}")
            shutil.copyfile(self.targetPath, self.ancestorPath)

        # Create scratch file (merge tool output).
        # Some merge tools (such as VS Code) use the contents of this file
        # as a starting point, so copy the workdir version for this purpose.
        self.scratchPath = os.path.join(mergeDirPath, f"[MERGED]{baseName}")
        shutil.copyfile(self.targetPath, self.scratchPath)

        # Keep track of this merge
        MergeDriver._ongoingMerges.append(self)
        self.destroyed.connect(lambda: MergeDriver._forget(id(self)))

    def deleteNow(self):
        MergeDriver._forget(id(self))
        # TODO: Terminate process?
        self.deleteLater()

    def startProcess(self, reopenWorkInProgress=False):
        tokens = {
            "$B": self.scratchPath if reopenWorkInProgress else self.ancestorPath,
            "$L": self.oursPath,
            "$R": self.theirsPath,
            "$M": self.scratchPath
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
                or filecmp.cmp(self.scratchPath, self.targetPath)):
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
        shutil.copyfile(self.scratchPath, self.targetPath)

    @classmethod
    def findOngoingMerge(cls, conflict: GitConflict) -> MergeDriver | None:
        try:
            return next(m for m in cls._ongoingMerges if m.conflict == conflict)
        except StopIteration:
            return None

    @classmethod
    def _forget(cls, deadId: int):
        cls._ongoingMerges = [x for x in cls._ongoingMerges if id(x) != deadId]
