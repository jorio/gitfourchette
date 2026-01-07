# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import multiprocessing
from pathlib import Path

from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks.repotask import AbortTask, RepoTask
from gitfourchette.toolbox import *

try:
    from gitfourchette.mount.treemount import TreeMount
    fuseImportError = None
except (ImportError, OSError) as exc:  # pragma: no cover
    fuseImportError = exc

logger = logging.getLogger(__name__)


def abortTaskIfFuseMissing():
    if fuseImportError is None:
        return
    message = _("Can’t perform this operation due to missing dependencies.")
    raise AbortTask(message, details=str(fuseImportError)) from fuseImportError


class MountCommit(RepoTask):
    def flow(self, oid: Oid):
        abortTaskIfFuseMissing()

        pathObj = Path(qTempDir(), "mnt", f"{oid}")
        pathObj.mkdir(parents=True)
        path = str(pathObj)

        fuseProcess = multiprocessing.Process(target=TreeMount.run, args=(self.repo.workdir, str(oid), path))
        fuseProcess.start()
        logger.info(f"PID {fuseProcess.pid}, mountpoint {path}")

        try:
            openFolder(path)
            yield from self.flowConfirm(
                text=_("Commit mounted at:") + "<p><b>" + escape(path),
                verb=_("Unmount"),
                canCancel=False)
        finally:
            fuseProcess.terminate()
            fuseProcess.join()

            pathObj.rmdir()

