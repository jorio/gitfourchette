# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import base64
import dataclasses
import enum
import json
import logging
import textwrap

from gitfourchette import settings
from gitfourchette.forms.prefsdialog import PrefsDialog
from gitfourchette.nav import NavLocator
from gitfourchette.prefsfile import PrefsFile
from gitfourchette.toolbox.fontpicker import FontPicker
from .util import *


def testPrefsDialog(tempDir, mainWindow):
    def openPrefs() -> PrefsDialog:
        triggerMenuAction(mainWindow.menuBar(), "file/settings")
        return findQDialog(mainWindow, "settings")

    # Open a repo so that refreshPrefs functions are exercised in coverage
    wd = unpackRepo(tempDir)
    mainWindow.openRepo(wd)

    # Open prefs, reset to first tab to prevent spillage from any previous test
    dlg = openPrefs()
    dlg.setCategory(0)
    dlg.reject()

    # Open prefs, navigate to some tab and reject
    dlg = openPrefs()
    assert dlg.stackedWidget.currentIndex() == 0
    dlg.setCategory(2)
    dlg.reject()

    # Open prefs again and check that the tab was restored
    dlg = openPrefs()
    assert dlg.stackedWidget.currentIndex() == 2
    dlg.reject()

    # Change statusbar setting, and cancel
    assert mainWindow.statusBar().isVisible()
    dlg = openPrefs()
    checkBox: QCheckBox = dlg.findChild(QCheckBox, "prefctl_showStatusBar")
    assert checkBox.isChecked()
    checkBox.setChecked(False)
    dlg.reject()
    assert mainWindow.statusBar().isVisible()

    # Change statusbar setting, and accept
    dlg = openPrefs()
    checkBox: QCheckBox = dlg.findChild(QCheckBox, "prefctl_showStatusBar")
    assert checkBox.isChecked()
    checkBox.setChecked(False)
    dlg.accept()
    assert not mainWindow.statusBar().isVisible()

    # Change topo setting, and accept
    dlg = openPrefs()
    comboBox: QComboBox = dlg.findChild(QComboBox, "prefctl_chronologicalOrder")
    qcbSetIndex(comboBox, "topological")
    dlg.accept()
    acceptQMessageBox(mainWindow, "take effect.+reload")


