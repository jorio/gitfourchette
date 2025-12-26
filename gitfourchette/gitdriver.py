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
    statusStaged: str = ""
    statusUnstaged: str = ""
    statusSubmodule: str = ""  # only valid for uncommitted changes in workdir
    statusCommit: str = ""
    modeHead: FileMode = FileMode.UNREADABLE
    modeIndex: FileMode = FileMode.UNREADABLE
    modeWorktree: FileMode = FileMode.UNREADABLE
    modeSrc: FileMode = FileMode.UNREADABLE
    modeDst: FileMode = FileMode.UNREADABLE
    hexHashHead: str = ""
    hexHashIndex: str = ""
    hexHashWorktree: str = ""
    hexHashSrc: str = ""
    hexHashDst: str = ""
    similarity: int = 0
    path: str = ""
    origPath: str = ""
    conflict: VanillaConflict | None = None

    def __post_init__(self):
        if self.statusStaged == ".":
            self.statusStaged = ""

        if self.statusUnstaged == ".":
            self.statusUnstaged = ""

        if self.statusSubmodule == "N...":
            self.statusSubmodule = ""
        else:
            assert not self.statusSubmodule or self.statusSubmodule.startswith("S")

    def distillOldNew(self, context: NavContext) -> ABDelta:
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

        oldIsBlob = oldMode & FileMode.BLOB == FileMode.BLOB
        newIsBlob = newMode & FileMode.BLOB == FileMode.BLOB

        if oldHash == HASH_40X0:
            oldSize = 0
        elif oldIsBlob:
            oldSize = self.repo.peel_blob(oldHash).size

        if newHash == HASH_40X0:
            newSize = 0
        elif newIsBlob and newSize < 0 and newHash != HASH_40XF:
            newSize = self.repo.peel_blob(newHash).size

        ss = self.statusSubmodule
        submoduleWorkdirDirty = "M" in ss or "U" in ss

        old = ABDeltaFile(self.origPath or self.path, oldHash, oldMode, oldSize, oldSource)
        new = ABDeltaFile(self.path, newHash, newMode, newSize, newSource)

        return ABDelta(
            status=status,
            old=old,
            new=new,
            similarity=self.similarity,
            submoduleWorkdirDirty=submoduleWorkdirDirty,
            conflict=self.conflict if context == NavContext.UNSTAGED else None,
        )


@dataclasses.dataclass
class ABDeltaFile:
    path: str = ""
    id: str = HASH_40X0
    mode: FileMode = FileMode.UNREADABLE
    size: int = -1
    source: NavContext = NavContext.EMPTY

    diskStat: tuple[int, int] = (-1, -1)
    """
    Filled in for unstaged files only. Allows quick comparison of ABDeltaFiles
    taken at two points in time for the same unstaged file. Internally, this is
    a snapshot of a subset of the file's status on disk (st_mtime_ns, st_size).
    """

    _cachedBlob: bytes | None = dataclasses.field(default=None, compare=False)
    """
    Cached file contents. Not used in object comparisons.
    None means that the file hasn't been cached yet (isDataValid() == False).
    """

    def isId0(self) -> bool:
        return self.id == HASH_40X0

    def isIdValid(self) -> bool:
        return self.id != HASH_40XF

    def isSizeValid(self) -> bool:
        return self.size >= 0

    def isDataValid(self) -> bool:
        return self._cachedBlob is not None

    @benchmark
    def read(self, repo: Repo) -> bytes:
        if self._cachedBlob is not None:
            pass
        elif self.isId0():
            self._cachedBlob = b""
            assert self.size == 0
        else:
            blob = self._readBlob(repo)
            assert not self.isIdValid() or blob.id == self.id  # TODO: Unsure about this assert - what if the file was modified between the calls to __init__ and read?
            assert not self.isSizeValid() or blob.size == self.size
            self.id = str(blob.id)
            self.size = blob.size
            self._cachedBlob = blob.data

        assert self.isSizeValid(), "size should be valid here"
        assert self.isIdValid(), "id should be valid here"
        assert self.isDataValid(), "data should be valid here"

        return self._cachedBlob

    def _readBlob(self, repo: Repo) -> Blob:
        if self.isIdValid():  # i.e. it's not the unknown hash (FFFFFFF)
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

    def __repr__(self) -> str:
        return f"({self.path},{id7(self.id)},{self.mode:o},{self.size})"


@dataclasses.dataclass
class ABDelta:
    status: str = ""
    old: ABDeltaFile = dataclasses.field(default_factory=ABDeltaFile)
    new: ABDeltaFile = dataclasses.field(default_factory=ABDeltaFile)
    similarity: int = 0
    submoduleWorkdirDirty: bool = False  # Only in UNSTAGED contexts
    conflict: VanillaConflict | None = None  # Only in UNSTAGED contexts

    @property
    def context(self) -> NavContext:
        return self.new.source

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
                xy, sub, m1, m2, m3, mw, h1, h2, h3, path = match.groups()
                stage1 = VanillaConflictStage(FileMode(int(m1, 8)), h1, path)
                stage2 = VanillaConflictStage(FileMode(int(m2, 8)), h2, path)
                stage3 = VanillaConflictStage(FileMode(int(m3, 8)), h3, path)
                conflict = VanillaConflict(ConflictSides(xy), stage1, stage2, stage3, path)
                delta = FatDelta(
                    repo=repo,
                    statusUnstaged="U",  # Fake an 'unmerged' status in the unstaged box
                    statusSubmodule=sub,
                    modeWorktree=FileMode(int(mw, 8)),
                    path=path,
                    conflict=conflict)
            elif ident in "?!":
                # ? Untracked items
                # ! Ignored items
                path, = match.groups()
                if path.endswith("/"):
                    path = path.removesuffix("/")
                    mode = FileMode.TREE
                else:
                    mode = FileMode.UNREADABLE  # a more precise mode will be filled in from the file's stats
                delta = FatDelta(repo=repo, statusUnstaged=ident, modeWorktree=mode, path=path)
            else:
                raise NotImplementedError(f"unsupported status ident '{ident}'")

            # Fill in additional information for unstaged files.
            if delta.statusUnstaged:
                try:
                    stat = Path(self.workingDirectory(), delta.path).lstat()
                except OSError:
                    pass
                else:
                    # Fill in modeWorktree for untracked/ignored files.
                    if delta.modeWorktree == FileMode.UNREADABLE and delta.statusUnstaged in "?!":
                        delta.modeWorktree = self.distillFileMode(stat.st_mode)

            deltas.append(delta)

        return deltas

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
