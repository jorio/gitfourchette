# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.blameview.blamemodel import BlameModel, Trace, TraceNode
from gitfourchette.gitdriver import argsIf
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID
from gitfourchette.tasks import RepoTask, TaskPrereqs
from gitfourchette.tasks.repotask import AbortTask
from gitfourchette.toolbox import *


class OpenBlame(RepoTask):
    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoUnborn

    def flow(self, path: str, seed: Oid = NULL_OID):
        from gitfourchette.blameview.blamewindow import BlameWindow

        trace = yield from self._buildTrace(path)

        blameModel = BlameModel(self.repoModel, trace, self.parentWidget())
        blameWindow = BlameWindow(blameModel)

        try:
            startNode = trace.nodeForCommit(seed)
        except KeyError:
            startNode = blameModel.currentTraceNode
        blameWindow.setTraceNode(startNode)

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