def testPrefsComboBoxWithPreview(tempDir, mainWindow):
    # Play with QComboBoxWithPreview (for coverage)
    dlg = GFApplication.instance().openPrefsDialog("shortTimeFormat")
    comboBox: QComboBox = dlg.findChild(QWidget, "prefctl_shortTimeFormat").findChild(QComboBox)
    comboBox.setFocus()
    QTest.keyClick(comboBox, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    QTest.qWait(0)
    QTest.keyClick(comboBox, Qt.Key.Key_Down)
    QTest.qWait(0)
    QTest.keyClick(comboBox, Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    QTest.qWait(0)  # trigger ItemDelegate.paint
    comboBox.setFocus()
    QTest.keyClicks(comboBox, "MMMM")  # trigger activation of out-of-bounds index
    QTest.keyClick(comboBox, Qt.Key.Key_Enter)
    dlg.reject()


def testPrefsFontControl(tempDir, mainWindow):
    # Open a repo so that refreshPrefs functions are exercized in coverage
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    rw.jump(NavLocator.inCommit(rw.repo.head_commit_id))
    defaultFamily = rw.diffView.document().defaultFont().family()
    if WINDOWS and OFFSCREEN:
        randomFamily = "Sans Serif"
    else:
        randomFamily = next(family for family in QFontDatabase.families(QFontDatabase.WritingSystem.Latin)
                            if not QFontDatabase.isPrivateFamily(family))
    assert defaultFamily != randomFamily

    # Change font setting, and accept
    dlg = GFApplication.instance().openPrefsDialog("font")
    fontPicker: FontPicker = dlg.findChild(FontPicker, "prefctl_font")
    assert not fontPicker.resetButton.isEnabled()
    fontPicker.familyEdit.showPopup()
    fontPicker.familyEdit.setCurrentFont(QFont(randomFamily))
    fontPicker.familyEdit.hidePopup()
    assert fontPicker.resetButton.isEnabled()
    fontPicker.sizeEdit.setValue(27)
    dlg.accept()
    effectiveFont = rw.diffView.document().defaultFont()
    assert effectiveFont.family() == randomFamily
    assert effectiveFont.pointSize() == 27

    dlg = GFApplication.instance().openPrefsDialog("font")
    fontPicker: FontPicker = dlg.findChild(FontPicker, "prefctl_font")
    assert fontPicker.resetButton.isEnabled()
    fontPicker.resetButton.click()
    assert not fontPicker.resetButton.isEnabled()
    dlg.accept()
    effectiveFont = rw.diffView.document().defaultFont()
    assert effectiveFont.family() == defaultFamily


def testPrefsLanguageControl(tempDir, mainWindow):
    # Open a repo so that refreshPrefs functions are exercized in coverage
    wd = unpackRepo(tempDir)
    mainWindow.openRepo(wd)

    # Change font setting, and accept
    dlg = GFApplication.instance().openPrefsDialog("language")
    comboBox: QComboBox = dlg.findChild(QWidget, "prefctl_language")
    qcbSetIndex(comboBox, "fran.ais")
    dlg.accept()
    acceptQMessageBox(mainWindow, "application des pr.f.rences")


def testPrefsRecreateDiffDocument(tempDir, mainWindow):
    wd = unpackRepo(tempDir)

    if WINDOWS:
        with RepoContext(wd) as repo:
            repo.config["core.autocrlf"] = "false"

    writeFile(f"{wd}/crlf.txt", "hello\r\nthat's it")
    rw = mainWindow.openRepo(wd)

    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged("crlf.txt"))
    assert "<CRLF>" in rw.diffView.toPlainText()

    dlg = GFApplication.instance().openPrefsDialog("showStrayCRs")
    checkBox: QCheckBox = dlg.findChild(QCheckBox, "prefctl_showStrayCRs")
    assert checkBox.isChecked()
    checkBox.setChecked(False)
    dlg.accept()

    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged("crlf.txt"))
    assert "<CRLF>" not in rw.diffView.toPlainText()


def testPrefsShowWhitespace(tempDir, mainWindow):
    whitespaceFlags = QTextOption.Flag.ShowTabsAndSpaces

    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/whitespace.txt", "x\t y\n")

    rw = mainWindow.openRepo(wd)
    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged("whitespace.txt"))

    def whitespaceFlagsSet() -> bool:
        f = rw.diffView.document().defaultTextOption().flags()
        return (f & whitespaceFlags) == whitespaceFlags

    assert not whitespaceFlagsSet()

    dlg = GFApplication.instance().openPrefsDialog("showWhitespace")
    checkBox: QCheckBox = dlg.findChild(QCheckBox, "prefctl_showWhitespace")
    assert checkBox is not None
    assert not checkBox.isChecked()
    checkBox.setChecked(True)
    dlg.accept()

    assert settings.prefs.showWhitespace
    assert whitespaceFlagsSet()

    dlg = GFApplication.instance().openPrefsDialog("showWhitespace")
    checkBox: QCheckBox = dlg.findChild(QCheckBox, "prefctl_showWhitespace")
    checkBox.setChecked(False)
    dlg.accept()

    assert not settings.prefs.showWhitespace
    assert not whitespaceFlagsSet()


def testPrefsUserCommandsSyntaxHighlighter(mainWindow):
    # This is just for code coverage for now.
    dlg = GFApplication.instance().openPrefsDialog("commands")
    editor: QPlainTextEdit = dlg.findChild(QPlainTextEdit, "prefctl_commands")
    editor.setPlainText(textwrap.dedent("""\
    # this is a standalone comment (not a command title)
    # -----
    ? hello $COMMIT $KOMMIT # Command &Title
    """))
    QTest.qWait(0)
    dlg.reject()


