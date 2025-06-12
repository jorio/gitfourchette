# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
from collections.abc import Set

from gitfourchette import colors
from gitfourchette import settings
from gitfourchette.graph import Graph, Frame
from gitfourchette.porcelain import Oid
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID

logger = logging.getLogger(__name__)

LANE_WIDTH = 10
LANE_THICKNESS = 2
DOT_RADIUS = 3
UC_COLOR = colors.gray
UC_STIPPLE = 12

_dummyEmptyList = []


def getColor(laneID):
    return colors.rainbowBright[laneID % len(colors.rainbowBright)]


def flattenLanes(frame: Frame, hiddenCommits: Set[Oid]) -> tuple[list[tuple[int, int]], int]:
    """
    Compute columns (horizontal positions) for each lane above and below this row.
    """

    if settings.prefs.flattenLanes:
        laneRemap, columnCount = frame.flattenLanes(hiddenCommits)
    else:
        # Straightforward lane positions (lane column == lane ID)
        laneRemap = []
        columnCount = max(len(frame.solvedArcs), len(frame.openArcs))
        for i in range(columnCount):
            laneRemap.append((i, i))

    return laneRemap, columnCount


def getCommitBulletColumn(
        commitLane: int,
        columnCount: int,
        lanePositionsAB: list[tuple[int, int]]
) -> tuple[int, int]:
    # Find out at which position to draw the commit's bullet point.
    myLanePosition = -1

    if commitLane < len(lanePositionsAB):
        posA, posB = lanePositionsAB[commitLane]

        # First, attempt to put bullet point in parent lane's position (below).
        if myLanePosition < 0:
            myLanePosition = posB

        # If that didn't work (commit has no parents), put bullet point in child lane's position (above).
        if myLanePosition < 0:
            myLanePosition = posA

    # If that still didn't work, we have a lone commit without parents or children; just toss the bullet to the right.
    if myLanePosition < 0:
        myLanePosition = columnCount
        columnCount += 1
        assert myLanePosition == commitLane, "expecting GraphGenerator to put lone commits on the rightmost column"

    return myLanePosition, columnCount


