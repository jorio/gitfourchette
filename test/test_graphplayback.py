# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.graph import *


def findSolvedArc(frame: Frame, openedBy, closedBy):
    for a in frame.solvedArcs:
        if not a:
            continue
        if a.openedBy == openedBy and a.closedBy == closedBy:
            return a
    raise AssertionError(f"did not find solved arc {openedBy} -> {closedBy} in frame {frame.row}")


def findOpenArc(frame: Frame, openedBy, closedBy):
    for a in frame.openArcs:
        if not a:
            continue
        if a.openedBy == openedBy and a.closedBy == closedBy:
            return a
    raise AssertionError(f"did not find open arc {openedBy} -> {closedBy} in frame {frame.row}")


def checkFrame(pb: PlaybackState, row, commit, solved="", open=""):
    pb.advanceToNextRow()
    frame = pb.sealCopy()

    assert frame.row == row
    assert frame.commit == commit

    numSolved = 0
    numOpen = 0
    if solved:
        for sa in solved.split(","):
            numSolved += 1
            findSolvedArc(frame, *sa.split("-"))
    if open:
        for oa in open.split(","):
            numOpen += 1
            findOpenArc(frame, *oa.split("-"))

    assert numSolved == sum(1 for sa in frame.solvedArcs if sa is not None), "there are more solved arcs to test"
    assert numOpen == sum(1 for oa in frame.openArcs if oa is not None), "there are more open arcs to test"

    return frame


def testSimpleGraph():
    """
    a1 ┯
    a2 ┿
    b1 │ ┯
    b2 │ ┿
    a3 ┿─╯
    a4 ┷
    """
    g = GraphDiagram.parse("a1-a2:a3 b1-b2-a3-a4")
    print("\n" + GraphDiagram.diagram(g))
    pb = g.startPlayback(0)

    checkFrame(pb, 0, "a1", open="a1-a2")
    checkFrame(pb, 1, "a2", solved="a1-a2", open="a2-a3")
    checkFrame(pb, 2, "b1", open="a2-a3,b1-b2")
    checkFrame(pb, 3, "b2", solved="b1-b2", open="b2-a3,a2-a3")
    checkFrame(pb, 4, "a3", solved="b2-a3,a2-a3", open="a3-a4")
    checkFrame(pb, 5, "a4", solved="a3-a4")


def testGapBetweenBranches():
    """
    a1 ┯
    b1 │ ┯
    c1 │ │ ┯
    a2 ┿─╯ │
    c2 │   ┿
     f ┷───╯
    """
    g = GraphDiagram.parse("a1:a2 b1:a2 c1:c2 a2:f c2-f")
    print("\n" + GraphDiagram.diagram(g))
    pb = g.startPlayback(0)

    checkFrame(pb, 0, "a1", open="a1-a2")
    checkFrame(pb, 1, "b1", open="a1-a2,b1-a2")
    checkFrame(pb, 2, "c1", open="a1-a2,b1-a2,c1-c2")
    checkFrame(pb, 3, "a2", solved="a1-a2,b1-a2", open="c1-c2,a2-f")
    frameC2 = checkFrame(pb, 4, "c2", solved="c1-c2", open="a2-f,c2-f")
    checkFrame(pb, 5, "f", solved="a2-f,c2-f")

    laneRemap, numColumns = frameC2.flattenLanes(set())
    assert numColumns == 2
    assert laneRemap[0] == (0, 0)
    assert laneRemap[1] == (-1, -1)
    assert laneRemap[2] == (1, 1)