def testPrefsUserCommandsGuide(mainWindow):
    dlg = GFApplication.instance().openPrefsDialog("language")
    if not QT5:  # Qt 5 doesn't want to hide the guide button initially, but I don't care about Qt 5
        assert not dlg.guideButton.isVisible()
    dlg.reject()

    dlg = GFApplication.instance().openPrefsDialog("commands")
    guideBrowser = dlg.guideBrowser
    guideButton = dlg.guideButton
    assert guideButton.isVisible()
    assert not guideBrowser.isVisible()

    # Click button to show, click button again to hide
    guideButton.click()
    assert guideBrowser.isVisible()
    assert guideButton.isChecked()
    guideButton.click()
    assert not guideBrowser.isVisible()
    assert not guideButton.isChecked()

    dlg.reject()


def testPrefsQtStyleVariantPicker(mainWindow):
    accent1 = mainWindow.palette().highlight().color()

    dlg = GFApplication.instance().openPrefsDialog("qtStyle")

    group: QWidget = dlg.findChild(QWidget, "prefctl_qtStyle")
    comboBoxes: list[QComboBox] = group.findChildren(QComboBox)

    stylePicker = comboBoxes[0]
    variantPicker = comboBoxes[1]

    assert stylePicker.isVisible()
    assert not variantPicker.isVisible()

    qcbSetIndex(stylePicker, APP_DISPLAY_NAME)
    assert variantPicker.isVisible()
    assert variantPicker.currentText().lower() == "system colors"

    qcbSetIndex(variantPicker, "dark pink")
    dlg.accept()

    accent2 = mainWindow.palette().highlight().color()
    assert accent1 != accent2


class _SampleIntEnum(enum.IntEnum):
    Zero = 0
    One = 1
    Two = 2


class _SampleStrEnum(enum.StrEnum):
    Apple = "apple"
    Banana = "banana"


@dataclasses.dataclass
class _SamplePrefs(PrefsFile):
    _filename = "sample-prefs.json"
    _parentDir = ""

    _privateField: int = 0
    myInt: int = 42
    myStr: str = "hello"
    myBool: bool = True
    myBytes: bytes = b""
    mySet: set = dataclasses.field(default_factory=set)
    myList: list[str] = dataclasses.field(default_factory=list)
    myDict: dict[str, int] = dataclasses.field(default_factory=dict)
    myIntEnum: _SampleIntEnum = _SampleIntEnum.Zero
    myStrEnum: _SampleStrEnum = _SampleStrEnum.Apple
    mySignature: Signature | None = None
    myOptionalInt: int | None = None

    def getParentDir(self):
        return self._parentDir


def _makeSamplePrefs(tempDir, jsonText: str | None = None) -> _SamplePrefs:
    prefs = _SamplePrefs()
    prefs._parentDir = tempDir.name
    if jsonText is not None:
        writeFile(os.path.join(tempDir.name, prefs._filename), jsonText)
    return prefs


def _assertSamplePrefsAreDefaults(prefs: _SamplePrefs):
    assert prefs == _SamplePrefs(), "all fields should still have their default values"


def testPrefsFileLoadMissingFile(tempDir):
    prefs = _makeSamplePrefs(tempDir)
    assert not prefs.load()
    _assertSamplePrefsAreDefaults(prefs)

    # No parent directory at all
    prefs._parentDir = ""
    assert not prefs.load()
    assert prefs.write() == ""
    _assertSamplePrefsAreDefaults(prefs)


def testPrefsFileWriteWithoutMakeDirs(tempDir):
    prefs = _makeSamplePrefs(tempDir)
    prefs._parentDir = os.path.join(tempDir.name, "doesnotexist")
    prefs._allowMakeDirs = False
    prefs.myInt = 1
    assert prefs.write() == ""
    assert not os.path.exists(prefs._parentDir)


