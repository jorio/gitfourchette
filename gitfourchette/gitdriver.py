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
import os
import re
import shlex
import signal
from enum import StrEnum
from pathlib import Path

from pygit2.enums import FileMode

from gitfourchette import settings
from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.nav import NavContext
from gitfourchette.porcelain import version_to_tuple, id7, Oid, Repo
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


class ABDeltaParser:
    @classmethod
    def parseMode(cls, octal: str) -> FileMode:
        return FileMode(int(octal, 8))

    @classmethod
    def parseGitStatus(cls, ident: str, *tokens: str) -> tuple[ABDelta | None, ABDelta | None]:
        if ident == "1":
            # Ordinary changed entries
            tokens = list(tokens)
            path = tokens.pop()
            tokens.extend(("0", path, path))
            return cls._parseStatus2(*tokens)
        elif ident == "2":
            # Renamed or copied entries
            return cls._parseStatus2(*tokens)
        elif ident == "u":
            # Unmerged entries (conflict)
            return cls._parseStatusConflict(*tokens)
        elif ident in "?!":
            # ? - Untracked items
            # ! - Ignored items
            return cls._parseStatusUntracked(ident, *tokens)
        else:
            raise ValueError(f"unknown ident: {ident}")

    @classmethod
    def _parseStatus2(cls, x, y, sub, mh, mi, mw, hh, hi, score, newPath, origPath):
        fileHead = ABDeltaFile(
            path=origPath,
            id=hh,
            mode=cls.parseMode(mh),
            source=NavContext.COMMITTED)

        fileIndex = ABDeltaFile(
            path=newPath,
            id=hi,
            mode=cls.parseMode(mi),
            source=NavContext.STAGED)

        fileWorktree = ABDeltaFile(
            path=newPath,
            id=HASH_40X0 if y == "D" else HASH_40XF,
            mode=cls.parseMode(mw),
            source=NavContext.UNSTAGED)

        xDelta, yDelta = None, None

        if x != ".":  # STAGED
            xDelta = ABDelta(status=x, old=fileHead, new=fileIndex, similarity=int(score))

        if y != ".":  # UNSTAGED
            yDelta = ABDelta(status=y, old=fileIndex, new=fileWorktree, submoduleStatus=sub)

        return xDelta, yDelta

    @classmethod
    def _parseStatusConflict(cls, xy, sub, m1, m2, m3, mw, h1, h2, h3, path):
        indexFile = ABDeltaFile(path=path, source=NavContext.STAGED)

        worktreeFile = ABDeltaFile(path=path, id=HASH_40XF,
                                   mode=cls.parseMode(mw),
                                   source=NavContext.UNSTAGED)

        sides = ConflictSides(xy)
        stage1 = VanillaConflictStage(cls.parseMode(m1), h1, path)
        stage2 = VanillaConflictStage(cls.parseMode(m2), h2, path)
        stage3 = VanillaConflictStage(cls.parseMode(m3), h3, path)
        conflict = VanillaConflict(sides, stage1, stage2, stage3, path)

        yDelta = ABDelta(status="U", old=indexFile, new=worktreeFile,
                         conflict=conflict, submoduleStatus=sub)
        return None, yDelta

    @classmethod
    def _parseStatusUntracked(cls, ident: str, path: str):
        if path.endswith("/"):
            path = path.removesuffix("/")
            mode = FileMode.TREE
        else:
            mode = FileMode.UNREADABLE  # a more precise mode will be filled in from the file's stats

        # "Old" state = empty file (not indexed yet)
        indexFile = ABDeltaFile(path=path, id=HASH_40X0, mode=FileMode.UNREADABLE, source=NavContext.STAGED)

        worktreeFile = ABDeltaFile(path=path, id=HASH_40XF, mode=mode, source=NavContext.UNSTAGED)

        yDelta = ABDelta(status=ident, old=indexFile, new=worktreeFile)
        return None, yDelta

    @classmethod
    def parseGitShow(cls, ms, md, hs, hd, status, score, path1, path2) -> ABDelta:
        fileSrc = ABDeltaFile(
            path=path1,
            id=hs,
            mode=cls.parseMode(ms),
            source=NavContext.COMMITTED)

        fileDst = ABDeltaFile(
            path=path2,
            id=hd,
            mode=cls.parseMode(md),
            source=NavContext.COMMITTED)

        return ABDelta(status, fileSrc, fileDst, similarity=int(score) if score else 0)


