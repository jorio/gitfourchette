# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.blame import *
from gitfourchette.graph import Graph, GraphWeaver
from gitfourchette.nav import NavContext, NavLocator
from gitfourchette.porcelain import *
from gitfourchette.repomodel import RepoModel, UC_FAKEID
from gitfourchette.qt import *


class BlameModel:
    taskInvoker: QWidget
    repoModel: RepoModel
    trace: Trace
    currentTraceNode: TraceNode
    currentBlame: AnnotatedFile
    nodeSequence: list[TraceNode]
    graph: Graph

    def __init__(self, repoModel: RepoModel, trace: Trace, taskInvoker: QWidget):
        self.taskInvoker = taskInvoker
        self.repoModel = repoModel
        self.trace = trace

        startNode = trace.first  # fall back to newest commit
        self.currentTraceNode = startNode

        # Create graph
        self.nodeSequence = []
        self.graph, graphWeaver = GraphWeaver.newGraph()
        for node in startNode.walkGraph():
            self.nodeSequence.append(node)
            parentIds = [parent.commitId for parent in node.parents]
            graphWeaver.newCommit(node.commitId, parentIds)
            self.graph.commitRows[node.commitId] = graphWeaver.row

        if APP_DEBUG:
            allCommitIds = [node.commitId for node in self.nodeSequence]
            assert len(set(allCommitIds)) == len(allCommitIds), "duplicate commits in sequence"
            self.graph.testConsistency()

        assert len(self.nodeSequence) == trace.numRelevantNodes, \
            f"{len(self.nodeSequence)} nodes in sequence, but traced {trace.numRelevantNodes} relevant nodes"

    @property
    def repo(self) -> Repo:
        return self.repoModel.repo

    @property
    def currentBlame(self) -> AnnotatedFile:
        return self.currentTraceNode.annotatedFile

    @property
    def currentLocator(self) -> NavLocator:
        return BlameModel.locatorFromTraceNode(self.currentTraceNode)

    @staticmethod
    def locatorFromTraceNode(node) -> NavLocator:
        isWorkdir = node.commitId == UC_FAKEID
        return NavLocator(
            context=NavContext.WORKDIR if isWorkdir else NavContext.COMMITTED,
            commit=node.commitId,
            path=node.path)
