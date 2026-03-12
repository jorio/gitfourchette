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
    """ This file isn't stored as LFS. """

    Unknown = 0
    """ This file's LFS status hasn't been cached yet. """

    Valid = 1
    """ This file is stored as LFS. """

    UnstagedTentative = 2
    """
    This file is expected to be stored as LFS once it's staged.
    It may not have an object file in the LFS database yet.
    """


@dataclasses.dataclass(frozen=True)
class LfsPointer:
    state: LfsPointerState = LfsPointerState.Unknown
    """ Status of this LFS pointer. """

    id: str = ""
    """ SHA-256 hexadecimal hash of the LFS object. """

    size: int = -1
    """ Size of the LFS object. -1 means unknown. """

    objectPath: str = "/dev/null"
    """ Absolute path to the LFS object file. """

    def __bool__(self) -> bool:
        return self.state > LfsPointerState.Unknown

    def isTentative(self) -> bool:
        return self.state == LfsPointerState.UnstagedTentative


class LfsObjectCacheMissingError(LookupError):
    def __init__(self, *pointers: LfsPointer):
        super().__init__()
        self.pointers = pointers
