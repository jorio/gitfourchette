# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses

from gitfourchette.blame.tracenode import TraceNode
from gitfourchette.porcelain import *
from gitfourchette.repomodel import UC_FAKEID


class AnnotatedFile:
    @dataclasses.dataclass
    class Line:
        traceNode: TraceNode
        text: str

    binary: bool
    lines: list[Line]

    def __init__(self, node: TraceNode):
        sentinel = AnnotatedFile.Line(node, "$$$BOGUS$$$")
        self.lines = [sentinel]
        self.binary = False

    @property
    def traceNode(self):
        return self.lines[0].traceNode

    def toPlainText(self, repo: Repo):  # pragma: no cover (for debugging)
        """ Intended for debugging. No need to localize the text within. """

        from datetime import datetime

        dateNow = datetime.now()
        result = ""

        for i, blameLine in enumerate(self.lines):
            node = blameLine.traceNode

            if node.commitId == UC_FAKEID:
                date = dateNow
                author = "Not Committed Yet"
            else:
                commit = repo[node.commitId].peel(Commit)
                author = commit.author.name
                date = datetime.fromtimestamp(commit.author.time)

            strDate = date.strftime("%Y-%m-%d")
            result += f"{id7(node.commitId)} {node.path:20} ({author:20} {strDate} {i}) {blameLine.text.rstrip()}\n"

        return result
