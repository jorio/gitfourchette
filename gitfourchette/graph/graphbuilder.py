# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import functools
import logging
from collections.abc import Sequence, Iterable, Callable, Set

from gitfourchette.graph.graph import Graph, BatchRow, KF_INTERVAL, Oid
from gitfourchette.graph.graphsplicer import GraphSplicer
from gitfourchette.graph.graphtrickle import GraphTrickle
from gitfourchette.graph.graphweaver import GraphWeaver
from gitfourchette.porcelain import Commit as _RealCommitType
from gitfourchette.toolbox import Benchmark

logger = logging.getLogger(__name__)


def _ensureSet(x) -> set:
    if x is None:
        return set()
    assert type(x) is not dict
    if type(x) is not set:
        return set(x)
    assert type(x) is set
    return x


@dataclasses.dataclass
class MockCommit:
    id: Oid
    parent_ids: Sequence[Oid]


# pygit2.Oid can't be subclassed.
@functools.total_ordering  # saves me from implementing le,ne,gt,ge
class MockOid:
    @classmethod
    def encode(cls, fakeOid: str) -> Oid:
        assert isinstance(fakeOid, str)
        return cls(fakeOid)

    @classmethod
    def encodeAll(cls, *fakeOids) -> list[Oid]:
        if not isinstance(fakeOids[0], str):
            assert len(fakeOids) == 1
            assert not isinstance(fakeOids[0], str)
            fakeOidList = fakeOids[0]
        else:
            fakeOidList = fakeOids
        return [cls.encode(o) for o in fakeOidList]

    def __init__(self, fakeOid: str):
        self.oid = Oid(raw=fakeOid.encode())

    @property
    def __class__(self):
        return Oid

    @property
    def raw(self):
        return self.oid.raw

    def __str__(self):
        return self.oid.raw.rstrip(b'\0').decode()

    def __repr__(self):
        return self.__str__()

    def __hash__(self):
        return hash(self.oid)

    def __lt__(self, other):
        if isinstance(other, str):
            return str(self) < other
        if isinstance(other, MockOid):
            other = other.oid
        return self.oid.__lt__(other)

    def __eq__(self, other):
        if isinstance(other, str):
            return str(self) == other
        if isinstance(other, MockOid):
            other = other.oid
        return self.oid.__eq__(other)


class GraphBuildLoop:
    onKeyframe: Callable[[int], None]

    def __init__(
            self,
            heads=None,
            hideSeeds=None,
            localSeeds=None,
            forceHide=None,
            keyframeInterval=KF_INTERVAL
    ):
        heads = _ensureSet(heads)
        hideSeeds = _ensureSet(hideSeeds)
        # If localSeeds was omitted, all heads are local by default
        localSeeds = _ensureSet(heads if localSeeds is None else localSeeds)

        self.graph, self.weaver = GraphWeaver.newGraph()
        self.hiddenTrickle = GraphTrickle.newHiddenTrickle(heads, hideSeeds, forceHide)
        self.foreignTrickle = GraphTrickle.newForeignTrickle(heads, localSeeds)
        self.keyframeInterval = keyframeInterval

        self.onKeyframe = GraphBuildLoop.defaultOnKeyframe

    def sendAll(self, sequence):
        gen = self.coBuild()
        gen.send(None)  # prime it
        for c in sequence:
            gen.send(c)
        gen.close()
        return self

    @staticmethod
    def defaultOnKeyframe(i: int):
        pass

    def coBuild(self):
        graph = self.graph
        weaver = self.weaver
        hiddenTrickle = self.hiddenTrickle
        foreignTrickle = self.foreignTrickle
        keyframeInterval = self.keyframeInterval

        while True:
            try:
                commit = yield
            except GeneratorExit:
                break

            oid = commit.id
            parents = commit.parent_ids

            weaver.newCommit(oid, parents)
            hiddenTrickle.newCommit(oid, parents)
            foreignTrickle.newCommit(oid, parents)

            row = weaver.row
            rowInt = int(row)
            assert type(row) is BatchRow
            assert rowInt >= 0
            graph.commitRows[oid] = row

            # Save keyframes at regular intervals for faster random access.
            if rowInt % keyframeInterval == 0:
                graph.saveKeyframe(weaver)
                self.onKeyframe(rowInt)

        logger.debug(f"Peak arc count: {weaver.peakArcCount}")

    @property
    def hiddenCommits(self):
        return self.hiddenTrickle.flaggedSet

    @property
    def foreignCommits(self):
        return self.foreignTrickle.flaggedSet


