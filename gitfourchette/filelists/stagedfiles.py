# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.filelists.filelist import FileList
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.nav import NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks import *
from gitfourchette.toolbox import *


class StagedFiles(FileList):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, navContext=NavContext.STAGED)

        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        makeWidgetShortcut(self, self.unstage, *(GlobalShortcuts.discardHotkeys + GlobalShortcuts.stageHotkeys))

    def contextMenuActions(self, patches: list[Patch]) -> list[ActionDef]:
        actions = []

        n = len(patches)
        modeSet = {patch.delta.new_file.mode for patch in patches}
        anySubmodules = FileMode.COMMIT in modeSet
        onlySubmodules = anySubmodules and len(modeSet) == 1

        if not anySubmodules:
            contextMenuActionUnstage = ActionDef(
                _n("&Unstage File", "&Unstage {n} Files", n),
                self.unstage,
                icon="git-unstage",
                shortcuts=GlobalShortcuts.discardHotkeys[0])

            actions += [
                contextMenuActionUnstage,
                self.contextMenuActionStash(),
                self.contextMenuActionRevertMode(patches, self.unstageModeChange, ellipsis=False),
                ActionDef.SEPARATOR,
                self.contextMenuActionBlame(patches),
                *self.contextMenuActionsDiff(patches),
                ActionDef.SEPARATOR,
                *self.contextMenuActionsEdit(patches),
            ]

        elif onlySubmodules:
            actions += [
                ActionDef(
                    _n("Submodule", "{n} Submodules", n),
                    kind=ActionDef.Kind.Section,
                ),

                ActionDef(
                    _n("Unstage Submodule", "Unstage {n} Submodules", n),
                    self.unstage,
                ),

                ActionDef(
                    _n("Open Submodule in New Tab", "Open {n} Submodules in New Tabs", n),
                    self.openSubmoduleTabs,
                ),
            ]

        else:
            sorry = _("Can’t unstage this selection in bulk.") + "\n" + _("Please review the files individually.")
            actions += [
                ActionDef(sorry, enabled=False),
            ]

        actions += super().contextMenuActions(patches)
        return actions

    def unstage(self):
        patches = list(self.selectedPatches())
        UnstageFiles.invoke(self, patches)

    def unstageModeChange(self):
        patches = list(self.selectedPatches())
        UnstageModeChanges.invoke(self, patches)

    def onSpecialMouseClick(self):
        if settings.prefs.middleClickToStage:
            self.unstage()
