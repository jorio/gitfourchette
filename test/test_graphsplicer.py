# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.graph import *
import pytest

KF_INTERVAL_TEST = 1
"""
In the real world, the interval between keyframes is on the order of thousands
of frames. For unit testing purposes, let's save keyframes more frequently --
our test graphs are tiny.
"""

# Values are 3-tuples:
# [0]: Old graph definition oneliner
# [1]: New graph definition oneliner (used for splicing)
# [2]: Should splicing find an equilibrium (i.e. recycle part of the old graph)
SCENARIOS = {
    "one branch, one new commit": (
        "  a-b-c-d-e",
        "n-a-b-c-d-e",
        True,
    ),

    "one new commit": (
        "  a-b:e c-d-e-f-g",
        "n-a-b:e c-d-e-f-g",
        True,
    ),

    "new parentless branch appears": (
        "                     a1:a2 b1:b2 c1:c2 a2 b2 c2",
        "a0:a1 b0:b1 d0:d1 d1 a1:a2 b1:b2 c1:c2 a2 b2 c2",
        True
    ),

    "several new commits": (
        "            a-b:e c-d-e-f-g",
        "m-n:a o:e,a a-b:e c-d-e-f-g",
        True,
    ),

    "change order of branches": (
        "a-b:e c-d-e-f-g",
        "c-d:e a-b-e-f-g",
        True,
    ),

    "delete top commit": (
        "x-a-b:e c-d-e-f-g",
        "  a-b:e c-d-e-f-g",
        True,
    ),

    "amend top commit": (
        "x:a   a-b:e c-d-e-f-g",
        "y:a   a-b:e c-d-e-f-g",
        True,
    ),

    "amend non-top commit": (
        "x-a-b:e   c-d-e-f-g",
        "x-a-b:e   y-d-e-f-g",
        True,
    ),

    "identical with 1 head": (
        "a-b-c-d",
        "a-b-c-d",
        True,
    ),

    "identical with 2 heads": (
        "a-b:e c-d-e-f-g",
        "a-b:e c-d-e-f-g",
        True,
    ),

    "non-top head rises to top after amending": (
        "    a-b:e c-d-e-f-g",
        "c:d a-b:e   d-e-f-g",
        True,
    ),

    "lone commit appears at top": (
        "  a-b-c-d",
        "x a-b-c-d",
        True,
    ),

    "lone commit appears in middle": (
        "a-b:c   c-d",
        "a-b:c x c-d",
        True,
    ),

    "lone commit appears at bottom": (
        "a-b-c-d  ",
        "a-b-c-d x",
        False,
    ),

    #  0 a ┯
    #  1 b ┿
    #      │─╮─╮─╮
    #  2 c ┿ │ │ │
    #  3 d │ ┿ │ │
    #      │ ╰───╮        JunctionOn"Arc(chain: 1, oa: 1, ob: b → ca: 5, cb: f)":1[d]->3;
    #  4 e │ │ ┿ │
    #  5 f │ │ │ ┿
    #  6 s │ │ │ ┿
    #  7 r │ │ ┿ │
    #  8 p ┿ │ │ │
    #  9 q │ ┿ │ │
    # 10 z ┷─╯─╯─╯
    "octopus": (
        "a-b:c,d,e,f c:p d:q,f e:r f-s:z r:z p:z q:z z",
        "a-b:c,d,e,f c:p d:q,f e:r f-s:z r:z p:z q:z z",
        True,
    ),

    "parentless commit appears at top; other branches don't need to be reviewed": (
        "  a-b-c-d-e:q f-g-h:i t:u i:r u-v:s q-r-s x-y-z",
        "n a-b-c-d-e:q f-g-h:i t:u i:r u-v:s q-r-s x-y-z",
        True,
    ),

    "neverending line due to unresolved arc": (
        "    a-b-c",
        "x:z a-b-c",
        False,
    ),

    "multiple new commits appear in middle": (
        "a-b-c-d:e         e-f-g",
        "a-b-c-d:e x-y-z:e e-f-g",
        True,
    ),

    "multiple commits disappear in middle": (
        "a-b-c-d:e x-y-z-e-f-g",
        "a-b-c-d:e     z-e-f-g",
        True,
    ),

    "commits disappear at top": (
        "a-b-c-d:e x-y-z-e-f-g",
        "  b-c-d:e x-y-z-e-f-g",
        True,
    ),

    "branch disappears": (
        "a-b:c p-q-r-c-d-e",
        "a-b:c       c-d-e",
        True,
    ),

    "0 to 0": (
        "",
        "",
        False,
    ),

    "0 to 1": (
        "",
        "a",
        False,
    ),

    "0 to 2": (
        "",
        "a-b",
        False,
    ),

    "1 to 2": (
        "b",
        "a-b",
        True,
    ),

    "1 to 2b": (
        "y-x-c",
        "a-b-c",
        True,
    ),

    "1 to 0": (
        "a",
        "",
        False,
    ),

    "many to 0": (
        "m-n:a o:e,a a-b:e c-d-e-f-g",
        "",
        False,
    ),

    "0 to many": (
        "",
        "m-n:a o:e,a a-b:e c-d-e-f-g",
        False,
    ),

    "completely different, newer is shorter": (
        "a-b-c-d-e-f",
        "p-q-r",
        False,
    ),

    "completely different, newer is longer": (
        "p-q-r",
        "a-b-c-d-e-f",
        False,
    ),

    "completely different, newer is longer, 1 commitless 'loop'": (
        "p-q-r",
        "a:b,f b-c-d-e-f",
        False,
    ),

    "completely different, newer is longer, 2 commitless 'loops'": (
        "p-q-r",
        "a:b,f,g b-c-d-e-f g",
        False,
    ),

    "messy junctions": (
        "a-b:c k:l c:c',l           c':d l:e d-e-f",
        "a-b:c k:l c:c',l p-q:r,l r-c':d l:e d-e-f",
        True,
    ),

    # Start from first graph, splice second graph, then splice first graph again.
    # The ChainHandle in Arc x-z must still be valid.
    "need chainhandle alias after multiple splicings 1": (
        "a-b-c:d,x       d-e:y x:z y-z",
        "a-b-c:d,x i-j-k-d-e:y x:z y-z",
        True,
    ),

    # Start from first graph, splice second graph, then splice first graph again.
    # The ChainHandle in Arc x-z must still be valid (at least the top row).
    "need chainhandle alias after multiple splicings 2": (
        "a-b-c:d,x       d-e:y x:z y",
        "a-b-c:d,x i-j-k-d-e:y x:z y",
        True,
    ),

    "super messy junctions - shifted rows + existing junctions before & after equilibrium + 1 new junction": (
        "      a-b:c k:l c:c',l           c'-m-n-o:d,l l:e d-e-f",
        "x-y-z-a-b:c k:l c:c',l p-q:r,l r-c'-m-n-o:d,l l:e d-e-f",
        True,
    ),

    "super messy junctions reversed": (
        "x-y-z-a-b:c k:l c:c',l p-q:r,l r-c'-m-n-o:d,l l:e d-e-f",
        "      a-b:c k:l c:c',l           c'-m-n-o:d,l l:e d-e-f",
        True,
    ),

    "stash at top": (
        "           a-b-c",
        "s1:a,s2 s2-a-b-c",
        True,
    ),

    "truncated graph with junctions (fork points) pointing outside the graph": (
        "c9e:ce1 493:6e1,f73,d01 d01:6db f73:6db 6e1:120,7f8 120-bab-838:646,6db 646-42e 7f8-597:c07",
        "c9e:ce1 493:6e1,f73,d01 d01:6db f73:6db 6e1:120,7f8 120-bab-838:646,6db 646-42e 7f8-597:c07",
        True,
    ),

    "careful not to rewire main dead branch into LL of branches after splicing": (
        "a:d b:d,c c-d-f-g",
        "m:d b:d,c c-d-f-g",
        True
    ),

    "careful not to rewire main dead branch into LL of branches after splicing 2": (
        "a1:a2 b1:b2,b' b'-b2:a2 c:a2,c' c'-a2-a3:a4 d1-d2-a4-f",
        "am:a2 b1:b2,b' b'-b2:a2 c:a2,c' c'-a2-a3:a4 d1-d2-a4-f",
        True,
    ),

    "equilibrium in between disjoint branches 1": (
        "a-b c-d",
        "x-b c-d",
        True,
    ),

    "equilibrium in between disjoint branches 2": (
        "a-b c-d",
        "x-y c-d",
        True,
    ),

    "equilibrium in between disjoint branches 3": (
        "a-b c-d",
        "x-b c-d",
        True,
    ),

    "topo sort branch shuffle 1": (
        "p-o m",
        "n-m p-o",
        False,
    ),

    "topo sort branch shuffle 1b": (
        "p-o m x-y-z",
        "n-m p-o x-y-z",
        True,
    ),

    "topo sort branch shuffle 2": (
        "p-o m",
        "n-m o",
        False,
    ),

    "topo sort branch shuffle 3": (
        "a:m b-c:m d-e-m-n-z",
        "a:m f-d-e:m b-c-m-n-z",
        True,
    ),

    "topo sort branch shuffle 4": (
        "u:a i-j a-b",
        "u-n-a-b i-j",
        False
    ),
}


