# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import bisect
import collections
from collections.abc import Sequence

from gitfourchette.graph.graph import Graph, Frame, Oid, Arc, ChainHandle, BatchRow, BATCHROW_UNDEF, ArcJunction


class GraphWeaver(Frame):
    freeLanes: list[int]
    parentLookup: collections.defaultdict[Oid, list[Arc]]  # list: all lanes
    peakArcCount: int
    batchNo: int

    @staticmethod
    def newGraph() -> tuple[Graph, GraphWeaver]:
        graph = Graph()
        assert graph.isEmpty(), "cannot regenerate an existing graph!"
        weaver = GraphWeaver(graph.startArc)
        graph.ownBatches.append(weaver.batchNo)
        return graph, weaver

    def __init__(self, startArcSentinel: Arc):
        super().__init__(row=BATCHROW_UNDEF, commit=None,
                         solvedArcs=[], openArcs=[], lastArc=startArcSentinel)
        self.freeLanes = []
        self.parentLookup = collections.defaultdict(list)
        self.peakArcCount = 0
        self.batchNo = BatchRow.BatchManager.reserveNewBatch()

    def newCommit(self, me: Oid, myParents: Sequence[Oid]):
        """Create arcs for a new commit row."""

        row = BatchRow(b=self.batchNo, y=self.row.y + 1)
        self.row = row
        self.commit = me

        hasParents = len(myParents) > 0

        # Resolve arcs that my child commits have opened higher up in the graph,
        # waiting for me to appear in the commit sequence so I can close them.
        myOpenArcs = self.parentLookup.get(me)
        myHomeLane = -1
        handOffHomeLane = False
        if not myOpenArcs:
            # Nobody was looking for me, so I'm the tip of a new branch
            myHomeChain = ChainHandle(row, BATCHROW_UNDEF)
        else:
            myMainOpenArc = min(myOpenArcs, key=lambda a: a.lane)
            myHomeLane = myMainOpenArc.lane
            myHomeChain = myMainOpenArc.chain
            assert myHomeChain.isValid()
            for arc in myOpenArcs:
                # Close off open arcs
                assert arc.closedBy == me
                assert arc.closedAt == BATCHROW_UNDEF
                assert arc.chain.bottomRow == BATCHROW_UNDEF
                arc.closedAt = row
                self.solvedArcs[arc.lane] = arc
                self.openArcs[arc.lane] = None  # Free up the lane below
                if hasParents and arc.lane == myHomeLane:
                    handOffHomeLane = True
                else:
                    bisect.insort(self.freeLanes, arc.lane)
                    # Close off chain
                    arc.chain.bottomRow = row
            del self.parentLookup[me]

            """
            # Compact null arcs at right of graph
            if not allocLanesInGaps:
                for _ in range(len(self.openArcs)-1, myHomeLane, -1):
                    if self.openArcs[-1] is not None:
                        break
                    self.openArcs.pop()
                    self.solvedArcs.pop()
            """

        sawFirstParent = False
        for parent in myParents:
            # See if there's already an arc that is looking for any of my parents BEYOND PARENT ZERO.
            # If so, make a junction on that arc.
            if sawFirstParent:
                arcsOfParent = self.parentLookup.get(parent)
                if arcsOfParent:
                    arc = min(arcsOfParent, key=lambda a: a.lane)
                    assert arc.closedBy == parent
                    assert arc.closedAt == BATCHROW_UNDEF
                    arc.junctions.append(ArcJunction(joinedAt=row, joinedBy=me))
                    continue

            # We didn't make a junction, so open up a new arc on a free lane.
            # Get a free lane.
            if not sawFirstParent and myHomeLane >= 0:
                assert handOffHomeLane
                freeLane = myHomeLane
                handOffHomeLane = False
            elif not self.freeLanes:
                # Allocate new lane on the right
                freeLane = len(self.openArcs)
                self.openArcs.append(None)  # Reserve the lane
                self.solvedArcs.append(None)  # Reserve the lane
            else:
                # Pick leftmost free lane
                freeLane = self.freeLanes.pop(0)

            if not sawFirstParent:
                # Hand off my chain
                parentChain = myHomeChain
            else:
                # Branch out new chain downward
                parentChain = ChainHandle(row, BATCHROW_UNDEF)
            assert parentChain.bottomRow == BATCHROW_UNDEF

            # Make arc from this commit to its parent
            newArc = Arc(lane=freeLane, chain=parentChain,
                         openedAt=row, closedAt=BATCHROW_UNDEF,
                         openedBy=me, closedBy=parent, junctions=[])
            self.openArcs[freeLane] = newArc
            self.parentLookup[parent].append(newArc)
            self.lastArc.nextArc = newArc
            self.lastArc = newArc

            sawFirstParent = True

        # Parentless commit: we'll insert a bogus arc so playback doesn't need the commit sequence.
        # This is just to keep the big linked list of arcs flowing.
        # Do NOT put it in solved or open arcs! This would interfere with detection of arcs that the commit
        # actually closes or opens.
        if not sawFirstParent:
            if myHomeLane < 0:
                # Edge case: the commit is BOTH childless AND parentless.
                # Put the commit in a free lane, but do NOT reserve the lane.
                if not self.freeLanes:
                    myHomeLane = len(self.openArcs)
                else:
                    myHomeLane = self.freeLanes[0]  # PEEK only! do not pop!

                # Close off home chain
                myHomeChain.bottomRow = row

            assert myHomeChain.bottomRow.isValid(), "parentless commit's home chain shouldn't be dangling at bottom"

            newArc = Arc(lane=myHomeLane, chain=myHomeChain,
                         openedAt=row, closedAt=row,
                         openedBy=me, closedBy=me, junctions=[])
            self.lastArc.nextArc = newArc
            self.lastArc = newArc
            assert newArc.isParentlessCommitBogusArc()

        assert not handOffHomeLane
        assert myHomeChain.topRow.isValid()
        assert len(self.openArcs) == len(self.solvedArcs)

        # Keep track of peak arc count for statistics
        self.peakArcCount = max(self.peakArcCount, len(self.openArcs))

    def isDangling(self):
        return len(self.parentLookup) > 0
