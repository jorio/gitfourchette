# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import itertools
from dataclasses import dataclass

import pytest

from gitfourchette.graph import *


@dataclass
class ChainMarkerFixture:
    graphName: str

    graphDef: str

    headsDef: str

    hiddenCommits: dict
    """ Map of hidden commit seeds to a list of all hidden commits,
    assuming the only "important" commits are listed out in graphDef.
    All unlisted commits are considered to be "visible". """

    localCommits: dict
    """ Map of local commit seeds to a list of all local commits.
    All unlisted commits are considered to be "foreign". """

    def hiddenCommitsParametrizedArgs(self):
        return [(self, k.split(), v.split()) for k, v in self.hiddenCommits.items()]

    def hiddenCommitsParametrizedNames(self):
        return [self.graphName + ": " + k for k in self.hiddenCommits]

    def localCommitsParametrizedArgs(self):
        return [(self, k.split(), v.split()) for k, v in self.localCommits.items()]

    def localCommitsParametrizedNames(self):
        return [self.graphName + ": " + k for k in self.localCommits]


allFixtures = [
    # a1 ┯
    # b1 │ ┯
    # c1 │ │ ┯
    # a2 ┿─╯ │
    # c2 │   ┿
    # d1 │ ┯ │
    # a3 ┿ │ │
    #  f ┿─╯─╯
    #    ├─╮
    # f1 ┷ │
    # g1   ┷
    ChainMarkerFixture(
        graphName="typical",
        graphDef="a1:a2 b1:a2 c1:c2 a2:a3 c2:f d1:f a3-f:f1,g1 f1 g1",
        headsDef="a1 b1 c1 d1",

        hiddenCommits={
            "": "",

            "a1": "a1",
            "b1": "b1",
            "c1": "c1 c2",
            "a2": "",  # don't hide anything because a1/b1 still visible
            "c2": "",  # don't hide anything because c1 still visible
            "d1": "d1",
            "a3": "",

            "a1 b1": "a1 b1 a2 a3",
            "b1 c1": "b1 c1 c2",
            "c1 d1": "c1 c2 d1",

            "a1 b1 a2": "a1 b1 a2 a3",
            "b1 c1 d1": "b1 c1 c2 d1",

            "a1 b1 c1": "a1 a2 b1 c1 c2 a3",
            "a1 b1 c1 d1": "a1 a2 b1 c1 c2 a3 d1 f f1 g1",
        },

        localCommits={
            "": "",

            "a1": "a1 a2 a3 f f1 g1",
            "a2": "a2 a3 f f1 g1",
            "a3": "a3 f f1 g1",
            "b1": "b1 a2 a3 f f1 g1",
            "c1": "c1 c2 f f1 g1",
            "c2": "c2 f f1 g1",
            "d1": "d1 f f1 g1",
            "f": "f f1 g1",

            "a1 b1": "a1 a2 a3 b1 f f1 g1",
            "a1 c1": "a1 a2 a3 c1 c2 f f1 g1",
            "a1 d1": "a1 a2 a3 d1 f f1 g1",

            "a1 b1 c1": "a1 a2 a3 b1 c1 c2 f f1 g1",

            "a1 b1 c1 d1": "a1 a2 a3 b1 c1 c2 d1 f f1 g1",
        },
    ),

    #  a ┯
    # sc │ ┯
    #    │ │─╮─╮
    # si │ │ ┿ │
    # su │ │ │ ┷
    #  b ┿─╯─╯
    #  c ┷
    ChainMarkerFixture(
        graphName="stash",
        graphDef="a:b sc:b,si,su si:b su b-c",
        headsDef="a sc",

        hiddenCommits={
            "": "",
            "a": "a",
            "b": "",  # cannot be hidden because VIP commits depend on it
            "sc": "sc si su",
            "a sc": "a sc si su b c",
            # Non-tips:
            "su!": "su",
            "si!": "si",
            "si! su!": "si su",
        },

        localCommits={
            "": "",
            "a": "a b c",
            "a b": "a b c",
            "sc": "sc si su b c",
            "a sc": "a sc si su b c",
        },
    ),

    # a ┯
    # b │ ┯
    # c ┿─╯  (intentionally incomplete)
    ChainMarkerFixture(
        graphName="incomplete",
        graphDef="a:c b-c:missingparent",
        headsDef="a b",

        hiddenCommits={
            "": "",
            "a": "a",
            "b": "b",
            "c": "",
            "a b": "a b c",
            "a b c": "a b c",
        },

        localCommits={
            "": "",
            "a": "a c",
            "b": "b c",
            "c": "c",
            "a b": "a b c",
            "a b c": "a b c",
        },
    ),

    # a ┯
    # c ┿─╮
    # d │ ┿
    # e ┷─╯
    ChainMarkerFixture(
        graphName="nojunction",
        graphDef="a:c c:e,d d-e",
        headsDef="a",
        hiddenCommits={
            "": "",
            "a": "a c d e",
        },
        localCommits={
            "": "",
            "a": "a c d e",
        },
    ),

    # a ┯
    # b │ ┯
    # c ┿─╮  (junction)
    # d │ ┿
    # e ┷─╯
    ChainMarkerFixture(
        graphName="junction",
        graphDef="a:c b:d c:e,d d-e",
        headsDef="a b",
        hiddenCommits={
            "": "",
            "a": "a c",
            "b": "b",
            "a b": "a b c d e",
        },
        localCommits={
            "": "",
            "a": "a c d e",
            "b": "b d e",
            "a b": "a b c d e",
        },
    ),

    #  a ┯
    #  b │ ┯
    #  c │ │ ┯
    #  j ┿─╮ │    FPbf
    #  k ┿─│─╮    FPcf
    # bf │ ┷ │
    # cf │   ┷
    # af ┷
    ChainMarkerFixture(
        graphName="2 junctions on 1 branch",
        graphDef="a:j b:bf c:cf j:k,bf k:af,cf bf cf af",
        headsDef="a b c",
        hiddenCommits={
            "": "",
            "a": "a j k af",
            "b": "b",
            "c": "c",
            "a b": "a j k af b bf",
        },
        localCommits={
            "": "",
            "a": "a j k af bf cf",
            "b": "b bf",
            "c": "c cf",
        },
    ),

    # a ┯─╮
    # b │ │ ┯
    # c │ ┿─╯
    # d ┿─╯
    # e ┷
    ChainMarkerFixture(
        graphName="deep propagation",
        graphDef="a:d,c b:c c-d-e",
        headsDef="a b",
        hiddenCommits={
            "": "",
            "a": "a",  # should not hide anything else because b depends on it
            "b": "b",
        },
        localCommits={
            "": "",
            "b": "b c d e",
        },
    ),

    ChainMarkerFixture(
        graphName="deep propagation with junctions",
        graphDef="a:f b:d c:j j:e,d d:e e-f-g",
        headsDef="a b c",
        hiddenCommits={
            "": "",
            "a": "a",
            "a b": "a b",
            "c": "c j",
            "b c": "b c j d e",
        },
        localCommits={
            "": "",
            "c": "c j d e f g",  # <--- that's the tricky one
            "b": "b d e f g",
        },
    ),

    # a ┯
    # b ┿─╮
    # c │ ┿
    # d │ ┿
    # e ┿─╯
    # f ┷
    ChainMarkerFixture(
        graphName="non-tip head should stay visible",
        graphDef="a-b:e,c c-d-e-f",
        headsDef="a c",  # note the extra head "c" here. We want it to stay visible when hiding "a"
        hiddenCommits={
            "": "",
            "a": "a b",  # "c" must be visible
        },
        localCommits={
            "": "",
        },
    ),
]


