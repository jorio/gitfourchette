# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import enum

import pytest
from pygit2 import Signature

from gitfourchette import jsonfriendly
from gitfourchette.jsonfriendly import JsonTypeMismatch
from .util import TEST_SIGNATURE


@dataclasses.dataclass
class Simple:
    yoink: str = "boink"

    def __hash__(self):
        return hash(self.yoink)


@dataclasses.dataclass
class SerializeMe:
    primitiveInt: int
    primitiveFloat: float
    primitiveStr: str
    primitiveBool: bool
    primitiveBytes: bytes
    listInt: list[int]
    listObj: list[Simple]
    setInt: set[int]
    setObj: set[Simple]
    dictStrInt: dict[str, int]
    dictStrObj: dict[str, Simple]
    optional1: Simple | None
    optional2: Simple | None
    tuple: tuple[int, str, bool]
    sig: Signature
    primitiveIntDefaultValue: int = -1337
    _private: int = 0


def testJsonFriendlySerialization():
    pythonObject = SerializeMe(
        primitiveInt=123,
        primitiveFloat=45.6,
        primitiveStr="hello",
        primitiveBool=True,
        primitiveBytes=b'bajn\xc3\xa4ri\x00',
        listInt=[1, 2, 3, 4],
        listObj=[Simple("foo"), Simple(), Simple("bar")],
        setInt={5, 6, 7, 8},
        setObj={Simple("foo"), Simple(), Simple("bar")},
        dictStrInt={"key1": 999, "key2": 888},
        dictStrObj={"key1": Simple("badonk"), "key2": Simple(), "key3": Simple("boink")},
        optional1=None,
        optional2=Simple("gotcha"),
        tuple=(3, "three", True),
        sig=TEST_SIGNATURE,
        _private=1234,
    )

    jsonData = jsonfriendly.toJson(pythonObject)

    assert "primitiveIntDefaultValue" not in jsonData
    assert "_private" not in jsonData

    reconstructedObject, _version = jsonfriendly.fromJson(jsonData, SerializeMe)

    assert reconstructedObject._private == 0

    # Ease comparison
    reconstructedObject._private = pythonObject._private

    assert pythonObject == reconstructedObject


def testJsonFriendlySerializationTypeMismatchInJsonText():
    @dataclasses.dataclass
    class DeserializeMe1:
        thing: int

    @dataclasses.dataclass
    class DeserializeMe2:
        thing: DeserializeMe1

    @dataclasses.dataclass
    class DeserializeMe3:
        thing: list[str]

    text = '{"thing": "bad type!"}'

    # Field is a primitive
    with pytest.raises(JsonTypeMismatch):
        jsonfriendly.fromJson(text, DeserializeMe1)

    # Field is another dataclass
    with pytest.raises(JsonTypeMismatch):
        jsonfriendly.fromJson(text, DeserializeMe2)

    # Field is a container
    with pytest.raises(JsonTypeMismatch):
        jsonfriendly.fromJson(text, DeserializeMe3)


def testJsonFriendlyPermissiveDeserializationIfDefaultAvailable():
    @dataclasses.dataclass
    class DeserializeMe:
        foo: int
        bar: int = 1234

    text = '{"foo": 200, "bar": "bad type!", "_version": -999}'

    # Field has a default value: be permissive
    result, version = jsonfriendly.fromJson(text, DeserializeMe)
    assert result.foo == 200
    assert result.bar == 1234
    assert version == ""


def testJsonFriendlyPermissiveDeserializationOfUnknownEnumValue():
    # e.g. a value written by a newer version of the app
    class Color(enum.StrEnum):
        Red = "red"

    @dataclasses.dataclass
    class DeserializeMe:
        foo: int
        color: Color = Color.Red

    @dataclasses.dataclass
    class DeserializeMeStrict:
        color: Color

    text = '{"foo": 200, "color": "ultraviolet"}'

    # Field has a default value: be permissive
    result, _version = jsonfriendly.fromJson(text, DeserializeMe)
    assert result.foo == 200
    assert result.color == Color.Red

    # No default value to fall back on
    with pytest.raises(ValueError):
        jsonfriendly.fromJson(text, DeserializeMeStrict)
