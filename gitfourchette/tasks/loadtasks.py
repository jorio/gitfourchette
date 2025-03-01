# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
from contextlib import suppress

from gitfourchette import colors
from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.diffview.diffdocument import DiffDocument
from gitfourchette.syntax.lexercache import LexerCache
from gitfourchette.syntax.lexjob import LexJob
from gitfourchette.syntax.lexjobcache import LexJobCache
from gitfourchette.diffview.specialdiff import (ShouldDisplayPatchAsImageDiff, SpecialDiffError, DiffImagePair)
from gitfourchette.graph import GraphBuildLoop
from gitfourchette.graphview.commitlogmodel import SpecialRow
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavFlags, NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks.repotask import RepoTask, TaskEffects
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables

logger = logging.getLogger(__name__)

RENAME_COUNT_THRESHOLD = 100
""" Don't find_similar beyond this number of files in the main diff """


def contextLines():
    return settings.prefs.contextLines


class PrimeRepo(RepoTask):
    progressRange = Signal(int, int)
    progressValue = Signal(int)
    progressMessage = Signal(str)
    progressAbortable = Signal(bool)

    abortFlag: bool

    def onAbortButtonClicked(self):
        self.abortFlag = True

    def flow(self, path: str, maxCommits: int = -1):
        from gitfourchette.repowidget import RepoWidget
        from gitfourchette.repomodel import RepoModel
        from gitfourchette.tasks.jumptasks import Jump

        assert path

        rw = self.rw
        assert isinstance(rw, RepoWidget)

        progressWidget = rw.setPlaceholderWidgetOpenRepoProgress()

        self.abortFlag = False
        self.progressRange.connect(progressWidget.ui.progressBar.setRange)
        self.progressValue.connect(progressWidget.ui.progressBar.setValue)
        self.progressMessage.connect(progressWidget.ui.label.setText)
        self.progressAbortable.connect(progressWidget.ui.abortButton.setEnabled)
        progressWidget.ui.abortButton.clicked.connect(self.onAbortButtonClicked)

        # Create the repo
        repo = Repo(path, RepositoryOpenFlag.NO_SEARCH)

        if repo.is_bare:
            raise NotImplementedError(_("Sorry, {app} doesn’t support bare repositories.", app=qAppName()))

        # Bind to sessionwide git config file
        sessionwideConfigPath = GFApplication.instance().sessionwideGitConfigPath
        # Level -1 was chosen because it's the only level for which changing branch settings
        # in a repo won't leak into this file (e.g. change branch upstream).
        # TODO: `level=4, force=True` would make sense here but this leaks branch settings. Is this a bug in pygit2?
        #       git_config_add_file_ondisk has an optional 'repo' argument "to allow parsing of conditional includes",
        #       but pygit2 doesn't make it possible to pass anything but NULL.
        #       See also https://github.com/libgit2/libgit2/blob/main/include/git2/config.h#L42
        repo.config.add_file(sessionwideConfigPath, level=-1)

        # Create RepoModel
        repoModel = RepoModel(repo)
        self.setRepoModel(repoModel)  # required to execute subtasks later

        # ---------------------------------------------------------------------
        # EXIT UI THREAD
        # ---------------------------------------------------------------------
        yield from self.flowEnterWorkerThread()

        locale = QLocale()

        # Prime the walker (this might take a while)
        walker = repoModel.primeWalker()

        commitSequence = [repoModel.uncommittedChangesMockCommit()]

        # Retrieve the number of commits that we loaded last time we opened this repo
        # so we can estimate how long it'll take to load it again
        numCommitsBallpark = settings.history.getRepoNumCommits(repo.workdir)
        if numCommitsBallpark != 0:
            # Reserve second half of progress bar for graph progress
            self.progressRange.emit(0, 2*numCommitsBallpark)

        # ---------------------------------------------------------------------
        # Build commit sequence

        self.progressAbortable.emit(True)

        truncatedHistory = False
        if maxCommits < 0:  # -1 means take maxCommits from prefs. Warning, pref value can be 0, meaning infinity!
            maxCommits = settings.prefs.maxCommits
        if maxCommits == 0:  # 0 means infinity
            maxCommits = 2**63  # ought to be enough
        progressInterval = 1000 if maxCommits >= 10000 else 1000

        for i, commit in enumerate(walker):
            commitSequence.append(commit)

            if i+1 >= maxCommits or (self.abortFlag and i+1 >= progressInterval):
                truncatedHistory = True
                break

            # Report progress, not too often
            if i % progressInterval == 0:
                message = _("{0} commits…", locale.toString(i))
                self.progressMessage.emit(message)
                if numCommitsBallpark > 0 and i <= numCommitsBallpark:
                    self.progressValue.emit(i)
                    # Let RepoTaskRunner kill us here (e.g. if closing the RepoWidget tab while we're loading)
                    yield from self.flowEnterWorkerThread()

        # Can't abort anymore
        self.progressAbortable.emit(False)

        numCommits = len(commitSequence) - 1
        logger.info(f"{repoModel.shortName}: loaded {numCommits} commits")
        if truncatedHistory:
            message = _("{0} commits (truncated log).", locale.toString(numCommits))
        else:
            message = _("{0} commits total.", locale.toString(numCommits))
        self.progressMessage.emit(message)

        if numCommitsBallpark != 0:
            # First half of progress bar was for commit log
            self.progressRange.emit(-numCommits, numCommits)
        else:
            self.progressRange.emit(0, numCommits)
        self.progressValue.emit(0)

        # ---------------------------------------------------------------------
        # Build graph

        hideSeeds = self.repoModel.getHiddenTips()
        localSeeds = self.repoModel.getLocalTips()
        buildLoop = GraphBuildLoop(heads=self.repoModel.getKnownTips(), hideSeeds=hideSeeds, localSeeds=localSeeds)
        buildLoop.onKeyframe = self.progressValue.emit
        buildLoop.sendAll(commitSequence)
        self.progressValue.emit(numCommits)

        graph = buildLoop.graph
        repoModel.hiddenCommits = buildLoop.hiddenCommits
        repoModel.foreignCommits = buildLoop.foreignCommits
        repoModel.commitSequence = commitSequence
        repoModel.truncatedHistory = truncatedHistory
        repoModel.graph = graph
        repoModel.hideSeeds = hideSeeds
        repoModel.localSeeds = localSeeds

        # ---------------------------------------------------------------------
        # RETURN TO UI THREAD
        # ---------------------------------------------------------------------
        yield from self.flowEnterUiThread()

        # Assign RepoModel to RepoWidget
        rw.repoModel = repoModel
        rw.updateBoundRepo()

        # Save commit count (if not truncated)
        if not truncatedHistory:
            settings.history.setRepoNumCommits(repo.workdir, numCommits)

        # Bump repo in history
        settings.history.addRepo(repo.workdir)
        settings.history.setRepoSuperproject(repo.workdir, repoModel.superproject)
        settings.history.write()
        rw.window().fillRecentMenu()  # TODO: emit signal instead?

        # Finally, prime the UI.

        # Prime GraphView
        with QSignalBlockerContext(rw.graphView):
            if repoModel.truncatedHistory:
                extraRow = SpecialRow.TruncatedHistory
            elif repo.is_shallow:
                extraRow = SpecialRow.EndOfShallowHistory
            else:
                extraRow = SpecialRow.Invalid

            rw.graphView.clFilter.setHiddenCommits(repoModel.hiddenCommits)
            rw.graphView.clModel._extraRow = extraRow
            rw.graphView.clModel.setCommitSequence(repoModel.commitSequence)
            rw.graphView.selectRowForLocator(NavLocator.inWorkdir(), force=True)

        # Prime Sidebar
        with QSignalBlockerContext(rw.sidebar):
            collapseCache = repoModel.prefs.collapseCache
            if collapseCache:
                rw.sidebar.sidebarModel.collapseCache = set(collapseCache)
                rw.sidebar.sidebarModel.collapseCacheValid = True
            rw.sidebar.refresh(repoModel)

        # Focus on some interesting widget within the RepoWidget after loading the repo.
        rw.setInitialFocus()

        # Restore main UI
        rw.removePlaceholderWidget()

        # Refresh tab text
        rw.nameChange.emit()

        # Splitters may have moved around while loading, restore them
        rw.restoreSplitterStates()

        # Scrolling HEAD into view isn't super intuitive if we boot to Uncommitted Changes
        # if newState.activeCommitId:
        #     rw.graphView.scrollToCommit(newState.activeCommitId, QAbstractItemView.ScrollHint.PositionAtCenter)

        # Jump to workdir (or pending locator, if any)
        if not rw.pendingLocator:
            initialLocator = NavLocator(NavContext.WORKDIR)
            initialLocator = initialLocator.withExtraFlags(NavFlags.AllowWriteIndex)
        else:
            # Consume pending locator
            initialLocator = rw.pendingLocator
            rw.pendingLocator = NavLocator()
        yield from self.flowSubtask(Jump, initialLocator)

        rw.refreshNumUncommittedChanges()
        rw.graphView.scrollToRowForLocator(initialLocator, QAbstractItemView.ScrollHint.PositionAtCenter)

        # It's not necessary to refresh everything again (including workdir patches)
        # after priming the repo.
        self.effects = TaskEffects.Nothing

    def onError(self, exc: Exception):
        self.rw.cleanup(str(exc), allowAutoReload=False)
        super().onError(exc)


