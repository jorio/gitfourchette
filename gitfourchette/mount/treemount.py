# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import os
import stat
from pathlib import Path
from typing import TypeVar

import mfusepy as fuse
from pygit2 import Blob, Commit, Object, Tree, Repository
from pygit2.enums import ObjectType

logger = logging.getLogger(__name__)

TPeelable = TypeVar("TPeelable", bound=Object)


class TreeMount(fuse.Operations):
    use_ns = True  # squelch mfusepy warning

    @classmethod
    def run(cls, workdir: str, lookup: str, mountPoint: str):
        repo = Repository(workdir)
        try:
            try:
                commit = repo[lookup]
            except ValueError:
                commit = repo.lookup_reference_dwim(lookup)
            commit = commit.peel(Commit)
            ops = cls(commit, mountPoint)
            fuse.FUSE(ops, mountPoint, foreground=True, ro=True)
        finally:
            repo.free()

    def __init__(self, commit: Commit, mountPoint: str) -> None:
        super().__init__()
        self.authorTime = commit.author.time * 1e9
        self.committerTime = commit.committer.time * 1e9
        self.tree = commit.tree
        self.mountPointPathObj = Path(mountPoint)  # to produce absolute paths in readlink

    def _resolve(self, path: str, t: type[TPeelable] = Object) -> TPeelable:
        assert path.startswith("/")
        path = path.removeprefix("/")
        o = self.tree
        if path:
            for part in path.split("/"):
                o = o[part]
        if t is not Object:
            return o.peel(t)
        return o

    @fuse.overrides(fuse.Operations)
    def getattr(self, path: str, fh: int) -> dict[str, int]:
        try:
            o = self._resolve(path)
        except KeyError:
            logger.warning(f"Could not resolve: {path}")
            return {}

        if o.type in (ObjectType.TREE, ObjectType.COMMIT):
            size = 0
            mode = stat.S_IFDIR | 0o111
        else:
            size = o.size
            mode = o.filemode

        mode |= 0o444  # Make everything readable

        return {
            "st_atime": self.committerTime,
            "st_ctime": self.authorTime,
            "st_mtime": self.authorTime,
            "st_gid": os.getgid(),
            "st_uid": os.getuid(),
            "st_size": size,
            "st_mode": mode,
        }

    @fuse.overrides(fuse.Operations)
    def readdir(self, path: str, fh: int) -> fuse.ReadDirResult:
        o = self._resolve(path)
        if o.type == ObjectType.TREE:
            tree = o.peel(Tree)
            return [".", ".."] + [entry.name for entry in tree]
        elif o.type == ObjectType.COMMIT:
            # TODO: Submodules
            return [".", ".."]
        else:
            return []

    @fuse.overrides(fuse.Operations)
    def read(self, path: str, size: int, offset: int, fh: int) -> bytes:
        blob = self._resolve(path, Blob)
        return blob.data[offset: offset+size]

    @fuse.overrides(fuse.Operations)
    def readlink(self, path: str) -> str:
        blobText = self._resolve(path, Blob).data.decode("utf-8")
        absTarget = Path(path).parent / blobText
        absOnHost = self.mountPointPathObj / absTarget.relative_to("/")
        return str(absOnHost)


if __name__ == '__main__':  # pragma: no cover
    import argparse
    parser = argparse.ArgumentParser(description="Mount Git tree with FUSE")
    parser.add_argument("repo")
    parser.add_argument("refish")
    parser.add_argument("mountpoint")
    args = parser.parse_args()
    TreeMount.run(args.repo, args.refish, args.mountpoint)
