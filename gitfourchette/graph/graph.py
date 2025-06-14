# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass
from collections.abc import Iterable, Iterator, Set
from typing import ClassVar

from gitfourchette.appconsts import *
from gitfourchette.porcelain import Oid

logger = logging.getLogger(__name__)

KF_INTERVAL = 5000
"""
Interval (in number of commits) at which keyframes are saved while preparing
the graph.

The bigger the interval...:
- faster initial loading of the repo & less memory usage;
- but slower random access to any point of the graph.
"""

DEAD_VALUE = Oid(hex="deaddeaddeaddeaddeaddeaddeaddeaddeaddead")


@dataclass(frozen=True)
class BatchRow:
    """
    For a row in the Graph, BatchRow keeps track of the row's batch number
    and position within the batch.

    When a repo is refreshed, new commits may appear at the top of the graph.
    This may push existing rows down, away from the top of the graph.

    Recomputing row numbers for the entire graph becomes costly if it contains
    tens of thousands of commits.

    Instead, we keep track of batches of rows inserted into the graph at each
    refresh. We adjust a single offset value for each batch.
    """

    b: int = -1
    "Batch number (look up its global offset in BatchManager)"

    y: int = -1
    "Position of this row relative to its batch"

    class BatchManager:
        """
        Manages row batch offsets.

        A single BatchManager is shared by all repositories opened throughout
        the lifespan of the app.
        """

        globalOffsets: ClassVar[list[int]] = []
        freeBatchNos: ClassVar[list[int]] = []

        @classmethod
        def reserveNewBatch(cls):
            if cls.freeBatchNos:
                batchNo = cls.freeBatchNos.pop()
                cls.globalOffsets[batchNo] = 0
            else:
                cls.globalOffsets.append(0)
                batchNo = len(cls.globalOffsets) - 1

            return batchNo

        @classmethod
        def freeBatch(cls, batchNo: int):
            cls.globalOffsets[batchNo] = -0xDEADBEEF
            cls.freeBatchNos.append(batchNo)

            # Compact freed batches at end of list
            for bn in range(len(cls.globalOffsets) - 1, -1, -1):
                assert bn == len(cls.globalOffsets) - 1
                if bn in cls.freeBatchNos:
                    cls.freeBatchNos.remove(bn)
                    cls.globalOffsets.pop()
                else:
                    # Stop iterating once the last batch is non-free
                    break

        @classmethod
        def shiftBatches(cls, shift: int, batchNos: Iterable[int]):
            for b in batchNos:
                assert b not in cls.freeBatchNos, "trying to shift a freed batch"
                cls.globalOffsets[b] += shift

    def isValid(self):
        """
        A BatchRow is considered valid if it is part of a valid batch, it has a
        positive offset in the batch, and it resolves to a positive int.
        """
        return self.b >= 0 and self.y >= 0 and int(self) >= 0

    def __repr__(self):
        offset = -1 if self.b < 0 else BatchRow.BatchManager.globalOffsets[self.b]
        return f"{int(self)} (b{self.b}r{self.y}+{offset})"

    def __str__(self):
        return str(int(self))

    def __int__(self) -> int:
        """Any BatchRow is convertible to int, giving a global row index.
        Note that the int value of any given BatchRow may change over time
        as the graph gets spliced."""
        if self.b < 0:
            return -1
        return BatchRow.BatchManager.globalOffsets[self.b] + self.y

    # -------------------------------------------------------------------------
    # Arithmetics

    def __add__(self, other: BatchRow | int) -> int:
        return int(self) + int(other)

    def __sub__(self, other: BatchRow | int) -> int:
        return int(self) - int(other)

    def __mod__(self, other: BatchRow | int) -> int:
        return int(self) % int(other)

    def __rmod__(self, other: BatchRow | int) -> int:
        return int(other) % int(self)

    # -------------------------------------------------------------------------
    # Comparisons
    # (BatchRows must be comparable so we can use bisect.)

    def __le__(self, other: BatchRow | int) -> bool:
        return int(self) <= int(other)

    def __lt__(self, other: BatchRow | int) -> bool:
        return int(self) < int(other)

    def __ge__(self, other: BatchRow | int) -> bool:
        return int(self) >= int(other)

    def __gt__(self, other: BatchRow | int) -> bool:
        return int(self) > int(other)

    def __eq__(self, other: BatchRow | int) -> bool:
        return int(self) == int(other)


