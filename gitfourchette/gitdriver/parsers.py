# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import logging
import re
from pathlib import Path
from collections.abc import Iterator

from gitfourchette.gitdriver.gitdelta import GitDelta, GitStatus
from gitfourchette.gitdriver.gitdeltafile import GitDeltaFile, GitDeltaSource, FileMode, HexHash0000, HexHashFFFF
from gitfourchette.gitdriver.gitconflict import GitConflict, GitConflictSides
from gitfourchette.porcelain import RefPrefix

_logger = logging.getLogger(__name__)


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

UPSTREAMS_FORMAT = "--format=%(refname)%00%(upstream)%00%(upstream:track,nobracket)"
"Format for `git for-each-ref refs/heads` that parseUpstreams expects."

REMOTES_COMMAND = ["remote", "-v"]
"Git command whose output parseRemotes expects."

UPSTREAM_CONFIG_COMMAND = ["config", "get", "-z", "--all", "--show-names", "--regexp", r"^branch\..+\.(remote|merge)$"]
"Git command whose output parseUpstreamConfig expects."


@dataclasses.dataclass(frozen=True)
class UpstreamEntry:
    """ One local branch from UPSTREAMS_FORMAT. """

    refName: str
    "Local branch refname (refs/heads/...)"

    upstreamRef: str
    """Local ref that tracks the upstream as git maps it.
    Empty string if there's no upstream or no refspec maps it."""

    aheadBehind: tuple[int, int]
    "Number of commits the branch is ahead/behind of its upstream"


def distillMode(realMode: int) -> FileMode:
    """
    Git uses simplified file modes that may not accurately reflect a file's
    actual mode in the filesystem (e.g., a symlink's st_mode might be
    0o120777, which to git is just 0o120000). Use this function to simplify
    a real file mode to a legal FileMode value for git.
    """
    for gitMode in _gitSimplifiedModes:
        stripped = gitMode & ~0o000077  # Keep 'user' bits, ignore 'group'/'all' bits
        if stripped == (realMode & stripped):
            return gitMode

    _logger.warning(f"cannot map to git FileMode: 0o{realMode:o}")
    return FileMode.UNREADABLE


def parseMode(octal: str) -> FileMode:
    return FileMode(int(octal, 8))


def iterateLines(text: str) -> Iterator[tuple[int, int]]:
    pos = 0
    limit = len(text)

    while pos < limit:
        nextPos = text.find('\n', pos)
        if nextPos < 0:
            nextPos = limit
        else:
            nextPos += 1
        yield pos, nextPos
        pos = nextPos


def parseGitStatus(stdout: str, workdir: str) -> Iterator[tuple[GitDelta | None, GitDelta | None]]:
    pos = 0
    limit = len(stdout)

    while pos < limit:
        ident = stdout[pos]

        try:
            pattern = _gitStatusPatterns[ident]
        except KeyError as ex:
            raise ValueError(f"unknown ident {ident}") from ex

        match = pattern.match(stdout, pos)
        if match is None:
            raise ValueError(f"malformed record {ident}")

        pos = match.end()
        assert stdout[pos-1] == '\0'

        staged, unstaged = _parseStatusLine(ident, *match.groups())

        # Fill in file mode for untracked/ignored files.
        if (unstaged
                and unstaged.status in [GitStatus.Untracked, GitStatus.Ignored]
                and unstaged.new.mode == FileMode.UNREADABLE):
            try:
                stat = Path(workdir, unstaged.new.path).lstat()
                unstaged.new.mode = distillMode(stat.st_mode)
            except OSError:
                pass

        yield staged, unstaged


def _parseStatusLine(ident: str, *tokens: str) -> tuple[GitDelta | None, GitDelta | None]:
    if ident == "1":
        # Ordinary changed entries
        path = tokens[-1]
        tweakedTokens = tokens[:-1] + ("0", path, path)
        return _parseStatus2(*tweakedTokens)
    elif ident == "2":
        # Renamed or copied entries
        return _parseStatus2(*tokens)
    elif ident == "u":
        # Unmerged entries (conflict)
        return _parseStatusConflict(*tokens)
    elif ident == "?":
        # Untracked
        return _parseStatusUntracked(GitStatus.Untracked, *tokens)
    elif ident == "!":
        # Ignored
        return _parseStatusUntracked(GitStatus.Ignored, *tokens)
    else:
        raise ValueError(f"unknown ident: {ident}")


def _parseStatus2(x, y, sub, mh, mi, mw, hh, hi, score, newPath, origPath):
    fileHead = GitDeltaFile(
        path=origPath,
        id=hh,
        mode=parseMode(mh),
        source=GitDeltaSource.Commit)

    fileIndex = GitDeltaFile(
        path=newPath,
        id=hi,
        mode=parseMode(mi),
        source=GitDeltaSource.Index)

    fileWorktree = GitDeltaFile(
        path=newPath,
        id=HexHash0000 if y == "D" else HexHashFFFF,
        mode=parseMode(mw),
        source=GitDeltaSource.Dirty)

    xDelta, yDelta = None, None

    if x != ".":  # STAGED
        xStatus = GitStatus(x)
        xDelta = GitDelta(status=xStatus, old=fileHead, new=fileIndex, similarity=int(score))

    if y != ".":  # UNSTAGED
        yStatus = GitStatus(y)
        yDelta = GitDelta(status=yStatus, old=fileIndex, new=fileWorktree, submoduleStatus=sub)

    return xDelta, yDelta