def testPrefsFileLoadInvalidJson(tempDir, caplog):
    prefs = _makeSamplePrefs(tempDir, '{"myInt": 5, "myStr": "oops"')  # truncated JSON
    assert not prefs.load()
    _assertSamplePrefsAreDefaults(prefs)
    assert any(r.levelno == logging.WARNING and "sample-prefs.json" in r.getMessage() for r in caplog.records)


def testPrefsFileLoadInvalidUtf8(tempDir):
    prefs = _makeSamplePrefs(tempDir)
    Path(tempDir.name, prefs._filename).write_bytes(b'{"myStr": "\xff\xfe\xfa"}')
    assert not prefs.load()
    _assertSamplePrefsAreDefaults(prefs)


@pytest.mark.parametrize("jsonText", ['[1, 2, 3]', '"hello"', '123', 'null', 'true'])
def testPrefsFileLoadTopLevelNotDict(tempDir, caplog, jsonText):
    prefs = _makeSamplePrefs(tempDir, jsonText)
    assert not prefs.load()
    _assertSamplePrefsAreDefaults(prefs)
    assert any("not a JSON dict" in r.getMessage() for r in caplog.records)


def testPrefsFileLoadDropsUnknownAndPrivateKeys(tempDir, caplog):
    prefs = _makeSamplePrefs(tempDir, json.dumps({
        "_version": "1.2.3",
        "myInt": 7,
        "bogusKey": "bogus",
        "_privateField": 99,
        "_somethingElse": 1,
        "_dirty": True,
    }))
    assert prefs.load()

    assert prefs.myInt == 7
    assert prefs._privateField == 0
    assert not hasattr(prefs, "bogusKey")
    assert not hasattr(prefs, "_somethingElse")
    assert not prefs.isDirty()
    assert prefs._fileVersion == "1.2.3"

    messages = [r.getMessage() for r in caplog.records]
    assert any("dropping key: bogusKey" in m for m in messages)
    assert any("dropping key: _privateField" in m for m in messages)
    assert any("dropping key: _somethingElse" in m for m in messages)
    assert any("dropping key: _dirty" in m for m in messages)


def testPrefsFileLoadIgnoresNonStringVersion(tempDir):
    prefs = _makeSamplePrefs(tempDir, json.dumps({"_version": 123, "myInt": 8}))
    assert prefs.load()
    assert prefs._fileVersion == ""
    assert prefs.myInt == 8


def testPrefsFileLoadNullValuesKeepDefaults(tempDir):
    prefs = _makeSamplePrefs(tempDir, json.dumps({
        "myInt": None,
        "myStr": None,
        "mySignature": None,
        "myOptionalInt": None,
        "myBool": False,
    }))
    assert prefs.load()
    assert prefs.myInt == 42
    assert prefs.myStr == "hello"
    assert prefs.mySignature is None
    assert prefs.myOptionalInt is None
    assert prefs.myBool is False


def testPrefsFileLoadWrongTypesKeepDefaults(tempDir, caplog):
    prefs = _makeSamplePrefs(tempDir, json.dumps({
        "myIntEnum": "two",              # str where IntEnum (int) expected
        "myStrEnum": 1,                  # int where StrEnum (str) expected
        "myBytes": 1234,                 # int where base64 str expected
        "mySet": "a,b,c",                # str where list expected
        "mySignature": "Toto <toto@example.com>",  # str where dict expected
        "myInt": 1234,                   # valid
    }))
    assert prefs.load()

    assert prefs.myIntEnum == _SampleIntEnum.Zero
    assert prefs.myStrEnum == _SampleStrEnum.Apple
    assert prefs.myBytes == b""
    assert prefs.mySet == set()
    assert prefs.mySignature is None
    assert prefs.myInt == 1234

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    for key in ["myIntEnum", "myStrEnum", "myBytes", "mySet", "mySignature"]:
        assert any(f"{key}: unexpected JSON field type" in m for m in warnings), key
    assert not any("myInt:" in m for m in warnings)


