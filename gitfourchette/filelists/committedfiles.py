# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import errno
import os

from gitfourchette import settings
from gitfourchette.exttools.toolprocess import ToolProcess
from gitfourchette.filelists.filelist import FileList
from gitfourchette.gitdriver import FatDelta, ABDeltaFile
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks import RestoreRevisionToWorkdir
from gitfourchette.toolbox import *


class CommittedFiles(FileList):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, navContext=NavContext.COMMITTED)

    def contextMenuActions(self, deltas: list[FatDelta]) -> list[ActionDef]:
        actions = []

        n = len(deltas)
        modeSet = {delta.modeDst for delta in deltas}
        anySubmodules = FileMode.COMMIT in modeSet
        onlySubmodules = anySubmodules and len(modeSet) == 1

        if not anySubmodules:
            actions += [
                self.contextMenuActionBlame(deltas),

                ActionDef.SEPARATOR,

                ActionDef(
                    _("Open Diff in New &Window"),
                    self.wantOpenDiffInNewWindow,
                ),

                *self.contextMenuActionsDiff(deltas),

                ActionDef.SEPARATOR,

                ActionDef(
                    _n("&Revert This Change…", "&Revert These Changes…", n),
                    self.revertPaths,
                ),

                ActionDef(
                    _("Restor&e File Revision…"),
                    submenu=[
                        ActionDef(_("&As Of This Commit"), self.restoreNewRevision),
                        ActionDef(_("&Before This Commit"), self.restoreOldRevision),
                    ]
                ),

                ActionDef.SEPARATOR,

                ActionDef(
                    _n("&Open File in {0}", "&Open {n} Files in {0}", n, settings.getExternalEditorName()),
                    icon="SP_FileIcon", submenu=[
                        ActionDef(_("&Current Revision (Working Copy)"), self.openWorkingCopyRevision),
                        ActionDef(_("&As Of This Commit"), self.openNewRevision),
                        ActionDef(_("&Before This Commit"), self.openOldRevision),
                    ]
                ),

                ActionDef(
                    _("&Save a Copy…"),
                    icon="SP_DialogSaveButton", submenu=[
                        ActionDef(_("&As Of This Commit"), self.saveNewRevision),
                        ActionDef(_("&Before This Commit"), self.saveOldRevision),
                    ]
                ),
            ]

        elif onlySubmodules:
            actions += [
                ActionDef(
                    _n("Submodule", "{n} Submodules", n),
                    kind=ActionDef.Kind.Section,
                ),

                ActionDef(
                    _n("Open Submodule in New Tab", "Open {n} Submodules in New Tabs", n),
                    self.openSubmoduleTabs,
                ),
            ]

        else:
            sorry = _("Please review the files individually.")
            actions += [
                ActionDef(sorry, enabled=False),
            ]

        actions += super().contextMenuActions(deltas)
        return actions

    def setCommit(self, oid: Oid):
        self.commitId = oid

    def openNewRevision(self):
        self.openRevision(beforeCommit=False)

    def openOldRevision(self):
        self.openRevision(beforeCommit=True)

    def saveNewRevision(self):
        self.saveRevisionAs(beforeCommit=False)

    def saveOldRevision(self):
        self.saveRevisionAs(beforeCommit=True)

    def restoreNewRevision(self):
        patches = list(self.selectedPatches())
        assert len(patches) == 1
        RestoreRevisionToWorkdir.invoke(self, patches[0], old=False)

    def restoreOldRevision(self):
        patches = list(self.selectedPatches())
        assert len(patches) == 1
        RestoreRevisionToWorkdir.invoke(self, patches[0], old=True)

    def saveRevisionAsTempFile(self, delta: FatDelta, beforeCommit: bool = False):
        # May raise FileNotFoundError!
        name, diffFile = self.getFileRevisionInfo(delta, beforeCommit)
        data = diffFile.read(self.repo)

        tempPath = os.path.join(qTempDir(), name)

        with open(tempPath, "wb") as f:
            f.write(data)

        return tempPath

    # TODO: Send all files to text editor in one command?
    def openRevision(self, beforeCommit: bool = False):
        def run(delta: FatDelta):
            tempPath = self.saveRevisionAsTempFile(delta, beforeCommit)
            ToolProcess.startTextEditor(self, tempPath)

        if beforeCommit:
            title = _("Open revision before commit")
        else:
            title = _("Open revision at commit")

        self.confirmBatch(run, title, _("Really open <b>{n} files</b> in external editor?"))

    # TODO: Perhaps this could be a RepoTask?
    def saveRevisionAs(self, beforeCommit: bool = False):
        def dump(path: str, mode: int, data: bytes):
            with open(path, "wb") as f:
                f.write(data)
            os.chmod(path, mode)

        def run(delta: FatDelta):
            # May raise FileNotFoundError!
            name, diffFile = self.getFileRevisionInfo(delta, beforeCommit)
            data = diffFile.read(self.repo)

            qfd = PersistentFileDialog.saveFile(self, "SaveFile", _("Save file revision as"), name)
            qfd.fileSelected.connect(lambda path: dump(path, diffFile.mode, data))
            qfd.show()

        if beforeCommit:
            title = _("Save revision before commit")
        else:
            title = _("Save revision at commit")

        self.confirmBatch(run, title, _("Really export <b>{n} files</b>?"))

    def getFileRevisionInfo(self, fatDelta: FatDelta, beforeCommit: bool = False) -> tuple[str, ABDeltaFile]:
        delta = fatDelta.distillOldNew(self.navContext)

        if beforeCommit:
            diffFile = delta.old
            if delta.status == "A":
                raise FileNotFoundError(errno.ENOENT, _("This file didn’t exist before the commit."), diffFile.path)
        else:
            diffFile = delta.new
            if delta.status == "D":
                raise FileNotFoundError(errno.ENOENT, _("This file was deleted by the commit."), diffFile.path)

        atSuffix = shortHash(self.commitId)
        if beforeCommit:
            atSuffix = F"before-{atSuffix}"

        name, ext = os.path.splitext(os.path.basename(diffFile.path))
        name = F"{name}@{atSuffix}{ext}"

        return name, diffFile

    def openWorkingCopyRevision(self):
        def run(delta: FatDelta):
            path = self.repo.in_workdir(delta.path)
            if not os.path.isfile(path):
                raise FileNotFoundError(_("There’s no file at this path in the working copy."))
            ToolProcess.startTextEditor(self, path)

        self.confirmBatch(run, _("Open working copy revision"), _("Really open <b>{n} files</b>?"))

    def wantOpenDiffInNewWindow(self):
        def run(patch: Patch):
            self.openDiffInNewWindow.emit(patch, NavLocator(self.navContext, self.commitId, patch.delta.new_file.path))

        self.confirmBatch(run, _("Open diff in new window"), _("Really open <b>{n} windows</b>?"))