def testNewBranchInGap():
    """
    Flattening OFF:         Flattening ON:

    a1                      a1
     |  b1                   |  b1
     |   |  c1               |   |  c1
    a2__/    |              a2__/    |
     |      c2               |     c2
     |  d1   |               |    /   d1
    a3   |   |              a3    |    |
     f__/___/                f___/____/
    """
    g = GraphDiagram.parse("a1:a2 b1:a2 c1:c2 a2:a3 c2:f d1:f a3-f")
    print("\n" + GraphDiagram.diagram(g))
    pb = g.startPlayback(0)

    frameA1 = checkFrame(pb, 0, "a1", open="a1-a2")
    frameB1 = checkFrame(pb, 1, "b1", open="a1-a2,b1-a2")
    frameC1 = checkFrame(pb, 2, "c1", open="a1-a2,b1-a2,c1-c2")
    frameA2 = checkFrame(pb, 3, "a2", solved="a1-a2,b1-a2", open="c1-c2,a2-a3")
    frameC2 = checkFrame(pb, 4, "c2", solved="c1-c2", open="a2-a3,c2-f")
    frameD1 = checkFrame(pb, 5, "d1", open="a2-a3,c2-f,d1-f")
    frameA3 = checkFrame(pb, 6, "a3", solved="a2-a3", open="a3-f,c2-f,d1-f")
    frameF = checkFrame(pb, 7, "f", solved="a3-f,c2-f,d1-f")

    hiddenCommits = set()

    laneRemap, numColumns = frameA1.flattenLanes(hiddenCommits)
    print("Frame A1:", laneRemap, numColumns)
    assert numColumns == 1
    assert laneRemap[0] == (-1, 0)  # a1: new branch tip in column 0

    laneRemap, numColumns = frameB1.flattenLanes(hiddenCommits)
    print("Frame B1:", laneRemap, numColumns)
    assert numColumns == 2
    assert laneRemap[0] == (0, 0)  # a1 still
    assert laneRemap[1] == (-1, 1)  # b1: new branch tip in column 1

    laneRemap, numColumns = frameC1.flattenLanes(hiddenCommits)
    print("Frame C1:", laneRemap, numColumns)
    assert numColumns == 3
    assert laneRemap[0] == (0, 0)  # a1 still
    assert laneRemap[1] == (1, 1)  # b1 still
    assert laneRemap[2] == (-1, 2)  # c1: new branch tip in column 2

    laneRemap, numColumns = frameA2.flattenLanes(hiddenCommits)
    print("Frame A2:", laneRemap, numColumns)
    assert numColumns == 3
    assert laneRemap[0] == (0, 0)  # A1-A2 in column 0
    assert laneRemap[1] == (1, -1)  # B1 comes from above in column 1, frees up column 1 as it merges into A2
    assert laneRemap[2] == (2, 1)  # C1 comes from above in column 2, and gets remapped to column 1 below

    laneRemap, numColumns = frameC2.flattenLanes(hiddenCommits)
    print("Frame C2:", laneRemap, numColumns)
    assert numColumns == 2
    assert laneRemap[0] == (0, 0)  # A2-A3 in column 0
    assert laneRemap[1] == (-1, -1)  # vacant
    assert laneRemap[2] == (1, 1)  # C2 is in lane 2, but it can use the gap in column 1 left by vacant lane 1

    laneRemap, numColumns = frameD1.flattenLanes(hiddenCommits)
    print("Frame D1:", laneRemap, numColumns)
    assert numColumns == 3
    assert laneRemap[0] == (0, 0)  # a2-a3 still
    assert laneRemap[1] == (-1, 2)  # d1: branch tip
    assert laneRemap[2] == (1, 1)  # c2 still

    laneRemap, numColumns = frameA3.flattenLanes(hiddenCommits)
    print("Frame A3:", laneRemap, numColumns)
    assert numColumns == 3

    laneRemap, numColumns = frameF.flattenLanes(hiddenCommits)
    print("Frame F:", laneRemap, numColumns)
    assert numColumns == 3
    assert laneRemap[0] == (0, -1)  # free up F
    assert laneRemap[1] == (2, -1)  # free up D1
    assert laneRemap[2] == (1, -1)  # free up C2


def testVisibleJunctionOnHiddenArc():
    # Inspired by a (simplified) version of pygit2's testrepoformerging.zip.
    # (Enter Detached HEAD at initial commit then hide all branches except ff-branch.)
    """
    Start:                      Hide 'a':
    u ┯
    a │ ┯                       u ┯
    b │ │ ┯                     b │   ┯
    c │ ╭─┿ <- Junction on      c │ ╭─┿ <- Should still show junction
    d │ │ ┿    arc "a-z"!       d │ │ ┿    and rest of arc downwards
    e │ ┿ │                     e │ ┿ │
    z ┷─╯─╯                     z ┷─╯─╯
    """
    sequence, heads = GraphDiagram.parseDefinition("u:z a:e b-c:d,e d:z e-z")

    heads = MockOid.encodeAll("u", "a", "b")
    hideSeeds = MockOid.encodeAll("a")

    gbu = GraphBuildLoop(heads, hideSeeds=hideSeeds).sendAll(sequence)
    g = gbu.graph
    hiddenCommits = gbu.hiddenCommits

    print()
    print(GraphDiagram.diagram(g))
    print(GraphDiagram.diagram(g, hiddenCommits=hiddenCommits))

    assert GraphDiagram.diagram(g, hiddenCommits=hiddenCommits).splitlines() == [
        "u ┯",
        "b │   ┯",
        "c │ ╭─┿",
        "d │ │ ┿",
        "e │ ┿ │",
        "z ┷─╯─╯",
    ]

    laneRemap = {str(frame.commit): frame.sealCopy().flattenLanes(hiddenCommits)[0]
                 for frame in g.startPlayback()}
    X = -1
    assert laneRemap['u'] == [(X, 0)]
    assert laneRemap['b'] == [(0, 0), (X, X), (X, 1)]
    assert laneRemap['c'] == [(0, 0), (X, 1), (1, 2)]
    assert laneRemap['d'] == [(0, 0), (1, 1), (2, 2)]
    assert laneRemap['e'] == [(0, 0), (1, 1), (2, 2)]
    assert laneRemap['z'] == [(0, X), (1, X), (2, X)]