BATCHROW_UNDEF = BatchRow(-1, -1)
"Use this special BatchRow as a placeholder for a row position that is yet to be determined."


@dataclass
class ChainHandle:
    """ Object shared by arcs on the same chain. """
    _t: BatchRow = BATCHROW_UNDEF
    _b: BatchRow = BATCHROW_UNDEF
    alias: ChainHandle | None = None

    def isValid(self):
        # It's OK for bottomRow to be dangling, but not topRow.
        return self.topRow.isValid()

    def __repr__(self):
        tr = int(self.topRow)
        br = int(self.bottomRow)
        return f"Chain({tr}\u2192{br})"

    def resolve(self):
        """ Return non-aliased ChainHandle """

        if self.alias is None:
            return self

        if self.alias.alias is not None:
            # Flatten aliases
            frontier = [self, self.alias]
            root = frontier[-1]
            while True:
                root = root.alias
                if root.alias is None:
                    break
                frontier.append(root)
            for ch in frontier:
                ch.alias = root
            if APP_DEBUG:
                assert root.alias is None
                assert root not in frontier
                assert root is self.alias

        return self.alias

    @property
    def topRow(self) -> BatchRow:
        return self.resolve()._t

    @property
    def bottomRow(self) -> BatchRow:
        return self.resolve()._b

    @bottomRow.setter
    def bottomRow(self, value):
        self._b = value
        assert self.alias is None, "Cannot modify row in aliased ChainHandle"

    def setAliasOf(self, master: ChainHandle):
        if self.alias is not None:
            self.alias.setAliasOf(master)

        self.alias = master
        self._t = BATCHROW_UNDEF
        self._b = BATCHROW_UNDEF


@dataclass
class ArcJunction:
    """ Represents the merging of an Arc into another Arc. """

    joinedAt: BatchRow
    "Row number in which this junction occurs"

    joinedBy: Oid
    "Hash of the joining arc's opening commit"

    def __lt__(self, other: ArcJunction):
        """
        Calling sorted() on a list of ArcJunctions will sort them by `joinedAt` (row numbers).
        """
        return self.joinedAt < other.joinedAt


@dataclass
class Arc:
    """ An arc connects two commits in the graph.

    Commits appear before their parents in the commit sequence.
    When processing the commit sequence, we "open" a new arc when
    encountering a new commit. The arc stays "open" until we've found
    the commit's parent in the sequence, at which point we "close" it.

    Other arcs may merge into an open arc via an ArcJunction.
    """

    openedAt: BatchRow
    "Row number in which this arc was opened"

    closedAt: BatchRow
    "Row number in which this arc was closed (may be BATCHROW_UNDEF until resolved)"

    chain: ChainHandle
    "Row number of the tip of the arc chain (topmost commit in branch)"

    lane: int
    "Lane assigned to this arc"

    openedBy: Oid
    "Hash of the opening commit (in git parlance, the child commit)"

    closedBy: Oid
    "Hash of the closing commit (in git parlance, the parent commit)"

    junctions: list[ArcJunction]
    "Other arcs merging into this arc"

    nextArc: Arc | None = None
    "Next node in the arc linked list"

    def __repr__(self):
        oa = int(self.openedAt)
        ca = int(self.closedAt)
        ob = str(self.openedBy)[:5]
        cb = str(self.closedBy)[:5]
        dangling = "?" if not self.closedAt.isValid() else ""
        return f"Arc({self.chain} {ob}\u2192{cb}{dangling} {oa}\u2192{ca})"

    def length(self):
        assert type(self.openedAt) is BatchRow
        assert type(self.closedAt) is BatchRow
        return int(self.closedAt) - int(self.openedAt)

    def __next__(self):
        return self.nextArc

    def __iter__(self) -> Iterator[Arc]:
        arc: Arc | None = self
        while arc is not None:
            yield arc
            assert arc.nextArc != arc, "self-referencing arc!"
            arc = arc.nextArc

    def getNumberOfArcsFromHere(self):
        n = 0
        for _ in self:
            n += 1
        return n

    def isParentlessCommitBogusArc(self):
        return self.openedBy == self.closedBy

    def isIndependentOfRowsAbove(self, row: int):
        """ Return True if this arc is entirely independent of row numbers lower than `row`. """
        return self.openedAt >= row and self.closedAt >= row

    def isStale(self, row: int):
        """
        Return True if this arc is considered stale at a given row in the graph.
        An arc is stale at row 'R' if it is closed above 'R',
        or if it is a ParentlessCommitBogusArc appearing at or above 'R',
        or if it is dangling (its closedAt row hasn't been resolved yet).
        """
        ca = int(self.closedAt)
        return (0 <= ca < row) or (0 <= ca == self.openedAt <= row)

    def isVisible(self, hiddenCommits: Set[Oid], row: int, filterJunctionRows=BatchRow.__lt__) -> bool:
        # FAIL if closing commit is hidden.
        if self.closedBy in hiddenCommits:
            return False

        # PASS if both the opening & closing commits are visible.
        if self.openedBy not in hiddenCommits:
            return True

        # Opening Commit hidden (above) and Closing Commit visible (below).
        # PASS if any of the junctions at/above the current row are visible.
        # TODO: We're looking at ALL the junctions - is it worth optimizing this?
        for j in self.junctions:
            if j.joinedBy in hiddenCommits:
                continue
            if filterJunctionRows(j.joinedAt, row):
                return True

        # All junctions should be hidden.
        return False


