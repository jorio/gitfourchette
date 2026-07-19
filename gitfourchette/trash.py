# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from tarfile import TarFile

import gitfourchette.pycompat  # noqa: F401 - Path.walk & Path.exists(follow_symlinks=...) for Python 3.10, 3.11
from gitfourchette import settings
from gitfourchette.qt import *
from gitfourchette.toolbox import withUniqueSuffix

logger = logging.getLogger(__name__)


class Trash:
    DirectoryName = "trash"
    QDateTimeFormat = "yyyyMMdd-HHmmss"
    MaxUniqueSuffix = 99

    _instance: Trash | None = None

    trashDir: Path
    trashFiles: list[Path]

    class BackupSkipped(Exception):
        pass

    def __init__(self):
        if not APP_TESTMODE:
            cacheDir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
        else:
            # CacheLocation is common for all tests, but we don't want parallel
            # tests to pollute each other's trashes. So, use the test-specific
            # temporary directory. Put the trash into a subdirectory that needs
            # to be created in order to simulate a fresh install where the cache
            # directory doesn't exist yet.
            cacheDir = Path(qTempDir(), "fake_cache_directory")

        self.trashDir = Path(cacheDir, Trash.DirectoryName)
        self.trashFiles = []
        self.refreshFiles()

    @classmethod
    def instance(cls) -> Trash:
        if not cls._instance:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def enabled(cls) -> bool:
        return cls.maxFileCount() > 0

    @classmethod
    def maxFileCount(cls) -> int:
        return settings.prefs.maxTrashFiles

    @classmethod
    def fileSizeLimit(cls) -> int:
        return settings.prefs.maxTrashFileKB * 1024

    @classmethod
    def hasFileSizeLimit(cls) -> bool:
        return settings.prefs.maxTrashFileKB > 0

    @classmethod
    def ensureTrashEnabled(cls):
        if not cls.enabled():
            raise Trash.BackupSkipped("trash disabled")

    def exists(self) -> bool:
        return self.trashDir.is_dir()

    def pathIsTrashManaged(self, p: Path) -> bool:
        if not p.is_relative_to(self.trashDir):
            return False
        return p.is_file(follow_symlinks=False) or p.is_symlink()

    def refreshFiles(self):
        self.trashFiles.clear()
        if self.exists():
            self.trashFiles.extend(p for p in self.trashDir.iterdir() if self.pathIsTrashManaged(p))
            self.trashFiles.sort(reverse=True)

    def makeRoom(self, maxFiles: int):
        while len(self.trashFiles) > maxFiles:
            f = self.trashFiles.pop()
            if self.pathIsTrashManaged(f):
                logger.debug(f"Deleting trash file {f}")
                f.unlink()

    def newFile(self, workdir: str, ext: str = "", originalPath: str = "") -> Path:
        self.ensureTrashEnabled()

        maxFiles = max(0, self.maxFileCount() - 1)
        self.makeRoom(maxFiles)

        self.trashDir.mkdir(parents=True, exist_ok=True)

        now = QDateTime.currentDateTime().toString(Trash.QDateTimeFormat)
        wdID = Path(workdir).name
        base = Path(originalPath).name
        stem = f"{now}-{wdID}---{base}"

        # If a file exists at this path, tack a number to the end of the name.
        uniqueName = withUniqueSuffix(
            stem,
            ext=ext,
            reserved=lambda candidate: Path(self.trashDir, candidate).exists(follow_symlinks=False),
            stop=Trash.MaxUniqueSuffix,
            suffixFormat="({})")

        path = Path(self.trashDir, uniqueName)

        # Replace existing file if withUniqueSuffix ran out of suffixes
        path.unlink(missing_ok=True)

        self.trashFiles.insert(0, path)
        return path

    def backupFile(self, workdir: str, originalPath: str) -> Path:
        self.ensureTrashEnabled()

        fullPath = Path(workdir, originalPath)
        try:
            size = fullPath.lstat().st_size
        except OSError as ex:  # FileNotFoundError, NotADirectoryError
            raise Trash.BackupSkipped("file inaccessible") from ex

        if self.hasFileSizeLimit() and size > self.fileSizeLimit():
            raise Trash.BackupSkipped("file too big")

        # Copy new file
        trashPath = self.newFile(workdir, originalPath=originalPath)
        shutil.copyfile(fullPath, trashPath, follow_symlinks=False)
        return trashPath

    def backupPatch(self, workdir: str, text: str, originalPath: str = "") -> Path:
        trashFile = self.newFile(workdir, ext=".patch", originalPath=originalPath)
        trashFile.write_text(text, encoding="utf-8", newline="\n")
        return trashFile

    def backupTree(self, workdir: str, treePath: str) -> Path:
        self.ensureTrashEnabled()

        treeFullPath = Path(workdir, treePath)

        # Check if tree is viable first
        if self.hasFileSizeLimit():
            totalSize = 0

            def reraise(walkError: OSError):
                raise Trash.BackupSkipped("inaccessible file in tree") from walkError

            for root, _dirs, files in treeFullPath.walk(on_error=reraise):
                for name in files:
                    fileSize = Path(root, name).lstat().st_size
                    totalSize += fileSize
                    if totalSize > self.fileSizeLimit():
                        raise Trash.BackupSkipped("tree too big")

        # Create a tarball
        trashFile = self.newFile(workdir, ext=".tar", originalPath=treePath)

        with TarFile(trashFile, "w") as tarball:
            tarball.add(treeFullPath, arcname=treePath)

        return trashFile

    def size(self) -> tuple[int, int]:
        size = 0
        count = 0

        for f in self.trashFiles:
            if self.pathIsTrashManaged(f):
                size += f.lstat().st_size
                count += 1

        return size, count

    def count(self) -> int:
        return self.size()[1]

    def clear(self):
        self.makeRoom(0)