def paintGraphFrame(
        painter: QPainter,
        rect: QRect,
        oid: Oid,
        graph: Graph,
        hiddenCommits: Set[Oid]
):
    try:
        # Get this commit's sequential index in the graph
        myRow = graph.getCommitRow(oid)
    except LookupError:  # pragma: no cover
        logger.warning(f"Skipping unregistered commit: {oid}")
        return

    painter.save()
    outlineColor = painter.background().color()

    # Lines are drawn with SquareCap to fill in gaps at fractional display scaling factors.
    # This may cause the painter to overflow to neighboring rows, so set a clip rect.
    painter.setClipRect(rect)

    # Ensure all coordinates below are integers so our straight lines don't look blurry
    x = int(rect.left() + LANE_WIDTH // 2)
    top = int(rect.y())
    bottom = int(rect.y() + rect.height())  # Don't use rect.bottom(), which for historical reasons doesn't return what we want (see Qt docs)
    middle = (top + bottom) // 2

    # Get graph frame for this row
    frame = graph.getFrame(myRow)
    assert frame.commit == oid
    assert frame.row == myRow

    # Get the commit's lane ID
    commitLane = frame.homeLane()

    # Flatten the lanes so there are no horizontal gaps in-between the lanes (optional).
    # laneColumnsAB is a table of lanes to columns (horizontal positions).
    laneColumnsAB, numFlattenedColumns = flattenLanes(frame, hiddenCommits)

    # Get column (horizontal position) of commit bullet point.
    myColumn, numFlattenedColumns = getCommitBulletColumn(commitLane, numFlattenedColumns, laneColumnsAB)

    rect.setRight(x + (numFlattenedColumns - 1) * LANE_WIDTH)
    mx = x + myColumn * LANE_WIDTH  # the screen X of this commit's bullet point

    # draw bullet point _outline_ for this commit, beneath everything else
    painter.setPen(QPen(outlineColor, 2, Qt.PenStyle.SolidLine))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QPoint(mx, middle), DOT_RADIUS, DOT_RADIUS)

    path = QPainterPath()

    def submitPath(path: QPainterPath, column, stipple=False, dashOffset = 0):
        assert not path.isEmpty()
        # white outline
        painter.setPen(QPen(outlineColor, LANE_THICKNESS + 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.BevelJoin))
        painter.drawPath(path)
        # actual color
        color = UC_COLOR if stipple else getColor(column)
        cap = Qt.PenCapStyle.FlatCap if stipple else Qt.PenCapStyle.SquareCap
        pen = QPen(color, LANE_THICKNESS, Qt.PenStyle.SolidLine, cap, Qt.PenJoinStyle.BevelJoin)
        if stipple:
            interval = rect.height()/(UC_STIPPLE*LANE_THICKNESS)
            pen.setDashPattern([interval, interval])
            pen.setDashOffset(dashOffset * 0.5 * rect.height()/(LANE_THICKNESS))
        painter.setPen(pen)
        painter.drawPath(path)
        # clear path for next iteration
        path.clear()

    if frame.commit in hiddenCommits:
        arcsPassingByCommit = _dummyEmptyList
        arcsOpenedByCommit = _dummyEmptyList
        arcsClosedByCommit = _dummyEmptyList
        junctionsAtCommit = _dummyEmptyList
    else:
        arcsPassingByCommit = frame.arcsPassingByCommit(hiddenCommits)
        arcsOpenedByCommit = list(frame.arcsOpenedByCommit(hiddenCommits))
        arcsClosedByCommit = list(frame.arcsClosedByCommit(hiddenCommits))
        junctionsAtCommit = frame.junctionsAtCommit(hiddenCommits)

    # draw arcs PASSING BY commit
    cy1 = middle
    cy2 = middle
    if not arcsOpenedByCommit:
        # Compress the curvature of arcs passing by a root commit    |  |  |
        # to the bottom half of the row to prevent these arcs from   O  |  |
        # looking like they are joined to the root commit in a         /  /
        # flattened graph.                                            |  |
        cy1 = bottom + 4
        cy2 = middle
    elif not arcsClosedByCommit:
        # Same, but compress above
        cy1 = middle - 4
        cy2 = top
    for arc in arcsPassingByCommit:
        columnA, columnB = laneColumnsAB[arc.lane]  # column above, column below
        ax = x + columnA * LANE_WIDTH
        bx = x + columnB * LANE_WIDTH
        path.moveTo(ax, top)
        path.cubicTo(ax, cy1, bx, cy2, bx, bottom)
        submitPath(path, arc.lane, arc.openedBy == UC_FAKEID)

    # draw arcs CLOSED BY commit (from above)
    for arc in reversed(arcsClosedByCommit):
        columnA, _dummy = laneColumnsAB[arc.lane]  # column above, column below
        ax = x + columnA * LANE_WIDTH
        # Path from above does elbow shape to merge into commit bullet point
        path.moveTo(ax, top)
        path.quadTo(ax, middle, mx, middle)
        submitPath(path, arc.lane, arc.openedBy == UC_FAKEID)

    # draw arcs OPENED BY commit (downwards)
    for arc in reversed(arcsOpenedByCommit):
        _dummy, columnB = laneColumnsAB[arc.lane]  # column above, column below
        bx = x + columnB * LANE_WIDTH
        # Path forks downward from commit bullet point
        path.moveTo(mx, middle)
        path.quadTo(bx, middle, bx, bottom)
        submitPath(path, arc.lane, arc.openedBy == UC_FAKEID, dashOffset=1)

    # draw arc junctions
    for arc, _junction in junctionsAtCommit:
        columnA, columnB = laneColumnsAB[arc.lane]
        ax = x + columnA * LANE_WIDTH
        bx = x + columnB * LANE_WIDTH
        path.moveTo(mx, middle)
        path.quadTo(bx, middle, bx, bottom)
        submitPath(path, arc.lane)

    # draw bullet point for this commit
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(getColor(commitLane) if oid != UC_FAKEID else UC_COLOR)
    painter.drawEllipse(QPoint(mx, middle), DOT_RADIUS, DOT_RADIUS)

    # we're done, clean up
    painter.restore()

    # add some padding to the right
    rect.setRight(rect.right() + LANE_WIDTH)

