# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

from gitfourchette import settings
from gitfourchette.blameview.blamemodel import BlameModel, RevList, Revision
from gitfourchette.diffview.diffdocument import LineData
from gitfourchette.gitdriver import argsIf, GitDriver, GitStatus, GitDeltaSource, GitDelta
from gitfourchette.gitdriver.gitdeltafile import HexHash0000
from gitfourchette.gitdriver.parsers import parseGitBlame
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID
from gitfourchette.syntax import LexJobCache, LexerCache, LexJob
from gitfourchette.tasks import RepoTask, TaskPrereqs
from gitfourchette.tasks.repotask import AbortTask
from gitfourchette.toolbox import *

if TYPE_CHECKING:
    from gitfourchette.blameview.blamewindow import BlameWindow


class OpenBlame(RepoTask):
    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoUnborn

    def flow(self, path: str, seed: Oid = NULL_OID) -> RepoTask.Flow[BlameWindow]:
        from gitfourchette.blameview.blamewindow import BlameWindow

        upperBound = yield from self._findUpperBound(path, seed)
        revList = yield from self._buildRevList(path, upperBound)

        blameModel = BlameModel(self.repoModel, revList)

        blameWindow = BlameWindow(blameModel)
        blameWindow.taskRunner.repoModel = self.repoModel
        blameWindow.exploreCommit.connect(self.rw.jump)
        blameModel.revsFile.setParent(blameWindow)

        # Die in tandem with RepoWidget
        self.rw.destroyed.connect(blameWindow.close)

        blameWindow.show()
        blameWindow.activateWindow()  # bring to foreground after ProcessDialog

        self.epilog.status = _n("{n} revision found.", "{n} revisions found.", n=len(revList))

        try:
            start = revList.revisionForCommit(seed)
        except KeyError:
            start = blameModel.currentRevision
        blameWindow.showRevision(start)

        return blameWindow

    def _findUpperBound(self, path: str, seed: Oid) -> RepoTask.Flow[Oid]:
        if seed == NULL_OID:
            return seed

        # Favor current branch if it contains this commit
        if path not in self.repo.head_tree:
            useHead = False
        else:
            driver = yield from self.flowCallGit(
                "merge-base",
                "--is-ancestor",
                str(seed),
                "HEAD",
                autoFail=False)
            if driver.exitCode() not in [0, 1]:
                raise AbortTask(driver.htmlErrorText(), details=driver.formatCommandLine())
            useHead = driver.exitCode() == 0

        if useHead:
            newSeed = self.repo.head_commit_id
        else:
            # Fall back to most recent branch that contains this commit
            driver = yield from self.flowCallGit(
                "for-each-ref",
                "--count=1",
                f"--contains={seed}",
                "--format=%(objectname)")
            hashStr = driver.stdoutScrollback().strip()
            newSeed = Oid(hex=hashStr)

        if seed != newSeed:
            tree = self.repo[newSeed].peel(Tree)
            if path in tree:
                seed = newSeed

        return seed

    def _buildRevList(self, path: str, upperBound: Oid) -> RepoTask.Flow[RevList]:
        seedPath = path
        revList = RevList()

        while path:
            revision, path = yield from self._expandRevList(revList, path, upperBound)
            if revision:
                upperBound = revision.commitId

        if len(revList) == 0:
            raise AbortTask(_("File {0} has no history in the repository.", bquo(seedPath)))

        wdDelta = self.repoModel.findWorkdirDelta(seedPath)
        if wdDelta is not None:
            topRev = revList.sequence[0]
            wdRev = Revision(wdDelta.new.path, UC_FAKEID, parentIds=[topRev.commitId], status=wdDelta.status)
            revList.insert(0, wdRev)

        return revList

    def _expandRevList(
            self,
            revList: RevList,
            path: str,
            upperBound: Oid
    ) -> RepoTask.Flow[tuple[Revision | None, str]]:
        # Notes about some of the arguments:
        # --parents
        #       Enable parent rewriting so we can build a simplified graph
        #       containing just the commits that touch this file.
        # --topo-order
        #       Prevent dangling lanes in the graph. Note that this causes git
        #       to output the result in one go, making line-by-line processing
        #       futile.
        # --show-pulls
        #       Show merge commits to make the graph easier to understand.
        # We're not using "--follow" because it appears to be incompatible with
        # parent rewriting, which we need to prepare the graph. Instead, we'll
        # chain 'git log' calls if we detect a rename at the bottom of the
        # history.
        driver = yield from self.flowCallGit(
            "log",
            "--show-pulls",
            "--parents",
            "--topo-order",
            *argsIf(settings.prefs.chronologicalOrder, "--date-order"),
            *argsIf(upperBound != NULL_OID, str(upperBound)),
            "--format=%H %P",
            "--",
            path)

        scrollback = driver.stdoutScrollback()

        revision = None
        bottomPath = ""

        for line in scrollback.splitlines():
            hashes = [Oid(hex=h) for h in line.strip().split(" ")]
            commitId = hashes[0]
            parentIds = hashes[1:]
            try:
                revision = revList.revisionForCommit(commitId)
                assert not revision.parentIds, "existing revision already has parents!!!"
                revision.parentIds = parentIds
            except KeyError:
                status = GitStatus.Modified if parentIds else GitStatus.Added
                revision = Revision(path, commitId, parentIds, status=status)
                revList.push(revision)

                # Tip commit (not referred to by another commit in the trace):
                # May be a deletion or a rename
                if commitId not in revList.nonTipCommits:
                    yield from self._refineWithDelta(revision)

            revList.nonTipCommits.update(parentIds)

        # Last revision has no parents - See if it's a rename
        if revision is not None and not revision.parentIds:
            delta = yield from self._refineWithDelta(revision)
            if delta.status in [GitStatus.Renamed, GitStatus.Copied]:
                bottomPath = delta.old.path

        # TODO: If the top commit is 'R' we could expand its history upwards!
        return revision, bottomPath

    def _refineWithDelta(self, node: Revision):
        commit = self.repo.peel_commit(node.commitId)
        diffAB = commit_diff_pair(commit)
        tokens = GitDriver.buildDiffRawCommand(diffAB)
        driver = yield from self.flowCallGit(*tokens)
        deltas = driver.readDiffRawZ()
        try:
            delta = next(d for d in deltas if d.new.path == node.path)
        except StopIteration:
            delta = next(d for d in deltas if d.old.path == node.path)
            node.path = delta.new.path
        node.status = delta.status
        return delta


