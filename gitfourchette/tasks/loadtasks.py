# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
from collections.abc import Generator

from gitfourchette import settings
from gitfourchette.diffview.diffdocument import DiffDocument
from gitfourchette.forms.repostub import RepoStub
from gitfourchette.gitdriver import GitDelta, GitDeltaFile, GitConflict, GitDriver
from gitfourchette.gitdriver.lfspointer import LfsObjectCacheMissingError
from gitfourchette.gitdriver.parsers import parseAheadBehind
from gitfourchette.syntax.lexercache import LexerCache
from gitfourchette.syntax.lexjob import LexJob
from gitfourchette.syntax.lexjobcache import LexJobCache
from gitfourchette.diffview.specialdiff import SpecialDiffError, ImageDelta
from gitfourchette.graph import GraphBuildLoop
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavFlags, NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks.repotask import RepoTask, TaskEffects, FlowControlToken, AbortTask
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)

RENAME_COUNT_THRESHOLD = 100
""" Don't find_similar beyond this number of files in the main diff """

LONG_LINE_THRESHOLD = 10_000

TMultiDiffDocument = DiffDocument | GitConflict | ImageDelta | SpecialDiffError


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

        from gitfourchette.mainwindow import MainWindow
        from gitfourchette.repowidget import RepoWidget
        from gitfourchette.repomodel import RepoModel
        from gitfourchette.tasks import Jump

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

        # Create RepoModel
        repoModel = RepoModel(repo)
        self.setRepoModel(repoModel)  # required to execute subtasks later

        # Fill in superproject
        with Benchmark("superproject"):
            driver = yield from self.flowCallGit("rev-parse", "--show-superproject-working-tree", workdir=path)
            repoModel.superproject = driver.stdoutScrollback().rstrip()

        # Fill in ahead/behind
        with Benchmark("ahead-behind"):
            driver = yield from self.flowCallGit("for-each-ref", "--format=%(refname:short) %(upstream:track)", "refs/heads")
            repoModel.aheadBehind = dict(parseAheadBehind(driver.stdoutScrollback()))

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

        repoStub.closing.connect(rw.prepareForDeletion)
        yield from self.flowSubtask(Jump, locator)
        repoStub.closing.disconnect(rw.prepareForDeletion)
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


