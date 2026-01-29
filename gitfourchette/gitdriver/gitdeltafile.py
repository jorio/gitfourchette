# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import os
import warnings
from pathlib import Path

from pygit2.enums import AttrCheck

from gitfourchette.gitdriver.lfspointer import LfsPointer, LfsPointerState, LfsPointerMagicBytes, LfsPointerPattern
from gitfourchette.nav import NavContext
from gitfourchette.porcelain import FileMode, Repo, Oid, id7, NULL_OID

HexHash0000 = "0" * 40
HexHashFFFF = "f" * 40

HexHashEmptyBlob = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"  # hashlib.sha1(b'blob 0\0').hexdigest()
""" The SHA-1 hash of an empty Git blob. """


@dataclasses.dataclass
class GitDeltaFile:
    path: str = ""
    id: str = HexHash0000
    mode: FileMode = FileMode.UNREADABLE
    source: NavContext = NavContext.EMPTY

    diskStat: tuple[int, int] = (-1, -1)
    """
    Filled in for unstaged files only. Allows quick comparison of GitDeltaFiles
    taken at two points in time for the same unstaged file. Internally, this is
    a snapshot of a subset of the file's status on disk (st_mtime_ns, st_size).
    """

    _data: bytes | None = dataclasses.field(default=None, compare=False)
    """
    Cached file contents. Not used in object comparisons.
    None means that the file hasn't been cached yet (isDataValid() == False).
    """

    lfs: LfsPointer = dataclasses.field(default_factory=LfsPointer, compare=False)
    """
    Cached LFS object information extracted from the LFS pointer (if any).
    """

    def __post_init__(self):
        assert self.id.isnumeric() or self.id.islower()
        if self.isId0():
            self._data = b""

    def __bool__(self) -> bool:
        return not self.isId0()

    def isId0(self) -> bool:
        return self.id == HexHash0000

    def isEmptyBlob(self) -> bool:
        return self.id == HexHashEmptyBlob

    def isIdValid(self) -> bool:
        return self.id != HexHashFFFF

    def isDataValid(self) -> bool:
        return self._data is not None

    def isBlob(self) -> bool:
        return self.mode & FileMode.BLOB == FileMode.BLOB

    def read(self, repo: Repo) -> bytes:
        if self._data is not None:
            # Data already cached
            pass

        elif self.lfs.state == LfsPointerState.Bypass:
            # Would be an LFS file once staged, read it direct from the workdir
            assert self.lfs.size < 0
            self._data = repo.apply_filters_to_workdir(self.path)
            self.lfs = dataclasses.replace(self.lfs, size=len(self._data))

        elif self.lfs.state == LfsPointerState.Valid:
            # LFS pointer resolved, load data from LFS object db
            self._data = Path(self.lfs.objectPath).read_bytes()
            assert self.lfs.size == len(self._data), "LFS object size mismatch"

        else:
            # Load blob from standard git object database
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
        if self.isId0():
            warnings.warn(f"dumping file with id zero: {self}")

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

        if self.lfs.size >= 0:
            return self.lfs.size

        if self.isIdValid():
            try:
                return repo.peel_blob(self.id).size
            except KeyError:
                pass

        _, size = self.stat(repo)
        return size

    def cacheLfsPointer(self, repo: Repo, commitId: Oid):
        if self.lfs.state != LfsPointerState.Unknown:
            # Already resolved
            return

        if commitId != NULL_OID:
            check = AttrCheck.INCLUDE_COMMIT
        elif self.source.isDirty():
            check = AttrCheck.FILE_THEN_INDEX
        else:
            check = AttrCheck.INDEX_THEN_FILE#AttrCheck.INDEX_ONLY
        attr = repo.get_attr(self.path, "diff", check, commitId)

        if attr != "lfs":
            self.lfs = LfsPointer(LfsPointerState.NoPointer)
            return

        if self.source.isDirty():
            # Force read data from wd
            self.lfs = LfsPointer(LfsPointerState.Bypass, objectPath=repo.in_workdir(self.path))
            return

        data = self.read(repo)
        if not data.startswith(LfsPointerMagicBytes):
            self.lfs = LfsPointer(LfsPointerState.NoPointer)
            return

        text = data.decode("utf-8", errors="replace")
        match = LfsPointerPattern.match(text)
        sha = match.group(1)
        size = int(match.group(2))
        objectPath = repo.in_gitdir(f"lfs/objects/{sha[:2]}/{sha[2:4]}/{sha}")
        self.lfs = LfsPointer(LfsPointerState.Valid, sha, size, objectPath)

        # Invalidate data so that next read() uses LFS data
        self._data = None

    def __repr__(self) -> str:
        return f"({self.path},{id7(self.id)},{self.mode:o})"


GitDeltaFile_Empty = GitDeltaFile()
