# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import datetime
import logging
import os
import shutil
from tarfile import TarFile

from gitfourchette import settings
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.toolbox import withUniqueSuffix

logger = logging.getLogger(__name__)


class Trash:
    DIR_NAME = "trash"
    TIME_FORMAT = '%Y%m%d-%H%M%S'
    _instance = None

    def __init__(self):
        if not APP_TESTMODE:
            cacheDir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
        else:
            cacheDir = qTempDir()
        self.trashDir = os.path.join(cacheDir, Trash.DIR_NAME)
        self.trashFiles = []
        self.refreshFiles()

    @staticmethod
    def instance():
        if not Trash._instance:
            Trash._instance = Trash()
        return Trash._instance

    @property
    def maxFileCount(self) -> int:
        return settings.prefs.maxTrashFiles

    @property
    def maxFileSize(self) -> int:
        return settings.prefs.maxTrashFileKB * 1024

    def exists(self):
        return os.path.isdir(self.trashDir)

    def refreshFiles(self):
        self.trashFiles = []
        if os.path.isdir(self.trashDir):
            files = os.listdir(self.trashDir)
            self.trashFiles = sorted(files, reverse=True)

    def makeRoom(self, maxFiles: int):
        while len(self.trashFiles) > maxFiles:
            f = self.trashFiles.pop()
            fullPath = os.path.join(self.trashDir, f)
            if os.path.isfile(fullPath):
                logger.debug(f"Deleting trash file {fullPath}")
                os.unlink(fullPath)

    def newFile(self, workdir: str, ext: str = "", originalPath: str = "") -> str:
        maxFiles = self.maxFileCount
        if maxFiles == 0:
            return ""

        maxFiles = max(0, maxFiles - 1)
        self.makeRoom(maxFiles)

        os.makedirs(self.trashDir, exist_ok=True)

        now = datetime.datetime.now().strftime(Trash.TIME_FORMAT)
        wdID = os.path.basename(os.path.normpath(workdir))
        base = os.path.basename(os.path.normpath(originalPath))
        stem = f"{now}-{wdID}---{base}"

        # If a file exists at this path, tack a number to the end of the name.
        path = withUniqueSuffix(os.path.join(self.trashDir, stem), ext=ext,
                                reserved=os.path.exists, stop=99, suffixFormat="({})")

        self.trashFiles.insert(0, path)
        return path

    def backupFile(self, workdir: str, originalPath: str) -> str:
        fullPath = os.path.join(workdir, originalPath)

        if self.maxFileSize != 0 and os.lstat(fullPath).st_size > self.maxFileSize:
            return ""

        # Copy new file
        trashPath = self.newFile(workdir, originalPath=originalPath)
        if not trashPath:
            return ""

        shutil.copyfile(fullPath, trashPath, follow_symlinks=False)
        return trashPath

    def backupPatch(self, workdir: str, text: str, originalPath: str = "") -> str:
        trashFile = self.newFile(workdir, ext=".patch", originalPath=originalPath)
        if not trashFile:
            return ""
        with open(trashFile, "w", encoding="utf-8") as f:
            f.write(text)
        return trashFile

    def backupTree(self, workdir: str, treePath: str):
        treeFullPath = os.path.join(workdir, treePath)

        if not self.isTreeSmallEnough(treeFullPath):
            return

        trashFile = self.newFile(workdir, ext=".tar", originalPath=treePath)
        if not trashFile:
            return

        with TarFile(trashFile, "w") as tarball:
            tarball.add(treeFullPath, arcname=treePath)

    def isTreeSmallEnough(self, sourcePath: str):
        if self.maxFileSize == 0:
            return True

        totalSize = 0

        for root, _dirs, files in os.walk(sourcePath):
            for name in files:
                fullPath = os.path.join(root, name)
                fileSize = os.lstat(fullPath).st_size
                totalSize += fileSize
                if totalSize > self.maxFileSize:
                    return False

        return True

    def size(self) -> tuple[int, int]:
        size = 0
        count = 0

        for f in self.trashFiles:
            filePath = os.path.join(self.trashDir, f)
            if os.path.isfile(filePath):
                size += os.lstat(filePath).st_size
                count += 1

        return size, count

    def clear(self):
        self.makeRoom(0)
