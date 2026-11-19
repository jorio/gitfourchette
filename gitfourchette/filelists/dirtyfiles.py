# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.filelists.filelist import FileList
from gitfourchette.gitdriver import GitDelta
from gitfourchette.globalshortcuts import GlobalShortcuts
from gitfourchette.localization import *
from gitfourchette.nav import NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import RepoModel
from gitfourchette.tasks import *
from gitfourchette.toolbox import *


class DirtyFiles(FileList):
    def __init__(self, repoModel: RepoModel, parent: QWidget):
        super().__init__(repoModel, parent, NavContext.UNSTAGED)

        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        makeWidgetShortcut(self, self.stage, *GlobalShortcuts.stageHotkeys)
        makeWidgetShortcut(self, self.discard, *GlobalShortcuts.discardHotkeys)

    def contextMenuActions(self, deltas: list[GitDelta]) -> list[ActionDef]:
        actions = []

        n = len(deltas)

        statusSet = {delta.status for delta in deltas}
        modeSet = {delta.new.mode for delta in deltas}  # mode in worktree

        anyConflicts = "U" in statusSet  # DeltaStatus.CONFLICTED in statusSet
        anyGitlinks = FileMode.COMMIT in modeSet
        onlyConflicts = anyConflicts and len(statusSet) == 1
        onlyGitlinks = anyGitlinks and len(modeSet) == 1
        onlyUntracked = statusSet == {"?"}  # {DeltaStatus.UNTRACKED}

        if not anyConflicts and not anyGitlinks:
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
                ActionDef(_("Keep OUR version") + "\u2026", lambda: self.hardSolve(True)),
                ActionDef(_("Accept THEIR version") + "\u2026", lambda: self.hardSolve(False)),
            ]

        elif onlyGitlinks:
            if self.areSubmodules(deltas):
                section = _n("Submodule", "{n} Submodules", n)
                stageText = _n("Stage Submodule", "Stage {n} Submodules", n)
                discardText = _n("Discard Changes in Submodule", "Discard Changes in {n} Submodules", n)
                openText = _n("Open Submodule in New Tab", "Open {n} Submodules in New Tabs", n)
            else:
                section = _n("Nested Repository", "{n} Nested Repositories", n)
                stageText = _n("Stage Nested Repo", "Stage {n} Nested Repos", n)
                discardText = _n("Discard Changes in Nested Repo", "Discard Changes in {n} Nested Repos", n)
                openText = _n("Open Nested Repo in New Tab", "Open {n} Nested Repos in New Tabs", n)
            actions += [
                ActionDef(section, kind=ActionDef.Kind.Section),
                ActionDef(stageText, self.stage),
                ActionDef(discardText, self.discard),
                ActionDef(openText, self.openNestedRepoTabs),
            ]

        else:
            # Conflicted + non-conflicted files selected
            # or nested repositories + other files selected
            sorry = _("Can’t stage this selection in bulk.") + "\n" + _("Please review the files individually.")
            actions += [
                ActionDef(sorry, enabled=False),
            ]

        if actions:
            actions.append(ActionDef.SEPARATOR)

        if not onlyGitlinks:
            actions += [
                *self.contextMenuActionsEdit(deltas),
                ActionDef.SEPARATOR,
            ]

        actions += super().contextMenuActions(deltas)
        return actions

    def wantStageOrUnstage(self):
        self.stage()

    def stage(self):
        deltas = list(self.selectedDeltas())
        StageFiles.invoke(self, deltas)

    def discard(self):
        deltas = list(self.selectedDeltas())
        DiscardFiles.invoke(self, deltas)

    def discardModeChanges(self):
        deltas = list(self.selectedDeltas())
        DiscardModeChanges.invoke(self, deltas)

    def hardSolve(self, keepOurs: bool):
        conflicts = [delta.conflict for delta in self.selectedDeltas()]
        HardSolveConflicts.invoke(self, conflicts, keepOurs)

    def ignoreSelection(self):
        selected = list(self.selectedPaths())
        assert len(selected) == 1, "QAction bound to ignoreSelection should be disabled"
        NewIgnorePattern.invoke(self, selected[0])
