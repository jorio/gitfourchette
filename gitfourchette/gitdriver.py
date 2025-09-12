# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import dataclasses
import html
import io
import logging
import re
import shlex
import signal
from enum import StrEnum
from os import stat_result
from pathlib import Path

from pygit2.enums import FileMode

from gitfourchette import settings
from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.nav import NavContext
from gitfourchette.porcelain import version_to_tuple, Oid
from gitfourchette.qt import *

logger = logging.getLogger(__name__)


HASH_40X0 = "0" * 40
HASH_40XF = "f" * 40


def argsIf(condition: bool, *args: str) -> tuple[str, ...]:
    if condition:
        return args
    else:
        return ()


class VanillaFetchStatusFlag(StrEnum):
    FastForward = " "
    ForcedUpdate = "+"
    PrunedRef = "-"
    TagUpdate = "t"
    NewRef = "*"
    Rejected = "!"
    UpToDate = "="


@dataclasses.dataclass
class FatDelta:
    conflictUs: str = ""
    conflictThem: str = ""
    statusStaged: str = ""
    statusUnstaged: str = ""
    statusSubmodule: str = ""
    statusCommit: str = ""
    modeHead: FileMode = FileMode.UNREADABLE
    modeIndex: FileMode = FileMode.UNREADABLE
    modeConflictStages: tuple[FileMode, FileMode, FileMode] = (FileMode.UNREADABLE, FileMode.UNREADABLE, FileMode.UNREADABLE)
    modeWorktree: FileMode = FileMode.UNREADABLE
    modeSrc: FileMode = FileMode.UNREADABLE
    modeDst: FileMode = FileMode.UNREADABLE
    hexHashHead: str = ""
    hexHashIndex: str = ""
    hexHashWorktree: str = ""
    hexHashConflictStages: tuple[str, str, str] = ("", "", "")
    hexHashSrc: str = ""
    hexHashDst: str = ""
    similarity: int = 0
    path: str = ""
    origPath: str = ""
    stat: stat_result | None = None

    def __post_init__(self):
        if self.statusStaged == ".":
            self.statusStaged = ""
        if self.statusUnstaged == ".":
            self.statusUnstaged = ""
        if self.statusSubmodule == "N...":
            self.statusSubmodule = ""

    def isConflict(self) -> bool:
        return bool(self.conflictUs)

    def isSubtreeCommitPatch(self):
        # TODO: Test more specifically?
        return FileMode.COMMIT in (self.modeHead, self.modeWorktree, self.modeIndex,
                                   self.modeSrc, self.modeDst)

    def isUntracked(self):
        return self.statusUnstaged == "?"

    def distillOldNew(self, context: NavContext) -> ABDelta:
        if context == NavContext.UNSTAGED:
            status = self.statusUnstaged
            oldMode, newMode = self.modeIndex, self.modeWorktree
            oldHash, newHash = self.hexHashIndex, self.hexHashWorktree
            if not newHash:
                logger.warning(f"worktree hash unknown for {self.path}")
                newHash = HASH_40XF
        elif context == NavContext.STAGED:
            status = self.statusStaged
            oldMode, newMode = self.modeHead, self.modeIndex
            oldHash, newHash = self.hexHashHead, self.hexHashIndex
        else:
            status = self.statusCommit
            oldMode, newMode = self.modeSrc, self.modeDst
            oldHash, newHash = self.hexHashSrc, self.hexHashDst

        oldHash = oldHash or HASH_40X0
        newHash = newHash or HASH_40X0
        old = ABDeltaFile(self.origPath or self.path, oldHash, oldMode)
        new = ABDeltaFile(self.path, newHash, newMode)
        return ABDelta(status=status, old=old, new=new, similarity=self.similarity)

    @staticmethod
    def isNullHash(hexHash: str) -> bool:
        return all(c == "0" for c in hexHash)


@dataclasses.dataclass
class ABDeltaFile:
    path: str = ""
    id: str = ""
    mode: FileMode = FileMode.UNREADABLE

    def isId0(self):
        return all(c == "0" for c in self.id)


