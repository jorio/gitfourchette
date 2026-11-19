# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import logging
import os
from pathlib import Path
from typing import ClassVar

from gitfourchette import jsonfriendly
from gitfourchette.qt import *

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class PrefsFile:
    _filename: ClassVar[str] = ""
    _allowMakeDirs: ClassVar[bool] = True

    _dirty = False
    _fileVersion = ""

    @property
    def fileVersion(self) -> str:
        """ App version that last wrote the file ("" if it isn't loaded or has no version). """
        return self._fileVersion

    def getParentDir(self) -> str:
        if APP_TESTMODE:
            return os.path.join(qTempDir(), "testmode-config")
        return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)

    def _getFullPath(self, forWriting: bool) -> str:
        assert self._filename != "", "you must override _filename"

        prefsDir = self.getParentDir()
        if not prefsDir:
            return ""

        if forWriting:
            if self._allowMakeDirs or False:
                os.makedirs(prefsDir, exist_ok=True)
            elif not os.path.isdir(prefsDir):
                return ""

        fullPath = os.path.join(prefsDir, self._filename)

        if not forWriting and not os.path.isfile(fullPath):
            return ""

        return fullPath

    def setDirty(self):
        self._dirty = True

    def isDirty(self):
        return self._dirty

    def reset(self):
        assert dataclasses.is_dataclass(self)
        for f in dataclasses.fields(self):
            if f.default_factory != dataclasses.MISSING:
                obj = f.default_factory()
            else:
                obj = f.default
            self.__dict__[f.name] = obj

    def write(self, force=False) -> str:
        assert dataclasses.is_dataclass(self)

        # Prepare the path
        prefsPath = self._getFullPath(forWriting=True)
        if not prefsPath:
            logger.warning("Couldn't get path for writing")
            return ""

        # Serialize the dataclass
        jsonText = jsonfriendly.toJson(self, emptyStringIfDefaultDict=True)

        # If the filtered object comes out empty (all defaults)
        # avoid cluttering the directory - don't write out an empty object
        if not jsonText:
            if not self._getFullPath(forWriting=False):
                # File doesn't exist - don't write out an empty object
                logger.debug("Not writing empty object")
            else:
                logger.debug("Deleting prefs file because we want defaults")
                os.unlink(prefsPath)
            return ""

        # Dump the object to disk
        Path(prefsPath).write_text(jsonText, encoding="utf-8")
        self._dirty = False

        logger.info(f"Wrote {prefsPath}")
        return prefsPath

    def load(self) -> bool:
        prefsPath = self._getFullPath(forWriting=False)
        if not prefsPath:  # couldn't be found
            return False

        # Read JSON blob
        jsonText = Path(prefsPath).read_text(encoding="utf-8")

        # Deserialize JSON blob into a dataclass
        try:
            obj, version = jsonfriendly.fromJson(jsonText, self.__class__)
        except ValueError as loadError:
            logger.warning(f"{prefsPath}: {loadError}", exc_info=True)
            return False

        # Merge into this object
        clean = {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        self.__dict__.update(clean)

        self._dirty = False
        self._fileVersion = version
        return True
