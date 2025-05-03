# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import base64
import dataclasses
import json
import logging
import os
import typing
from types import NoneType, UnionType
from typing import Any

from gitfourchette import pycompat  # noqa: F401 - StrEnum for Python 3.10
from gitfourchette.porcelain import *
from gitfourchette.qt import *

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class PrefsFile:
    _filename = ""
    _allowMakeDirs = True
    _fileVersionKey = "_version"

    _dirty = False
    _fileVersion = ""

    def getParentDir(self) -> str:
        from gitfourchette.settings import TEST_MODE
        if TEST_MODE:
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
        # Prepare the path
        prefsPath = self._getFullPath(forWriting=True)
        if not prefsPath:
            logger.warning("Couldn't get path for writing")
            return ""

        # Filter the values
        assert dataclasses.is_dataclass(self)
        fields: dict[str, dataclasses.Field] = self.__dataclass_fields__
        filtered = {}
        for key, field in fields.items():
            # Skip private fields
            if key.startswith("_"):
                continue

            if field.default_factory != dataclasses.MISSING:
                default = field.default_factory()
            else:
                default = field.default

            value = self.__dict__[key]

            # Skip default values
            if value == default:
                continue

            # Make the value JSON-friendly
            value = self.encode(value)
            filtered[key] = value

        # If the filtered object comes out empty (all defaults)
        # avoid cluttering the directory - don't write out an empty object
        if not filtered:
            if not self._getFullPath(forWriting=False):
                # File doesn't exist - don't write out an empty object
                logger.debug("Not writing empty object")
            else:
                logger.debug("Deleting prefs file because we want defaults")
                os.unlink(prefsPath)
            return ""

        # Inject file version into JSON object before writing
        self._fileVersion = APP_VERSION
        filtered[self._fileVersionKey] = self._fileVersion

        # Dump the object to disk
        with open(prefsPath, "w", encoding="utf-8") as jsonFile:
            json.dump(obj=filtered, fp=jsonFile, indent='\t')
        self._dirty = False

        logger.info(f"Wrote {prefsPath}")
        return prefsPath

    def load(self) -> bool:
        prefsPath = self._getFullPath(forWriting=False)
        if not prefsPath:  # couldn't be found
            return False

        # Load JSON blob
        with open(prefsPath, encoding="utf-8") as file:
            try:
                jsonObject: dict[str, Any] = json.load(file)
            except ValueError as loadError:
                logger.warning(f"{prefsPath}: {loadError}", exc_info=True)
                return False

        if not isinstance(jsonObject, dict):
            logger.warning(f"{prefsPath}: not a JSON dict")
            return False

        # Pop file version before decoding user fields
        fv = jsonObject.pop(self._fileVersionKey, "")
        if isinstance(fv, str):
            self._fileVersion = fv

        assert dataclasses.is_dataclass(self)
        fields: dict[str, dataclasses.Field] = self.__dataclass_fields__

        # Decode values and store them in this object
        for key, value in jsonObject.items():
            if key.startswith('_') or key not in fields:
                logger.warning(f"{prefsPath}: dropping key: {key}")
                continue

            if value is None:
                continue

            try:
                value = self.decode(value, fields[key].type)
            except ValueError as error:
                logger.warning(f"{prefsPath}: {key}: {error}")
                continue

            self.__dict__[key] = value

        self._dirty = False
        return True

    @staticmethod
    def encode(o: Any) -> Any:
        """ Encode a value to make it JSON-friendly """
        if isinstance(o, enum.Enum):  # Convert Qt enums to plain old data type
            return o.value
        elif type(o) is bytes:
            return base64.b64encode(o).decode("ascii")
        elif type(o) is set:
            return list(o)
        elif type(o) is Signature:
            return {"name": o.name, "email": o.email, "time": o.time, "offset": o.offset}
        return o

    @staticmethod
    def decode(o: Any, dstType: type | UnionType) -> Any:
        """ Convert a value coming from a JSON blob to a target type """
        construct: typing.Callable[[Any], Any] | None = None

        # Extract type from "SomeType | None" unions
        if type(dstType) is UnionType:
            union = typing.get_args(dstType)
            assert len(union) == 2
            dstType = next(t for t in union if t is not NoneType)

        srcType: type
        if dstType is bytes:
            srcType = str
            construct = base64.b64decode
        elif dstType is set:
            srcType = list
        elif issubclass(dstType, enum.StrEnum):
            srcType = str
        elif issubclass(dstType, enum.IntEnum | enum.Enum):
            srcType = int
        elif dstType is Signature:
            srcType = dict
            construct = PrefsFile.decodeSignature
        else:
            srcType = dstType

        if srcType is not dstType:
            if not isinstance(o, srcType):
                raise ValueError("unexpected JSON field type")
            if construct is not None:
                o = construct(o)
            else:
                o = dstType(o)

        return o

    @staticmethod
    def decodeSignature(j: dict) -> Signature:
        name = str(j["name"])
        email = str(j["email"])
        time = int(j["time"])
        offset = int(j["offset"])
        return Signature(name, email, time, offset)