@pytest.mark.parametrize(
    argnames=("fixture", "seedsAscii", "expectedHidden"),
    argvalues=itertools.chain.from_iterable(g.hiddenCommitsParametrizedArgs() for g in allFixtures),
    ids=itertools.chain.from_iterable(g.hiddenCommitsParametrizedNames() for g in allFixtures),
)
def testHiddenCommitMarks(fixture: ChainMarkerFixture, seedsAscii, expectedHidden):
    seeds = set(MockOid.encodeAll(seedsAscii))
    fixtureHeads = set(MockOid.encodeAll(fixture.headsDef.split()))

    sequence, graphHeads = GraphDiagram.parseDefinition(fixture.graphDef)
    assert all(h in fixtureHeads for h in graphHeads)

    hiddenTips = set(MockOid.encodeAll(c for c in seedsAscii if not c.endswith("!")))
    hiddenTaps = set(MockOid.encodeAll(c.removesuffix("!") for c in seedsAscii if c.endswith("!")))
    gbu = GraphBuildLoop(fixtureHeads, hideSeeds=hiddenTips, forceHide=hiddenTaps)
    gbu.sendAll(sequence)

    print("\n" + GraphDiagram.diagram(gbu.graph, verbose=False))
    print("Seed hidden commits:", seeds)
    print("Expected hidden commits:", expectedHidden)
    assert gbu.hiddenTrickle.done or gbu.weaver.isDangling()

    def verb(hidden: bool):
        return 'hide' if hidden else 'show'

    for commit in sequence:
        oid = commit.id
        shouldHide = oid in expectedHidden
        didHide = oid in gbu.hiddenCommits
        print(f"{oid}\t: should {verb(shouldHide)}, did {verb(didHide)}")
        assert shouldHide == didHide


@pytest.mark.parametrize(
    argnames=("fixture", "seedsAscii", "expected"),
    argvalues=itertools.chain.from_iterable(g.localCommitsParametrizedArgs() for g in allFixtures),
    ids=itertools.chain.from_iterable(g.localCommitsParametrizedNames() for g in allFixtures),
)
def testLocalCommitMarks(fixture: ChainMarkerFixture, seedsAscii, expected):
    seeds = set(MockOid.encodeAll(seedsAscii))
    fixtureHeads = set(MockOid.encodeAll(fixture.headsDef.split()))

    sequence, graphHeads = GraphDiagram.parseDefinition(fixture.graphDef)
    assert all(h in fixtureHeads for h in graphHeads)

    builder = GraphBuildLoop(heads=fixtureHeads, localSeeds=seeds)
    builder.sendAll(sequence)
    assert builder.foreignTrickle.done or builder.weaver.isDangling()

    graph = builder.graph

    print("\n" + GraphDiagram.diagram(graph))
    print("Seed commits:", seeds)
    print("Expected commits:", expected)

    for commit in sequence:
        oid = commit.id
        isLocal = oid not in builder.foreignCommits
        assert isLocal == (oid in expected), f"{oid} should be marked {oid in expected}, was marked {isLocal}"