class LoadPatch(RepoTask):
    def canKill(self, task: RepoTask):
        return isinstance(task, LoadPatch)

    def flow(self, delta: GitDelta, locator: NavLocator):
        try:
            diff = yield from self._getPatch(delta, locator)
        except LfsObjectCacheMissingError as lfsMissing:
            diff = SpecialDiffError.missingLfsObjects(lfsMissing)
        except Exception as exc:
            # Yikes! Don't prevent loading a repo
            summary, details = excStrings(exc)
            diff = SpecialDiffError(escape(summary), icon="SP_MessageBoxCritical", preformatted=details)

        assert onAppThread()

        if isinstance(diff, DiffDocument):
            # Complete existing delta with actual blob hashes.
            # WARNING: GitDelta.id represents a *vanilla* blob, not an LFS blob,
            # so don't update the id if we're diffing an unpacked LFS object.
            if not delta.old.lfs:
                assert diff.oldHash == delta.old.id
            if not delta.new.lfs and not delta.new.isIdValid():
                delta.new.id = diff.newHash

            # Prime lexer
            diff.oldLexJob, diff.newLexJob = self._primeLexJobs(delta)

        header = self._makeHeader(diff, delta, locator)

        self.result = diff
        self.header = header

    def _getPatch(
            self,
            delta: GitDelta,
            locator: NavLocator,
    ) -> Generator[FlowControlToken, None, TMultiDiffDocument]:
        if delta.conflict is not None:
            return delta.conflict

        if delta.isSubtreeCommitPatch():
            return SpecialDiffError.submoduleDiff(self.repo, delta, locator)

        if delta.similarity == 100:
            return SpecialDiffError.noChange(self.repo, delta)

        # Special formatting for TYPECHANGE.
        if delta.status == "T":  # TYPECHANGE
            return SpecialDiffError.typeChange(delta)

        # ---------------------------------------------------------------------
        # Load the patch

        commit = self.repo.peel_commit(locator.commit) if locator.context == NavContext.COMMITTED else None

        # See if we should load an LFS object
        loadLfs = False
        if not settings.prefs.rawLfsPointers:
            commitId = commit.id if commit else NULL_OID
            delta.cacheLfsPointers(self.repo, commitId)

            hasOldLfs = bool(delta.old.lfs)
            hasNewLfs = bool(delta.new.lfs)

            if delta.status == "D":
                loadLfs = hasOldLfs
            elif delta.status in "?A":
                loadLfs = hasNewLfs
            else:
                loadLfs = hasOldLfs and hasNewLfs

        # Determine size/line limits
        likelyImage = isImageFormatSupported(delta.old.path) and isImageFormatSupported(delta.new.path)
        if locator.hasFlags(NavFlags.AllowLargeFiles):
            maxLineLength = 0
            maxFileSize = 0
        else:
            maxLineLength = LONG_LINE_THRESHOLD
            if likelyImage:
                maxFileSize = settings.prefs.imageFileThresholdKB * 1024
            else:
                maxFileSize = settings.prefs.largeFileThresholdKB * 1024

        # Don't load large diffs
        if maxFileSize != 0 and GitDeltaFile.SupportsFastSizeBallpark:
            oldBallpark = delta.old.sizeBallpark(self.repo)
            newBallpark = delta.new.sizeBallpark(self.repo)
            ballpark = max(oldBallpark, newBallpark)
            if maxFileSize < ballpark:
                return SpecialDiffError.fileTooLarge(ballpark, maxFileSize, locator, image=likelyImage)

        # Render SVG file if user wants to.
        if (settings.prefs.renderSvg
                and delta.new.path.lower().endswith(".svg")
                and isImageFormatSupported("file.svg")):
            return SpecialDiffError.binaryDiff(self.repo, delta, locator)

        # Build diff command
        if loadLfs:
            tokens = GitDriver.buildDiffCommandLFS(delta)
        else:
            tokens = GitDriver.buildDiffCommand(delta, commit, binary=False)

        # Run diff command
        driver = yield from self.flowCallGit(*tokens, autoFail=False)
        patch = driver.stdoutScrollback()

        # Don't display large diffs (legacy pygit2 version)
        # TODO: Remove this once we drop support for pygit2 <= 1.19.1
        if not GitDeltaFile.SupportsFastSizeBallpark and 0 < maxFileSize < len(patch):  # pragma: no cover (old pygit2)
            return SpecialDiffError.fileTooLarge(len(patch), maxFileSize, locator, image=False, legacy=True)

        # Building the diff document on the background thread lets the user
        # interrupt the task, e.g. if dragging the mouse across many commits.
        yield from self.flowEnterWorkerThread()

        # Special case for unstaged files: Before loading the patch, update the
        # GitDelta with fresh filesystem stats (st_mtime_ns). This allows
        # bypassing LoadPatch in a future refresh of the UI if the file isn't
        # modified. (We don't need to stat non-unstaged files because blob
        # hashes are known in advance, so for those, we can simply compare the
        # hashes stored in GitDelta to figure out if it's fresh.)
        if locator.context.isDirty():
            delta.new.diskStat = delta.new.stat(self.repo)

        try:
            diff = DiffDocument.fromPatch(patch, maxLineLength)
            diff.document.moveToThread(QApplication.instance().thread())
            return diff
        except DiffDocument.BinaryError:
            return SpecialDiffError.binaryDiff(self.repo, delta, locator)
        except DiffDocument.NoChangeError:
            stderr = driver.stderrScrollback()
            return SpecialDiffError.noChange(self.repo, delta, stderr)
        except DiffDocument.VeryLongLinesError:
            loadAnywayLoc = locator.withExtraFlags(NavFlags.AllowLargeFiles)
            return SpecialDiffError(
                _("This file contains very long lines."),
                linkify(_("[Load diff anyway] (this may take a moment)"), loadAnywayLoc.url()),
                "SP_MessageBoxWarning")
        finally:
            # Exit background thread
            yield from self.flowEnterUiThread()

    def _makeHeader(self, result: TMultiDiffDocument, delta: GitDelta, locator: NavLocator):
        header = "<html>" + settings.prefs.addDelColorsStyleTag() + escape(locator.path)

        if isinstance(result, DiffDocument):
            if result.pluses:
                header += f" <b><add>+{result.pluses}</add></b>"
            if result.minuses:
                header += f" <b><del>-{result.minuses}</del></b>"

        suffix = []
        if locator.context == NavContext.COMMITTED:
            suffix.append(_p("at (specific commit)", "at {0}", shortHash(locator.commit)))
        elif locator.context.isWorkdir():
            suffix.append(locator.context.translateName().lower())

        if not delta.new.lfs.isTentative():
            if delta.new.lfs and not delta.old.lfs:
                suffix.append(tagify(_("LFS pointer [added]"), "<add>"))
            elif not delta.new.lfs and delta.old.lfs:
                suffix.append(tagify(_("LFS pointer [removed]"), "<del>"))
            elif delta.new.lfs and delta.old.lfs:
                suffix.append(_("LFS pointer changed"))
        elif delta.old.lfs:
            suffix[0] = _("unstaged changes to LFS object")

        if suffix:
            header += f" <span style='color: gray;'>({', '.join(suffix)})</span>"

        return header

    def _primeLexJobs(self, delta: GitDelta) -> tuple[LexJob | None, LexJob | None]:
        assert onAppThread()

        if not settings.prefs.isSyntaxHighlightingEnabled():
            return None, None

        lexer = LexerCache.getLexerFromPath(delta.new.path, settings.prefs.pygmentsPlugins)

        if lexer is None:
            return None, None

        # Avoid awkward syntax highlighting of LFS pointers
        # when diffing against a vanilla Git blob
        if (not delta.old.isId0() and not delta.new.isId0()
                and bool(delta.old.lfs) != bool(delta.new.lfs)):
            return None, None

        oldLexJob = self._primeSingleLexJob(lexer, delta.old)
        newLexJob = self._primeSingleLexJob(lexer, delta.new)
        return oldLexJob, newLexJob

    def _primeSingleLexJob(self, lexer, file: GitDeltaFile):
        if file.isId0() or file.isEmptyBlob():
            return None

        # Figure out a key to look up this file in the lex cache.
        if file.isIdValid():
            # Use blob SHA-1 (most common case)
            key = file.id
        elif file.hasDiskStat():
            # Blob SHA-1 not available, but we've got a stat
            # (E.g. unstaged modification to an LFS file)
            key = file.diskStat
        else:
            raise NotImplementedError("need valid blob id or stat for lexing")

        try:
            return LexJobCache.get(key)
        except KeyError:
            pass

        data = file.read(self.repo)
        job = LexJob(lexer, data, key)

        assert job.fileKey == key
        assert job.fileKey not in LexJobCache.cache
        LexJobCache.put(job)

        return job