class LoadWorkdir(RepoTask):
    """
    Refresh stage/dirty diffs in the RepoModel.
    """

    def canKill(self, task: RepoTask):
        if isinstance(task, LoadWorkdir):
            warnings.warn("LoadWorkdir is killing another LoadWorkdir. This is inefficient!")
            return True
        return isinstance(task, LoadCommit | LoadPatch)

    def flow(self, allowWriteIndex: bool):
        yield from self.flowEnterWorkerThread()

        with Benchmark("LoadWorkdir/Index"):
            self.repo.refresh_index()

        with Benchmark("LoadWorkdir/Staged"):
            stageDiff = self.repo.get_staged_changes(context_lines=contextLines())

        # yield from self.flowEnterWorkerThread()  # let task thread be interrupted here
        with Benchmark("LoadWorkdir/Unstaged"):
            dirtyDiff = self.repo.get_unstaged_changes(allowWriteIndex, context_lines=contextLines())

        yield from self.flowEnterUiThread()
        self.repoModel.stageDiff = stageDiff
        self.repoModel.dirtyDiff = dirtyDiff
        self.repoModel.workdirDiffsReady = True
        self.repoModel.numUncommittedChanges = len(stageDiff) + len(dirtyDiff)


class LoadCommit(RepoTask):
    def canKill(self, task: RepoTask):
        return isinstance(task, LoadWorkdir | LoadCommit | LoadPatch)

    def flow(self, locator: NavLocator):
        yield from self.flowEnterWorkerThread()

        oid = locator.commit
        largeCommitThreshold = -1 if locator.hasFlags(NavFlags.AllowLargeCommits) else RENAME_COUNT_THRESHOLD

        self.diffs, self.skippedRenameDetection = self.repo.commit_diffs(
            oid, find_similar_threshold=largeCommitThreshold, context_lines=contextLines())
        self.message = self.repo.get_commit_message(oid)


