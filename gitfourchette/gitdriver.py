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


def readTable(pattern, stdout, linesep="\n"):
    stdout = stdout.decode("utf-8", errors="replace")
    stdout = stdout.removesuffix(linesep)
    return [re.match(pattern, line).groups() for line in stdout.split(linesep)]

