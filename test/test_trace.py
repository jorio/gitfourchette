# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import dataclasses
import hashlib

import pytest

from gitfourchette.blame import *
from gitfourchette.graph import GraphDiagram, MockOid, GraphBuildLoop
from gitfourchette.porcelain import *

TRACEPATH = "TraceMe.txt"

@dataclasses.dataclass
class Scenario:
    textGraph: str
    blobDefs: str
    textSignificantCommits: str
    skimInterval: int = 0


# Each scenario is a 3-tuple interpreted as such:
# 1. Commit graph definition parsed by GraphDiagram.
# 2. Text contents of TraceMe.txt at each point of the commit sequence.
#    An underscore means that TraceMe.txt does not exist in that commit's tree.
# 3. Expected significant commits.
SCENARIOS = {
    # a ┯ 4
    # b ┿ 4 <-- significant revision
    # c ┿ 3 <-- significant revision
    # d ┿ 2 <-- significant revision
    # e ┿ 1
    # f ┿ 1
    # g ┷ 1 <-- significant revision
    "linear": Scenario(
        "a-b-c-d-e-f-g",
        "4 4 3 2 1 1 1",
        "  b c d     g",
    ),

    # a ┯ 3
    # b ┿ 2
    # c ┿ 1
    # x ┿ _ <-- file did not exist; stop tracing here
    # y ┿ _
    # z ┷ _
    "linear with extra history before file is created": Scenario(
        "a-b-c-x-y-z",
        "3 2 1 _ _ _",  # underscore means the file doesn't exist
        "a b c",
    ),

    # a ┯     2
    # b ┿─╮   2
    # c │ ┿─╮ 2
    # d │ │ ┿ 2
    # e │ ┿─╯ 2
    # f ┿─╯   2 <-- significant
    # g ┷     1 <-- significant
    "collapse": Scenario(
        "a-b:f,c c:e,d d-e-f-g",
        "2 2     2     2 2 2 1",
        "                  f g",
    ),

    "parallel prune0a": Scenario(
        "a:b,p p-b",
        "2     1 1",
        "a       b",
    ),

    "parallel prune0b": Scenario(
        "a:b,p p-q-r-s-b",
        "2     1 1 1 1 1",
        "a             b",
    ),

    # a ┯   2
    # m ┿─╮ 2
    # p │ ┿ 1
    # b ┿ │ 2
    # c ┿ │ 2 <-- significant
    # d ┿ │ 1
    # z ┷─╯ 1 <-- significant
    "parallel prune1": Scenario(
        "a-m:b,p p:z b-c-d-z",
        "2 2     1   2 2 1 1",
        "              c   z",
    ),

    # a ┯   1
    # m ┿─╮ 1
    # p │ ┿ 2 <-- don't prune this because '2' is not a known hash
    # b ┿ │ 3
    # c ┿ │ 3
    # d ┿ │ 4
    # z ┷─╯ 4
    "parallel keep1": Scenario(
        "a-m:b,p p:z b-c-d-z",
        "1 1     2   3 3 4 4",
        "  m     p     c   z",
    ),

    # a ┯   1
    # b ┿   2
    # c ┿─╮ 3
    # d │ ┿ 4 <-- should be able to prune this because '4' is a known hash further down the main branch
    # e │ ┿ 4
    # f ┿ │ 3 <-- significant contributor on main branch
    # g │ ┿ 4
    # h ┷─╯ 4
    "parallel prune2": Scenario(
        "a-b-c:f,d d-e:g f:h g-h",
        "1 2 3     4 4   3   4 4",
        "a b             f     h"
    ),

    # a ┯   1
    # b ┿   2
    # c ┿─╮ 3
    # d │ ┿ 3 <-- don't prune this branch because its top commit is '3', meaning it is the contributor for this blob that is eventually merged into c
    # e │ ┿ 3 <-- significant contributor on parallel branch
    # f ┿ │ 4
    # g │ ┿ 4
    # h ┷─╯ 4
    "parallel keep2": Scenario(
        "a-b-c:f,d d-e:g f:h g-h",
        "1 2 3     3 3   4   4 4",
        "a b c       e         h"
    ),

    # c ┯─╮ 3 <-- significant because merge point
    # e │ ┿ 3 <-- significant contributor on parallel branch
    # g │ ┿ 4     (don't care)
    # h ┷─╯ 4 <-- significant because main branch
    "parallel keep2 reduced": Scenario(
        "c:h,e e-g-h",
        "3     3 4 4",
        "c     e   h"
    ),

    "double merge": Scenario(
        "a:e,b b-c-d:f e:g,f f-g",
        "2     2 2 2   2     2 1",
        "              e     f g",
    ),

    "triple merge": Scenario(
        "a:d,b b-c:z,e d:f,e e:g f:h,g g:i h:j,i i:k j:z,k k:z z",
        "3     2 2     3     2   3     2   3     2   3     2   1",
        "j k z",
    ),

    # a ┯─╮  <-- 1 (add)
    # b │ ┿  <-- 1 (add)
    # z ┷─╯  <-- file did not exist yet
    "bumper 1": Scenario(
        "a:z,b b-z",
        "1     1 _",
        "a     b",
    ),

    # a ┯─╮  <-- 2 (add)
    # b │ ┿  <-- 2 (modify)
    # c │ ┿  <-- 1 (add)
    # z ┷─╯  <-- file did not exist yet
    "bumper 2": Scenario(
        "a:z,b b-c-z",
        "2     2 1 _",
        "a     b c",
    ),

    # a ┯─╮  <-- 1
    # b │ ┿  <-- 2
    # z ┷─╯  <-- 3
    "simple merge, all relevant": Scenario(
        "a:z,b b-z",
        "1     2 3",
        "a     b z",
    ),

    # a ┯─╮  <-- 1
    # b │ ┿  <-- 2
    # n ┿─╯  <-- 3
    # z ┷    <-- 3
    "simple merge, root commit not relevant": Scenario(
        "a:n,b b-n-z",
        "1     2 3 3",
        "a     b   z",
    ),

    "multi tails": Scenario(
        "a-c:f,d d-e f",
        "1 2     3 4 5",
        "a c     d e f",
    ),

    # a ┯─╮
    # b ┿───╮
    # c │ │ ┿
    # d │ │ ┿
    # e │ ┿─╯
    # f ┿─╯
    #   │─╮
    # g │ ┷
    # h ┷
    "significant rev merged into lower level": Scenario(
        "a:b,e b:f,c c-d-e-f:h,g g h",
        "3     2     2 1 1 1     1 0",
        "a     b     c     f     g h",
    ),

    # a ┯─╮
    # b │ ┿
    # c ┿─╮
    # d │ ┿
    # e ┷─╯
    "don't visit twice 1": Scenario(
        "a:c,b b:d c:e,d d-e",
        "4     3   2     1 0",
        "a     b   c     d e",
    ),

    "don't visit twice 2": Scenario(
        "a:c,b b-b2:d c:e,d d-e",
        "4     3 3b   2     1 0",
        "a     b b2   c     d e",
    ),

    "don't visit twice 3": Scenario(
        "a:c,b b:d c-c2:e,d d-e",
        "4     3   2 2    1 0",
        "a     b     c2   d e",
    ),

    "don't visit twice 4": Scenario(
        "a:c,b b:d c:e,d d-e",
        "4     3   1     1 1",
        "a     b           e",
    ),

    # a ┯─╮
    # b │ ┿─╮  <-- here b returns into a shallower branch, but d's contribution is still relevant
    # d │ │ ┷
    # c ┿─╯
    # e ┷
    "consider extra parent even if returning to shallower branch": Scenario(
        "a:c,b b:c,d d c-e",
        "4     4     2 3 1",
        "a     b     d c e",
    ),

    "junction?": Scenario(
        "a:c,b b:d c:e,d d-e",
        "4     3   2     1 0",
        "a     b   c     d e",
    ),

    # a ┯─╮  <-- blob 2
    # b │ ┿  <-- file did not exist
    # c ┿ │  <-- blob 1
    # d ┷─╯  <-- file did not exist
    "prune branch that diverged before file was created": Scenario(
        "a:c,b b:d c-d",
        "2     _   1 _",
        "a         c  ",
    ),

    "graphwalk don't revisit 1": Scenario(
        "67:2d,fc fc-a8:c1 2d-b4-c1-88-zz",
        "17       04 04    71 68 ef ef b3",
        "67          a8    2d b4    88 zz",
    ),

    "graphwalk don't revisit 2": Scenario(
        "74:84,ff ff:e8 84-c8-5c-e8-dd",
        "f8       77    fb 6b 13 5d 5d",
        "74       ff    84 c8 5c    dd",
    ),

    "skimming beyond history": Scenario(
        "c0-c1-c2-c3-c4-c5-c6-c7-c8-c9",
        " 2  2  2  2  2  2  2  2  2  2",
        "                           c9",
        skimInterval=50,
    ),

    "skimming 2 hops": Scenario(
        "c0-c1-c2-c3-c4-c5-c6-c7-c8-c9",
        " 2  2  2  2  2  2  2  2  1  1",
        "                     c7    c9",
        skimInterval=4,
    ),

    "skimming 1 hop 1": Scenario(
        "c0-c1-c2-c3-c4-c5-c6-c7-c8-c9",
        " 2  2  2  2  2  2  2  2  2  1",
        "                        c8 c9",
        skimInterval=9,
    ),

    "skimming 1 hop 2": Scenario(
        "c0-c1-c2-c3-c4-c5-c6-c7-c8-c9",
        " 2  2  2  2  2  2  2  2  1  1",
        "                     c7    c9",
        skimInterval=9,
    ),

    "added file in merge commit": Scenario(
        "a:z,b b-c-d-z",
        "3     3 2 1 _",
        "a     b c d  ",
    ),

    # a ┯─╮ 2
    # b │ ┿ 2
    # c │ ┿
    # d │ ┿
    # e │ ┿
    # f ┿─╮
    # g │ ┿
    # z ┷─╯ 1
    "skim double merge, interval 2": Scenario(
        "a:f,b b-c-d-e:g f:z,g g-z",
        "2     2 1 1 1   1     1 1",
        "a     b                 z",
        skimInterval=2,
    ),

    # Same as above with different skim interval
    "skim double merge, interval 1": Scenario(
        "a:f,b b-c-d-e:g f:z,g g-z",
        "2     2 1 1 1   1     1 1",
        "a     b                 z",
        skimInterval=1,
    ),
}


