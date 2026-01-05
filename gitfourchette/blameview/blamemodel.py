# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import dataclasses
import os

from gitfourchette.graph import Graph, GraphWeaver
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import *
from gitfourchette.repomodel import RepoModel, UC_FAKEID
from gitfourchette.qt import *


class BlameModel:
    repoModel: RepoModel
    trace: Trace
    currentBlame: AnnotatedFile
    graph: Graph

    @property
    def nodeSequence(self):
        return self.trace.sequence

    def __init__(self, repoModel: RepoModel, trace: Trace):
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

        # Dump revs file to speed up calls to 'git blame'
        # (and to make sure it won't return commits outside the trace)
        revsFileTemplate = os.path.join(qTempDir(), "blamerevs-XXXXXX.txt")
        self.revsFile = QTemporaryFile(revsFileTemplate, None)
        self.revsFile.open()
        self.revsFile.write(trace.serializeRevisionList().encode("utf-8"))
        self.revsFile.close()

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
    status: str = "M"

    def toLocator(self) -> NavLocator:
        if self.commitId == UC_FAKEID:
            return NavLocator.inWorkdir(self.path)
        else:
            return NavLocator.inCommit(self.commitId, self.path)


class Trace:
    sequence: list[TraceNode]
    byCommit: dict[Oid, TraceNode]
    nonTipCommits: set[Oid]

    def __init__(self):
        self.sequence = []
        self.byCommit = {}
        self.nonTipCommits = set()

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

    def serializeRevisionList(self) -> str:
        """ Serialize the file's commit history (including parent rewriting)
        in a format suitable for "git blame -S <revs-file>". """
        lines = []
        for node in self.sequence:
            lines.append(f"{node.commitId} {' '.join(str(p) for p in node.parentIds)}")
        return "\n".join(lines)


class AnnotatedFile:
    @dataclasses.dataclass(frozen=True)
    class Line:
        commitId: Oid
        originalLineNumber: int

    binary: bool
    lines: list[Line]
    fullText: str | None

    def __init__(self, node: TraceNode):
        sentinel = AnnotatedFile.Line(node.commitId, 0)
        self.lines = [sentinel]
        self.binary = False
        self.fullText = None

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
