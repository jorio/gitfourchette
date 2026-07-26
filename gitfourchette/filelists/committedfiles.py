# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os

from gitfourchette import settings
from gitfourchette.exttools.toolprocess import ToolProcess
from gitfourchette.filelists.filelist import FileList
from gitfourchette.gitdriver import GitDelta
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import RepoModel
from gitfourchette.settings import getExternalEditorName
from gitfourchette.tasks import *
from gitfourchette.toolbox import *


class CommittedFiles(FileList):
    def __init__(self, repoModel: RepoModel, parent: QWidget):
        super().__init__(repoModel, parent, NavContext.COMMITTED)

    def contextMenuActions(self, deltas: list[GitDelta]) -> list[ActionDef]:
        actions = []

        n = len(deltas)
        modeSet = {delta.new.mode for delta in deltas}  # modeDst
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

    def setCommitLocator(self, locator: NavLocator):
        assert locator.context == NavContext.COMMITTED
        self.flModel.navLocator = locator.coarse().replace(path="")

    def openNewRevision(self):
        self.openRevision(beforeCommit=False)

    def openOldRevision(self):
        self.openRevision(beforeCommit=True)

    def saveNewRevision(self):
        self.saveRevisionAs(beforeCommit=False)

    def saveOldRevision(self):
        self.saveRevisionAs(beforeCommit=True)

    def _restoreRevision(self, old: bool):
        deltas = list(self.selectedDeltas())
        assert len(deltas) == 1
        RestoreRevisionToWorkdir.invoke(self, deltas[0], old=old)

    def restoreNewRevision(self):
        self._restoreRevision(old=False)

    def restoreOldRevision(self):
        self._restoreRevision(old=True)

    # TODO: Send all files to text editor in one command?
    def openRevision(self, beforeCommit: bool = False):
        def run(task: RepoTask, delta: GitDelta):
            yield from task.flowSubtask(OpenRevisionInEditor, delta, beforeCommit)

        toolName = getExternalEditorName()
        self.confirmBatch(
            run,
            _("Open file revision"),
            _("Really open [# files] in {0}?", toolName))

    def saveRevisionAs(self, beforeCommit: bool = False):
        def run(task: RepoTask, delta: GitDelta):
            yield from task.flowSubtask(SaveRevisionAs, delta, old=beforeCommit)

        self.confirmBatch(run, _("Save file revision as"), _("Really export [# files]?"))

    def openWorkingCopyRevision(self):
        def run(task: RepoTask, delta: GitDelta):
            path = task.repo.in_workdir(delta.new.path)
            if not os.path.isfile(path):
                raise FileNotFoundError(_("There’s no file at this path in the working copy."))
            ToolProcess.startTextEditor(task.parentWidget(), path)
            yield from task.flowEnterUiThread()  # dummy yield

        toolName = getExternalEditorName()
        self.confirmBatch(
            run,
            _("Open working copy revision"),
            _("Really open [# files] in {0}?", toolName))

    def wantOpenDiffInNewWindow(self):
        sourceLocator = self.flModel.navLocator

        def run(task: RepoTask, delta: GitDelta):
            locator = sourceLocator.replace(path=delta.new.path)
            yield from task.flowSubtask(LoadPatchInNewWindow, delta, locator)

        self.confirmBatch(run, _("Open diff in new window"), _("Really open [# windows]?"))
