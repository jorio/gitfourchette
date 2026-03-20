# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import hashlib
import os
import warnings
from pathlib import Path

from pygit2.enums import AttrCheck

from gitfourchette.gitdriver.lfspointer import LfsPointer, LfsPointerState, LfsPointerMagicBytes, LfsPointerPattern, LfsObjectCacheMissingError
from gitfourchette.nav import NavContext
from gitfourchette.porcelain import FileMode, ObjectType, Repo, Oid, id7, pygit2_version_at_least

HexHash0000 = "0" * 40
HexHashFFFF = "f" * 40

HexHashEmptyBlob = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"  # hashlib.sha1(b'blob 0\0').hexdigest()
""" The SHA-1 hash of an empty Git blob. """

_NoDiskStat = (-1, -1)

_UnknownLfsPointer = LfsPointer(LfsPointerState.Unknown)
_NoLfsPointer = LfsPointer(LfsPointerState.NoPointer)

_sha1ToSha256Equivalent: dict[str, str] = {}
"""
Map SHA-1 blob hashes to SHA-256 equivalents for quick comparison of regular
git blobs (SHA-1) to LFS pointers (SHA-256).
"""


@dataclasses.dataclass
class GitDeltaFile:
    path: str = ""
    id: str = HexHash0000
    mode: FileMode = FileMode.UNREADABLE
    source: NavContext = NavContext.EMPTY
    sourceCommit: Oid | None = None

    diskStat: tuple[int, int] = _NoDiskStat
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

    lfs: LfsPointer = dataclasses.field(default=_UnknownLfsPointer, compare=False)
    """
    Cached LFS object information extracted from the LFS pointer (if any).
    """

    SupportsFastSizeBallpark = pygit2_version_at_least("1.19.2", False, "fast size ballpark")

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

    def hasDiskStat(self) -> bool:
        return self.diskStat != _NoDiskStat

    def isBlob(self) -> bool:
        return self.mode & FileMode.BLOB == FileMode.BLOB

    def read(self, repo: Repo, maxSize: int = -1) -> bytes:
        if self._data is not None:
            # Data already cached
            pass

        elif self.lfs.state == LfsPointerState.UnstagedTentative:
            # Would be an LFS file once staged, read it direct from the workdir
            assert self.lfs.size < 0
            self._data = repo.apply_filters_to_workdir(self.path)
            self.lfs = dataclasses.replace(self.lfs, size=len(self._data))

        elif self.lfs.state == LfsPointerState.Valid:
            # LFS pointer resolved, load data from LFS object db
            try:
                self._data = Path(self.lfs.objectPath).read_bytes()
            except FileNotFoundError as fnf:
                raise LfsObjectCacheMissingError(self.lfs) from fnf
            assert self.lfs.size == len(self._data), "LFS object size mismatch"

        else:
            try:
                # Load blob from standard git object database
                if not self.isIdValid():  # unknown hash (FFFFFFF...)
                    raise KeyError()

                # Honor size heuristic, if any
                if 0 <= maxSize < self.sizeBallpark(repo):
                    raise OverflowError("blob size exceeds limit")

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
        diskStat = _NoDiskStat
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

        if self.isIdValid() and self.SupportsFastSizeBallpark:
            try:
                blobType, blobSize = repo.odb.read_header(self.id)
                assert blobType == ObjectType.BLOB
                return blobSize
            except KeyError:
                # Fall back to workdir stat
                pass

        if self.isIdValid() and not self.SupportsFastSizeBallpark:  # pragma: no cover (Odb.read_header missing in old versions of pygit2)
            # The mere act of looking up a blob can be much slower than Odb.read_header for large blobs!
            # TODO: Remove once we can stop supporting pygit2 <= 1.19.1
            try:
                return repo.peel_blob(self.id).size
            except KeyError:
                pass

        assert self.source.isWorkdir(), "can't estimate non-workdir blob size without a blob ID"

        _, size = self.stat(repo)
        return size

    def cacheLfsPointer(self, repo: Repo, checkOrKnownValue: AttrCheck | str):
        # No-op if LFS pointer already resolved
        if self.lfs.state != LfsPointerState.Unknown:
            return

        # No LFS pointer if the file doesn't exist at this point
        if self.isId0():
            self.lfs = _NoLfsPointer
            return

        # Get filter attribute for this file
        if isinstance(checkOrKnownValue, str):
            attr = checkOrKnownValue
        else:
            check = checkOrKnownValue
            attr = repo.get_attr(self.path, "filter", check, self.sourceCommit)

        # File must have 'lfs' filter attribute past this point
        if attr != "lfs":
            self.lfs = _NoLfsPointer
            return

        # Unstaged: Force read data from wd
        if self.source.isDirty():
            assert self.sourceCommit is None
            objectPath = repo.in_workdir(self.path)
            self.lfs = LfsPointer(LfsPointerState.UnstagedTentative, objectPath=objectPath)
            return

        # Analyze the non-LFS blob to make sure it's really an LFS pointer.
        try:
            data = self.read(repo, maxSize=256)
        except OverflowError:
            # Don't bother loading large blobs; unlikely to be a valid pointer
            data = b""

        if not data.startswith(LfsPointerMagicBytes):
            self.lfs = _NoLfsPointer
            return

        text = data.decode("utf-8", errors="replace")
        match = LfsPointerPattern.match(text)
        sha = match.group(1)
        size = int(match.group(2))
        objectPath = repo.in_gitdir(f"lfs/objects/{sha[:2]}/{sha[2:4]}/{sha}")
        self.lfs = LfsPointer(LfsPointerState.Valid, sha, size, objectPath, text)

        # Invalidate data so that next read() uses LFS data
        self._data = None

    def blobSha256(self, repo) -> str:
        try:
            sha256 = _sha1ToSha256Equivalent[self.id]
        except KeyError:
            blobContents = self.read(repo)
            sha256 = hashlib.sha256(blobContents)
            sha256 = sha256.hexdigest()
            _sha1ToSha256Equivalent[self.id] = sha256
        return sha256

    def __repr__(self) -> str:
        return f"({self.path},{id7(self.id)},{self.mode:o})"


GitDeltaFile_Empty = GitDeltaFile()
