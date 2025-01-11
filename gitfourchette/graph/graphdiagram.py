# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import re
from itertools import zip_longest

from gitfourchette.graph import *
from gitfourchette.graph.graphbuilder import GraphBuildLoop, MockCommit, MockOid, Oid

PADDING = 2
ABRIDGMENT_THRESHOLD = 25


def padx(x):
    assert x >= 0
    return x * PADDING


class GraphDiagram:
    @staticmethod
    def parse(text: str):
        sequence, heads = GraphDiagram.parseDefinition(text)
        return GraphBuildLoop().sendAll(sequence).graph

    @staticmethod
    def parseDefinition(text: str) -> tuple[list[MockCommit], set[Oid]]:
        sequence = []
        seen: set[Oid] = set()
        heads: set[Oid] = set()

        lines = re.split(r"\s+", text)

        for line in lines:
            line = line.strip()
            if not line:
                continue

            split = line.strip().split(":")
            assert 1 <= len(split) <= 2

            chainStr = split[0]
            assert chainStr
            assert "," not in chainStr

            try:
                assert "-" not in split[1]
                rootParents = MockOid.encodeAll(split[1].split(","))
            except IndexError:
                rootParents = []

            chain = MockOid.encodeAll(chainStr.split("-"))
            parents = [[c] for c in chain[1:]] + [rootParents]

            for oid, commitParents in zip(chain, parents, strict=True):
                assert all(c.id != oid for c in sequence), f"Commit hash appears twice in sequence! {oid}"
                mockCommit = MockCommit(oid, commitParents)
                sequence.append(mockCommit)
                if mockCommit.id not in seen:
                    heads.add(mockCommit.id)
                seen.update(mockCommit.parent_ids)

        return sequence, heads

    @staticmethod
    def diagram(graph: Graph, row0=0, maxRows=20, hiddenCommits=None, verbose=False):
        if not hiddenCommits:
            hiddenCommits = set()

        try:
            player = graph.startPlayback(row0)
        except StopIteration:
            return f"Won't draw graph because it's empty below row {row0}!"

        diagram = GraphDiagram()

        for _ in player:
            frame = player.sealCopy()
            if frame.commit in hiddenCommits:
                continue
            diagram.newFrame(frame, hiddenCommits, verbose)
            maxRows -= 1
            if maxRows < 0:
                break

        return diagram.bake()

    # -----------------------------------------------------------------

    def __init__(self):
        self.scanlines = []
        self.margins = []

    def reserve(self, x, y, fill=" "):
        assert len(fill) == 1
        for _ in range(len(self.scanlines), y + 1):
            self.scanlines.append([])
            self.margins.append([])
        scanline = self.scanlines[y]
        for _ in range(len(scanline), padx(x) + 1):
            scanline.append(fill)
        return scanline

    def plot(self, x, y, c):
        assert len(c) == 1
        scanline = self.reserve(x, y)
        assert scanline[padx(x)] not in "╭╮╰╯", "overwriting critical glyph!"
        scanline[padx(x)] = c

    def hline(self, x1, y, x2, fill="─"):
        assert len(fill) == 1
        left, right = min(x1, x2), max(x1, x2)
        scanline = self.reserve(right, y)
        for i in range(padx(left), padx(right) + 1):
            assert scanline[i] not in "╭╮╰╯", "overwriting critical glyph!"
            scanline[i] = fill

    def addMarginText(self, y, text):
        self.reserve(0, y)
        self.margins[y].append(text)

    def removeLastRow(self):
        self.scanlines.pop()
        self.margins.pop()

    def bake(self):
        if self.margins:
            numMargins = max(len(rowMargins) for rowMargins in self.margins)
        else:
            numMargins = 0
        marginWidths = [0] * numMargins
        for margins in self.margins:
            for i, mText in enumerate(margins):
                marginWidths[i] = max(marginWidths[i], len(mText))

        text = ""
        for margins, scanline in zip(self.margins, self.scanlines, strict=True):
            for mWidth, mText in zip_longest(reversed(marginWidths), reversed(margins), fillvalue=""):
                text += mText.rjust(mWidth) + " "
            text += ''.join(scanline).rstrip()
            text += "\n"
        text = text.removesuffix("\n")
        return text

    def newFrame(self, frame: Frame, hiddenCommits, verbose):
        upper = len(self.scanlines)
        lower = upper + 1
        homeLane = frame.homeLane()
        homeChain = frame.homeChain()

        for arc in frame.arcsPassingByCommit(hiddenCommits):
            # TODO: Depending on junctions, we may or may not want to abridge
            glyph = "│" if arc.length() <= ABRIDGMENT_THRESHOLD else "┊"
            self.plot(arc.lane, upper, glyph)
            self.plot(arc.lane, lower, glyph)

        closed = list(frame.arcsClosedByCommit(hiddenCommits))
        opened = list(frame.arcsOpenedByCommit(hiddenCommits))
        trivialClosed = True

        if closed:
            leftmostClosedLane = min([cl.lane for cl in closed])
            rightmostClosedLane = max([cl.lane for cl in closed])
            self.hline(leftmostClosedLane, upper, rightmostClosedLane)
            for cl in closed:
                if cl.lane != homeLane:
                    self.plot(cl.lane, upper, "╰╯"[cl.lane > homeLane])
                    trivialClosed = False

        if opened:
            row = upper if trivialClosed else lower
            leftmostOpenedLane = min([ol.lane for ol in opened])
            rightmostOpenedLane = max([ol.lane for ol in opened])
            self.hline(leftmostOpenedLane, row, rightmostOpenedLane)
            for ol in opened:
                if ol.lane == homeLane:
                    self.plot(ol.lane, row, "│")
                else:
                    self.plot(ol.lane, row, "╭╮"[ol.lane > homeLane])
                if row == upper:
                    self.plot(ol.lane, lower, "│")

        for arc, junction in frame.junctionsAtCommit(hiddenCommits):
            row = upper if trivialClosed else lower
            assert arc.junctions == sorted(arc.junctions), "junction list is supposed to be sorted!"
            assert junction.joinedBy == frame.commit, "junction commit != frame commit"
            assert homeLane != arc.lane, "junction plugged into passing arc that's on my homeLane?"
            self.hline(homeLane, row, arc.lane)
            self.plot(arc.lane, row, "╭╮"[homeLane < arc.lane])
            if row != upper:
                self.plot(homeLane, row, "╯╰"[homeLane < arc.lane])

        commitGlyph = "╳┷┯┿"[bool(opened) << 1 | bool(closed)]
        self.plot(homeLane, upper, commitGlyph)

        self.addMarginText(upper, str(frame.commit))
        if verbose:
            self.addMarginText(upper, str(int(frame.row)))
            self.addMarginText(upper, str(int(homeChain.topRow)))

        self.reserve(0, lower)  # make sure we're not removing upper row if we didn't plot anything in last row
        if not any(c in "╭╮╰╯" for c in self.scanlines[-1]):
            self.removeLastRow()
