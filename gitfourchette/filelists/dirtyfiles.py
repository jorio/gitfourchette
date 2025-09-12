# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.filelists.filelist import FileList
from gitfourchette.gitdriver import VanillaDelta
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.nav import NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks import *
from gitfourchette.toolbox import *


class DirtyFiles(FileList):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs, navContext=NavContext.UNSTAGED)

        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        makeWidgetShortcut(self, self.stage, *GlobalShortcuts.stageHotkeys)
        makeWidgetShortcut(self, self.discard, *GlobalShortcuts.discardHotkeys)

    def contextMenuActions(self, deltas: list[VanillaDelta]) -> list[ActionDef]:
        actions = []

        n = len(deltas)

        statusSet = {delta.statusUnstaged for delta in deltas}
        modeSet = {delta.modeWorktree for delta in deltas}

        anyConflicts = "U" in statusSet  # DeltaStatus.CONFLICTED in statusSet
        anySubmodules = FileMode.COMMIT in modeSet
        onlyConflicts = anyConflicts and len(statusSet) == 1
        onlySubmodules = anySubmodules and len(modeSet) == 1
        onlyUntracked = statusSet == {"?"}  # {DeltaStatus.UNTRACKED}

        if not anyConflicts and not anySubmodules:
            contextMenuActionStage = ActionDef(
                _n("&Stage File", "&Stage {n} Files", n),
                self.stage,
                icon="git-stage",
                shortcuts=GlobalShortcuts.stageHotkeys[0])

            contextMenuActionIgnore = ActionDef(
                _n("&Ignore Untracked File…", "&Ignore Untracked Files…", n),
                self.ignoreSelection,
                enabled=n == 1 and onlyUntracked)

            if onlyUntracked:
                discardText = _n("&Delete File…", "&Delete {n} Files…", n)
            else:
                discardText = _n("&Discard Changes in File…", "&Discard Changes in {n} Files…", n)
            contextMenuActionDiscard = ActionDef(
                discardText,
                self.discard,
                icon="git-discard",
                shortcuts=GlobalShortcuts.discardHotkeys[0])

            actions += [
                contextMenuActionStage,
                contextMenuActionDiscard,
                self.contextMenuActionStash(),
                self.contextMenuActionRevertMode(deltas, self.discardModeChanges),
                contextMenuActionIgnore,
                ActionDef.SEPARATOR,
                self.contextMenuActionBlame(deltas),
                *self.contextMenuActionsDiff(deltas),
            ]

        elif onlyConflicts:
            actions += [
                ActionDef(
                    _n("Merge Conflict", "{n} Merge Conflicts", n),
                    kind=ActionDef.Kind.Section,
                ),

                ActionDef(
                    _("Resolve by Accepting “Theirs”"),
                    self.mergeTakeTheirs,
                ),

                ActionDef(
                    _("Resolve by Keeping “Ours”"),
                    self.mergeKeepOurs,
                ),
            ]

        elif onlySubmodules:
            actions += [
                ActionDef(
                    _n("Submodule", "{n} Submodules", n),
                    kind=ActionDef.Kind.Section,
                ),
                ActionDef(
                    _n("Stage Submodule", "Stage {n} Submodules", n),
                    self.stage,
                ),
                ActionDef(
                    _n("Discard Changes in Submodule", "Discard Changes in {n} Submodules", n),
                    self.discard,
                ),
                ActionDef(
                    _n("Open Submodule in New Tab", "Open {n} Submodules in New Tabs", n),
                    self.openSubmoduleTabs,
                ),
            ]

        else:
            # Conflicted + non-conflicted files selected
            # or Submodules + non-submodules selected
            sorry = _("Can’t stage this selection in bulk.") + "\n" + _("Please review the files individually.")
            actions += [
                ActionDef(sorry, enabled=False),
            ]

        if actions:
            actions.append(ActionDef.SEPARATOR)

        if not onlySubmodules:
            actions += [
                *self.contextMenuActionsEdit(deltas),
                ActionDef.SEPARATOR,
            ]

        actions += super().contextMenuActions(deltas)
        return actions

    def stage(self):
        deltas = list(self.selectedDeltas())
        StageFiles.invoke(self, deltas)

    def discard(self):
        deltas = list(self.selectedDeltas())
        DiscardFiles.invoke(self, deltas)

    def discardModeChanges(self):
        deltas = list(self.selectedDeltas())
        DiscardModeChanges.invoke(self, deltas)

    def _mergeKeep(self, keepOurs: bool):
        # TODO: Migrate to Vanilla
        patches = list(self.selectedPatches())

        conflicts = self.repo.index.conflicts

        table = {}

        for patch in patches:
            path = patch.delta.new_file.path
            ancestor, ours, theirs = conflicts[path]

            keepEntry = ours if keepOurs else theirs
            keepId = keepEntry.id if keepEntry is not None else NULL_OID
            table[path] = keepId

        HardSolveConflicts.invoke(self, table)

    def mergeKeepOurs(self):
        self._mergeKeep(keepOurs=True)

    def mergeTakeTheirs(self):
        self._mergeKeep(keepOurs=False)

    def onSpecialMouseClick(self):
        if settings.prefs.middleClickToStage:
            self.stage()

    def ignoreSelection(self):
        selected = list(self.selectedPaths())

        if len(selected) != 1:
            QApplication.beep()
            return

        NewIgnorePattern.invoke(self, selected[0])
