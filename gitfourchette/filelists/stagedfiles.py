# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.filelists.filelist import FileList
from gitfourchette.gitdriver import GitDelta
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

    def contextMenuActions(self, deltas: list[GitDelta]) -> list[ActionDef]:
        actions = []

        n = len(deltas)
        modeSet = {delta.new.mode for delta in deltas}  # mode in worktree
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
                self.contextMenuActionRevertMode(deltas, self.unstageModeChange, ellipsis=False),
                ActionDef.SEPARATOR,
                self.contextMenuActionBlame(deltas),
                *self.contextMenuActionsDiff(deltas),
                ActionDef.SEPARATOR,
                *self.contextMenuActionsEdit(deltas),
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

        actions += super().contextMenuActions(deltas)
        return actions

    def unstage(self):
        deltas = list(self.selectedDeltas())
        UnstageFiles.invoke(self, deltas)

    def unstageModeChange(self):
        deltas = list(self.selectedDeltas())
        UnstageModeChanges.invoke(self, deltas)

    def onSpecialMouseClick(self):
        if settings.prefs.middleClickToStage:
            self.unstage()
