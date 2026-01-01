# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import TYPE_CHECKING

from gitfourchette import settings
from gitfourchette.blameview.blamemodel import BlameModel, Trace, TraceNode, AnnotatedFile
from gitfourchette.gitdriver import argsIf
from gitfourchette.gitdriver.parsers import parseGitBlame
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID
from gitfourchette.tasks import RepoTask, TaskPrereqs
from gitfourchette.tasks.repotask import AbortTask
from gitfourchette.toolbox import *

if TYPE_CHECKING:
    from gitfourchette.blameview.blamewindow import BlameWindow


class OpenBlame(RepoTask):
    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoUnborn

    def flow(self, path: str, seed: Oid = NULL_OID):
        from gitfourchette.blameview.blamewindow import BlameWindow

        trace = yield from self._buildTrace(path)

        blameModel = BlameModel(self.repoModel, trace, self.parentWidget())
        blameWindow = BlameWindow(blameModel)
        blameWindow.repoWidget = self.rw

        try:
            startNode = trace.nodeForCommit(seed)
        except KeyError:
            startNode = blameModel.currentTraceNode
        yield from self.flowSubtask(AnnotateFile, blameWindow, startNode, False, False)

        windowHeight = int(QApplication.primaryScreen().availableSize().height() * .8)
        windowWidth = blameWindow.textEdit.gutter.calcWidth() + blameWindow.textEdit.fontMetrics().horizontalAdvance("M" * 81) + blameWindow.textEdit.verticalScrollBar().width()
        blameWindow.resize(windowWidth, windowHeight)

        blameWindow.show()
        blameWindow.activateWindow()  # bring to foreground after ProcessDialog

        self.postStatus = _n("{n} revision found.", "{n} revisions found.", n=len(trace))

    def _buildTrace(self, path: str):
        seedPath = path

        trace = Trace()
        upperBound = NULL_OID

        while path:
            node, path = yield from self._expandTrace(trace, path, upperBound)
            if node:
                upperBound = node.commitId

        if len(trace) == 0:
            raise AbortTask(_("File {0} has no history in the repository.", hquoe(seedPath)))

        hasPendingChanges = (
                seedPath in (d.old.path for d in self.repoModel.workdirStagedDeltas)
                or seedPath in (d.new.path for d in self.repoModel.workdirStagedDeltas)
                or seedPath in (d.new.path for d in self.repoModel.workdirUnstagedDeltas))
        if hasPendingChanges:
            firstNode = trace.sequence[0]
            driver = yield from self.flowCallGit(
                "merge-base", "--is-ancestor", str(firstNode.commitId), "HEAD",
                autoFail=False)
            if driver.exitCode() == 0:
                workdirNode = TraceNode(seedPath, UC_FAKEID, parentIds=[firstNode.commitId],
                                        statusChar="M")  # TODO actual status char...
                trace.insert(0, workdirNode)

        return trace

    def _expandTrace(self, trace: Trace, path: str, upperBound: Oid):
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

        node = None
        bottomPath = ""

        for line in scrollback.splitlines():
            hashes = [Oid(hex=h) for h in line.strip().split(" ")]
            commitId = hashes[0]
            parentIds = hashes[1:]
            try:
                node = trace.nodeForCommit(commitId)
                assert not node.parentIds, "existing node already has parents!!!"
                node.parentIds = parentIds
            except KeyError:
                node = TraceNode(path, commitId, parentIds, statusChar="M" if parentIds else "A")
                trace.push(node)

        # Last node has no parents - See if it's a rename
        if node is not None and not node.parentIds:
            driver = yield from self.flowCallGit(
                "-c", "core.abbrev=no",
                "show", "--diff-merges=1", "-z", "--raw", "--format=", str(node.commitId))
            deltas = driver.readShowRawZ()
            delta = next(d for d in deltas if d.new.path == path)
            if delta.status in "RC":
                node.statusChar = delta.status
                bottomPath = delta.old.path

        # TODO: Detect if top commit is deletion (so we don't show an 'M')
        # TODO: If the top commit is a deletion, it may also be a rename
        #       that we should expand upwards!
        return node, bottomPath


