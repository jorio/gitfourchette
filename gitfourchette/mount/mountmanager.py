# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import dataclasses
import logging
import shlex
import sys
from contextlib import suppress
from pathlib import Path

from gitfourchette import settings
from gitfourchette.exttools.toolprocess import ToolProcess
from gitfourchette.localization import *
from gitfourchette.porcelain import Oid
from gitfourchette.qt import *
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)

try:
    import gitfourchette.mount.treemount as _dummy
    fuseImportError = None
    del _dummy
except (ImportError, OSError) as exc:  # pragma: no cover
    fuseImportError = exc
    logger.info(f"FUSE not available: {fuseImportError}")


@dataclasses.dataclass
class MountedCommit:
    repoWorkdir: str
    commitId: Oid
    mountPoint: str
    fuseProcess: QProcess

    def friendlyName(self) -> str:
        repoName = settings.history.getRepoNickname(self.repoWorkdir)
        return f"{repoName} @ {shortHash(self.commitId)}"

    def openFolder(self):
        openFolder(self.mountPoint)

    def openTerminal(self, parent: QWidget):
        ToolProcess.startTerminal(parent, self.mountPoint)

    def unmount(self):
        self.fuseProcess.terminate()
        self.fuseProcess.waitForFinished(5000)

        with suppress(OSError):
            Path(self.mountPoint).rmdir()


class MountManager(QObject):
    mountPointsChanged = Signal()
    statusMessage = Signal(str)

    mountedCommits: dict[Oid, MountedCommit]

    def __init__(self, parent):
        super().__init__(parent)
        self.mountedCommits = {}

    @classmethod
    def isFuseAvailable(cls):
        return fuseImportError is None

    @classmethod
    def requireFuse(cls):
        if fuseImportError is not None:
            raise fuseImportError

    @classmethod
    def supportsMounting(cls) -> bool:
        return fuseImportError is None

    def isMounted(self, oid: Oid):
        return oid in self.mountedCommits

    def checkAliveProcesses(self):
        """
        Check if any processes have been terminated outside our control,
        e.g. by "ejecting" a drive on macOS.
        """
        alive = {oid: mc for oid, mc in self.mountedCommits.items()
                 if mc.fuseProcess.state() != QProcess.ProcessState.NotRunning}
        if len(alive) != len(self.mountedCommits):
            self.mountedCommits.clear()
            self.mountedCommits.update(alive)
            self.mountPointsChanged.emit()

    def mount(self, workdir: str, oid: Oid):
        self.requireFuse()

        if FLATPAK:
            # Flatpak version can't mount inside qTempDir, so create the mount
            # point somewhere on the disk. Avoid the repo's .git directory.
            mountParentDir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericCacheLocation)
        else:
            mountParentDir = qTempDir()

        wdName = Path(workdir).name
        pathObj = Path(mountParentDir, f"mnt-{wdName}@{str(oid)[:8]}")
        if pathObj.is_dir():
            pathObj.rmdir()
        pathObj.mkdir(parents=True)
        path = str(pathObj)

        tokens = [
            sys.executable,
            "-m",
            "gitfourchette.mount.treemount",
            workdir,
            str(oid),
            path
        ]
        logger.info(f"Starting: {shlex.join(tokens)}")

        fuseProcess = QProcess(self)
        fuseProcess.setProgram(tokens[0])
        fuseProcess.setArguments(tokens[1:])

        mc = MountedCommit(workdir, oid, path, fuseProcess)
        self.mountedCommits[oid] = mc

        fuseProcess.started.connect(lambda: self.onProcessStarted(mc))
        fuseProcess.start()
        logger.info(f"PID {fuseProcess.processId()}, mountpoint {path}")

        self.statusMessage.emit(
            _("Created a FUSE mount point for {0}. Find it in the {1} menu.",
              tquo(mc.friendlyName()),
              tquo(stripAccelerators(_("&Mount")))))

        return mc

    def onProcessStarted(self, mc: MountedCommit):
        self.mountPointsChanged.emit()
        mc.openFolder()

    def copyPath(self, mc: MountedCommit):
        QApplication.clipboard().setText(mc.mountPoint)
        self.statusMessage.emit(clipboardStatusMessage(mc.mountPoint))

    def unmount(self, mc: MountedCommit):
        mc.unmount()
        del self.mountedCommits[mc.commitId]
        self.statusMessage.emit(_("Unmounted {0}.", tquo(mc.friendlyName())))
        self.mountPointsChanged.emit()

    def unmountAll(self, closeCallback=None):
        for m in self.mountedCommits.values():
            m.unmount()
        self.mountedCommits.clear()
        self.statusMessage.emit(_("Unmounted all commit folders."))
        self.mountPointsChanged.emit()
        if closeCallback is not None:
            closeCallback()

    def makeMenu(self, widget: QWidget):
        items = []
        numMounts = len(self.mountedCommits)

        for oid, mc in self.mountedCommits.items():
            items.append(ActionDef(escamp(mc.friendlyName()), enabled=False))
            items.extend(self.makeMenuItemsForMount(oid, widget, numMounts == 1))
            items.append(ActionDef.SEPARATOR)

        if numMounts >= 2:
            items.append(ActionDef("Unmount All", self.unmountAll))

        return items

    def makeMenuItemsForMount(self, oid: Oid, widget: QWidget, single: bool = True):
        mc = self.mountedCommits[oid]

        items = [
            ActionDef(_("Open Mounted Folder"), mc.openFolder),
            ActionDef(_("Open in Terminal"), lambda mc=mc: mc.openTerminal(widget)),
            ActionDef(_("Copy Mount Point Path"), lambda mc=mc: self.copyPath(mc)),
            ActionDef(_("Unmount"), lambda mc=mc: self.unmount(mc)),
        ]

        if single:  # Single item: insert separator before 'Unmount'
            items.insert(-1, ActionDef.SEPARATOR)

        return items

    def checkOnClose(self, parentWidget, closeCallback):
        numMounts = len(self.mountedCommits)
        if numMounts == 0:
            return True

        oldestMount = next(iter(self.mountedCommits.values()))

        title = _("Unmount before quitting")
        prompt = _n(
            "Do you want to unmount folder {c} before quitting?",
            "Do you want to unmount {n} commit folders before quitting? ({c}, etc.)",
            n=numMounts, c=tquo(escamp(oldestMount.friendlyName())))

        buttons = QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        messageBox = asyncMessageBox(parentWidget, "question", title, prompt, buttons)

        quitButton = messageBox.button(QMessageBox.StandardButton.Ok)
        quitButton.setText(_("&Unmount && Quit"))
        quitButton.clicked.connect(lambda: self.unmountAll(closeCallback))

        messageBox.show()
        return False