@dataclass
class Frame:
    """ A frame is a slice of the graph at a given row. """

    row: BatchRow
    commit: Oid
    solvedArcs: list[Arc | None]  # Arcs that have resolved their parent commit
    openArcs: list[Arc | None]  # Arcs that have not resolved their parent commit yet
    lastArc: Arc

    def arcsClosedByCommit(self, hiddenCommits: Set[Oid] | None = None):
        if APP_DEBUG:
            # Assume that all the arcs in solvedArcs are either None, or are closed by this commit.
            assert all(arc is None or arc.closedAt == self.row for arc in self.solvedArcs)
            assert all(arc is None or arc.closedBy == self.commit for arc in self.solvedArcs)

        gen = (arc for arc in self.solvedArcs if arc)

        if hiddenCommits:
            assert self.commit not in hiddenCommits, "calling this func is pointless if commit is hidden"
            row = int(self.row)
            gen = (arc for arc in gen if arc.isVisible(hiddenCommits, row))

        return gen

    def arcsOpenedByCommit(self, hiddenCommits: Set[Oid] | None = None):
        row = int(self.row)
        gen = (arc for arc in self.openArcs if arc and arc.openedAt == row)

        if hiddenCommits:
            assert self.commit not in hiddenCommits, "calling this func is pointless if commit is hidden"
            # Not looking at junctions here because the parents of a visible commit
            # are all supposed to be visible too.
            gen = (arc for arc in gen if arc.closedBy not in hiddenCommits)

        return gen

    def arcsPassingByCommit(self, hiddenCommits: Set[Oid] | None = None, filterJunctionRows=BatchRow.__lt__):
        row = int(self.row)
        gen = (arc for arc in self.openArcs if arc and arc.openedAt != row)

        if hiddenCommits:
            assert self.commit not in hiddenCommits, "calling this func is pointless if commit is hidden"
            gen = (arc for arc in gen if arc.isVisible(hiddenCommits, row, filterJunctionRows))

        return gen

    def junctionsAtCommit(self, hiddenCommits: Set[Oid]):
        row = int(self.row)
        for arc in self.arcsPassingByCommit(hiddenCommits, BatchRow.__eq__):
            # TODO: We're looking at all the junctions here, but isVisible (via getArcsPassingByCommit)
            #       just looked at the specific junction we were looking for.
            for j in arc.junctions:
                if j.joinedAt == row and j.joinedBy not in hiddenCommits:
                    assert j.joinedBy == self.commit
                    yield arc, j
                    break  # stop iterating on junctions, look at next arc

    def homeArc(self) -> Arc:
        leftmostClosed = next(self.arcsClosedByCommit(), None)
        leftmostOpened = next(self.arcsOpenedByCommit(), None)
        if leftmostOpened and leftmostClosed:
            return max(leftmostClosed, leftmostOpened, key=lambda a: a.lane)
        elif leftmostClosed:
            return leftmostClosed
        elif leftmostOpened:
            return leftmostOpened
        else:
            # It's a parentless + childless commit.
            # Implementation detail: for parentless commits, we create a bogus arc
            # as the "last" arc in the frame; we can get the lane from this bogus arc.
            assert self.lastArc.isParentlessCommitBogusArc()
            assert self.lastArc.openedBy == self.commit
            return self.lastArc

    def homeLane(self) -> int:
        return self.homeArc().lane

    def homeChain(self) -> ChainHandle:
        return self.homeArc().chain

    def sealCopy(self) -> Frame:
        """
        Generated frames must be "sealed off" to make them suitable
        for rendering or for use as keyframes.
        """
        solvedArcsCopy = self.solvedArcs.copy()
        openArcsCopy = self.openArcs.copy()

        # Move arcs that just got closed to solved list
        for lane, arc in enumerate(openArcsCopy):
            if arc and 0 <= arc.closedAt <= self.row:
                openArcsCopy[lane] = None

                # For parentless commits, prevent bogus auto-closing arcs
                # from overwriting legitimate closed arcs.
                if not arc.isParentlessCommitBogusArc():
                    self.reserveArcListCapacity(solvedArcsCopy, lane+1)
                    solvedArcsCopy[lane] = arc

        # Remove stale closed arcs and trim "Nones" off end of list
        self.cleanUpArcList(openArcsCopy, self.row, alsoTrimBack=True)
        self.cleanUpArcList(solvedArcsCopy, self.row, alsoTrimBack=True)

        # In debug mode, make sure none of the arcs are dangling
        if APP_DEBUG:
            assert all(arc is None or arc.openedBy != DEAD_VALUE for arc in openArcsCopy)
            assert all(arc is None or arc.openedBy != DEAD_VALUE for arc in solvedArcsCopy)
            assert all(arc is None or arc.chain.isValid() for arc in openArcsCopy)
            assert all(arc is None or arc.chain.isValid() for arc in solvedArcsCopy)

        return Frame(self.row, self.commit, solvedArcsCopy, openArcsCopy, self.lastArc)

    @staticmethod
    def reserveArcListCapacity(theList, newLength):
        if len(theList) >= newLength:
            return
        for _ in range(newLength - len(theList)):
            theList.append(None)

    @staticmethod
    def cleanUpArcList(theList: list[Arc | None], olderThanRow: BatchRow, alsoTrimBack: bool = True):
        # Remove references to arcs that were closed earlier than `olderThanRow`
        for j, arc in enumerate(theList):
            if arc and 0 <= arc.closedAt < olderThanRow:
                theList[j] = None

        # Cull None items at the end of the list
        if alsoTrimBack:
            while theList and not theList[-1]:
                del theList[-1]

        return theList

    def flattenLanes(self, hiddenCommits: Set[Oid]) -> tuple[list[tuple[int, int]], int]:
        """Flatten the lanes so there are no unused columns in-between the lanes."""

        row = int(self.row)

        # Filter arcs

        def genArcsAbove():
            gen1 = (arc for arc in self.solvedArcs if arc)
            gen2 = (arc for arc in self.openArcs if arc and arc.openedAt < row)
            if hiddenCommits:
                gen1 = (arc for arc in gen1 if arc.isVisible(hiddenCommits, row))
                gen2 = (arc for arc in gen2 if arc.isVisible(hiddenCommits, row))
            yield from gen1
            yield from gen2

        def genArcsBelow():
            gen = (arc for arc in self.openArcs if arc)
            if hiddenCommits:
                gen = (arc for arc in gen if arc.isVisible(hiddenCommits, row, BatchRow.__le__))
            yield from gen

        # Sort arcs by Chain Birth Row

        def sortArc(a: Arc):
            return (int(a.chain.topRow) << 16) + a.lane

        arcsAbove = sorted(genArcsAbove(), key=sortArc, reverse=True)
        arcsBelow = sorted(genArcsBelow(), key=sortArc, reverse=True)

        # Assign columns to all lanes used by arcs above and below

        N = max(len(self.solvedArcs), len(self.openArcs))
        mapAbove = [-1] * N
        mapBelow = [-1] * N

        column = -1
        while arcsAbove or arcsBelow:
            column += 1

            if arcsAbove:
                a = arcsAbove.pop()
                mapAbove[a.lane] = column

            if arcsBelow:
                a = arcsBelow.pop()
                mapBelow[a.lane] = column

        remapTable = list(zip(mapAbove, mapBelow, strict=True))
        return remapTable, column + 1