@dataclasses.dataclass
class ABDeltaFile:
    path: str = ""
    id: str = HASH_40X0
    mode: FileMode = FileMode.UNREADABLE
    source: NavContext = NavContext.EMPTY

    diskStat: tuple[int, int] = (-1, -1)
    """
    Filled in for unstaged files only. Allows quick comparison of ABDeltaFiles
    taken at two points in time for the same unstaged file. Internally, this is
    a snapshot of a subset of the file's status on disk (st_mtime_ns, st_size).
    """

    _data: bytes | None = dataclasses.field(default=None, compare=False)
    """
    Cached file contents. Not used in object comparisons.
    None means that the file hasn't been cached yet (isDataValid() == False).
    """

    def __post_init__(self):
        if self.isId0():
            self._data = b""

    def isId0(self) -> bool:
        return self.id == HASH_40X0

    def isIdValid(self) -> bool:
        return self.id != HASH_40XF

    def isDataValid(self) -> bool:
        return self._data is not None

    def isBlob(self) -> bool:
        return self.mode & FileMode.BLOB == FileMode.BLOB

    @benchmark
    def read(self, repo: Repo) -> bytes:
        if self._data is None:
            try:
                if not self.isIdValid():  # unknown hash (FFFFFFF...)
                    raise KeyError()
                self._data = repo.peel_blob(self.id).data
            except KeyError:
                # Blob ID isn't in the database. Typically, that means
                # it's an unstaged file. Read it from the workdir.
                assert self.source.isDirty(), f"expecting untracked/unstaged, got {self.source}"
                self._data = repo.apply_filters_to_workdir(self.path)

        assert self.isDataValid(), "data should be valid here"
        return self._data

    def dump(self, repo: Repo, directory: str, namePrefix: str) -> str:
        data = self.read(repo)
        relPathObj = Path(self.path)
        pathObj = Path(directory, f"{namePrefix}{relPathObj.name}")
        pathObj.write_bytes(data)

        """
        # Make it read-only
        mode = pathObj.stat().st_mode
        pathObj.chmod(mode & ~0o222)  # ~(write, write, write)
        """

        return str(pathObj)

    def stat(self, repo: Repo) -> tuple[int, int]:
        diskStat = (-1, -1)
        absPath = repo.in_workdir(self.path)
        try:
            stat = os.lstat(absPath)
            diskStat = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            pass
        return diskStat

    def sizeBallpark(self, repo: Repo) -> int:
        if self.isId0():
            return 0
        if self.isIdValid():
            try:
                return repo.peel_blob(self.id).size
            except KeyError:
                pass
        _, size = self.stat(repo)
        return size

    def __repr__(self) -> str:
        return f"({self.path},{id7(self.id)},{self.mode:o})"


@dataclasses.dataclass
class ABDelta:
    status: str = ""
    old: ABDeltaFile = dataclasses.field(default_factory=ABDeltaFile)
    new: ABDeltaFile = dataclasses.field(default_factory=ABDeltaFile)
    similarity: int = 0
    submoduleStatus: str = ""  # Only in UNSTAGED contexts
    conflict: VanillaConflict | None = None  # Only in UNSTAGED contexts

    @property
    def context(self) -> NavContext:
        return self.new.source

    @property
    def submoduleWorkdirDirty(self) -> bool:
        sub = self.submoduleStatus
        return "M" in sub or "U" in sub

    def isSubtreeCommitPatch(self) -> bool:
        return FileMode.COMMIT in (self.old.mode, self.new.mode)


@dataclasses.dataclass
class VanillaConflictStage:
    mode: FileMode
    id: str
    path: str  # for compatibility with existing code - TODO: Remove or keep?

    def __bool__(self):
        return not self.isId0()

    def isId0(self) -> bool:
        return self.id == HASH_40X0


