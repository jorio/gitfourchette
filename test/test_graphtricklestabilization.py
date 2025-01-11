# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses

import pytest

from gitfourchette.graph import GraphDiagram, GraphBuildLoop, GraphSpliceLoop, MockOid


@dataclasses.dataclass
class TrickleStabilizationFixture:
    oldSequence: str
    oldHeads: str
    newHeads: str
    oldHideSeeds: str
    newHideSeeds: str
    oldHiddenCommitsExpected: str
    newHiddenCommitsExpected: str
    newSequence: str = ""


SCENARIOS = [
    #  u ┯
    # a1 │ ┯  <--- Hidden Ref
    # a2 │ ┿
    # a3 │ ┿
    #  c │ ┿  <--- Initially Visible Ref - this ref gets deleted,
    #  d │ ┿       so only u-e-f should remain visible after splicing
    #  e ┿─╯
    #  f ┷
    TrickleStabilizationFixture(
        oldSequence="u:e a1-a2-a3-c-d-e-f",
        oldHeads="u a1 c",
        newHeads="u a1",
        oldHideSeeds="a1",
        newHideSeeds="a1",
        oldHiddenCommitsExpected="a1 a2 a3",
        newHiddenCommitsExpected="a1 a2 a3 c d",
    ),

    #  u ┯
    # a1 │ ┯  <--- Visible Ref  [NUKE THIS COMMIT]
    # a2 │ ┿                    [NUKE THIS COMMIT]
    # a3 │ ┿                    [NUKE THIS COMMIT]
    #  c │ ┿  <--- Hidden Ref
    #  d │ ┿
    #  e ┿─╯
    #  f ┷
    # Everything is visible initially.
    # After splicing, a1-a2-a3 get nuked, and c-d become hidden.
    TrickleStabilizationFixture(
        oldSequence="u:e a1-a2-a3-c-d-e-f",
        newSequence="u:e c-d-e-f",
        oldHeads="u a1 c",
        newHeads="u c",
        oldHideSeeds="c",
        newHideSeeds="c",
        oldHiddenCommitsExpected="",
        newHiddenCommitsExpected="c d",
    ),

    #      u ┯
    #      a │ ┯
    #      b │ ┿
    # master ┿─╯
    #      d ┿
    #     e1 │ ┯  <---- initially visible, then this ref gets hidden
    #     e2 │ ┿
    #     e3 │ ┿
    #      f │ │ ┯  <--- hidden
    #      g ┷─╯─╯
    TrickleStabilizationFixture(
        oldSequence="u:master a-b-master-d:g e1-e2-e3:g f:g g",
        oldHeads="u a master e1",
        newHeads="u a master e1",
        oldHideSeeds="f",
        newHideSeeds="f e1",
        oldHiddenCommitsExpected="f",
        newHiddenCommitsExpected="f e1 e2 e3",
    ),

    #      u ┯
    #      a │ ┯
    #      b │ ┿
    # master ┿─╯
    #      d ┿
    #     e1 │ ┯  <---- initially hidden, then we create a new VISIBLE branch here
    #     e2 │ ┿
    #     e3 │ ┿
    #      f │ │ ┯
    #      g ┿─╯─╯
    #      h ┿
    #      i │ ┯  <---- hidden (causes trickle to stabilize BEFORE being "done")
    #      j ┷─╯
    TrickleStabilizationFixture(
        oldSequence="u:master a-b-master-d:g e1-e2-e3:g f:g g-h:j i-j",
        oldHeads="u a master e1",
        newHeads="u a master e1",
        oldHideSeeds="i e1",
        newHideSeeds="i",
        oldHiddenCommitsExpected="i e1 e2 e3",
        newHiddenCommitsExpected="i",
    ),

    # a ┯   <--- Initially visible, then hide
    # b ┿─╮
    # c │ ┿ <--- Visible ref - should remain visible (along with c-e-f chain)
    # d ┿ │
    # e ┿─╯
    # f ┷
    TrickleStabilizationFixture(
        oldSequence="a-b:d,c c:e d-e-f",
        oldHeads="a c",
        newHeads="a c",
        oldHideSeeds="",
        newHideSeeds="a",
        oldHiddenCommitsExpected="",
        newHiddenCommitsExpected="a b d",
    ),
]


@pytest.mark.parametrize('reverse', ["", "reverse"])
@pytest.mark.parametrize('scenario', SCENARIOS)
def testGraphTrickleStabilization(scenario, reverse):
    sequence, _dummy = GraphDiagram.parseDefinition(scenario.oldSequence)
    if scenario.newSequence:
        newSequence, _dummy = GraphDiagram.parseDefinition(scenario.newSequence)
    else:
        newSequence = sequence
    oldHeads = MockOid.encodeAll(scenario.oldHeads.split())
    newHeads = MockOid.encodeAll(scenario.newHeads.split())
    oldHideSeeds = MockOid.encodeAll(scenario.oldHideSeeds.split())
    newHideSeeds = MockOid.encodeAll(scenario.newHideSeeds.split())
    oldHiddenCommitsExpected = set(MockOid.encodeAll(scenario.oldHiddenCommitsExpected.split()))
    newHiddenCommitsExpected = set(MockOid.encodeAll(scenario.newHiddenCommitsExpected.split()))

    if reverse:
        sequence, newSequence = newSequence, sequence
        oldHeads, newHeads = newHeads, oldHeads
        oldHideSeeds, newHideSeeds = newHideSeeds, oldHideSeeds
        oldHiddenCommitsExpected, newHiddenCommitsExpected = newHiddenCommitsExpected, oldHiddenCommitsExpected

    gbl = GraphBuildLoop(oldHeads, hideSeeds=oldHideSeeds)
    gbl.sendAll(sequence)

    print()
    print(GraphDiagram.diagram(gbl.graph))
    print(GraphDiagram.diagram(gbl.graph, hiddenCommits=gbl.hiddenCommits))

    assert gbl.hiddenCommits == oldHiddenCommitsExpected

    gsl = GraphSpliceLoop(gbl.graph, sequence, oldHeads, newHeads, hideSeeds=newHideSeeds)
    gsl.sendAll(newSequence)
    print("---- Post splicing ----")
    print(GraphDiagram.diagram(gsl.graph, hiddenCommits=gsl.hiddenCommits))

    assert gsl.hiddenCommits == newHiddenCommitsExpected