class GraphSpliceLoop:
    def __init__(
            self,
            graph: Graph,
            oldCommitSequence: list[_RealCommitType | MockCommit],
            oldHeads: Iterable[Oid],
            newHeads: Iterable[Oid],
            hideSeeds: Set[Oid] | None = None,
            localSeeds: Set[Oid] | None = None,
            keyframeInterval=KF_INTERVAL,
    ):
        oldHeads = _ensureSet(oldHeads)
        newHeads = _ensureSet(newHeads)
        hideSeeds = _ensureSet(hideSeeds)
        # If localSeeds was omitted, all heads are local by default
        localSeeds = _ensureSet(newHeads if localSeeds is None else localSeeds)

        self.graph = graph
        self.oldCommitSequence = oldCommitSequence
        self.commitSequence: list[_RealCommitType | MockCommit] = []  # unknown yet
        self.oldHeads = oldHeads
        self.newHeads = newHeads
        self.hideSeeds = hideSeeds
        self.localSeeds = localSeeds
        self.keyframeInterval = keyframeInterval

        self.splicer = GraphSplicer(self.graph, self.oldHeads, self.newHeads)
        self.hiddenTrickle = GraphTrickle.newHiddenTrickle(self.newHeads, self.hideSeeds)
        self.foreignTrickle = GraphTrickle.newForeignTrickle(self.newHeads, self.localSeeds)

        self.numRowsRemoved = 0
        self.numRowsAdded = 0

    def sendAll(self, sequence):
        gen = self.coSplice()
        gen.send(None)  # prime it
        for c in sequence:
            try:
                gen.send(c)
            except StopIteration:
                break
        gen.close()
        return self

    def coSplice(self):
        newCommitSequence = []
        splicer = self.splicer
        hiddenTrickle = self.hiddenTrickle
        foreignTrickle = self.foreignTrickle

        while not splicer.done:
            try:
                commit = yield
            except GeneratorExit:
                splicer.onGraphDepleted()
                break
            oid = commit.id
            parents = commit.parent_ids

            newCommitSequence.append(commit)
            splicer.spliceNewCommit(oid, parents, self.keyframeInterval)
            hiddenTrickle.newCommit(oid, parents)
            foreignTrickle.newCommit(oid, parents)

        if splicer.foundEquilibrium:
            nRemoved = splicer.equilibriumOldRow
            nAdded = splicer.equilibriumNewRow
        else:
            nRemoved = -1  # We could use len(self.commitSequence), but -1 will force refreshRepo to replace the model wholesale
            nAdded = len(newCommitSequence)

        # Piece correct commit sequence back together
        with Benchmark("Reassemble commit sequence"):
            if not splicer.foundEquilibrium:
                pass  # keep newCommitSequence
            elif nAdded == 0 and nRemoved == 0:
                newCommitSequence = self.oldCommitSequence
            elif nRemoved == 0:
                newCommitSequence = newCommitSequence[:nAdded] + self.oldCommitSequence
            else:
                newCommitSequence = newCommitSequence[:nAdded] + self.oldCommitSequence[nRemoved:]

        # Finish patching hidden/foreign commit sets.
        # Keep feeding commits to trickle until it stabilizes.
        if splicer.foundEquilibrium:
            with Benchmark("Stabilize trickles"):
                row = nAdded + 1
                r1 = self._stabilizeTrickle(hiddenTrickle, row, newCommitSequence)
                r2 = self._stabilizeTrickle(foreignTrickle, row, newCommitSequence)
            logger.debug(f"Trickle stabilization: Hidden={r1}; Foreign={r2}")

        self.numRowsRemoved = nRemoved
        self.numRowsAdded = nAdded
        self.commitSequence = newCommitSequence

    @staticmethod
    def _stabilizeTrickle(trickle: GraphTrickle, startRow: int, newCommitSequence: list[MockCommit]):
        if trickle.done:
            return startRow

        for row in range(startRow, len(newCommitSequence)):
            commit = newCommitSequence[row]
            trickle.newCommit(commit.id, commit.parent_ids)

            # See if finished (not too often - expensive)
            if ((row & 0xFF) == 0) and trickle.done:
                return row

    @property
    def hiddenCommits(self):
        return self.hiddenTrickle.flaggedSet

    @property
    def foreignCommits(self):
        return self.foreignTrickle.flaggedSet