class LoadPatch(RepoTask):
    def canKill(self, task: RepoTask):
        return isinstance(task, LoadPatch)

    def _processPatch(self, patch: Patch, locator: NavLocator
                      ) -> DiffDocument | SpecialDiffError | DiffConflict | DiffImagePair:
        if not patch:
            locator = locator.withExtraFlags(NavFlags.ForceDiff)
            longformItems = [linkify(_("Try to reload the file."), locator.url())]

            if locator.context.isWorkdir() and not settings.prefs.autoRefresh:
                prefKey = "autoRefresh"
                tip = _("Consider re-enabling {0} to prevent this issue.",
                        linkify(hquo(TrTables.prefKey(prefKey)), makeInternalLink("prefs", prefKey)))
                longformItems.append(tip)

            return SpecialDiffError(_("Outdated diff."),
                                    _("The file appears to have changed on disk."),
                                    icon="SP_MessageBoxWarning",
                                    longform=toRoomyUL(longformItems))

        if not patch.delta:
            # Rare libgit2 bug, should be fixed in 1.6.0
            return SpecialDiffError(_("Patch has no delta!"), icon="SP_MessageBoxWarning")

        if patch.delta.status == DeltaStatus.CONFLICTED:
            path = patch.delta.new_file.path
            return self.repo.wrap_conflict(path)

        if FileMode.COMMIT in (patch.delta.new_file.mode, patch.delta.old_file.mode):
            return SpecialDiffError.submoduleDiff(self.repo, patch, locator)

        try:
            diffModel = DiffDocument.fromPatch(patch, locator)
            diffModel.document.moveToThread(QApplication.instance().thread())
            return diffModel
        except SpecialDiffError as dme:
            return dme
        except ShouldDisplayPatchAsImageDiff:
            return DiffImagePair(self.repo, patch.delta, locator)
        except BaseException as exc:
            summary, details = excStrings(exc)
            return SpecialDiffError(summary, icon="SP_MessageBoxCritical", preformatted=details)

    def _makeHeader(self, result, locator):
        header = "<html>" + escape(locator.path)

        if isinstance(result, DiffDocument):
            if settings.prefs.colorblind:
                addColor = colors.teal
                delColor = colors.orange
            else:
                addColor = colors.olive
                delColor = colors.red
            if result.pluses:
                header += f" <span style='color: {addColor.name()};'>+{result.pluses}</span>"
            if result.minuses:
                header += f" <span style='color: {delColor.name()};'>-{result.minuses}</span>"

        locationText = ""
        if locator.context == NavContext.COMMITTED:
            locationText = _p("at (specific commit)", "at {0}", shortHash(locator.commit))
        elif locator.context.isWorkdir():
            locationText = locator.context.translateName().lower()
        if locationText:
            header += f" <span style='color: gray;'>({locationText})</span>"

        return header

    def flow(self, patch: Patch, locator: NavLocator):
        yield from self.flowEnterWorkerThread()
        # QThread.msleep(500)
        self.result = self._processPatch(patch, locator)
        self.header = self._makeHeader(self.result, locator)

        # Prime lexer
        yield from self.flowEnterUiThread()
        if type(self.result) is DiffDocument:
            oldLexJob, newLexJob = self._primeLexJobs(patch.delta.old_file, patch.delta.new_file, locator)
            self.result.oldLexJob = oldLexJob
            self.result.newLexJob = newLexJob

    def _primeLexJobs(self, oldFile: DiffFile, newFile: DiffFile, locator: NavLocator):
        assert onAppThread()

        if not settings.prefs.isSyntaxHighlightingEnabled():
            return None, None

        lexer = LexerCache.getLexerFromPath(newFile.path, settings.prefs.pygmentsPlugins)

        if lexer is None:
            return None, None

        def primeLexJob(file: DiffFile, isDirty: bool):
            assert file.flags & DiffFlag.VALID_ID, "need valid blob id for lexing"

            if file.id == NULL_OID:
                assert not file.flags & DiffFlag.EXISTS, "need valid blob id if reading dirty file from disk"
                return None

            if file.id == EMPTYBLOB_OID:
                return None

            with suppress(KeyError):
                return LexJobCache.get(file.id)

            try:
                data = self.repo[file.id].data
            except KeyError:
                assert isDirty, "reading from disk should only occur for dirty files"
                blobId = self.repo.create_blob_fromworkdir(file.path)
                assert blobId == file.id
                data = self.repo[file.id].data

            return LexJob(lexer, data, file.id)

        oldLexJob = primeLexJob(oldFile, False)
        newLexJob = primeLexJob(newFile, locator.context.isDirty())

        for job in oldLexJob, newLexJob:
            if job is not None and job.fileKey not in LexJobCache.cache:
                LexJobCache.put(job)

        return oldLexJob, newLexJob
