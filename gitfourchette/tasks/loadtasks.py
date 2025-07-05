# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
from contextlib import suppress

from gitfourchette import colors
from gitfourchette import settings
from gitfourchette.diffview.diffdocument import DiffDocument
from gitfourchette.forms.repostub import RepoStub
from gitfourchette.syntax.lexercache import LexerCache
from gitfourchette.syntax.lexjob import LexJob
from gitfourchette.syntax.lexjobcache import LexJobCache
from gitfourchette.diffview.specialdiff import (ShouldDisplayPatchAsImageDiff, SpecialDiffError, DiffImagePair)
from gitfourchette.graph import GraphBuildLoop
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
    """
    This task initializes a RepoModel and a RepoWidget.
    It runs on a RepoStub's RepoTaskRunner, then hands over control to the RepoWidget.
    """

    @classmethod
    def name(cls) -> str:
        return _("Loading repo")

    def flow(self, repoStub: RepoStub):
        # Store repoStub in class instance so that onError() can manipulate it
        # if this coroutine raises an exception
        self.repoStub = repoStub

        from gitfourchette.application import GFApplication
        from gitfourchette.mainwindow import MainWindow
        from gitfourchette.repowidget import RepoWidget
        from gitfourchette.repomodel import RepoModel
        from gitfourchette.tasks import Jump

        app = GFApplication.instance()
        mainWindow: MainWindow = repoStub.window()
        assert isinstance(repoStub, RepoStub)
        assert isinstance(mainWindow, MainWindow)

        mainWindow.statusBar2.showBusyMessage(repoStub.ui.progressLabel.text())

        path = repoStub.workdir
        locator = repoStub.locator
        maxCommits = repoStub.maxCommits

        # Create the repo
        repo = Repo(path, RepositoryOpenFlag.NO_SEARCH)

        if repo.is_bare:
            raise NotImplementedError(_("Sorry, {app} doesn’t support bare repositories.", app=qAppName()))

        # Bind to sessionwide git config file.
        # Level -1 was chosen because it's the only level for which changing branch settings
        # in a repo won't leak into this file (e.g. change branch upstream).
        sessionwideConfigPath = app.sessionwideGitConfigPath
        repo.config.add_file(sessionwideConfigPath, level=-1)

        # Create RepoModel
        repoModel = RepoModel(repo)
        self.setRepoModel(repoModel)  # required to execute subtasks later

        # ---------------------------------------------------------------------
        # EXIT UI THREAD
        # ---------------------------------------------------------------------
        yield from self.flowEnterWorkerThread()

        # Get a locale to format numbers on the worker thread
        locale = QLocale()

        # Prime the walker (this might take a while)
        walker = repoModel.primeWalker()

        # Retrieve the number of commits that we loaded last time we opened this repo
        # so we can estimate how long it'll take to load it again
        numCommitsBallpark = settings.history.getRepoNumCommits(repo.workdir)

        if not numCommitsBallpark:
            repoStub.progressFraction.emit(-1.0)  # Indeterminate progress

        # ---------------------------------------------------------------------
        # Build commit sequence

        truncatedHistory = False
        if maxCommits < 0:  # -1 means take maxCommits from prefs. Warning, pref value can be 0, meaning infinity!
            maxCommits = settings.prefs.maxCommits
        if maxCommits == 0:  # 0 means infinity
            maxCommits = 2**63  # ought to be enough
        progressInterval = 1000 if maxCommits >= 10000 else 1000

        commitSequence = [repoModel.uncommittedChangesMockCommit()]

        for i, commit in enumerate(walker):
            commitSequence.append(commit)

            if i + 1 >= maxCommits or (i + 1 >= progressInterval and repoStub.didAbort):
                truncatedHistory = True
                break

            # Report progress, not too often
            if i % progressInterval == 0 and not repoStub.didAbort:
                message = _("{0} commits…", locale.toString(i))
                repoStub.progressMessage.emit(message)
                if numCommitsBallpark:  # Fill up left half of progress bar
                    repoStub.progressFraction.emit(.5 * min(1.0, i / numCommitsBallpark))
                # Let RepoTaskRunner kill us here (e.g. if closing the tab while we're loading)
                yield from self.flowEnterWorkerThread()

        # Can't abort anymore
        repoStub.progressAbortable.emit(False)

        numCommits = len(commitSequence) - 1
        logger.info(f"{repoModel.shortName}: loaded {numCommits} commits")
        if truncatedHistory:
            message = _("{0} commits loaded (truncated log).", locale.toString(numCommits))
        else:
            message = _("{0} commits total.", locale.toString(numCommits))
            repoStub.progressMessage.emit(message)

        # ---------------------------------------------------------------------
        # Build graph

        def reportGraphProgress(commitNo: int):
            if not numCommits:  # Avoid division by 0
                return
            progress = commitNo / numCommits
            if numCommitsBallpark:
                progress = .5 + .5 * progress  # Fill up the right half of the progress bar.
            self.repoStub.progressFraction.emit(progress)

        hideSeeds = repoModel.getHiddenTips()
        localSeeds = repoModel.getLocalTips()
        buildLoop = GraphBuildLoop(heads=repoModel.getKnownTips(), hideSeeds=hideSeeds, localSeeds=localSeeds)
        buildLoop.onKeyframe = reportGraphProgress
        buildLoop.sendAll(commitSequence)
        repoStub.progressFraction.emit(1.0)

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
        assert not repoStub.didClose, "unexpectedly continuing PrimeRepo after RepoStub was closed"

        # Save commit count (if not truncated)
        if not truncatedHistory:
            settings.history.setRepoNumCommits(repo.workdir, numCommits)

        # Bump repo in history
        settings.history.addRepo(repo.workdir)
        settings.history.setRepoSuperproject(repo.workdir, repoModel.superproject)
        settings.history.write()

        # Finally, prime the UI: Create RepoWidget
        repoStub.taskRunner.repoModel = repoModel
        rw = RepoWidget(repoModel, repoStub.taskRunner, parent=mainWindow)
        # del repoStub.taskRunner

        # Replicate final loading message in status bar
        rw.pendingStatusMessage = message

        # Jump to workdir (or pending locator, if any)
        assert not rw.pendingLocator
        if not locator:
            locator = NavLocator(NavContext.WORKDIR).withExtraFlags(NavFlags.AllowWriteIndex)

        repoStub.closing.connect(rw.cleanup)
        yield from self.flowSubtask(Jump, locator)
        repoStub.closing.disconnect(rw.cleanup)
        assert not repoStub.didClose, "unexpectedly continuing InstallRepoWidget after RepoStub was closed during Jump"

        rw.refreshNumUncommittedChanges()
        rw.graphView.scrollToRowForLocator(locator, QAbstractItemView.ScrollHint.PositionAtCenter)

        mainWindow.installRepoWidget(rw, mainWindow.tabs.indexOf(repoStub))

        # Once RepoWidget is installed, consider repoStub dead beyond this point
        del repoStub, self.repoStub

        # Refresh tab/window/banner text
        rw.nameChange.emit()

        # It's not necessary to refresh everything again (including workdir patches)
        # after priming the repo.
        self.effects = TaskEffects.Nothing

        # RepoWidget.refreshRepo may have been called while we were setting up the widget in this task.
        # Clear the stashed effect bits to avoid an unnecessary refresh.
        rw.pendingEffects = TaskEffects.Nothing

        # Focus on some interesting widget within the RepoWidget after loading the repo.
        rw.graphView.setFocus()

    def onError(self, exc: Exception):
        try:
            repoStub = self.repoStub
        except AttributeError:
            pass
        else:
            if not repoStub.didClose:
                repoStub.disableAutoLoad(message=str(exc))

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
