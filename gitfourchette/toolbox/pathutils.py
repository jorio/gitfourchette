# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import enum
import os
from os import PathLike
from pathlib import Path

HOME = os.path.abspath(os.path.expanduser('~'))


class PathDisplayStyle(enum.IntEnum):
    FullPaths = 1
    AbbreviateDirs = 2
    FileNameOnly = 3
    FileNameFirst = 4


def compactPath(path: str | PathLike) -> str:
    # Normalize path first, which also turns forward slashes to backslashes on Windows.
    path = os.path.abspath(path)
    if path.startswith(HOME):
        path = "~" + path[len(HOME):]
    return path


def disambiguateTabTitlesByPath(workdirs: list[str]) -> list[str]:
    """Return unique tab titles for repos that share the same base name."""
    partsList = [Path(compactPath(workdir)).parts for workdir in workdirs]

    maxDepth = max(len(parts) for parts in partsList)
    uniqueDepth = maxDepth
    for depth in range(1, maxDepth + 1):
        tails = [parts[-depth:] for parts in partsList]
        if len(set(tails)) == len(tails):
            uniqueDepth = depth
            break

    labels = []
    for parts in partsList:
        tail = parts[-uniqueDepth:]
        if len(tail) == 1:
            labels.append(tail[0])
        elif len(tail) == 2:
            labels.append(str(Path(*tail)))
        else:
            labels.append(str(Path(tail[0], "…", tail[-1])))
    return labels


def abbreviatePath(
        path: str,
        style: PathDisplayStyle = PathDisplayStyle.FullPaths,
        allowNul: bool = False
) -> str:
    if style == PathDisplayStyle.AbbreviateDirs:
        splitLong = path.split('/')
        for i in range(len(splitLong) - 1):
            if splitLong[i][0] == '.':
                splitLong[i] = splitLong[i][:2]
            else:
                splitLong[i] = splitLong[i][0]
        return '/'.join(splitLong)

    elif style == PathDisplayStyle.FileNameFirst:
        try:
            directory, file = path.rsplit('/', 1)
            separator = '\0 ' if allowNul else '  '
            return separator.join((file, directory))
        except ValueError:
            return path

    elif style == PathDisplayStyle.FileNameOnly:
        return path.rsplit('/', 1)[-1]

    else:
        return path
