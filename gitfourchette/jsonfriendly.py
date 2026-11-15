# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Serialize/deserialize dataclasses to/from JSON-friendly dicts.
"""

from __future__ import annotations  # TODO: Remove once we can drop support for Python <= 3.13

import base64
import dataclasses
import enum
import json
import logging
import typing
from types import NoneType, UnionType, GenericAlias
from typing import Any

from pygit2 import Signature

from gitfourchette.appconsts import APP_VERSION

_TPrimitive = str | int | float | bool | None
_TContainer = list | set | dict | tuple
_TJsonFriendly = dict | list | _TPrimitive
_versionKey = "_version"

_logger = logging.getLogger(__name__)


class JsonTypeMismatch(TypeError):
    def __init__(self, expected, got):
        self.expectedType = expected
        self.gotType = got
        self.fieldName = ""
        super().__init__()

    def __str__(self):
        return f"'{self.fieldName}' should be type '{self.expectedType.__name__}', but JSON file contains '{self.gotType.__name__}'"


def _checkInputType[T](data, t: type[T]) -> T:
    if not isinstance(data, t):
        raise JsonTypeMismatch(t, type(data))
    return data


def _dataclassFieldFilter(name: str):
    return not name.startswith("_")


def toJson(obj: Any, emptyStringIfDefaultDict: bool = False) -> str:
    data = encode(obj)

    if isinstance(data, dict):
        if emptyStringIfDefaultDict and not data:
            return ""

        assert _versionKey not in data
        data[_versionKey] = APP_VERSION

    return json.dumps(data, indent="\t")


def fromJson[T](jsonData: str | bytes | bytearray, targetType: type[T]) -> tuple[Any, str]:
    data = json.loads(jsonData)

    version = ""
    if isinstance(data, dict):
        versionCandidate = data.pop(_versionKey, "")
        if isinstance(versionCandidate, str):
            version = versionCandidate

    obj = decode(data, targetType)
    return obj, version


def encode(obj: Any) -> _TJsonFriendly:
    """ Encode a value to a JSON-friendly dict, list, or primitive. """

    codec = _codecRegistry.get(type(obj))
    if codec is not None:
        obj = codec.encode(obj)  # type: ignore[attr-defined]

    if isinstance(obj, enum.Enum):  # Convert Qt enums to int
        return obj.value

    if isinstance(obj, list | set | tuple):
        return [encode(v) for v in obj]

    if isinstance(obj, dict):
        return {k: encode(v) for k, v in obj.items()}

    if dataclasses.is_dataclass(obj):
        return _encodeDataclass(obj)

    # Primitives can be copied verbatim in JSON-friendly objects
    assert isinstance(obj, _TPrimitive)
    return obj


def decode(data: _TJsonFriendly, targetType: type | GenericAlias | UnionType) -> Any:
    """ Convert a JSON blob to a target type. """

    # Extract type from "SomeType | None" unions
    if type(targetType) is UnionType:
        union = typing.get_args(targetType)
        assert len(union) == 2

        isOptional = any(t for t in union if t is NoneType)
        targetType = next(t for t in union if t is not NoneType)

        assert isOptional
        if isOptional and data is None:
            return None

    # Special treatment for container types
    origin = typing.get_origin(targetType)

    if origin is dict:
        dataDict = _checkInputType(data, dict)
        kt, vt = typing.get_args(targetType)
        return {decode(k, kt): decode(v, vt) for k, v in dataDict.items()}

    if origin is list or origin is set:
        dataList = _checkInputType(data, list)
        (vt,) = typing.get_args(targetType)
        assert vt is not typing.Any
        return origin(decode(v, vt) for v in dataList)

    if origin is tuple:
        dataList = _checkInputType(data, list)
        tupleTypes = typing.get_args(targetType)
        assert all(vt is not typing.Any for vt in tupleTypes)
        return tuple(decode(v, vt) for v, vt in zip(dataList, tupleTypes, strict=True))

    # Not a container type beyond this point
    assert origin is None, f"container decode not implemented: {origin}"
    assert not isinstance(targetType, GenericAlias), "alias origin should have been processed above"
    assert not isinstance(targetType, UnionType), "union should have been processed above"
    assert not issubclass(targetType, _TContainer), "incomplete container type annotation"

    codec = _codecRegistry.get(targetType)
    if codec is not None:
        try:
            return codec.decode(data)  # type: ignore[attr-defined]
        except Exception as ex:
            raise ValueError(f"could not convert JSON back to {targetType.__name__}") from ex

    if issubclass(targetType, enum.StrEnum):
        dataStr = _checkInputType(data, str)
        return targetType(dataStr)

    if issubclass(targetType, enum.IntEnum | enum.Enum):
        dataInt = _checkInputType(data, int)
        return targetType(dataInt)

    if dataclasses.is_dataclass(targetType):
        return _decodeDataclass(data, targetType)

    # Return object verbatim in other cases (primitives)
    dataPrimitive = _checkInputType(data, targetType)
    return dataPrimitive


def _encodeDataclass(obj: Any) -> dict[str, _TJsonFriendly]:
    assert dataclasses.is_dataclass(obj)

    fields: dict[str, dataclasses.Field] = obj.__dataclass_fields__
    filtered = {}

    for name, field in fields.items():
        # Skip private fields
        if not _dataclassFieldFilter(name):
            continue

        if field.default_factory is not dataclasses.MISSING:
            default = field.default_factory()
        else:
            default = field.default

        value = obj.__dict__[name]

        # Skip default values
        if value == default:
            continue

        # Make the value JSON-friendly
        encodedValue = encode(value)
        filtered[name] = encodedValue

    return filtered


def _decodeDataclass[T](data: _TJsonFriendly, targetType: type[T]) -> T:
    assert dataclasses.is_dataclass(targetType)
    dataDict = _checkInputType(data, dict)
    typeHints = None

    fields: dict[str, dataclasses.Field] = targetType.__dataclass_fields__
    kwargs = {}

    for name, field in fields.items():
        if name not in dataDict or not _dataclassFieldFilter(name):
            continue

        fieldValue = dataDict[name]

        # TODO: Clean this up when we drop "from __future__ import annotations"
        #       (field types shouldn't be stored as str anymore once that's done)
        if isinstance(field.type, str):
            if typeHints is None:
                typeHints = typing.get_type_hints(targetType)
            fieldType = typeHints[name]
        else:
            fieldType = field.type

        assert isinstance(fieldType, type | GenericAlias | UnionType), f"unsupported field type '{fieldType}' in {targetType.__name__}"

        try:
            value = decode(fieldValue, fieldType)
        except (JsonTypeMismatch, ValueError) as ex:  # ValueError: e.g. stale enum value
            if isinstance(ex, JsonTypeMismatch):
                ex.fieldName = name
            if field.default_factory is dataclasses.MISSING and field.default is dataclasses.MISSING:
                raise
            else:
                _logger.warning(f"Falling back to default value for '{name}' ({ex})")
                continue

        kwargs[name] = value

    return targetType(**kwargs)


class _BytesCodec:
    @classmethod
    def encode(cls, obj: bytes) -> str:
        return base64.b64encode(obj).decode("ascii")

    @classmethod
    def decode(cls, data: _TJsonFriendly) -> bytes:
        return base64.b64decode(_checkInputType(data, str))


@dataclasses.dataclass
class _SignatureCodec:
    name: str = ""
    email: str = ""
    time: int = 0
    offset: int = 0

    @classmethod
    def encode(cls, obj: Signature) -> _SignatureCodec:
        return cls(obj.name, obj.email, obj.time, obj.offset)

    @classmethod
    def decode(cls, data: _TJsonFriendly) -> Signature:
        bridge = _decodeDataclass(data, cls)
        return Signature(bridge.name, bridge.email, bridge.time, bridge.offset)


_codecRegistry = {
    bytes: _BytesCodec,
    Signature: _SignatureCodec,
}
