# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import dataclasses

from gitfourchette.graph import Graph, GraphWeaver
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import *
from gitfourchette.repomodel import RepoModel, UC_FAKEID
from gitfourchette.qt import *


class BlameModel:
    taskInvoker: QWidget
    repoModel: RepoModel
    trace: Trace
    currentTraceNode: TraceNode
    currentBlame: AnnotatedFile
    graph: Graph

    @property
    def nodeSequence(self):
        return self.trace.sequence

    def __init__(self, repoModel: RepoModel, trace: Trace, taskInvoker: QWidget):
        self.taskInvoker = taskInvoker
        self.repoModel = repoModel
        self.trace = trace

        # Create graph
        self.graph, graphWeaver = GraphWeaver.newGraph()
        for node in trace.sequence:
            graphWeaver.newCommit(node.commitId, node.parentIds)
            self.graph.commitRows[node.commitId] = graphWeaver.row

        self.currentTraceNode = trace.sequence[0]  # fall back to newest commit

        if APP_DEBUG:
            allCommitIds = {node.commitId for node in trace.sequence}
            assert len(allCommitIds) == len(trace.sequence), "duplicate commits in sequence"
            self.graph.testConsistency()

    @property
    def repo(self) -> Repo:
        return self.repoModel.repo

    @property
    def currentBlame(self) -> AnnotatedFile:
        return self.currentTraceNode.annotatedFile

    @property
    def currentLocator(self) -> NavLocator:
        return self.currentTraceNode.toLocator()


@dataclasses.dataclass
class TraceNode:
    path: str
    commitId: Oid
    parentIds: list[Oid] = dataclasses.field(default_factory=list)
    annotatedFile: AnnotatedFile | None = None
    statusChar: str = "M"

    @property
    def status(self) -> DeltaStatus:
        return {
            "M": DeltaStatus.MODIFIED,
            "A": DeltaStatus.ADDED,
            "U": DeltaStatus.UNTRACKED,
            "D": DeltaStatus.DELETED,
            "R": DeltaStatus.RENAMED,
            "C": DeltaStatus.COPIED,
            "T": DeltaStatus.TYPECHANGE,
        }.get(self.statusChar, DeltaStatus.UNREADABLE)

    def toLocator(self) -> NavLocator:
        if self.commitId == UC_FAKEID:
            return NavLocator.inWorkdir(self.path)
        else:
            return NavLocator.inCommit(self.commitId, self.path)


class Trace:
    sequence: list[TraceNode]
    byCommit: dict[Oid, TraceNode]

    def __init__(self):
        self.sequence = []
        self.byCommit = {}

    def insert(self, index: int, node: TraceNode):
        self.sequence.insert(index, node)
        self.byCommit[node.commitId] = node

    def push(self, node: TraceNode):
        self.sequence.append(node)
        self.byCommit[node.commitId] = node

    def __len__(self):
        return len(self.sequence)

    def nodeForCommit(self, oid: Oid):
        return self.byCommit[oid]

    def revisionNumber(self, oid: Oid) -> int:
        node = self.byCommit[oid]
        index = self.sequence.index(node)
        return len(self.sequence) - index


class AnnotatedFile:
    @dataclasses.dataclass(frozen=True)
    class Line:
        commitId: Oid
        originalLineNumber: int

    binary: bool
    lines: list[Line]

    def __init__(self, node: TraceNode):
        sentinel = AnnotatedFile.Line(node.commitId, 0)
        self.lines = [sentinel]
        self.binary = False

    @property
    def commitId(self):
        # Get commit ID from sentinel line
        return self.lines[0].commitId

    def findLine(self, target: Line, start: int, searchRange: int = 250) -> int:
        lines = self.lines
        count = len(lines)
        start = min(start, count - 1)
        searchRange = min(searchRange, count)

        lo = start
        hi = start + 1

        for _i in range(searchRange):
            if lo >= 0 and lines[lo] == target:
                return lo
            if hi < count and lines[hi] == target:
                return hi
            lo -= 1
            hi += 1

        raise ValueError("annotated line not found within given range")