def testPrefsFileLoadInvalidValuesKeepDefaults(tempDir, caplog):
    prefs = _makeSamplePrefs(tempDir, json.dumps({
        "myIntEnum": 999,                # not a member of the IntEnum
        "myStrEnum": "cherry",           # not a member of the StrEnum
        "myBytes": "!!not base64!!",     # bogus base64 (binascii.Error is a ValueError)
        "mySignature": {"name": "Toto", "email": "toto@example.com", "time": "noon", "offset": 0},
        "myStr": "valid",
    }))
    assert prefs.load()

    assert prefs.myIntEnum == _SampleIntEnum.Zero
    assert prefs.myStrEnum == _SampleStrEnum.Apple
    assert prefs.myBytes == b""
    assert prefs.mySignature is None
    assert prefs.myStr == "valid"

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    for key in ["myIntEnum", "myStrEnum", "myBytes", "mySignature"]:
        assert any(f"sample-prefs.json: {key}:" in m for m in warnings), key


def testPrefsFileDecodeValidValues(tempDir):
    signature = Signature("Toto", "toto@example.com", 1672600000, 60)
    prefs = _makeSamplePrefs(tempDir, json.dumps({
        "myIntEnum": 2,
        "myStrEnum": "banana",
        "myBytes": base64.b64encode(b"\x00\x01binary\xff").decode("ascii"),
        "mySet": ["x", "y", "x"],
        "myList": ["b", "a"],
        "myDict": {"k": 1},
        "mySignature": {"name": "Toto", "email": "toto@example.com", "time": 1672600000, "offset": 60},
        "myOptionalInt": 5,
        "myBool": False,
    }))
    assert prefs.load()

    assert prefs.myIntEnum is _SampleIntEnum.Two
    assert prefs.myStrEnum is _SampleStrEnum.Banana
    assert prefs.myBytes == b"\x00\x01binary\xff"
    assert prefs.mySet == {"x", "y"}
    assert type(prefs.mySet) is set
    assert prefs.myList == ["b", "a"]
    assert prefs.myDict == {"k": 1}
    assert prefs.mySignature == signature
    assert prefs.mySignature.offset == 60
    assert prefs.myOptionalInt == 5
    assert prefs.myBool is False


def testPrefsFileEncodeDecodeRoundTrip(tempDir):
    signature = Signature("Ünïcødé Person", "uni@example.com", 1700000000, -120)

    prefs = _makeSamplePrefs(tempDir)
    prefs.myInt = -3
    prefs.myStr = "round trip ✓"
    prefs.myBool = False
    prefs.myBytes = bytes(range(256))
    prefs.mySet = {"one", "two", "three"}
    prefs.myList = ["z", "y"]
    prefs.myDict = {"a": 1, "b": 2}
    prefs.myIntEnum = _SampleIntEnum.One
    prefs.myStrEnum = _SampleStrEnum.Banana
    prefs.mySignature = signature
    prefs.myOptionalInt = 0
    prefs._privateField = 123
    prefs.setDirty()
    assert prefs.isDirty()

    path = prefs.write()
    assert path == os.path.join(tempDir.name, "sample-prefs.json")
    assert not prefs.isDirty()

    # Inspect the encoded JSON
    with open(path, encoding="utf-8") as f:
        blob = json.load(f)
    assert blob["_version"] == APP_VERSION
    assert "_privateField" not in blob
    assert blob["myIntEnum"] == 1
    assert blob["myStrEnum"] == "banana"
    assert blob["myBytes"] == base64.b64encode(bytes(range(256))).decode("ascii")
    assert sorted(blob["mySet"]) == ["one", "three", "two"]
    assert blob["mySignature"] == {"name": signature.name, "email": signature.email,
                                   "time": signature.time, "offset": signature.offset}

    # Decode it back into a fresh object
    prefs2 = _makeSamplePrefs(tempDir)
    assert prefs2.load()
    assert prefs2._fileVersion == APP_VERSION
    assert prefs2._privateField == 0
    for f in dataclasses.fields(_SamplePrefs):
        if f.name.startswith("_"):
            continue
        assert getattr(prefs2, f.name) == getattr(prefs, f.name), f.name
    assert type(prefs2.myIntEnum) is _SampleIntEnum
    assert type(prefs2.myStrEnum) is _SampleStrEnum
    assert type(prefs2.mySet) is set
    assert type(prefs2.myBytes) is bytes
    assert type(prefs2.mySignature) is Signature

    # Reset to defaults and write: the file should be deleted
    prefs2.reset()
    _assertSamplePrefsAreDefaults(prefs2)
    assert prefs2.write() == ""
    assert not os.path.exists(path)

    # Writing defaults again when the file doesn't exist: no file created
    assert prefs2.write() == ""
    assert not os.path.exists(path)