class PlaybackState(Frame):
    def __init__(self, keyframe: Frame):
        super().__init__(
            row=keyframe.row,
            commit=keyframe.commit,
            solvedArcs=[],
            openArcs=[],
            lastArc=keyframe.lastArc)

        self.solvedArcs = keyframe.solvedArcs.copy()
        self.openArcs = keyframe.openArcs.copy()
        self.callingNextWillAdvanceFrame = True
        self.seenCommits: set[Oid] = set()

    def advanceToNextRow(self):
        if not self.callingNextWillAdvanceFrame:
            self.callingNextWillAdvanceFrame = True
            return

        # Put commit from previous iteration into set of previously-seen commits
        if self.commit:
            self.seenCommits.add(self.commit)

        goalFound = False
        goalRow = BATCHROW_UNDEF
        goalCommit = None

        while self.lastArc.nextArc:
            arc: Arc = self.lastArc.nextArc

            if not goalFound and arc.openedAt > self.row:
                # The goal row is determined by the first arc opened at a row greater than the player's current row.
                goalFound = True
                goalRow = arc.openedAt
                goalCommit = arc.openedBy
            elif goalFound and arc.openedAt > goalRow:
                # If we went past the goal row, we have seen all arcs opened at the goal row. Stop.
                break
            else:
                # Keep iterating on arcs in the goal row. Gather them in a frame.
                pass

            self.reserveArcListCapacity(self.solvedArcs, arc.lane + 1)
            self.reserveArcListCapacity(self.openArcs, arc.lane + 1)

            self.solvedArcs[arc.lane] = self.openArcs[arc.lane]  # move any open arc to "just closed"
            self.openArcs[arc.lane] = arc
            self.lastArc = arc

        if not goalFound:
            raise StopIteration()

        assert self.row < goalRow
        assert goalCommit is not None

        self.row = goalRow
        self.commit = goalCommit

        assert isinstance(self.row, BatchRow)

    def __iter__(self):
        return self

    def __next__(self):
        self.advanceToNextRow()
        return self


