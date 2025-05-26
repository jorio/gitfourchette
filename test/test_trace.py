# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import hashlib

import pytest

from gitfourchette.graph import GraphDiagram, MockOid, GraphBuildLoop
from gitfourchette.trace import *

TRACEPATH = "TraceMe.txt"

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
    "linear": (
        "a-b-c-d-e-f-g",
        "4 4 3 2 1 1 1",
        "  b c d     g",
    ),

    "linear with extra history before file is created": (
        "a-b-c-d-e-f-g-h-i-j",
        "4 4 3 2 1 1 1 _ _ _",  # underscore means the file doesn't exist
        "  b c d     g",
    ),

    # a ┯     2
    # b ┿─╮   2
    # c │ ┿─╮ 2
    # d │ │ ┿ 2
    # e │ ┿─╯ 2
    # f ┿─╯   2 <-- significant
    # g ┷     1 <-- significant
    "collapse": (
        "a-b:f,c c:e,d d-e-f-g",
        "2 2     2     2 2 2 1",
        "                  f g",
    ),

    # a ┯   2
    # m ┿─╮ 2
    # p │ ┿ 1
    # b ┿ │ 2
    # c ┿ │ 2 <-- significant
    # d ┿ │ 1
    # z ┷─╯ 1 <-- significant
    "parallel skip": (
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
    "parallel don't prune": (
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
    "parallel prune d-e-g": (
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
    "parallel don't prune d-e-g": (
        "a-b-c:f,d d-e:g f:h g-h",
        "1 2 3     3 3   4   4 4",
        "a b c       e         h"
    ),

    "double merge": (
        "a:e,b b-c-d:f e:g,f f-g",
        "2     2 2 2   2     2 1",
        "              e     f g",
    ),

    "triple merge": (
        "a:d,b b-c:z,e d:f,e e:g f:h,g g:i h:j,i i:k j:z,k k:z z",
        "3     2 2     3     2   3     2   3     2   3     2   1",
        "j k z",
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

    textGraph, blobDefs, textSignificantCommits = SCENARIOS[scenarioKey]
    significantCommits = MockOid.encodeAll(textSignificantCommits.split())
    sequence, heads = GraphDiagram.parseDefinition(textGraph)

    diagram = GraphDiagram.diagram(GraphBuildLoop(heads).sendAll(sequence).graph)
    print(diagram)

    for commit, blobText in zip(sequence, blobDefs.split(), strict=True):
        commit.tree = MockTree()
        if blobText != "_":
            commit.tree[TRACEPATH] = MockBlob(blobText)

    ll = traceFile(TRACEPATH, sequence[0])
    ll.dump()

    for traceNode, significantCommit in zip(ll, significantCommits, strict=True):
        assert traceNode.commitId == significantCommit

    assert ll.tail.sealed
    assert ll.tail.status == DeltaStatus.ADDED