class AnnotateFile(RepoTask):
    def flow(self, blameWindow: BlameWindow, node: TraceNode,
             saveFilePositionFirst: bool,
             transposeFilePosition: bool):
        blameModel = blameWindow.model

        # Stop lexing BEFORE changing the document!
        blameWindow.textEdit.highlighter.stopLexJobs()

        previousNode = blameModel.currentTraceNode
        if previousNode.annotatedFile is None:
            saveFilePositionFirst = False
            transposeFilePosition = False

        # Update current locator
        if saveFilePositionFirst:
            blameWindow.saveFilePosition()

        blameModel.currentTraceNode = node

        # Update scrubber
        # Heads up: Look up scrubber row from the sequence of nodes, not via
        # scrubber.findData(commitId, CommitLogModel.Role.Oid), because this
        # compares references to Oid objects, not Oid values.
        scrubberIndex = blameModel.nodeSequence.index(node)
        with QSignalBlockerContext(blameWindow.scrubber):
            blameWindow.scrubber.setCurrentIndex(scrubberIndex)

        # Load the annotated file
        if node.annotatedFile is None:
            yield from self.buildAnnotatedFile(blameModel, node)
            assert node.annotatedFile is not None

        # Figure out which line number (QTextBlock) to scroll to
        topBlock = blameWindow.textEdit.topLeftCornerCursor().blockNumber()
        if transposeFilePosition:  # Attempt to restore position across files
            try:
                oldLine = previousNode.annotatedFile.lines[1 + topBlock]
                topBlock = node.annotatedFile.findLine(oldLine, topBlock) - 1
            except (IndexError,  # Zero lines in annotatedFile ("File deleted in commit" notice)
                    ValueError):  # Could not findLineByReference
                pass  # default to raw line number already stored in topBlock

        # Resolve blob
        # TODO: 2026: Handle fake UC commit!
        if node.commitId == UC_FAKEID or node.statusChar == "D":
            data = None
        else:
            commit = blameModel.repo.peel_commit(node.commitId)
            blob = commit.tree[node.path]
            data = blob.data

        useLexer = False
        if data is None:#node.blobId == NULL_OID:
            text = "*** " + _("File deleted in commit {0}", shortHash(node.commitId)) + " ***"
        elif False and self.model.currentBlame.binary:  # TODO: 2026: Detect binary data
            text = _("Binary blob, {size} bytes, {hash}", size=len(data), hash=node.blobId)
        else:
            text = data.decode('utf-8', errors='replace')
            useLexer = True

        newLocator = blameModel.currentLocator
        newLocator = blameWindow.navHistory.refine(newLocator)
        blameWindow.navHistory.push(newLocator)  # this should update in place

        blameWindow.textEdit.setPlainText(text)
        blameWindow.textEdit.currentLocator = newLocator
        blameWindow.textEdit.restorePosition(newLocator)
        blameWindow.textEdit.syncViewportMarginsWithGutter()

        title = _("Blame {path} @ {commit}", path=tquo(node.path),
                  commit=shortHash(node.commitId) if node.commitId else _("(Uncommitted)"))
        blameWindow.setWindowTitle(title)

        if transposeFilePosition:
            blockPosition = blameWindow.textEdit.document().findBlockByNumber(topBlock).position()
            blameWindow.textEdit.restoreScrollPosition(blockPosition)

        # Install lex job
        useLexer = False # TODO: 2026: -------------
        if useLexer:
            lexJob = BlameWindow._getLexJob(node.path, node.blobId, text)
        else:
            lexJob = None
        if lexJob is not None:
            blameWindow.textEdit.highlighter.installLexJob(lexJob)
            blameWindow.textEdit.highlighter.rehighlight()

        blameWindow.syncNavButtons()

    def buildAnnotatedFile(self, blameModel: BlameModel, node: TraceNode):
        assert node.annotatedFile is None, "node annotation already built"

        driver = yield from self.flowCallGit(
            "blame", "--porcelain", str(node.commitId), "--", node.path)

        stdout = driver.stdoutScrollback()

        annotatedFile = AnnotatedFile(node)
        allLines = []

        for hexHash, originalLineNumber, lineText in parseGitBlame(stdout):
            oid = Oid(hex=hexHash)
            annotatedLine = AnnotatedFile.Line(oid, originalLineNumber)
            annotatedFile.lines.append(annotatedLine)
            allLines.append(lineText)

        annotatedFile.fullText = "".join(allLines)
        node.annotatedFile = annotatedFile