class ConflictSides(StrEnum):
    BothDeleted   = "DD"
    AddedByUs     = "AU"
    DeletedByThem = "UD"
    AddedByThem   = "UA"
    DeletedByUs   = "DU"
    BothAdded     = "AA"
    BothModified  = "UU"


@dataclasses.dataclass
class VanillaConflict:
    sides: ConflictSides
    ancestor: VanillaConflictStage
    ours: VanillaConflictStage
    theirs: VanillaConflictStage
    path: str


# 1 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <path>
# 2 <XY> <sub> <mH> <mI> <mW> <hH> <hI> <R|C><score> <path><sep><origPath>
# u <XY> <sub> <m1> <m2> <m3> <mW> <h1> <h2> <h3> <path>
_gitStatusPatterns = {
    "1": re.compile(r"1 (.)(.) (....) (\d+) (\d+) (\d+) ([\da-f]+) ([\da-f]+) ([^\x00]*)\x00"),
    "2": re.compile(r"2 (.)(.) (....) (\d+) (\d+) (\d+) ([\da-f]+) ([\da-f]+) [RC](\d+) ([^\x00]*)\x00([^\x00]*)\x00"),
    "u": re.compile(r"u (..) (....) (\d+) (\d+) (\d+) (\d+) ([\da-f]+) ([\da-f]+) ([\da-f]+) ([^\x00]*)\x00"),
    "?": re.compile(r"\? ([^\x00]*)\x00"),
    "!": re.compile(r"! ([^\x00]*)\x00"),
}

_gitShowPattern = re.compile(r":(\d+) (\d+) ([\da-f]+) ([\da-f]+) (.)(\d*)\x00([^\x00]*)\x00")

# The order of this table is SIGNIFICANT!
_gitSimplifiedModes = [
    FileMode.LINK,              # 0o120000
    FileMode.TREE,              # 0o040000
    FileMode.BLOB_EXECUTABLE,   # 0o100755
    FileMode.BLOB,              # 0o100644
]


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
    def _cacheGitVersion(cls, rawVersionText: str = ""):
        if cls._cachedGitVersionValid:
            return

        if not rawVersionText:
            rawVersionText = cls.runSync("version")
        text = rawVersionText.removeprefix("git version").strip()

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

    def readStatusPorcelainV2Z(self) -> tuple[int, list[ABDelta], list[ABDelta]]:
        stdout = self.stdoutScrollback()
        pos = 0
        limit = len(stdout)
        stagedDeltas = []
        unstagedDeltas = []
        numEntries = 0

        while pos < limit:
            ident = stdout[pos]
            try:
                pattern = _gitStatusPatterns[ident]
            except KeyError:
                logger.warning(f"unknown git status ident '{ident}'")
                continue

            match = pattern.match(stdout, pos)
            pos = match.end()
            numEntries += 1

            staged, unstaged = ABDeltaParser.parseGitStatus(ident, *match.groups())

            # Fill in file mode for untracked/ignored files.
            if unstaged and unstaged.status in "?!" and unstaged.new.mode == FileMode.UNREADABLE:
                try:
                    stat = Path(self.workingDirectory(), unstaged.new.path).lstat()
                    unstaged.new.mode = self.distillFileMode(stat.st_mode)
                except OSError:
                    pass

            if staged:
                stagedDeltas.append(staged)
            if unstaged:
                unstagedDeltas.append(unstaged)

        return numEntries, stagedDeltas, unstagedDeltas

    @staticmethod
    def distillFileMode(realMode: int) -> FileMode:
        """
        Git uses simplified file modes that may not accurately reflect a file's
        actual mode in the filesystem (e.g., a symlink's st_mode might be
        0o120777, which to git is just 0o120000). Use this function to simplify
        a real file mode to a legal FileMode value for git.
        """
        for m in _gitSimplifiedModes:
            if m == (realMode & m):
                return m

        raise ValueError(f"cannot map to git FileMode: 0o{realMode:o}")

    def readShowRawZ(self) -> list[ABDelta]:
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
            else:
                path2 = path1

            delta = ABDeltaParser.parseGitShow(ms, md, hs, hd, status, score, path1, path2)
            deltas.append(delta)

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