class LoadPatchInNewWindow(LoadPatch):
    def flow(self, delta: GitDelta, locator: NavLocator):
        yield from super().flow(delta, locator)

        diffDocument = self.result
        if not isinstance(diffDocument, DiffDocument):
            raise AbortTask(_("Only text diffs may be opened in a separate window."), icon="information")

        from gitfourchette.diffview.diffview import DiffView

        diffWindow = QWidget(self.parentWidget())
        diffWindow.setObjectName("DetachedDiffWindow")
        diffWindow.setWindowTitle(locator.asTitle())
        diffWindow.setWindowFlag(Qt.WindowType.Window, True)
        diffWindow.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        diff = DiffView(diffWindow)
        diff.isDetachedWindow = True
        diff.setFrameStyle(QFrame.Shape.NoFrame)
        diff.replaceDocument(self.repo, delta, locator, self.result)

        layout = QVBoxLayout(diffWindow)
        layout.setContentsMargins(QMargins())
        layout.setSpacing(0)
        layout.addWidget(diff)
        layout.addWidget(diff.searchBar)

        diffWindow.resize(550, 700)
        diffWindow.show()

        diff.setUpAsDetachedWindow()  # Required for detached windows


class DownloadLfsObjects(RepoTask):
    def flow(self, errors: LfsObjectCacheMissingError, informativeName: str = ""):
        for pointer in errors.pointers:
            # If successful, `git lfs smudge` will cache the LFS object in .git/lfs/objects
            # Note: the name isn't significant and is only for progress reporting
            driver = self.createGitProcess("lfs", "smudge", informativeName or pointer.id[:7])

            # Discard stdout
            driver.setStandardOutputFile(QProcess.nullDevice())

            yield from self.flowStartProcess(driver, stdin=pointer.pointerText)
            self.effects |= TaskEffects.DefaultRefresh
