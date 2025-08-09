# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import re
from enum import StrEnum


class VanillaFetchStatusFlag(StrEnum):
    FastForward = " "
    ForcedUpdate = "+"
    PrunedRef = "-"
    TagUpdate = "t"
    NewRef = "*"
    Rejected = "!"
    UpToDate = "="


def readTable(pattern, stdout, linesep="\n", strict=True):
    table = []

    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
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


def readGitProgress(stderr):
    text = ""
    num = -1
    denom = -1

    if isinstance(stderr, bytes):
        stderr = stderr.decode(errors="replace")
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

    return (text, num, denom)