class OpenBlameToLine(RepoTask):
    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoUnborn

    def flow(self, delta: GitDelta, lineData: LineData):
        if lineData.origin == "-":
            file = delta.old
            line = lineData.oldLineNo
        else:
            file = delta.new
            line = lineData.newLineNo

        # ----------------------------------------------------------------------
        # Find out which commit introduced this line.
        # We'll start the blame window to that commit.

        if file.source == GitDeltaSource.Commit:
            lineSeedRev = str(file.sourceCommit)
        elif file.source == GitDeltaSource.Index and delta.source == GitDeltaSource.Dirty:
            lineSeedRev = "HEAD"
        else:
            lineSeedRev = ""
        assert lineSeedRev not in ["None", HexHash0000]

        driver = yield from self.flowCallGit(
            "blame",
            "--porcelain",
            f"-L{line},{line}",
            *argsIf(bool(lineSeedRev), lineSeedRev),
            "--",
            file.path)

        seedHash, line, _dummy = next(parseGitBlame(driver.stdoutScrollback()))
        seedCommit = Oid(hex=seedHash)
        # Note: Git can return 0000000 if the change originated in the workdir.
        # We happen to interpret that as UC_FAKEID.

        # ----------------------------------------------------------------------
        # Perform the full blame

        blameWindow: BlameWindow = yield from self.flowSubtask(OpenBlame, file.path, seedCommit)

        # ----------------------------------------------------------------------
        # Select the line

        block = blameWindow.textEdit.document().findBlockByNumber(line - 1)
        assert block.isValid()
        cursor = QTextCursor(block)  # cursor positioned at block start
        cursor.setPosition(block.position() + block.length() - 1, QTextCursor.MoveMode.KeepAnchor)
        blameWindow.textEdit.setTextCursor(cursor)
        blameWindow.textEdit.centerCursor()

        # Check selection accuracy
        if file.source.isWorkdir() and cursor.selectedText().rstrip() != lineData.text.rstrip():
            sorry = paragraphs(
                _("Couldn’t blame the exact line you selected, because "
                  "the file contains both staged and unstaged changes."),
                _("Try staging the entire file for more reliable results."))
            showInformation(blameWindow, _("Blame Line"), sorry)