class MockBlob:
    def __init__(self, data: str):
        self.data = data.encode()
        realHash = hashlib.sha1(f'blob {len(self.data)}'.encode() + b'\0' + self.data)
        self.id = Oid(hex=realHash.hexdigest())


class MockTree(dict):
    def diff_to_tree(self, treeAbove: MockTree, _a, _b, _c):
        assert _a == 0
        assert _b == 0
        assert _c == 0

        class DummyDiffNoRenames:
            def __init__(self):
                self.deltas = {}

            def find_similar(self):
                pass

        return DummyDiffNoRenames()


@pytest.mark.parametrize('scenarioKey', SCENARIOS.keys())
def testTrace(scenarioKey):
    print()

    scenario = SCENARIOS[scenarioKey]
    significantCommits = MockOid.encodeAll(scenario.textSignificantCommits.split())
    sequence, heads = GraphDiagram.parseDefinition(scenario.textGraph)

    diagram = GraphDiagram.diagram(GraphBuildLoop(heads).sendAll(sequence).graph)
    print(diagram)

    for commit, blobText in zip(sequence, scenario.blobDefs.split(), strict=True):
        commit.tree = MockTree()
        if blobText != "_":
            commit.tree[TRACEPATH] = MockBlob(blobText)

    traceState = Trace(TRACEPATH, sequence[0], skimInterval=scenario.skimInterval)
    assert traceState.numRelevantNodes == len(significantCommits)

    for traceNode, significantCommit in zip(traceState.first.walkGraph(), significantCommits, strict=True):
        print(f"[GRAPHWALK] {traceNode} {traceNode.blobId} {traceNode.sealed}")
        assert traceNode.sealed
        assert traceNode.commitId == significantCommit

    assert traceNode.status == DeltaStatus.ADDED
