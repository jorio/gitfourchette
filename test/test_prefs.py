# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import textwrap

from gitfourchette.forms.prefsdialog import PrefsDialog
from gitfourchette.nav import NavLocator
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
    dlg = mainWindow.openPrefsDialog("shortTimeFormat")
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
    if WINDOWS:
        randomFamily = "Sans Serif"
    else:
        randomFamily = next(family for family in QFontDatabase.families(QFontDatabase.WritingSystem.Latin)
                            if not QFontDatabase.isPrivateFamily(family))
    assert defaultFamily != randomFamily

    # Change font setting, and accept
    dlg = mainWindow.openPrefsDialog("font")
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

    dlg = mainWindow.openPrefsDialog("font")
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
    dlg = mainWindow.openPrefsDialog("language")
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

    dlg = mainWindow.openPrefsDialog("showStrayCRs")
    checkBox: QCheckBox = dlg.findChild(QCheckBox, "prefctl_showStrayCRs")
    assert checkBox.isChecked()
    checkBox.setChecked(False)
    dlg.accept()

    assert rw.navLocator.isSimilarEnoughTo(NavLocator.inUnstaged("crlf.txt"))
    assert "<CRLF>" not in rw.diffView.toPlainText()


def testPrefsUserCommandsSyntaxHighlighter(mainWindow):
    # This is just for code coverage for now.
    dlg = mainWindow.openPrefsDialog("commands")
    editor: QPlainTextEdit = dlg.findChild(QPlainTextEdit, "prefctl_commands")
    editor.setPlainText(textwrap.dedent("""\
    # this is a standalone comment (not a command title)
    # -----
    ? hello $COMMIT $KOMMIT # Command &Title
    """))
    QTest.qWait(0)
    dlg.reject()


def testPrefsUserCommandsGuide(mainWindow):
    dlg = mainWindow.openPrefsDialog("language")
    if not QT5:  # Qt 5 doesn't want to hide the guide button initially, but I don't care about Qt 5
        assert not dlg.guideButton.isVisible()
    dlg.reject()

    dlg = mainWindow.openPrefsDialog("commands")
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
