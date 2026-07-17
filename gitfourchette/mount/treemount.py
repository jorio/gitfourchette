# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import os
import stat
from pathlib import Path

import mfusepy as fuse
from pygit2 import Blob, Commit, Object, Tree, Repository
from pygit2.enums import ObjectType

logger = logging.getLogger(__name__)


class TreeMount(fuse.Operations):
    use_ns = True  # squelch mfusepy warning

    @classmethod
    def run(cls, workdir: str, lookup: str, mountPoint: str):
        repo = Repository(workdir)
        try:
            try:
                gitObj = repo[lookup]
            except ValueError:
                gitObj = repo.lookup_reference_dwim(lookup)
            commit = gitObj.peel(Commit)
            ops = cls(commit, mountPoint)
            fuse.FUSE(ops, mountPoint, foreground=True, ro=True)
        finally:
            repo.free()

    def __init__(self, commit: Commit, mountPoint: str) -> None:
        super().__init__()
        self.authorTime = commit.author.time * 1_000_000_000
        self.committerTime = commit.committer.time * 1_000_000_000
        self.tree = commit.tree
        self.mountPointPathObj = Path(mountPoint)  # to produce absolute paths in readlink

        try:
            self.defaultGid, self.defaultUid = os.getgid(), os.getuid()
        except AttributeError:  # Windows doesn't have these
            self.defaultGid, self.defaultUid = 0, 0

    def _resolve(self, path: str) -> Object:
        assert path.startswith("/")
        path = path.removeprefix("/")
        o = self.tree
        if path:
            for part in path.split("/"):
                o = o[part]
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
        elif o.type == ObjectType.BLOB:
            assert isinstance(o, Blob)
            size = o.size
            mode = o.filemode
        else:
            logger.warning(f"Unsupported object type {o.type} for: {path}")
            return {}

        mode |= 0o444  # Make everything readable

        return {
            "st_birthtime": self.authorTime,  # Only relevant on macOS
            "st_ctime": self.committerTime,
            "st_atime": self.committerTime,
            "st_mtime": self.committerTime,
            "st_gid": self.defaultGid,
            "st_uid": self.defaultUid,
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
        blob = self._resolve(path).peel(Blob)
        return blob.data[offset: offset+size]

    @fuse.overrides(fuse.Operations)
    def readlink(self, path: str) -> str:
        blobText = self._resolve(path).peel(Blob).data.decode("utf-8")
        absTarget = Path(path).parent / blobText
        absOnHost = self.mountPointPathObj / absTarget.relative_to("/")
        return str(absOnHost)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Mount Git tree with FUSE")
    parser.add_argument("repo")
    parser.add_argument("refish")
    parser.add_argument("mountpoint")
    args = parser.parse_args()
    TreeMount.run(args.repo, args.refish, args.mountpoint)


if __name__ == '__main__':
    main()