class BlameRevision(RepoTask):
    def broadcastProcesses(self) -> bool:
        # Don't show ProcessDialog when switching to another revision
        return False

    def canKill(self, task: RepoTask) -> bool:
        # Allow interrupting a blame by switching to another revision via the
        # scrubber or nav buttons
        return isinstance(task, BlameRevision) or super().canKill(task)

    def flow(self, revision: Revision, saveAndTransposePosition: bool):
        from gitfourchette.blameview.blamewindow import BlameWindow

        blameWindow = self.parentWidget()
        assert isinstance(blameWindow, BlameWindow)

        blameModel = blameWindow.model

        # Stop lexing BEFORE changing the document!
        blameWindow.textEdit.highlighter.stopLexJobs()

        previousRevision = blameModel.currentRevision
        saveAndTransposePosition &= previousRevision.isAnnotated()

        # Save current locator in nav history
        if saveAndTransposePosition:
            blameWindow.saveFilePosition()

        # Update scrubber
        # Heads up: Look up scrubber row from the sequence of nodes, not via
        # scrubber.findData(commitId, CommitLogModel.Role.Oid), because this
        # compares references to Oid objects, not Oid values.
        scrubberIndex = blameModel.revList.sequence.index(revision)
        with QSignalBlockerContext(blameWindow.scrubber):
            blameWindow.scrubber.setCurrentIndex(scrubberIndex)

        # Sync back/forward/newer/older states with scrubber and history BEFORE
        # loading the file to keep the user from spamming a button that's
        # supposed to be disabled.
        blameWindow.syncNavButtons()

        # Load the annotated revision if we haven't cached it before.
        # Note that the user can kill the task here, either by closing the
        # BlameWindow, or by switching to another commit using the scrubber
        # or nav buttons.
        if not revision.isAnnotated():
            blameWindow.busySpinner.start()
            yield from self._annotate(revision, blameModel)
            assert revision.isAnnotated()

        # OK, we haven't been interrupted and we're ready to display the file.
        # Make this TraceNode current in the model.
        blameModel.currentRevision = revision

        # Figure out which line number (QTextBlock) to scroll to
        topBlock = blameWindow.textEdit.topLeftCornerCursor().blockNumber()
        if saveAndTransposePosition:  # Attempt to restore position across files
            try:
                oldLine = previousRevision.blameLines[1 + topBlock]
                topBlock = revision.findLine(oldLine, topBlock) - 1
            except (IndexError,  # Zero lines in annotatedFile ("File deleted in commit" notice)
                    ValueError):  # Could not findLineByReference
                pass  # default to raw line number already stored in topBlock

        # Get file text
        useLexer = False
        if revision.binary:
            text = _("Binary blob")
            text = f"*** {text} ***"
        elif revision.fullText is None:
            if revision.commitId == NULL_OID:
                text = _("File deleted in working directory")
            else:
                text = _("File deleted in commit {0}", shortHash(revision.commitId))
            text = f"*** {text} ***"
        else:
            text = revision.fullText
            useLexer = bool(text)

        newLocator = blameModel.currentRevision.toLocator()
        newLocator = blameWindow.navHistory.refine(newLocator)
        blameWindow.navHistory.push(newLocator)  # this should update in place

        blameWindow.textEdit.setPlainText(text)
        blameWindow.textEdit.currentLocator = newLocator
        blameWindow.textEdit.restorePosition(newLocator)
        blameWindow.textEdit.syncViewportMarginsWithGutter()

        title = _("Blame {path} @ {commit} (Revision {rev}/{total})",
                  path=tquo(revision.path),
                  commit=shortHash(revision.commitId) if revision.commitId else _("Uncommitted"),
                  rev=blameModel.revList.revisionNumber(revision.commitId),
                  total=len(blameModel.revList))
        blameWindow.setWindowTitle(title)

        if saveAndTransposePosition:
            blockPosition = blameWindow.textEdit.document().findBlockByNumber(topBlock).position()
            blameWindow.textEdit.restoreScrollPosition(blockPosition)

        # Install lex job
        lexJob = self._getLexJob(revision) if useLexer else None
        if lexJob is not None:
            blameWindow.textEdit.highlighter.installLexJob(lexJob)
            blameWindow.textEdit.highlighter.rehighlight()

        blameWindow.busySpinner.stop()
        blameWindow.syncNavButtons()

        # Refresh search term now that the document has changed
        blameWindow.textEdit.searchBar.reevaluateSearchTerm()

    def _annotate(self, revision: Revision, blameModel: BlameModel):
        assert not revision.isAnnotated(), "node annotation already built"

        # Initialize list with a dummy line #0 so effective numbering can start at 1
        dummyLine0 = Revision.BlameLine(revision.commitId, 0)
        revision.blameLines.append(dummyLine0)

        if revision.status == GitStatus.Deleted:
            return

        driver = yield from self.flowCallGit(
            "blame",
            "--porcelain",
            *argsIf(revision.commitId != UC_FAKEID, str(revision.commitId)),
            "-S", blameModel.revsFile.fileName(),
            "--",
            revision.path)

        stdout = driver.stdoutScrollback()

        allLines = []
        binaryCheckChars = 8000  # similar to git's buffer_is_binary

        for hexHash, originalLineNumber, lineText in parseGitBlame(stdout):
            oid = Oid(hex=hexHash)
            annotatedLine = Revision.BlameLine(oid, originalLineNumber)
            revision.blameLines.append(annotatedLine)

            if revision.binary:
                continue

            allLines.append(lineText)

            if binaryCheckChars < 0:
                pass
            elif lineText.find("\0", 0, binaryCheckChars) >= 0:
                revision.binary = True
                allLines.clear()  # don't care about the text anymore
            else:
                binaryCheckChars -= len(lineText)

        if not revision.binary:
            revision.fullText = "".join(allLines)

    @staticmethod
    def _getLexJob(revision: Revision) -> LexJob | None:
        if not settings.prefs.isSyntaxHighlightingEnabled():
            return None

        assert revision.fullText
        cacheKey = f"blame:{revision.commitId}:{revision.path}"

        try:
            return LexJobCache.get(cacheKey)
        except KeyError:
            pass

        lexer = LexerCache.getLexerFromPath(revision.path, settings.prefs.pygmentsPlugins)
        if lexer is None:
            return None

        lexJob = LexJob(lexer, revision.fullText, cacheKey)
        if lexJob is None:
            return None

        LexJobCache.put(lexJob)
        return lexJob
