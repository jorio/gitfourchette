# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.filelists.filelist import FileList
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.nav import NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *
from gitfourchette.tasks import *


class StagedFiles(FileList):
    def __init__(self, parent):
        super().__init__(parent, NavContext.STAGED)

        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def contextMenuActions(self, patches: list[Patch]) -> list[ActionDef]:
        actions = []

        n = len(patches)
        modeSet = {patch.delta.new_file.mode for patch in patches}
        anySubmodules = FileMode.COMMIT in modeSet
        onlySubmodules = anySubmodules and len(modeSet) == 1

        if not anySubmodules:
            contextMenuActionUnstage = ActionDef(
                self.tr("&Unstage %n Files", "please omit %n in singular form", n),
                self.unstage,
                icon="git-unstage",
                shortcuts=GlobalShortcuts.discardHotkeys[0])

            actions += [
                contextMenuActionUnstage,
                self.contextMenuActionStash(),
                self.contextMenuActionRevertMode(patches, self.unstageModeChange),
                ActionDef.SEPARATOR,
                *self.contextMenuActionsDiff(patches),
                ActionDef.SEPARATOR,
                *self.contextMenuActionsEdit(patches),
            ]

        elif onlySubmodules:
            actions += [
                ActionDef(
                    self.tr("%n Submodules", "please omit %n in singular form", n),
                    kind=ActionDef.Kind.Section,
                ),

                ActionDef(
                    self.tr("Unstage %n Submodules", "please omit %n in singular form", n),
                    self.unstage,
                ),

                ActionDef(
                    self.tr("Open %n Submodules in New Tabs", "please omit %n in singular form", n),
                    self.openSubmoduleTabs,
                ),
            ]

        else:
            sorry = (translate("FileList", "Can’t unstage this selection in bulk.") + "\n" +
                     translate("FileList", "Please review the files individually."))
            actions += [
                ActionDef(sorry, enabled=False),
            ]

        actions += super().contextMenuActions(patches)
        return actions

    def keyPressEvent(self, event: QKeyEvent):
        k = event.key()
        if k in GlobalShortcuts.stageHotkeys + GlobalShortcuts.discardHotkeys:
            self.unstage()
        else:
            super().keyPressEvent(event)

    def unstage(self):
        patches = list(self.selectedPatches())
        UnstageFiles.invoke(self, patches)

    def unstageModeChange(self):
        patches = list(self.selectedPatches())
        UnstageModeChanges.invoke(self, patches)

    def onSpecialMouseClick(self):
        if settings.prefs.middleClickToStage:
            self.unstage()
