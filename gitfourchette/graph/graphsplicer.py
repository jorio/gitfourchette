# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
from collections.abc import Iterable
from itertools import zip_longest

from gitfourchette.graph.graph import (
    ArcJunction,
    BATCHROW_UNDEF,
    BatchRow,
    Frame,
    Graph,
    KF_INTERVAL,
    Oid,
)
from gitfourchette.graph.graphweaver import GraphWeaver
from gitfourchette.toolbox import Benchmark

logger = logging.getLogger(__name__)


class GraphSplicer:
    def __init__(self, oldGraph: Graph, oldHeads: Iterable[Oid], newHeads: Iterable[Oid]):
        self.done = False
        self.foundEquilibrium = False
        self.equilibriumNewRow = -1
        self.equilibriumOldRow = -1
        self.oldGraphRowOffset = 0

        self.newGraph, self.weaver = GraphWeaver.newGraph()

        self.oldGraph = oldGraph
        self.oldPlayer = oldGraph.startPlayback()

        # Commits that we must see before finding the equilibrium.
        newHeads = set(newHeads)
        oldHeads = set(oldHeads)
        self.newHeads = newHeads
        self.requiredNewCommits = (newHeads - oldHeads)  # heads that appeared
        self.requiredOldCommits = (oldHeads - newHeads)  # heads that disappeared

    def spliceNewCommit(self, newCommit: Oid, parentsOfNewCommit: list[Oid], keyframeInterval=KF_INTERVAL):
        assert not self.done

        # Generate arcs for new frame.
        self.weaver.newCommit(newCommit, parentsOfNewCommit)

        # Save keyframe in new context every now and then.
        if int(self.weaver.row) % keyframeInterval == 0:
            self.newGraph.saveKeyframe(self.weaver)

        # Register this commit in the new graph's row sequence.
        self.newGraph.commitRows[newCommit] = self.weaver.row

        # Is it one of the commits that we must see before we can stop consuming new commits?
        if newCommit in self.requiredNewCommits:
            self.requiredNewCommits.remove(newCommit)

        # If the commit wasn't known in the old graph, don't advance the old graph.
        newCommitWasKnown = newCommit in self.oldGraph.commitRows
        if not newCommitWasKnown:
            return

        # The old graph's playback may be positioned past this commit already,
        # e.g. if branches were reordered. In that case, don't advance the old graph.
        if newCommit in self.oldPlayer.seenCommits:
            return

        # We know the new commit is ahead in the old graph.
        # Advance playback of the old graph to the new commit.
        try:
            while self.oldPlayer.commit != newCommit:
                self.oldPlayer.advanceToNextRow()  # May raise StopIteration

                oldCommit = self.oldPlayer.commit
                self.requiredOldCommits.discard(oldCommit)

                # Topological sort may reorder branches. If we've skipped a
                # head that still exists, we've got to see it in the new graph.
                if oldCommit in self.newHeads and oldCommit not in self.newGraph.commitRows:
                    self.requiredNewCommits.add(oldCommit)
                # Otherwise, the old commit is now unreachable. We'll purge it afterward.

            self.requiredOldCommits.discard(newCommit)

        except StopIteration:
            # Old graph depleted.
            self.onGraphDepleted()
            return

        # See if we're done: no more commits we want to see,
        # and the graph frames start being "equal" in both graphs.
        if (not self.requiredNewCommits and
                not self.requiredOldCommits and
                self.isEquilibriumReached(self.weaver, self.oldPlayer)):
            self.onEquilibriumFound()
            return

    def onEquilibriumFound(self):
        """Completion with equilibrium"""

        self.done = True
        self.foundEquilibrium = True

        # We'll basically concatenate newContext[eqNewRow:] and oldContext[:eqOldRow].
        equilibriumNewRow = int(self.weaver.row)
        equilibriumOldRow = int(self.oldPlayer.row)
        rowShiftInOldGraph = equilibriumNewRow - equilibriumOldRow

        # Save rows for use by external code
        self.equilibriumNewRow = equilibriumNewRow
        self.equilibriumOldRow = equilibriumOldRow
        self.oldGraphRowOffset = rowShiftInOldGraph

        logger.debug(f"Equilibrium: commit={str(self.oldPlayer.commit):.7} new={equilibriumNewRow} old={equilibriumOldRow}")

        # We can bail now if nothing changed.
        if equilibriumOldRow == 0 and equilibriumNewRow == 0:
            return

        # After reaching equilibrium there might still be open arcs that aren't closed yet.
        # Let's find out where they end before we can concatenate the graphs.
        equilibriumNewOpenArcs = list(filter(None, self.weaver.openArcs))
        equilibriumOldOpenArcs = list(filter(None, self.oldPlayer.sealCopy().openArcs))
        assert len(equilibriumOldOpenArcs) == len(equilibriumNewOpenArcs)

        # Fix up dangling open arcs in new graph
        for oldOpenArc, newOpenArc in zip(equilibriumOldOpenArcs, equilibriumNewOpenArcs, strict=True):
            # Find out where the arc is resolved
            assert newOpenArc.openedBy == oldOpenArc.openedBy
            assert newOpenArc.closedBy == oldOpenArc.closedBy
            assert newOpenArc.closedAt == BATCHROW_UNDEF  # new graph's been interrupted before resolving this arc
            newOpenArc.closedAt = oldOpenArc.closedAt

            # Remap chain - the ChainHandle object is shared with all arcs on this chain
            newCH = newOpenArc.chain
            oldCH = oldOpenArc.chain
            assert newCH.topRow.isValid()
            assert oldCH.topRow.isValid()
            newCH.bottomRow = oldCH.bottomRow   # rewire bottom row BEFORE setting alias
            oldCH.setAliasOf(newCH)

            # Splice old junctions into new junctions
            if oldOpenArc.junctions:
                junctions: list[ArcJunction] = []
                junctions.extend(j for j in newOpenArc.junctions if j.joinedAt <= equilibriumNewRow)  # before eq
                junctions.extend(j for j in oldOpenArc.junctions if j.joinedAt > equilibriumOldRow)  # after eq
                assert all(junctions.count(x) == 1 for x in junctions), "duplicate junctions after splicing"
                newOpenArc.junctions = junctions

        # Do the actual splicing.

        # If we're adding a commit at the top of the graph, the closed arcs of the first keyframe will be incorrect,
        # so we must make sure to nuke the keyframe for equilibriumOldRow if it exists.
        with Benchmark("Delete lost keyframes"):
            self.oldGraph.deleteKeyframesDependingOnRowsAbove(equilibriumOldRow + 1)

        with Benchmark("Delete lost arcs"):
            self.oldGraph.deleteArcsDependingOnRowsAbove(equilibriumOldRow)

        with Benchmark("Delete lost rows"):
            for lostCommit in (self.oldPlayer.seenCommits - self.newGraph.commitRows.keys()):
                del self.oldGraph.commitRows[lostCommit]

        with Benchmark(F"Shift {len(self.oldGraph.ownBatches)} old batches by {rowShiftInOldGraph} rows"):
            BatchRow.BatchManager.shiftBatches(rowShiftInOldGraph, self.oldGraph.ownBatches)

        with Benchmark("Insert Front"):
            self.oldGraph.insertFront(self.newGraph, equilibriumNewRow)

        with Benchmark("Update row cache"):
            self.oldGraph.commitRows.update(self.newGraph.commitRows)
            self.oldGraph.ownBatches.extend(self.newGraph.ownBatches)  # Steal newGraph's batches
            self.newGraph.ownBatches = []  # Don't let newGraph nuke the batches in its __del__

        # Invalidate volatile player, which may be referring to dead keyframes
        self.oldGraph.volatilePlayer = None

    def onGraphDepleted(self):
        """Completion without equilibrium: no more commits in oldGraph"""

        self.done = True

        # If we exited the loop without reaching equilibrium, the whole graph has changed.
        # In that case, steal the contents of newGraph, and bail.

        self.equilibriumOldRow = int(self.oldPlayer.row)
        self.equilibriumNewRow = int(self.weaver.row)
        self.oldGraphRowOffset = 0

        self.oldGraph.shallowCopyFrom(self.newGraph)

    @staticmethod
    def isEquilibriumReached(frameA: Frame, frameB: Frame):
        rowA = int(frameA.row)
        rowB = int(frameB.row)

        for arcA, arcB in zip_longest(frameA.openArcs, frameB.openArcs):
            isStaleA = (not arcA) or arcA.isStale(rowA)
            isStaleB = (not arcB) or arcB.isStale(rowB)

            if isStaleA != isStaleB:
                return False

            if isStaleA:
                assert isStaleB
                continue

            assert arcA.lane == arcB.lane

            if not (arcA.openedBy == arcB.openedBy and arcA.closedBy == arcB.closedBy):
                return False

        # Do NOT test solved arcs!
        return True