class Graph:
    keyframes: list[Frame]
    keyframeRows: list[BatchRow]

    startArc: Arc
    """
    Start sentinel of the linked list of Arcs. Guaranteed to never be None.
    Use startArc.nextArc to get to the first actual arc.
    """

    commitRows: dict[Oid, BatchRow]
    ownBatches: list[int]

    volatilePlayer: PlaybackState | None

    def __init__(self):
        self.keyframes = []
        self.keyframeRows = []
        self.commitRows = {}
        self.startArc = Arc(
            openedAt=BATCHROW_UNDEF,
            closedAt=BATCHROW_UNDEF,
            chain=ChainHandle(BATCHROW_UNDEF, BATCHROW_UNDEF),
            lane=-1,
            openedBy="!TOP",
            closedBy="!BOTTOM",
            junctions=[],
            nextArc=None)
        self.ownBatches = []
        self.volatilePlayer = None

    def __del__(self):
        self.freeOwnBatches()

    def freeOwnBatches(self):
        for b in self.ownBatches:
            BatchRow.BatchManager.freeBatch(b)
        self.ownBatches = []

    def shallowCopyFrom(self, source: Graph):
        assert not set(self.ownBatches).intersection(set(source.ownBatches))

        # Free up owned batches
        self.freeOwnBatches()

        self.keyframes = source.keyframes
        self.keyframeRows = source.keyframeRows
        self.startArc = source.startArc
        self.commitRows = source.commitRows
        self.ownBatches = source.ownBatches

        source.ownBatches = []

        source.volatilePlayer = None
        self.volatilePlayer = None

    def isEmpty(self):
        return self.startArc.nextArc is None

    def getCommitRow(self, oid: Oid):
        return int(self.commitRows[oid])

    def saveKeyframe(self, frame: Frame) -> int:
        assert len(self.keyframes) == len(self.keyframeRows)

        kfID = bisect.bisect_left(self.keyframeRows, frame.row)
        if kfID < len(self.keyframes) and self.keyframes[kfID].row == frame.row:
            logger.info(f"Not overwriting existing keyframe {kfID}")
            assert self.keyframes[kfID] == frame.sealCopy()
        else:
            kf = frame.sealCopy()
            self.keyframes.insert(kfID, kf)
            self.keyframeRows.insert(kfID, frame.row)
        return kfID

    def getBestKeyframeID(self, row: int) -> int:
        """
        Attempts to find a keyframe closest to `row` in the frame sequence.
        If an adequate keyframe is found, return its index into the keyframes list; otherwise, return -1.
        Note that the returned value is an **index into the list of keyframes**; it is NOT a frame row number.

        If a valid keyframe was found, its row is guaranteed to be lower or equal to `row`.
        This function never returns a keyframe located at a greater row than `row`.

        If the keyframe occurs before the desired `row`, you can create a PlaybackState from that keyframe
        and iterate the PlaybackState until it reaches the desired row.
        """
        assert row >= 0
        assert len(self.keyframes) == len(self.keyframeRows)

        bestKeyframeID = bisect.bisect_right(self.keyframeRows, row) - 1
        if bestKeyframeID < 0:
            return -1

        bestKeyframeRow = self.keyframeRows[bestKeyframeID]
        assert 0 <= bestKeyframeRow <= row

        return bestKeyframeID

    def startPlayback(self, goalRow: int = 0, oneOff: bool = False) -> PlaybackState:
        kfID = self.getBestKeyframeID(goalRow)
        if kfID >= 0:
            kf = self.keyframes[kfID]
        else:
            kf = self.initialKeyframe()

        if oneOff and self.volatilePlayer and goalRow >= self.volatilePlayer.row >= kf.row:
            player = self.volatilePlayer
        else:
            player = PlaybackState(kf)

        # Position playback context on target row
        try:
            volatileKeyframeCounter = 1
            assert player.row <= goalRow, f"{player.row} {goalRow}"
            while player.row < goalRow:
                player.advanceToNextRow()  # raises StopIteration if depleted

                # Save keyframes every now and then
                if player.row - kf.row >= volatileKeyframeCounter:
                    volatileKeyframeCounter *= 2
                    self.saveKeyframe(player)

            assert player.row == goalRow
            player.callingNextWillAdvanceFrame = False  # let us re-obtain current frame by calling next()
        except StopIteration:
            # Depleted - make sure we get StopIteration next time we call `next`.
            assert player.callingNextWillAdvanceFrame
            assert player.lastArc.nextArc is None

        if oneOff:
            self.volatilePlayer = player

        return player

    def getCommitFrame(self, commit: Oid, unsafe=False) -> Frame:
        row = self.getCommitRow(commit)
        return self.getFrame(row, unsafe)

    def getFrame(self, row: int = 0, unsafe=False) -> Frame:
        assert row >= 0

        kfID = self.getBestKeyframeID(row)

        if kfID >= 0 and self.keyframes[kfID].row == row:
            # Cache hit
            frame = self.keyframes[kfID]
        else:
            # Cache miss
            frame = self.startPlayback(row)
            if not unsafe:
                frame = frame.sealCopy()

        assert frame.row == row, f"frame({int(frame.row)})/row({row}) mismatch"
        return frame

    def initialKeyframe(self):
        return Frame(
            row=BATCHROW_UNDEF,
            commit=self.startArc.openedBy,
            solvedArcs=[],
            openArcs=[],
            lastArc=self.startArc)

    def deleteKeyframesDependingOnRowsAbove(self, row: int):
        """
        Deletes all keyframes containing any arcs opened above the given row.
        """

        if len(self.keyframes) == 0:
            return

        # Get a starting keyframe for a row <= the desired row.
        kfID = self.getBestKeyframeID(row)
        if kfID < 0:
            kfID = 0

        # Fast-forward to the next keyframe with a row >= the desired row.
        while kfID < len(self.keyframes) and self.keyframes[kfID].row < row:
            kfID += 1

        # Once we reach keyframes occuring at a row >= `row`, see if we should stop deleting keyframes.
        # All open arcs, and all non-stale solved arcs, must be independent of rows <= `row`.
        while kfID < len(self.keyframes):
            kf = self.keyframes[kfID]

            if (all(arc is None or arc.isIndependentOfRowsAbove(row) for arc in kf.openArcs)
                    and all(arc is None or arc.isIndependentOfRowsAbove(row) or arc.isStale(row) for arc in kf.solvedArcs)):
                break
            else:
                kfID += 1

        # Delete the keyframes up to kfID.
        self.keyframes = self.keyframes[kfID:]
        self.keyframeRows = self.keyframeRows[kfID:]
        assert len(self.keyframes) == len(self.keyframeRows)

    def deleteArcsDependingOnRowsAbove(self, row: int):
        """
        Deletes all arcs opened before the given row.
        """

        if row == 0:
            return

        # In debug mode, bulldoze opening commits in dead arcs so they stand out in the debugger (make them dangling)
        if APP_DEBUG and self.startArc.nextArc:
            for deadArc in self.startArc.nextArc:
                if deadArc.openedAt >= row:
                    break
                deadArc.openedAt = BATCHROW_UNDEF
                deadArc.openedBy = DEAD_VALUE

        # Rewire top of list
        self.startArc.nextArc =\
            next((arc for arc in self.startArc if arc.openedAt >= row), None)

    def insertFront(self, frontGraph: Graph, numRowsToInsert: int):
        """
        Inserts contents of frontGraph at the beginning of this graph.
        (This function is invoked as step 2 of merging two graphs.)
        """

        # Graph to insert is empty? Bail.
        if frontGraph.startArc.nextArc is None:
            return

        # Don't want to insert any rows? Bail.
        if numRowsToInsert == 0:
            return

        # Find out the last arc we want to take from the front graph
        theirLastArc = next(arc for arc in frontGraph.startArc
                            if arc.nextArc is None or arc.nextArc.openedAt >= numRowsToInsert)
        assert theirLastArc is not None
        assert theirLastArc != frontGraph.startArc

        # In the arc linked list, rewire their last arc onto my first arc.
        theirLastArc.nextArc = self.startArc.nextArc

        # Rewire my top sentinel onto their first actual arc
        self.startArc.nextArc = frontGraph.startArc.nextArc

        # Steal their keyframes
        lastFrontKeyframeID = frontGraph.getBestKeyframeID(numRowsToInsert - 1)
        if lastFrontKeyframeID >= 0:
            assert len(self.keyframes) == len(self.keyframeRows)
            assert len(frontGraph.keyframes) == len(frontGraph.keyframeRows)
            self.keyframes = frontGraph.keyframes[:lastFrontKeyframeID + 1] + self.keyframes
            self.keyframeRows = frontGraph.keyframeRows[:lastFrontKeyframeID + 1] + self.keyframeRows

    def testConsistency(self):
        """ Very expensive consistency check for unit testing """

        # Verify chains
        if self.startArc.nextArc:
            for a in self.startArc.nextArc:
                assert a.chain.isValid()

        # Verify keyframes
        playback = self.startPlayback(0)
        for row, keyframe in zip(self.keyframeRows, self.keyframes, strict=True):
            while playback.commit != keyframe.commit:
                next(playback)
            frame1 = playback.sealCopy()
            frame2 = keyframe.sealCopy()
            assert frame1 == frame2, f"Keyframe at row {row} doesn't match actual graph state"