@dataclasses.dataclass
class ABDelta:
    status: str = ""
    old: ABDeltaFile = dataclasses.field(default_factory=ABDeltaFile)
    new: ABDeltaFile = dataclasses.field(default_factory=ABDeltaFile)
    similarity: int = 0


# 1 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <path>
# 2 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <R|C><score> <path><sep><origPath>
# u <XY> <sub> <m1> <m2> <m3> <mW> <h1> <h2> <h3> <path>
_gitStatusPatterns = {
    "1": re.compile(r"1 (.)(.) (....) (\d+) (\d+) (\d+) ([\da-f]+) ([\da-f]+) ([^\x00]*)\x00"),
    "2": re.compile(r"2 (.)(.) (....) (\d+) (\d+) (\d+) ([\da-f]+) ([\da-f]+) [RC](\d+) ([^\x00]*)\x00([^\x00]*)\x00"),
    "u": re.compile(r"u (.)(.) (....) (\d+) (\d+) (\d+) (\d+) ([\da-f]+) ([\da-f]+) ([\da-f]+) ([^\x00]*)\x00"),
    "?": re.compile(r"\? ([^\x00]*)\x00"),
    "!": re.compile(r"! ([^\x00]*)\x00"),
}

_gitShowPattern = re.compile(r":(\d+) (\d+) ([\da-f]+) ([\da-f]+) (.)(\d*)\x00([^\x00]*)\x00")


