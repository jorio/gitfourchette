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
    revList: RevList
    graph: Graph
    currentRevision: Revision
    revsFile: QTemporaryFile

    def __init__(self, repoModel: RepoModel, revList: RevList):
        self.repoModel = repoModel
        self.revList = revList

        # Create graph
        self.graph, graphWeaver = GraphWeaver.newGraph()
        for revision in revList.sequence:
            graphWeaver.newCommit(revision.commitId, revision.parentIds)
            self.graph.commitRows[revision.commitId] = graphWeaver.row

        # Fall back to newest revision
        self.currentRevision = revList.sequence[0]

        if APP_DEBUG:
            allCommitIds = {revision.commitId for revision in revList.sequence}
            assert len(allCommitIds) == len(revList.sequence), "duplicate commits in sequence"
            self.graph.testConsistency()

        # Dump revs file to speed up calls to 'git blame'
        # (and to make sure it won't return commits outside the trace)
        revsFileTemplate = os.path.join(qTempDir(), "blamerevs-XXXXXX.txt")
        self.revsFile = QTemporaryFile(revsFileTemplate, None)
        self.revsFile.open()
        self.revsFile.write(revList.serializeRevisionList().encode("utf-8"))
        self.revsFile.close()

    @property
    def repo(self) -> Repo:
        return self.repoModel.repo


@dataclasses.dataclass
class Revision:
    @dataclasses.dataclass(frozen=True)
    class BlameLine:
        commitId: Oid
        originalLineNumber: int

    path: str
    commitId: Oid
    parentIds: list[Oid] = dataclasses.field(default_factory=list)
    status: str = "M"
    blameLines: list[BlameLine] = dataclasses.field(default_factory=list)
    fullText: str | None = None
    binary: bool = False

    def toLocator(self) -> NavLocator:
        if self.commitId == UC_FAKEID:
            return NavLocator.inWorkdir(self.path)
        else:
            return NavLocator.inCommit(self.commitId, self.path)

    def isAnnotated(self) -> bool:
        return bool(self.blameLines)

    def findLine(self, target: BlameLine, start: int, searchRange: int = 250) -> int:
        assert self.isAnnotated()

        lines = self.blameLines
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


class RevList:
    sequence: list[Revision]
    byCommit: dict[Oid, Revision]
    nonTipCommits: set[Oid]

    def __init__(self):
        self.sequence = []
        self.byCommit = {}
        self.nonTipCommits = set()

    def insert(self, index: int, revision: Revision):
        self.sequence.insert(index, revision)
        self.byCommit[revision.commitId] = revision

    def push(self, revision: Revision):
        self.sequence.append(revision)
        self.byCommit[revision.commitId] = revision

    def __len__(self):
        return len(self.sequence)

    def revisionForCommit(self, oid: Oid):
        return self.byCommit[oid]

    def revisionNumber(self, oid: Oid) -> int:
        revision = self.byCommit[oid]
        index = self.sequence.index(revision)
        return len(self.sequence) - index

    def serializeRevisionList(self) -> str:
        """ Serialize the file's commit history (including parent rewriting)
        in a format suitable for "git blame -S <revs-file>". """
        lines = []
        for revision in self.sequence:
            parents = ' '.join(str(p) for p in revision.parentIds)
            lines.append(f"{revision.commitId} {parents}")
        return "\n".join(lines)
