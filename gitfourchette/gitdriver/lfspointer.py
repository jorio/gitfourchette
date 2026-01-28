# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import enum
import re

LfsPointerMagic = "version https://git-lfs.github.com/spec/v1\n"
LfsPointerMagicBytes = LfsPointerMagic.encode("utf-8")
LfsPointerPattern = re.compile(rf"^{LfsPointerMagic}oid sha256:([0-9a-f]+)\nsize (\d+)")


class LfsPointerState(enum.IntEnum):
    NoPointer = -1
    Unknown = 0
    Valid = 1
    Bypass = 2


@dataclasses.dataclass(frozen=True)
class LfsPointer:
    state: LfsPointerState = LfsPointerState.Unknown
    id: str = ""
    size: int = -1
    objectPath: str = "/dev/null"

    def __bool__(self):
        return self.state > LfsPointerState.Unknown
