# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import errno
import os

from gitfourchette import settings
from gitfourchette.exttools.toolprocess import ToolProcess
from gitfourchette.filelists.filelist import FileList, SelectedFileBatchError
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks import RestoreRevisionToWorkdir
from gitfourchette.toolbox import *


class CommittedFiles(FileList):
    def __init__(self, parent: QWidget):
        super().__init__(parent, NavContext.COMMITTED)

    def contextMenuActions(self, patches: list[Patch]) -> list[ActionDef]:
        actions = []

        n = len(patches)
        modeSet = {patch.delta.new_file.mode for patch in patches}
        anySubmodules = FileMode.COMMIT in modeSet
        onlySubmodules = anySubmodules and len(modeSet) == 1

        if not anySubmodules:
            actions += [
                ActionDef(
                    _("Open Diff in New &Window"),
                    self.wantOpenDiffInNewWindow,
                ),

                *self.contextMenuActionsDiff(patches),

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

        actions += super().contextMenuActions(patches)
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

    def saveRevisionAsTempFile(self, patch: Patch, beforeCommit: bool = False):
        try:
            name, blob, _dummy = self.getFileRevisionInfo(patch, beforeCommit)
        except FileNotFoundError as fnf:
            raise SelectedFileBatchError(fnf.filename + ": " + fnf.strerror) from fnf

        tempPath = os.path.join(qTempDir(), name)

        with open(tempPath, "wb") as f:
            f.write(blob.data)

        return tempPath

    # TODO: Send all files to text editor in one command?
    def openRevision(self, beforeCommit: bool = False):
        def run(patch: Patch):
            tempPath = self.saveRevisionAsTempFile(patch, beforeCommit)
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

        def run(patch: Patch):
            try:
                name, blob, diffFile = self.getFileRevisionInfo(patch, beforeCommit)
            except FileNotFoundError as fnf:
                raise SelectedFileBatchError(fnf.filename + ": " + fnf.strerror) from fnf

            qfd = PersistentFileDialog.saveFile(self, "SaveFile", _("Save file revision as"), name)
            qfd.fileSelected.connect(lambda path: dump(path, diffFile.mode, blob.data))
            qfd.show()

        if beforeCommit:
            title = _("Save revision before commit")
        else:
            title = _("Save revision at commit")

        self.confirmBatch(run, title, _("Really export <b>{n} files</b>?"))

    def getFileRevisionInfo(self, patch: Patch, beforeCommit: bool = False) -> tuple[str, Blob, DiffFile]:
        if beforeCommit:
            diffFile = patch.delta.old_file
            if patch.delta.status == DeltaStatus.ADDED:
                raise FileNotFoundError(errno.ENOENT, _("This file didn’t exist before the commit."), diffFile.path)
        else:
            diffFile = patch.delta.new_file
            if patch.delta.status == DeltaStatus.DELETED:
                raise FileNotFoundError(errno.ENOENT, _("This file was deleted by the commit."), diffFile.path)

        blob = self.repo.peel_blob(diffFile.id)

        atSuffix = shortHash(self.commitId)
        if beforeCommit:
            atSuffix = F"before-{atSuffix}"

        name, ext = os.path.splitext(os.path.basename(diffFile.path))
        name = F"{name}@{atSuffix}{ext}"

        return name, blob, diffFile

    def openWorkingCopyRevision(self):
        def run(patch: Patch):
            diffFile = patch.delta.new_file
            path = self.repo.in_workdir(diffFile.path)
            if os.path.isfile(path):
                ToolProcess.startTextEditor(self, path)
            else:
                raise SelectedFileBatchError(_("{0}: There’s no file at this path in the working copy.", diffFile.path))

        self.confirmBatch(run, _("Open working copy revision"), _("Really open <b>{n} files</b>?"))

    def wantOpenDiffInNewWindow(self):
        def run(patch: Patch):
            self.openDiffInNewWindow.emit(patch, NavLocator(self.navContext, self.commitId, patch.delta.new_file.path))

        self.confirmBatch(run, _("Open diff in new window"), _("Really open <b>{n} windows</b>?"))