@pytest.mark.parametrize('scenarioKey', SCENARIOS.keys())
def testGraphSplicing(scenarioKey):
    textGraph1, textGraph2, expectEquilibrium = SCENARIOS[scenarioKey]
    sequence1, heads1 = GraphDiagram.parseDefinition(textGraph1)
    sequence2, heads2 = GraphDiagram.parseDefinition(textGraph2)

    g = GraphBuildLoop(keyframeInterval=KF_INTERVAL_TEST).sendAll(sequence1).graph

    verification = GraphBuildLoop().sendAll(sequence2).graph

    print("---------------------------------------------------")
    print(F"Graph before --------- (heads: {heads1})")
    print(GraphDiagram.diagram(g))
    print("Keyframes BEFORE REFRESH:", g.keyframeRows)
    print("Num arcs total BEFORE REFRESH:", g.startArc.getNumberOfArcsFromHere())

    print("Initial consistency check...")
    g.testConsistency()

    # verify that row cache is consistent
    assert list(range(len(sequence1))) == [g.getCommitRow(c.id) for c in sequence1]

    print("---------------------------------------------------")
    print("Splice...")

    # modify top of history
    spliceLoop = GraphSpliceLoop(g, sequence1, heads1, heads2, keyframeInterval=KF_INTERVAL_TEST)
    spliceLoop.sendAll(sequence2)
    g.testConsistency()

    assert [c.id for c in spliceLoop.commitSequence] == [c.id for c in sequence2], "output commit sequence incorrect"

    for trashedCommit in (spliceLoop.splicer.oldCommitsSeen - spliceLoop.splicer.newCommitsSeen):
        assert not any(trashedCommit == c.id for c in sequence2), f"commit '{trashedCommit}' erroneously trashed"

    assert spliceLoop.splicer.foundEquilibrium == expectEquilibrium

    # delete the splicer to ensure that any dtors don't mess up the spliced graph
    del spliceLoop

    print(F"Graph after --------- (heads: {heads2})")
    print("Keyframes AFTER SPLICING:", g.keyframeRows)
    print("Num branches AFTER SPLICING:", g.startArc.getNumberOfArcsFromHere())

    # Nuke KFs to force going thru everything again
    g.keyframes = []
    g.keyframeRows = []
    print(GraphDiagram.diagram(g))

    # verify that the splicing was correct
    assert GraphDiagram.diagram(g, verbose=True) == GraphDiagram.diagram(verification, verbose=True)

    # verify that row cache is consistent
    assert list(range(len(sequence2))) == [g.getCommitRow(c.id) for c in sequence2]

    # verify that all the keyframes are correct after re-creating them
    g.testConsistency()

    # Stress test: go back to first graph
    print("---------------------------------------------------")
    print("Revert to first graph...")
    gsl2 = GraphSpliceLoop(g, oldCommitSequence=sequence2, oldHeads=heads2,
                           newHeads=heads1, keyframeInterval=KF_INTERVAL_TEST)
    gsl2.sendAll(sequence1)
    g.testConsistency()