@pytest.mark.parametrize("value", [
    True,
    b"hello",
    {"a", "b"},
    Signature("Toto", "toto@example.com", 1234, 30),
    _SampleIntEnum.Two,
    _SampleStrEnum.Banana,
])
def testPrefsFileEncodeDecodeValue(value):
    encoded = PrefsFile.encode(value)
    json.dumps(encoded)  # must be JSON-friendly
    decoded = PrefsFile.decode(json.loads(json.dumps(encoded)), type(value))
    assert decoded == value
    assert type(decoded) is type(value)


@pytest.mark.parametrize("signature", [
    {"name": "Toto"},
    {"name": "Toto", "email": "toto@example.com", "time": None, "offset": 0},
])
def testPrefsFileLoadSignatureMissingKeys(tempDir, signature):
    prefs = _makeSamplePrefs(tempDir, json.dumps({
        "mySignature": signature,
        "myInt": 3,
    }))
    assert prefs.load()
    assert prefs.mySignature is None
    assert prefs.myInt == 3


@pytest.mark.parametrize("myInt", ["not an int", True, 1.5])
def testPrefsFileLoadPlainTypeMismatch(tempDir, myInt):
    prefs = _makeSamplePrefs(tempDir, json.dumps({
        "myInt": myInt,
        "myBool": "yes",
        "myStr": 123,
        "myList": "not a list",
        "myDict": ["not", "a", "dict"],
        "myOptionalInt": "nope",
    }))
    assert prefs.load()
    assert prefs.myInt == 42
    assert prefs.myBool is True
    assert prefs.myStr == "hello"
    assert prefs.myList == []
    assert prefs.myDict == {}
    assert prefs.myOptionalInt is None


def testRepoPrefsCorruptFile(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
    writeFile(f"{wd}/.git/{APP_SYSTEM_NAME}.json", '{"draftCommitMessage": "oops"')  # truncated JSON
    rw = mainWindow.openRepo(wd)
    assert rw.repoModel.prefs.draftCommitMessage == ""

    mainWindow.closeAllTabs()
    writeFile(f"{wd}/.git/{APP_SYSTEM_NAME}.json", json.dumps({
        "draftCommitMessage": "hello",
        "sortTags": "bogus",
        "hidePatterns": "bogus",
        "draftCommitSignature": {"name": "missing email, time, offset"},
        "draftAmendMessage": 123,
        "unknownKey": 1,
    }))
    rw = mainWindow.openRepo(wd)
    assert rw.repoModel.prefs.draftCommitMessage == "hello"
    assert rw.repoModel.prefs.hidePatterns == set()
    assert rw.repoModel.prefs.draftCommitSignature is None
    assert rw.repoModel.prefs.draftAmendMessage == ""
