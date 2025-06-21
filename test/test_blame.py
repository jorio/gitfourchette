# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import dataclasses

from gitfourchette.blame import *
from .util import *


@dataclasses.dataclass
class Scenario:
    path: str
    lineCommits: list[str]
    seedCommit: str = ""  # if blank, start at workdir
    testRepo: str = "TestGitRepository"


SCENARIOS = {
    "hello.txt": Scenario(
        "hello.txt",
        ["acecd5e", "6aaa262", "4ec4389"],
        testRepo="testrepoformerging",
    ),

    "add file in merge commit": Scenario(
        "b/b2.txt",
        ["d31f5a6", "7f82283"],
        testRepo="TestGitRepository",
    ),
}


@pytest.mark.parametrize('scenarioKey', SCENARIOS.keys())
def testBlameFileInRepo(tempDir, scenarioKey):
    scenario = SCENARIOS[scenarioKey]

    wd = unpackRepo(tempDir, scenario.testRepo)
    repo = Repo(wd)

    if not scenario.seedCommit:
        seed = Trace.makeWorkdirMockCommit(repo, scenario.path)
    else:
        seed = repo[scenario.seedCommit].peel(Commit)

    trace = Trace(scenario.path, seed)
    trace.annotate(repo)

    anno = trace.first.annotatedFile
    print(anno.toPlainText(repo))

    for line, expectedOid in zip(anno.lines[1:], scenario.lineCommits, strict=True):
        assert str(line.traceNode.commitId).startswith(expectedOid)