class GitDriver(QProcess):
    _commandStem = ["/usr/bin/git"]

    _cachedGitVersionValid = False
    _cachedGitVersion = ""
    _cachedGitVersionTuple = (0,)

    progressMessage = Signal(str)
    progressFraction = Signal(int, int)

    @classmethod
    def runSync(
            cls,
            *args: str,
            directory: str = "",
            strict: bool = False
    ):
        return ToolCommands.runSync(*cls._commandStem, *args, directory=directory, strict=strict)

    @classmethod
    def setGitPath(cls, gitPath: str):
        cls._commandStem = shlex.split(gitPath, posix=True)
        cls._cachedGitVersionValid = False

    @classmethod
    def _cacheGitVersion(cls):
        if cls._cachedGitVersionValid:
            return

        text = cls.runSync("version")
        text = text.removeprefix("git version").strip()

        try:
            numberStr = text.split(maxsplit=1)[0]
        except IndexError:
            numberStr = "0"

        cls._cachedGitVersionValid = True
        cls._cachedGitVersion = text
        cls._cachedGitVersionTuple = version_to_tuple(numberStr)

    @classmethod
    def gitVersion(cls) -> str:
        cls._cacheGitVersion()
        return cls._cachedGitVersion

    @classmethod
    def gitVersionTuple(cls) -> tuple[int, ...]:
        cls._cacheGitVersion()
        return cls._cachedGitVersionTuple

    @classmethod
    def supportsFetchPorcelain(cls) -> bool:
        # fetch --porcelain is only available since git 2.41 (June 2023)
        # Ubuntu 22.04 LTS ships with git 2.34.1.
        # macOS 15 ships with git 2.39.5.
        return cls.gitVersionTuple() >= (2, 41)

    @classmethod
    def parseTable(cls, pattern: str, stdout: str, linesep="\n", strict=True) -> list:
        table = []

        stdout = stdout.removesuffix(linesep)

        for line in stdout.split(linesep):
            match = re.match(pattern, line)

            if match is None:
                if strict:
                    raise ValueError("table line does not match pattern: " + line)
                else:
                    continue

            table.append(match.groups())

        return table

    def __init__(self, *args: str, parent: QObject | None = None):
        super().__init__(parent)

        self.setObjectName("GitDriver")

        tokens = GitDriver._commandStem + list(args)
        self.setProgram(tokens[0])
        self.setArguments(tokens[1:])

        self.readyReadStandardError.connect(self._onReadyReadStandardError)
        self._stderrScrollback = io.BytesIO()
        self._stdout = None

    def stdoutTable(self, pattern: str, linesep="\n", strict=True) -> list:
        stdout = self.stdoutScrollback()
        return self.parseTable(pattern, stdout, linesep, strict)

    def stdoutTableNumstatZ(self, strict=True) -> list[tuple[str, str, str]]:
        pattern = r"^(-|\d+)\t(-|\d+)\t(.+)$"
        stdout = self.stdoutScrollback()
        return self.parseTable(pattern, stdout, "\0", strict)

    @classmethod
    def parseProgress(cls, stderr: bytes | str) -> tuple[str, int, int]:
        text = ""
        num = -1
        denom = -1

        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        lines = stderr.splitlines()

        if lines:
            # Report last line
            text = lines[-1]

            # Look for a fraction, e.g. "(50/1000)"
            for line in lines:
                fractionMatch = re.search(r"\((\d+)/(\d+)\)", line)
                if fractionMatch:
                    num = int(fractionMatch.group(1))
                    denom = int(fractionMatch.group(2))

        return text, num, denom

    @classmethod
    def reformatHintText(cls, stderr: str):
        previousTag = ""
        parts = []

        for stderrLine in stderr.splitlines():
            try:
                tag, text = stderrLine.split(":", 1)
                tag = html.escape(tag)
                text = html.escape(text)
            except ValueError:
                tag, text = "", stderrLine

            if tag != previousTag:
                if parts:
                    parts.append("<br>")
                if tag:
                    parts.append(f"<b>{tag}:</b>")

            parts.append(text)
            previousTag = tag

        return "".join(parts)

    def _onReadyReadStandardError(self):
        raw = self.readAllStandardError().data()
        self._stderrScrollback.write(raw)

        text, num, denom = GitDriver.parseProgress(raw)
        if text:
            self.progressMessage.emit(text)
        if num >= 0 and denom >= 0:
            self.progressFraction.emit(num, denom)

    def stderrScrollback(self) -> str:
        return '\n'.join(
            line.rstrip().decode("utf-8", errors="replace")
            for line in self._stderrScrollback.getvalue().splitlines(keepends=True)
            if not line.endswith(b"\r")
        )

    def stdoutScrollback(self) -> str:
        if self._stdout is None:
            self._stdout = self.readAllStandardOutput().data().decode("utf-8", errors="replace")
        return self._stdout

    def readPostCommitInfo(self) -> tuple[str, str]:
        # [master 123abc]
        # [master (root-commit) 123abc]
        # [detached HEAD 123abc]
        stdout = self.stdoutScrollback()
        match = re.match(r"^\[(.+)\s+([\da-f]+)]", stdout, re.I)
        if not match:
            raise ValueError("couldn't parse post-commit stdout: " + stdout.splitlines()[0])
        branchName = match.group(1)
        commitHash = match.group(2)
        return branchName, commitHash

    def readFetchPorcelainUpdatedRefs(self) -> dict[str, tuple[str, Oid, Oid]]:
        """
        Read a table of updated refs from the output of "git fetch --porcelain".
        Requires git 2.41.
        """
        assert self.supportsFetchPorcelain(), "did you forget to gate this call with GitDriver.supportsFetchPorcelain()?"

        table = self.stdoutTable(r"^(.) ([\da-f]+) ([\da-f]+) (.+)$", strict=False)

        return {
            localRef: (flag, Oid(hex=oldHex), Oid(hex=newHex))
            for flag, oldHex, newHex, localRef in table
        }

    def readStatusPorcelainV2Z(self) -> list[FatDelta]:
        stdout = self.stdoutScrollback()
        pos = 0
        limit = len(stdout)
        deltas = []

        while pos < limit:
            ident = stdout[pos]
            try:
                patt = _gitStatusPatterns[ident]
            except KeyError:
                continue

            match = patt.match(stdout, pos)
            pos = match.end()

            if ident == "1":
                # Ordinary changed entries
                x, y, sub, mh, mi, mw, hh, hi, path = match.groups()
                delta = FatDelta(
                    statusStaged=x,
                    statusUnstaged=y,
                    statusSubmodule=sub,
                    modeHead=FileMode(int(mh, 8)),
                    modeIndex=FileMode(int(mi, 8)),
                    modeWorktree=FileMode(int(mw, 8)),
                    hexHashHead=hh,
                    hexHashIndex=hi,
                    path=path)
            elif ident == "2":
                # Renamed or copied entries
                x, y, sub, mh, mi, mw, hh, hi, score, path, origPath = match.groups()
                delta = FatDelta(
                    statusStaged=x,
                    statusUnstaged=y,
                    statusSubmodule=sub,
                    modeHead=FileMode(int(mh, 8)),
                    modeIndex=FileMode(int(mi, 8)),
                    modeWorktree=FileMode(int(mw, 8)),
                    hexHashHead=hh,
                    hexHashIndex=hi,
                    similarity=int(score),
                    path=path,
                    origPath=origPath)
            elif ident == "u":
                # Unmerged entries
                x, y, sub, m1, m2, m3, mw, h1, h2, h3, path = match.groups()
                delta = FatDelta(
                    conflictUs=x,
                    conflictThem=y,
                    statusUnstaged="U",  # Fake an 'unmerged' status in the unstaged box
                    statusSubmodule=sub,
                    modeWorktree=FileMode(int(mw, 8)),
                    modeConflictStages=(FileMode(int(m1, 8)), FileMode(int(m2, 8)), FileMode(int(m3, 8))),
                    path=path)
            else:
                # ? Untracked items
                # ! Ignored items
                # TODO: Should we hash the file? Note: git doesn't seem to hash unstaged 'M' files until they're staged
                path, = match.groups()
                if path.endswith("/"):
                    path = path.removesuffix("/")
                    mode = FileMode.TREE
                else:
                    mode = FileMode.UNREADABLE  # unknown, actually, but that's the next best thing
                delta = FatDelta(
                    statusUnstaged=ident,
                    modeWorktree=mode,
                    path=path)

            # Get stat if it's unstaged
            if delta.statusUnstaged:
                try:
                    delta.stat = Path(self.workingDirectory(), path).lstat()
                    delta.modeWorktree = FileMode(delta.stat.st_mode)
                except OSError:
                    pass

            deltas.append(delta)

        return deltas

    def readShowRawZ(self) -> list[FatDelta]:
        stdout = self.stdoutScrollback()
        pos = 0
        limit = len(stdout)
        deltas = []

        while pos < limit:
            match = _gitShowPattern.match(stdout, pos)
            pos = match.end()

            ms, md, hs, hd, status, score, path1 = match.groups()

            # WARNING! In case of a rename, "git show" outputs the old/new
            # paths in the reverse order from "git status --porcelain=v2"!
            # git show: ... old, new
            # git status: ... new, old
            if status in "RC":
                pos2 = stdout.find("\0", pos)
                path2 = stdout[pos:pos2]
                pos = pos2 + 1
                origPath, path = path1, path2
            else:
                origPath, path = "", path1

            deltas.append(FatDelta(
                modeSrc=FileMode(int(ms, 8)),
                modeDst=FileMode(int(md, 8)),
                hexHashSrc=hs,
                hexHashDst=hd,
                statusCommit=status,
                similarity=int(score) if score else 0,
                path=path,
                origPath=origPath))

        return deltas

    def formatExitCode(self) -> str:
        code = self.exitCode()
        try:
            s = signal.Signals(code)
            return f"{code} ({s.name})"
        except ValueError:
            return f"{code}"

    def formatCommandLine(self):
        return shlex.join([self.program()] + self.arguments())

    def htmlErrorText(self, subtitle: str = "", reformatHintText=False) -> str:
        from gitfourchette.localization import _
        from gitfourchette.toolbox import escape

        stderr = self.stderrScrollback().strip()
        if reformatHintText:
            stderr = self.reformatHintText(stderr)
        elif stderr:
            stderr = escape(stderr)

        if subtitle:
            subtitle = f"<p>{subtitle}</p>"

        exitText = self.formatExitCode()
        if self.exitCode() == 0:
            exitText = f"<b><add>{exitText}</b></add>"
        else:
            exitText = f"<b><del>{exitText}</b></del>"

        return "".join([
            "<html style='white-space: pre-wrap;'>",
            settings.prefs.addDelColorsStyleTag(),
            "<p>",
            _("Git command exited with code {0}.", exitText),
            "</p>",
            subtitle,
            "<small>",
            stderr,
            "</html>"
        ])
