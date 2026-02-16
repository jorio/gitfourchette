# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import enum
import os

HOME = os.path.abspath(os.path.expanduser('~'))


class PathDisplayStyle(enum.IntEnum):
    FullPaths = 1
    AbbreviateDirs = 2
    FileNameOnly = 3
    FileNameFirst = 4


def compactPath(path: str) -> str:
    # Normalize path first, which also turns forward slashes to backslashes on Windows.
    path = os.path.abspath(path)
    if path.startswith(HOME):
        path = "~" + path[len(HOME):]
    return path


def abbreviatePath(path: str, style: PathDisplayStyle = PathDisplayStyle.FullPaths) -> str:
    if style == PathDisplayStyle.AbbreviateDirs:
        splitLong = path.split('/')
        for i in range(len(splitLong) - 1):
            if splitLong[i][0] == '.':
                splitLong[i] = splitLong[i][:2]
            else:
                splitLong[i] = splitLong[i][0]
        return '/'.join(splitLong)
    elif style == PathDisplayStyle.FileNameFirst:
        split = path.rsplit('/', 1)
        if len(split) == 1:
            return path
        return split[-1] + ' \0' + split[0]
    elif style == PathDisplayStyle.FileNameOnly:
        return path.rsplit('/', 1)[-1]
    else:
        return path
