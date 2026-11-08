# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations  # TODO: Remove once we can drop support for Python <= 3.13

import base64
import collections
import dataclasses
import enum
import re
from pathlib import Path
from typing import ClassVar

from gitfourchette import colors
from gitfourchette.porcelain import Oid, RefPrefix
from gitfourchette.qt import *


class RebaseOp(enum.StrEnum):
    Pick        = "pick"
    Reword      = "reword"
    Edit        = "edit"
    Squash      = "squash"
    Fixup       = "fixup"
    FixupC      = "fixup -C"  # rebase.autoSquash makes these from "amend!" commits
    Exec        = "exec"
    Break       = "break"
    Drop        = "drop"
    Label       = "label"
    Reset       = "reset"
    Merge       = "merge"
    UpdateRef   = "update-ref"
    FakeDone    = "__done"
    FakeDoneRW  = "__donerewritten"
    FakeStop    = "__stop"
    FakeStart   = "__start"
    FakeRewrite = "__rewrite"

    def isMelding(self) -> bool:
        """True if this operation requires a connection to an older commit."""
        return self in {"fixup", "fixup -C", "squash"}

    def isConcrete(self) -> bool:
        """True if this operation breaks a chain of melding operations."""
        return self in {"pick", "edit", "reword"}

    def isEditable(self) -> bool:
        """True if this operation allows editing the commit message."""
        return self == "reword" or self == "squash"

    def isFake(self) -> bool:
        """True if this is an internal operation that must be stripped from the
        sequence before feeding it to Git."""
        return self.startswith("__")


SupportedRebaseOps = {
    RebaseOp.Pick,
    RebaseOp.Reword,
    RebaseOp.Edit,
    # RebaseOp.Squash,  # TODO - need message edit support
    RebaseOp.Fixup,
    RebaseOp.Drop,
}


RebaseOpLetters: dict[RebaseOp, str] = {
    RebaseOp.Pick       : "p",
    RebaseOp.Reword     : "r",
    RebaseOp.Edit       : "e",
    RebaseOp.Squash     : "s",
    RebaseOp.Fixup      : "f",
    RebaseOp.Exec       : "x",
    RebaseOp.Break      : "b",
    RebaseOp.Drop       : "d",
    RebaseOp.Label      : "l",
    RebaseOp.Reset      : "t",
    RebaseOp.Merge      : "m",
    RebaseOp.UpdateRef  : "u",
}


RebaseOpColors: dict[RebaseOp, QColor] = {
    RebaseOp.Pick      : colors.olive,
    RebaseOp.Edit      : colors.yellow,
    RebaseOp.Reword    : QColor(0xFFD18DE1),
    RebaseOp.Squash    : colors.blue,
    RebaseOp.Fixup     : colors.teal,
    RebaseOp.FixupC    : colors.teal,
    RebaseOp.Drop      : colors.red,
    RebaseOp.FakeDone  : colors.gray,
    RebaseOp.FakeStop  : colors.black,
    RebaseOp.FakeStart : colors.gray,
    RebaseOp.FakeRewrite: QColor(Qt.GlobalColor.transparent),
}


_PayloadMagicPrefix = "GITFOURCHETTE_REBASE_PAYLOAD="


@dataclasses.dataclass
class RebaseInfo:
    headName: str  # may be "detached HEAD"
    onto: Oid
    origHead: Oid
    stoppedSha: Oid | str  # may be empty string
    msgnum: int
    end: int
    todoSeq: TRebaseSequence
    doneSeq: TRebaseSequence
    rewritten: dict[Oid, Oid]
    todoSet: set[Oid]
    doneSet: set[Oid]
    rewriters: dict[Oid, list[Oid]]

    @property
    def headShorthand(self):
        _dummy, ref = RefPrefix.split(self.headName)
        return ref

    @classmethod
    def parse(cls, gitdir: str) -> RebaseInfo:
        # I attempted to expose the corresponding libgit2 functions in pygit2,
        # but libgit2 refuses to parse info about an ongoing interactive rebase.

        rebaseMerge = Path(gitdir, "rebase-merge")
        if not rebaseMerge.exists():
            raise FileNotFoundError("no .git/rebase-merge directory")

        def readFile(n) -> str:
            try:
                return (rebaseMerge / n).read_text("utf-8").strip()
            except OSError:
                return ""

        text = {
            fileName: readFile(fileName)
            for fileName in ["head-name", "onto", "orig-head", "stopped-sha", "msgnum", "end", "git-rebase-todo", "done", "rewritten-list"]
        }

        def intOrZero(s):  # rebase numbers are 1-indexed, so 0 in case of failure is fine
            try:
                return int(s)
            except ValueError:
                return 0

        headName = text["head-name"]
        onto = Oid(hex=text["onto"])
        origHead = Oid(hex=text["orig-head"])
        stoppedSha = Oid(hex=text["stopped-sha"]) if text["stopped-sha"] else ""
        msgnum = intOrZero(text["msgnum"])
        end = intOrZero(text["end"])
        todoSeq = parseRebaseTodo(text["git-rebase-todo"])
        doneSeq = parseRebaseTodo(text["done"])
        rewritten = parseRebaseRewrittenList(text["rewritten-list"])

        rewriters = collections.defaultdict(list)
        for k, v in rewritten.items():
            rewriters[v].append(k)

        return cls(headName, onto, origHead, stoppedSha, msgnum, end, todoSeq, doneSeq, rewritten,
                   {s.oid for s in todoSeq},
                   {s.oid for s in doneSeq},
                   rewriters)

    def sequenceIndexOf(self, oid: Oid | None) -> tuple[int, bool]:
        if oid is None:
            return -1, False

        if oid == self.onto:
            return 0, True

        if oid in self.doneSet:
            num = next(i for i, entry in enumerate(self.doneSeq) if entry.oid == oid)
            return 1 + num, True

        if oid in self.todoSet:
            num = next(i for i, entry in enumerate(self.todoSeq) if entry.oid == oid)
            return 1 + num + len(self.doneSeq), False

        return -1, False

    def sequenceLine(self, i: int) -> RebaseLine:
        i -= 1
        if i < 0:
            raise IndexError()
        if i < len(self.doneSeq):
            return self.doneSeq[i]
        i -= len(self.doneSeq)
        return self.todoSeq[i]


