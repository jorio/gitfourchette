# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import re
from pathlib import Path

from gitfourchette.gitdriver.gitdelta import GitDelta
from gitfourchette.gitdriver.gitdeltafile import GitDeltaFile, FileMode, HexHash0000, HexHashFFFF, NavContext
from gitfourchette.gitdriver.gitconflict import GitConflict, GitConflictSides

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

    logging.warning(f"cannot map to git FileMode: 0o{realMode:o}")
    return FileMode.UNREADABLE


def parseMode(octal: str) -> FileMode:
    return FileMode(int(octal, 8))


def iterateLines(text: str):
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


def parseGitStatus(stdout: str, workdir: str):
    pos = 0
    limit = len(stdout)

    while pos < limit:
        ident = stdout[pos]
        try:
            pattern = _gitStatusPatterns[ident]
        except KeyError:
            logging.warning(f"unknown git status ident '{ident}'")
            continue

        match = pattern.match(stdout, pos)
        pos = match.end()

        staged, unstaged = _parseStatusLine(ident, *match.groups())

        # Fill in file mode for untracked/ignored files.
        if unstaged and unstaged.status in "?!" and unstaged.new.mode == FileMode.UNREADABLE:
            try:
                stat = Path(workdir, unstaged.new.path).lstat()
                unstaged.new.mode = distillMode(stat.st_mode)
            except OSError:
                pass

        yield staged, unstaged


def _parseStatusLine(ident: str, *tokens: str) -> tuple[GitDelta | None, GitDelta | None]:
    if ident == "1":
        # Ordinary changed entries
        tokens = list(tokens)
        path = tokens.pop()
        tokens.extend(("0", path, path))
        return _parseStatus2(*tokens)
    elif ident == "2":
        # Renamed or copied entries
        return _parseStatus2(*tokens)
    elif ident == "u":
        # Unmerged entries (conflict)
        return _parseStatusConflict(*tokens)
    elif ident in "?!":
        # ? - Untracked items
        # ! - Ignored items
        return _parseStatusUntracked(ident, *tokens)
    else:
        raise ValueError(f"unknown ident: {ident}")


def _parseStatus2(x, y, sub, mh, mi, mw, hh, hi, score, newPath, origPath):
    fileHead = GitDeltaFile(
        path=origPath,
        id=hh,
        mode=parseMode(mh),
        source=NavContext.COMMITTED)

    fileIndex = GitDeltaFile(
        path=newPath,
        id=hi,
        mode=parseMode(mi),
        source=NavContext.STAGED)

    fileWorktree = GitDeltaFile(
        path=newPath,
        id=HexHash0000 if y == "D" else HexHashFFFF,
        mode=parseMode(mw),
        source=NavContext.UNSTAGED)

    xDelta, yDelta = None, None

    if x != ".":  # STAGED
        xDelta = GitDelta(status=x, old=fileHead, new=fileIndex, similarity=int(score))

    if y != ".":  # UNSTAGED
        yDelta = GitDelta(status=y, old=fileIndex, new=fileWorktree, submoduleStatus=sub)

    return xDelta, yDelta


def _parseStatusConflict(xy, sub, m1, m2, m3, mw, h1, h2, h3, path):
    indexFile = GitDeltaFile(path=path, source=NavContext.STAGED)
    worktreeFile = GitDeltaFile(path=path, id=HexHashFFFF, mode=parseMode(mw), source=NavContext.UNSTAGED)

    sides = GitConflictSides(xy)
    stage1 = GitDeltaFile(path=path, id=h1, mode=parseMode(m1))
    stage2 = GitDeltaFile(path=path, id=h2, mode=parseMode(m2))
    stage3 = GitDeltaFile(path=path, id=h3, mode=parseMode(m3))
    conflict = GitConflict(sides, stage1, stage2, stage3)

    yDelta = GitDelta(status="U", old=indexFile, new=worktreeFile,
                      conflict=conflict, submoduleStatus=sub)
    return None, yDelta


def _parseStatusUntracked(ident: str, path: str):
    if path.endswith("/"):
        path = path.removesuffix("/")
        mode = FileMode.TREE
    else:
        mode = FileMode.UNREADABLE  # a more precise mode will be filled in from the file's stats

    # "Old" state = empty file (not indexed yet)
    indexFile = GitDeltaFile(path=path, id=HexHash0000, mode=FileMode.UNREADABLE, source=NavContext.STAGED)

    worktreeFile = GitDeltaFile(path=path, id=HexHashFFFF, mode=mode, source=NavContext.UNSTAGED)

    yDelta = GitDelta(status=ident, old=indexFile, new=worktreeFile)
    return None, yDelta


def parseGitShow(stdout: str):
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


def _parseShowLine(ms, md, hs, hd, status, score, path1, path2) -> GitDelta:
    fileSrc = GitDeltaFile(
        path=path1,
        id=hs,
        mode=parseMode(ms),
        source=NavContext.COMMITTED)

    fileDst = GitDeltaFile(
        path=path2,
        id=hd,
        mode=parseMode(md),
        source=NavContext.COMMITTED)

    return GitDelta(status, fileSrc, fileDst, similarity=int(score) if score else 0)


def parseGitBlame(stdout: str):
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