def _parseStatusConflict(xy, sub, m1, m2, m3, mw, h1, h2, h3, path):
    indexFile = GitDeltaFile(path=path, source=GitDeltaSource.Index)  # no stage 0 in a conflict
    worktreeFile = GitDeltaFile(path=path, id=HexHashFFFF, mode=parseMode(mw), source=GitDeltaSource.Dirty)

    sides = GitConflictSides(xy)
    stage1 = GitDeltaFile(path=path, id=h1, mode=parseMode(m1))
    stage2 = GitDeltaFile(path=path, id=h2, mode=parseMode(m2))
    stage3 = GitDeltaFile(path=path, id=h3, mode=parseMode(m3))
    conflict = GitConflict(sides, stage1, stage2, stage3)

    yDelta = GitDelta(status=GitStatus.Unmerged, old=indexFile, new=worktreeFile,
                      conflict=conflict, submoduleStatus=sub)
    return None, yDelta


def _parseStatusUntracked(status: GitStatus, path: str):
    if path.endswith("/"):
        path = path.removesuffix("/")
        mode = FileMode.TREE
    else:
        mode = FileMode.UNREADABLE  # a more precise mode will be filled in from the file's stats

    # "Old" state = empty file (not indexed yet)
    indexFile = GitDeltaFile(path=path, id=HexHash0000, mode=FileMode.UNREADABLE, source=GitDeltaSource.Index)

    worktreeFile = GitDeltaFile(path=path, id=HexHashFFFF, mode=mode, source=GitDeltaSource.Dirty)

    yDelta = GitDelta(status=status, old=indexFile, new=worktreeFile)
    return None, yDelta


def parseGitDiffRawZ(stdout: str):
    pos = 0
    limit = len(stdout)

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

        yield _parseShowLine(ms, md, hs, hd, status, score, path1, path2)


def _parseShowLine(ms, md, hs, hd, statusChar, score, path1, path2) -> GitDelta:
    status = GitStatus(statusChar)

    fileSrc = GitDeltaFile(
        path=path1,
        id=hs,
        mode=parseMode(ms),
        source=GitDeltaSource.Commit)

    fileDst = GitDeltaFile(
        path=path2,
        id=hd,
        mode=parseMode(md),
        source=GitDeltaSource.Commit)

    return GitDelta(status, fileSrc, fileDst, similarity=int(score) if score else 0)


def parseGitBlame(stdout: str) -> Iterator[tuple[str, int, str]]:
    # Transient data for current line
    commitId = ""
    originalLineNumber = -1

    for pos, endPos in iterateLines(stdout):
        if not commitId:  # Looking for header
            tokens = stdout[pos : endPos].split(" ", 2)
            commitId = tokens[0]
            originalLineNumber = int(tokens[1])
        elif stdout[pos] == '\t':
            text = stdout[pos+1 : endPos]
            yield commitId, originalLineNumber, text
            commitId = ""  # Look for next line
        else:
            # Ignore author, author-mail, etc.
            pass


def parseUpstreams(stdout: str) -> Iterator[UpstreamEntry]:
    """
    Parse the output of `git for-each-ref UPSTREAMS_FORMAT refs/heads`,
    one UpstreamEntry per local branch.
    """
    for pos, endPos in iterateLines(stdout):  # Not splitlines(), which also breaks on U+2028 etc.
        refName, upstreamRef, track = stdout[pos:endPos].rstrip("\n").split("\0")
        ahead = behind = 0
        for part in track.split(", "):  # e.g. "ahead 2, behind 1", "behind 3", "gone", or empty
            kind, _sep, count = part.partition(" ")
            if kind == "ahead":
                ahead = int(count)
            elif kind == "behind":
                behind = int(count)
        yield UpstreamEntry(refName, upstreamRef, (ahead, behind))


def parseRemotes(stdout: str) -> dict[str, str]:
    """
    Parse the output of REMOTES_COMMAND into a table of remote names to the
    URL that Git fetches from (after url.<base>.insteadOf), or an empty string
    if the remote only has a pushurl.

    `git remote` lists a remote for any remote.<name>.* key, at any config
    level (e.g. a global remote.origin.prune). Skip the remotes that have
    neither url nor pushurl: Git can't fetch or push them.
    """
    remotes: dict[str, str] = {}

    for line in stdout.splitlines():
        name, _tab, urlAndKind = line.partition("\t")

        if urlAndKind.endswith(" (push)"):
            remotes.setdefault(name, "")
            continue

        # A partial clone adds its filter after the kind: "(fetch) [blob:none]"
        fetchUrl, isFetchLine, _filter = urlAndKind.rpartition(" (fetch)")
        if isFetchLine:
            remotes[name] = fetchUrl

    return remotes


def parseUpstreamConfig(stdout: str) -> dict[str, tuple[str, str]]:
    """
    Parse the output of UPSTREAM_CONFIG_COMMAND into a table of local branch
    refnames to their configured upstream: (branch.*.remote, branch.*.merge).
    Like Git, skip branches that lack either key, let the last remote win, and
    take the first merge if there are several.
    """
    remotes: dict[str, str] = {}
    merges: dict[str, str] = {}

    for record in stdout.split("\0"):
        if not record:
            continue

        key, _newline, value = record.partition("\n")
        branchName, _dot, variable = key.removeprefix("branch.").rpartition(".")
        refName = RefPrefix.HEADS + branchName

        if variable == "remote":
            remotes[refName] = value
        else:
            merges.setdefault(refName, value)

    return {refName: (remote, merges[refName])
            for refName, remote in remotes.items()
            if refName in merges}