@dataclasses.dataclass
class RebaseLine:
    EmptyCommitSuffix: ClassVar = " # empty"

    op: RebaseOp
    hexHash: str
    originalComment: str = ""
    payload: str = ""

    verifiedEmpty: bool = dataclasses.field(default=False, compare=False)
    """ True if we've verified that the commit has no changes w/r/t its first
    parent. """

    def displayMessage(self, unmodified: bool = False) -> str:
        if not unmodified and self.op.isEditable() and self.payload:
            return self.payload
        elif self.verifiedEmpty:
            return self.originalComment.removesuffix(RebaseLine.EmptyCommitSuffix)
        else:
            return self.originalComment

    def copy(self) -> RebaseLine:
        return dataclasses.replace(self)

    @property
    def oid(self) -> Oid:
        return Oid(hex=self.hexHash)

    def __str__(self) -> str:
        # Note that git strips comment-only lines from .git/rebase-merge/git-rebase-todo,
        # so our payload must fit on the same line as the opcode.
        if self.op.isEditable() and self.payload:
            payloadBase64 = base64.b64encode(self.payload.encode("utf-8"))
            comment = "#" + _PayloadMagicPrefix + payloadBase64.decode("ascii")
        else:
            comment = "# " + self.originalComment

        return f"{self.op} {self.hexHash} {comment}"


TRebaseSequence = list[RebaseLine]


@dataclasses.dataclass
class RebasePlan:
    sequence: TRebaseSequence
    headName: str
    origHead: Oid
    onto: Oid

    def serializeSequence(self) -> str:
        return "\n".join(str(line) for line in self.sequence)

    @property
    def headShorthand(self) -> str:
        return RefPrefix.split(self.headName)[1]


def parseRebaseTodo(text: str) -> TRebaseSequence:
    CommentMarker = "#"
    sequence: TRebaseSequence = []
    for line in text.splitlines():
        line = line.strip()

        if not line or line.startswith(CommentMarker):
            continue

        if _todoNoopPattern.match(line):
            continue

        match = _todoLinePattern.match(line)
        if match is None:
            raise NotImplementedError(f"unsupported todo line {line!r}")
        commandName, hexHash, comment = match.groups()

        if comment.startswith(_PayloadMagicPrefix):
            payloadBase64 = comment.removeprefix(_PayloadMagicPrefix)
            editedMessage = base64.b64decode(payloadBase64).decode("utf-8")
        else:
            editedMessage = ""

        item = RebaseLine(RebaseOp(commandName), hexHash, comment, editedMessage)
        sequence.append(item)
    return sequence


def parseRebaseRewrittenList(text: str) -> dict[Oid, Oid]:
    rewritten = {}
    for line in text.splitlines():
        match = _rewrittenListPattern.match(line)
        if not match:
            continue
        h1 = Oid(hex=match.group(1))
        h2 = Oid(hex=match.group(2))
        rewritten[h1] = h2
    return rewritten


_opsRegex = "|".join(op for op in RebaseOp if not op.startswith("_"))
_todoNoopPattern = re.compile(r"^noop\b")
_todoLinePattern = re.compile(rf"^({_opsRegex})\s+([0-9a-f]+)(?:\s*#\s*|\s+)(.+)$")
#                                                             ^^^^^^^^^
# Note: At some point between git 2.43 and 2.54, git rebase started adding
# comment marks in todo lines. We're treating those as optional for now.
_rewrittenListPattern = re.compile(r"^([0-9a-f]+)\s+([0-9a-f]+)")
