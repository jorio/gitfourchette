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
from gitfourchette.porcelain import version_to_tuple, id7, Blob, Oid, Repo
from gitfourchette.qt import *
from gitfourchette.toolbox import benchmark

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
    repo: Repo
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
    """ Kept in ABDelta for comparison purposes when refreshing the repo.
    This lets us figure out if an unstaged file was modified since the FatDelta
    was created. """

    _abDeltaCache: dict[NavContext, ABDelta] = dataclasses.field(default_factory=dict, compare=False)

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
        try:
            return self._abDeltaCache[context]
        except KeyError:
            pass

        oldSize = -1
        newSize = -1

        if context == NavContext.UNSTAGED:
            status = self.statusUnstaged
            oldMode, newMode = self.modeIndex, self.modeWorktree
            oldHash, newHash = self.hexHashIndex, self.hexHashWorktree
            oldSource, newSource = NavContext.STAGED, NavContext.UNSTAGED
            if not newHash:
                logger.warning(f"worktree hash unknown for {self.path}")
                if status == "D":
                    newHash = HASH_40X0
                else:
                    newHash = HASH_40XF  # "unknown" non-zero hash
            # Even though we may have a filesystem stat for the unstaged file,
            # don't copy stat.st_size to the ABDelta because the size on disk
            # may differ from the size obtained after applying the filters
            # (e.g. CRLF).
        elif context == NavContext.STAGED:
            status = self.statusStaged
            oldMode, newMode = self.modeHead, self.modeIndex
            oldHash, newHash = self.hexHashHead, self.hexHashIndex
            oldSource, newSource = NavContext.COMMITTED, NavContext.STAGED
        else:
            status = self.statusCommit
            oldMode, newMode = self.modeSrc, self.modeDst
            oldHash, newHash = self.hexHashSrc, self.hexHashDst
            oldSource, newSource = NavContext.COMMITTED, NavContext.COMMITTED

        oldHash = oldHash or HASH_40X0
        newHash = newHash or HASH_40X0

        oldSize = 0 if oldHash == HASH_40X0 else self.repo.peel_blob(oldHash).size

        if newSize < 0 and newHash != HASH_40XF:
            newSize = 0 if newHash == HASH_40X0 else self.repo.peel_blob(newHash).size

        old = ABDeltaFile(self.origPath or self.path, oldHash, oldMode, oldSize, oldSource)
        new = ABDeltaFile(self.path, newHash, newMode, newSize, newSource)
        abDelta = ABDelta(status=status, old=old, new=new, similarity=self.similarity)
        self._abDeltaCache[context] = abDelta
        return abDelta

    @staticmethod
    def isNullHash(hexHash: str) -> bool:
        return all(c == "0" for c in hexHash)


@dataclasses.dataclass
class ABDeltaFile:
    path: str = ""
    id: str = HASH_40X0
    mode: FileMode = FileMode.UNREADABLE
    size: int = -1
    source: NavContext = NavContext.EMPTY

    _data: bytes = b""
    _dataValid: bool = False

    def isId0(self) -> bool:
        return self.id == HASH_40X0

    def isIdValid(self) -> bool:
        return self.id != HASH_40XF

    def isSizeValid(self) -> bool:
        return self.size >= 0

    @benchmark
    def read(self, repo: Repo) -> bytes:
        if self._dataValid:
            pass
        elif self.isId0():
            self._dataValid = True
            assert self.size == 0
        else:
            blob = self._readBlob(repo)
            assert not self.isIdValid() or blob.id == self.id  # TODO: Unsure about this assert - what if the file was modified between the calls to __init__ and read?
            assert not self.isSizeValid() or blob.size == self.size
            self.size = blob.size
            self._data = blob.data
            self._dataValid = True
            assert self.isSizeValid()

        return self._data

    def _readBlob(self, repo: Repo) -> Blob:
        if self.isIdValid():
            try:
                return repo.peel_blob(self.id)
            except KeyError:
                # Blob isn't in the database.
                pass

        # Typically, if a blob id isn't in the database, it's an unstaged file.
        # Read it from the workdir.
        assert self.source == NavContext.UNSTAGED, f"can't read blob from workdir for source {self.source}"
        blobId = repo.create_blob_fromworkdir(self.path)
        return repo.peel_blob(blobId)

    def __repr__(self) -> str:
        return f"({self.path},{id7(self.id)},{self.mode:o},{self.size})"


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

    def readStatusPorcelainV2Z(self, repo: Repo) -> list[FatDelta]:
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
                    repo=repo,
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
                    repo=repo,
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
                    repo=repo,
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
                    repo=repo,
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

    def readShowRawZ(self, repo: Repo) -> list[FatDelta]:
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
                repo=repo,
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
