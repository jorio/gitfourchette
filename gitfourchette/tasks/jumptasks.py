# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Tasks that navigate to a specific area of the repository.

Unlike most other tasks, jump tasks directly manipulate the UI extensively, via RepoWidget.
"""
import dataclasses
import logging
import os
from collections.abc import Generator

from gitfourchette.diffview.diffdocument import DiffDocument
from gitfourchette.diffview.specialdiff import SpecialDiffError, DiffConflict, DiffImagePair
from gitfourchette.graphview.commitlogmodel import SpecialRow
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavContext, NavFlags
from gitfourchette.porcelain import DeltaStatus, NULL_OID, Oid, Patch
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID
from gitfourchette.sidebar.sidebarmodel import UC_FAKEREF
from gitfourchette.tasks import TaskPrereqs
from gitfourchette.tasks.loadtasks import LoadCommit, LoadPatch, LoadWorkdir
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskEffects, RepoGoneError, FlowControlToken
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)


class Jump(RepoTask):
    """
    Single entry point to navigate to any NavLocator in a repository.

    Only the Jump task may "cement" the RepoWidget's navLocator.
    """

    @dataclasses.dataclass
    class Result(Exception):
        locator: NavLocator
        header: str
        document: DiffDocument | DiffConflict | DiffImagePair | SpecialDiffError | None
        patch: Patch | None = None

    def canKill(self, task: RepoTask):
        return isinstance(task, Jump | RefreshRepo)

    def flow(self, locator: NavLocator):
        if not locator:
            return

        rw = self.rw

        # Back up current locator
        if not rw.navHistory.isWriteLocked():
            rw.saveFilePositions()

        # If the locator is "coarse" (i.e. no specific path given, just a generic context),
        # try to recall where we were last time we looked at this context.
        locator = rw.navHistory.refine(locator)

        try:
            # Load workdir or commit, and show the corresponding view
            if locator.context == NavContext.SPECIAL:
                self.showSpecial(locator)  # always raises Jump.Result
            else:
                if locator.context.isWorkdir():
                    locator = yield from self.showWorkdir(locator)
                else:
                    locator = yield from self.showCommit(locator)
        except Jump.Result as r:
            # The showXXX functions may bail early by raising Jump.Result.
            result = r

            # Set up DiffArea for this locator.
            rw.diffArea.setUpForLocator(result.locator)
        else:
            fileList = rw.diffArea.fileListByContext(locator.context)

            # If we don't have a path in the locator, fall back to first path in file list.
            # (Only for non-special locators, though!)
            if not locator.path and locator.context != NavContext.SPECIAL:
                locator = locator.replace(path=fileList.firstPath())
                locator = rw.navHistory.refine(locator)

            # Set up DiffArea for this locator.
            # Note that this may return a new locator if the desired path is not available.
            locator = rw.diffArea.setUpForLocator(locator)

            # Prepare Result object.
            if locator.path:
                # Load patch in DiffView
                patch = fileList.getPatchForFile(locator.path)
                patchTask = yield from self.flowSubtask(LoadPatch, patch, locator)
                result = Jump.Result(locator, patchTask.header, patchTask.result, patch)
            else:
                # Blank path
                result = Jump.Result(locator, "", None)

        self.saveFinalLocator(result.locator)
        self.displayResult(result)

    def showWorkdir(self, locator: NavLocator) -> Generator[FlowControlToken, None, NavLocator]:
        rw = self.rw
        repoModel = self.repoModel
        previousLocator = rw.navLocator

        # Save selected row number for the end of the function
        previousRowStaged = rw.stagedFiles.earliestSelectedRow()
        previousRowDirty = rw.dirtyFiles.earliestSelectedRow()

        with (
            QSignalBlockerContext(rw.graphView, rw.sidebar),  # Don't emit jump signals
            QScrollBackupContext(rw.sidebar),  # Stabilize scroll bar value
        ):
            rw.graphView.selectRowForLocator(locator)
            rw.sidebar.selectAnyRef(UC_FAKEREF)

        # Reset diff banner
        rw.diffArea.diffBanner.setVisible(False)
        rw.diffArea.contextHeader.setContext(locator)

        # Stale workdir model - force load workdir
        if (previousLocator.context == NavContext.EMPTY
                or locator.hasFlags(NavFlags.ForceDiff)
                or repoModel.workdirStale):
            # Don't clear stale flag until AFTER we're done reloading the workdir
            # so that it stays stale if this task gets interrupted.
            repoModel.workdirStale = True

            # Load workdir (async)
            workdirTask = yield from self.flowSubtask(
                LoadWorkdir, allowWriteIndex=locator.hasFlags(NavFlags.AllowWriteIndex))

            # Fill FileListViews
            with QSignalBlockerContext(rw.dirtyFiles, rw.stagedFiles):  # Don't emit jump signals
                rw.dirtyFiles.setContents([workdirTask.dirtyDiff], False)
                rw.stagedFiles.setContents([workdirTask.stageDiff], False)

            nDirty = rw.dirtyFiles.model().rowCount()
            nStaged = rw.stagedFiles.model().rowCount()
            rw.diffArea.dirtyHeader.setText(_n("Unstaged ({n})", "Unstaged ({n})", nDirty))
            rw.diffArea.stagedHeader.setText(_n("Staged ({n})", "Staged ({n})", nStaged))
            rw.diffArea.commitButton.setText(_n("Commit {n} file", "Commit {n} files", nStaged))

            commitButtonFont = rw.diffArea.commitButton.font()
            commitButtonBold = nStaged != 0
            if commitButtonFont.bold() != commitButtonBold:
                commitButtonFont.setBold(commitButtonBold)
                rw.diffArea.commitButton.setFont(commitButtonFont)

            newNumChanges = nDirty + nStaged
            numChangesDifferent = repoModel.numUncommittedChanges != newNumChanges
            repoModel.numUncommittedChanges = newNumChanges

            repoModel.workdirStale = False

            # Show number of staged changes in sidebar and graph
            if numChangesDifferent:
                rw.sidebar.repaint()
                rw.graphView.repaintCommit(UC_FAKEID)

        # If jumping to generic workdir context, find a concrete context
        if locator.context == NavContext.WORKDIR:
            if rw.dirtyFiles.isEmpty() and not rw.stagedFiles.isEmpty():
                locator = locator.replace(context=NavContext.STAGED)
            else:
                locator = locator.replace(context=NavContext.UNSTAGED)
            locator = rw.navHistory.refine(locator)

        # Early out if workdir is clean
        if rw.dirtyFiles.isEmpty() and rw.stagedFiles.isEmpty():
            locator = locator.replace(path="")
            header = toLengthVariants(_("Working directory clean|Workdir clean"))
            sde = SpecialDiffError(
                _("The working directory is clean."),
                _("There aren’t any changes to commit."))
            raise Jump.Result(locator, header, sde)

        # (Un)Staging a file makes it vanish from its file list.
        # But we don't want the selection to go blank in this case.
        # Restore selected row (by row number) in the file list so the user
        # can keep hitting RETURN/DELETE to stage/unstage a series of files.
        isStaged = locator.context == NavContext.STAGED
        flModel = (rw.stagedFiles if isStaged else rw.dirtyFiles).flModel
        flPrevRow = previousRowStaged if isStaged else previousRowDirty

        if locator.path and not flModel.hasFile(locator.path) and flPrevRow >= 0:
            path = flModel.getFileAtRow(min(flPrevRow, flModel.rowCount()-1))
            locator = locator.replace(path=path)
            locator = locator.coarse(keepFlags=True)  # don't carry cursor over from old locator
            locator = rw.navHistory.refine(locator)

        return locator

    def showSpecial(self, locator: NavLocator):
        rw = self.rw
        locale = QLocale()

        with QSignalBlockerContext(rw.sidebar, rw.committedFiles, rw.graphView):
            rw.sidebar.clearSelection()
            rw.diffArea.committedFiles.clear()
            rw.diffArea.committedHeader.setText(" ")
            rw.diffArea.diffBanner.hide()
            rw.diffArea.contextHeader.setContext(locator)
            rw.graphView.selectRowForLocator(locator)

        if locator.path == str(SpecialRow.EndOfShallowHistory):
            sde = SpecialDiffError(
                _("Shallow clone – End of available history."),
                _("More commits may be available in a full clone."))
            raise Jump.Result(locator, _("Shallow clone – End of commit history"), sde)

        elif locator.path == str(SpecialRow.TruncatedHistory):
            from gitfourchette import settings
            expandSome = makeInternalLink("expandlog")
            expandAll = makeInternalLink("expandlog", n=str(0))
            changePref = makeInternalLink("prefs", "maxCommits")
            humanNextThreshold = locale.toString(self.repoModel.nextTruncationThreshold)
            humanPrefThreshold = locale.toString(settings.prefs.maxCommits)
            options = [
                linkify(_("Load up to {0} commits", humanNextThreshold), expandSome),
                linkify(_("[Load full commit history] (this may take a moment)"), expandAll),
                linkify(_("[Change threshold setting] (currently: {0} commits)", humanPrefThreshold), changePref),
            ]
            sde = SpecialDiffError(
                _("History truncated to {0} commits.", locale.toString(self.repoModel.numRealCommits)),
                _("More commits may be available."),
                longform=toRoomyUL(options))
            raise Jump.Result(locator, _("History truncated"), sde)

        else:
            raise NotImplementedError(f"Unsupported special locator: {locator}")

    def showCommit(self, locator: NavLocator) -> Generator[FlowControlToken, None, NavLocator]:
        """
        Jump to a commit.
        Return a refined NavLocator.
        """

        rw = self.rw
        area = rw.diffArea
        assert locator.context == NavContext.COMMITTED

        # If it's a ref, look it up
        if locator.ref:
            assert locator.commit == NULL_OID
            try:
                oid = self.repoModel.refs[locator.ref]
                locator = locator.replace(commit=oid, ref="")
            except KeyError as exc:
                raise AbortTask(_("Unknown reference {0}.", tquo(locator.ref))) from exc

        assert locator.commit
        assert not locator.ref

        try:
            stashIndex = rw.repoModel.stashes.index(locator.commit)
            isStash = True
        except ValueError:
            stashIndex = -1
            isStash = False

        commit = rw.repo.peel_commit(locator.commit)
        warnings = []

        # Select row in commit log
        from gitfourchette.graphview.graphview import GraphView
        with QSignalBlockerContext(rw.graphView):  # Don't emit jump signals
            try:
                rw.graphView.selectRowForLocator(locator)
            except GraphView.SelectCommitError as e:
                # Commit is hidden or not loaded
                rw.graphView.clearSelection()
                if not isStash:  # Don't show a warning for stashes - never shown in graph
                    warnings.append(str(e))

        # Attempt to select matching ref in sidebar
        with (
            QSignalBlockerContext(rw.sidebar),  # Don't emit jump signals
            QScrollBackupContext(rw.sidebar),  # Stabilize scroll bar value
        ):
            if isStash:
                rw.sidebar.selectAnyRef(f"stash@{{{stashIndex}}}")
            else:
                refCandidates = rw.repoModel.refsAt.get(locator.commit, [])
                rw.sidebar.selectAnyRef(*refCandidates)

        flv = area.committedFiles
        area.diffBanner.setVisible(False)
        area.contextHeader.setContext(locator, commit.message, isStash)

        if locator.commit == flv.commitId and not locator.hasFlags(NavFlags.ForceDiff):
            # No need to reload the same commit
            # (if this flv was dormant and is sent back to the foreground).
            pass

        else:
            # Loading a different commit
            area.diffBanner.lastWarningWasDismissed = False

            # Load commit (async)
            subtask = yield from self.flowSubtask(LoadCommit, locator)

            # Get data from subtask
            diffs = subtask.diffs
            summary = subtask.message.strip()

            # Fill committed file list
            with QSignalBlockerContext(flv):  # Don't emit jump signals
                flv.clear()
                flv.setCommit(locator.commit)
                flv.setContents(diffs, subtask.skippedRenameDetection)
                numChanges = flv.model().rowCount()

            # Set header text
            headerText = toLengthVariants(_n("{n} change:|{n} ch.:", "{n} changes:|{n} ch.:", numChanges))
            area.committedHeader.setText(headerText)
            area.committedHeader.setToolTip("<p>" + escape(summary).replace("\n", "<br>"))

        # Early out if the commit is empty
        if flv.isEmpty():
            locator = locator.replace(path="")
            header = _("Empty commit")
            sde = SpecialDiffError(
                _("This commit is empty."),
                _("Commit {0} doesn’t affect any files.", hquo(shortHash(locator.commit))))
            raise Jump.Result(locator, header, sde)

        # Warning banner
        if not area.diffBanner.lastWarningWasDismissed:
            if flv.skippedRenameDetection:
                warnings.append(_("Rename detection was skipped to load this large commit faster."))
            elif locator.hasFlags(NavFlags.AllowLargeCommits | NavFlags.ForceDiff):
                n = sum(sum(1 if delta.status == DeltaStatus.RENAMED else 0 for delta in diff.deltas) for diff in diffs)
                warnings.append(_n("{n} rename detected.", "{n} renames detected.", n))

            if warnings:
                warningText = "<br>".join(warnings)
                area.diffBanner.popUp("", warningText, canDismiss=True, withIcon=True)

            if flv.skippedRenameDetection:
                area.diffBanner.addButton(
                    _("Detect Renames"),
                    lambda: Jump.invoke(rw, locator.withExtraFlags(NavFlags.AllowLargeCommits | NavFlags.ForceDiff)))

        return locator

    def saveFinalLocator(self, locator: NavLocator):
        # Strip Force flags before saving the locator
        # (otherwise switching back and forth into the app may reload a commit)
        locator = locator.withoutFlags(NavFlags.ForceDiff | NavFlags.ForceRecreateDocument)

        self.rw.navLocator = locator

        if not self.rw.navHistory.isWriteLocked():
            self.rw.navHistory.push(locator)
            self.rw.historyChanged.emit()

    def displayResult(self, result: Result):
        area = self.rw.diffArea

        # Set header
        area.diffHeader.setText(result.header)

        document = result.document

        if document is None:
            area.clearDocument()

        elif isinstance(document, DiffDocument):
            assert result.patch is not None
            area.setDiffStackPage("text")
            area.diffView.replaceDocument(self.repo, result.patch, result.locator, document)

        elif isinstance(document, DiffConflict):
            conflict = document
            area.setDiffStackPage("conflict")
            area.conflictView.displayConflict(conflict)

        elif isinstance(document, SpecialDiffError):
            area.setDiffStackPage("special")
            area.specialDiffView.displaySpecialDiffError(document)

        elif isinstance(document, DiffImagePair):
            assert result.patch is not None
            area.setDiffStackPage("special")
            area.specialDiffView.displayImageDiff(result.patch.delta, document.oldImage, document.newImage)

        else:
            raise NotImplementedError(f"Can't display {type(document)}")


class JumpBackOrForward(RepoTask):
    """
    Navigate back or forward in the RepoWidget's NavHistory.
    """

    def flow(self, delta: int):
        rw = self.rw

        start = rw.saveFilePositions()
        history = rw.navHistory

        while history.canGoDelta(delta):
            # Move back or forward in the history
            locator = history.navigateDelta(delta)

            # Keep going if same file comes up several times in a row
            if locator.isSimilarEnoughTo(start):
                continue

            # Jump
            # (lock history because we want full control over it)
            with history.writeLock:
                yield from self.flowSubtask(Jump, locator)

            # The jump was successful if the RepoWidget's locator
            # comes out similar enough to the one from the history.
            if rw.navLocator.isSimilarEnoughTo(locator):
                break

            # This point in history is stale, nuke it and keep going
            history.popCurrent()

        # Finalize history
        history.push(rw.navLocator)
        rw.historyChanged.emit()


class JumpBack(JumpBackOrForward):
    def flow(self):
        yield from JumpBackOrForward.flow(self, -1)


class JumpForward(JumpBackOrForward):
    def flow(self):
        yield from JumpBackOrForward.flow(self, 1)


class JumpToUncommittedChanges(Jump):
    def flow(self):
        yield from Jump.flow(self, NavLocator.inWorkdir())


class JumpToHEAD(Jump):
    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoUnborn

    def flow(self):
        yield from Jump.flow(self, NavLocator.inRef("HEAD"))


class RefreshRepo(RepoTask):
    @staticmethod
    def canKill_static(task: RepoTask):
        return task is None or isinstance(task, Jump | RefreshRepo)

    def canKill(self, task: RepoTask):
        return RefreshRepo.canKill_static(task)

    def flow(self, effectFlags: TaskEffects = TaskEffects.DefaultRefresh, jumpTo: NavLocator = NavLocator.Empty):
        rw = self.rw
        repoModel = self.repoModel
        assert onAppThread()

        if effectFlags == TaskEffects.Nothing:
            return

        # Early out if repo has gone missing
        if not os.path.isdir(self.repo.path):
            raise RepoGoneError(self.repo.path)

        repoModel.workdirStale |= bool(effectFlags & TaskEffects.Workdir)

        initialLocator = rw.navLocator
        initialGraphScroll = rw.graphView.verticalScrollBar().value()
        restoringInitialLocator = jumpTo.context == NavContext.EMPTY
        wasExploringDetachedCommit = initialLocator.commit and initialLocator.commit not in repoModel.graph.commitRows

        try:
            previousFileList = rw.diffArea.fileListByContext(initialLocator.context)
            previousFileList.backUpSelection()
        except ValueError:
            previousFileList = None

        refsChanged = False
        stashesChanged = False
        submodulesChanged = False
        remotesChanged = False
        homeBranchChanged = False
        upstreamsChanged = effectFlags & TaskEffects.Upstreams

        # Refresh the index
        if effectFlags & TaskEffects.Index:
            repoModel.repo.refresh_index()

        if effectFlags & (TaskEffects.Head | TaskEffects.Workdir):
            submodulesChanged = repoModel.syncSubmodules()

        if effectFlags & (TaskEffects.Refs | TaskEffects.Remotes):
            remotesChanged = repoModel.syncRemotes()

        if effectFlags & (TaskEffects.Refs | TaskEffects.Remotes | TaskEffects.Head):
            # Refresh ref cache
            oldRefs = repoModel.refs
            oldHeadBranch = repoModel.homeBranch

            refsChanged = repoModel.syncRefs()
            refsChanged |= repoModel.syncMergeheads()
            stashesChanged = repoModel.syncStashes()
            homeBranchChanged = oldHeadBranch != repoModel.homeBranch

            # Load commits from changed refs only
            if refsChanged:
                self.syncTopOfGraph(oldRefs)

        # Schedule a repaint of the entire GraphView if the refs changed
        if effectFlags & (TaskEffects.Head | TaskEffects.Refs):
            rw.graphView.viewport().update()

        # Refresh sidebar
        rw.sidebar.backUpSelection()
        if refsChanged | stashesChanged | submodulesChanged | remotesChanged | homeBranchChanged | upstreamsChanged:
            with QSignalBlockerContext(rw.sidebar):
                rw.sidebar.refresh(repoModel)

        # Now jump to where we should be after the refresh
        assert rw.navLocator == initialLocator, "locator has changed"

        jumpTo = jumpTo or initialLocator

        jumpToWorkdir = jumpTo.context.isWorkdir() or (jumpTo.context == NavContext.EMPTY and initialLocator.context.isWorkdir())

        if effectFlags & TaskEffects.Workdir and not jumpToWorkdir:
            # Clear uncommitted change count if we know the workdir is stale
            repoModel.numUncommittedChanges = 0
            repoModel.workdirStale = True

        if jumpToWorkdir:
            # Refresh workdir view on separate thread AFTER all the processing above
            if not jumpTo.context.isWorkdir():
                jumpTo = NavLocator(NavContext.WORKDIR)

            if effectFlags & TaskEffects.Workdir:
                newFlags = jumpTo.flags | NavFlags.ForceDiff | NavFlags.AllowWriteIndex
                jumpTo = jumpTo.replace(flags=newFlags)

        elif initialLocator and initialLocator.context == NavContext.COMMITTED:
            # After inserting/deleting rows in the commit log model,
            # the selected row may jump around. Try to restore the initial
            # locator to ensure the previously selected commit stays selected.
            rw.graphView.verticalScrollBar().setValue(initialGraphScroll)
            if (jumpTo == initialLocator
                    and jumpTo.commit not in repoModel.graph.commitRows
                    and not wasExploringDetachedCommit):
                # We were looking at a commit that is not in the graph anymore.
                # Probably refreshing after amending. Jump to HEAD commit.
                jumpTo = NavLocator.inCommit(repoModel.headCommitId)

        # Jump
        yield from self.flowSubtask(Jump, jumpTo)

        # Try to restore sidebar selection
        if restoringInitialLocator:
            rw.sidebar.restoreSelectionBackup()
        else:
            rw.sidebar.clearSelectionBackup()

        # Try to restore path selection
        if previousFileList is None:
            pass
        elif restoringInitialLocator:
            previousFileList.restoreSelectionBackup()
        else:
            previousFileList.clearSelectionBackup()

        # Refresh window title and state banner.
        # Do this last because it requires the index to be fresh (updated by the Jump subtask)
        rw.refreshWindowChrome()

        logger.debug(f"Changes detected on refresh: "
                     f"Ref={refsChanged} Stash={stashesChanged} Submo={submodulesChanged} Remote={remotesChanged}")

    def syncTopOfGraph(self, oldRefs: dict[str, Oid]):
        repoModel = self.repoModel
        graphView = self.rw.graphView
        clModel = graphView.clModel
        clFilter = graphView.clFilter

        # Make sure we're on the UI thread.
        # We don't want GraphView to try to read an incomplete state while repainting.
        assert onAppThread()

        # Update our graph model
        gsl = repoModel.syncTopOfGraph(oldRefs)

        with QSignalBlockerContext(graphView):
            # Hidden commits may have changed in RepoState.syncTopOfGraph!
            # If new commits are part of a hidden branch, we've got to invalidate the CommitFilter.
            clFilter.setHiddenCommits(repoModel.hiddenCommits)

            if gsl.numRowsRemoved >= 0:
                # Sync top of graphview
                clModel.mendCommitSequence(gsl.numRowsRemoved, gsl.numRowsAdded, repoModel.commitSequence)
            else:
                # Replace graph wholesale
                clModel.setCommitSequence(repoModel.commitSequence)
