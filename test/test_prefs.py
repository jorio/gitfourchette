# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

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
    dlg.tabs.setCurrentIndex(0)
    dlg.reject()

    # Open prefs, navigate to some tab and reject
    dlg = openPrefs()
    assert dlg.tabs.currentIndex() == 0
    dlg.tabs.setCurrentIndex(2)
    dlg.reject()

    # Open prefs again and check that the tab was restored
    dlg = openPrefs()
    assert dlg.tabs.currentIndex() == 2
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
    randomFamily = next(family for family in QFontDatabase.families(QFontDatabase.WritingSystem.Latin)
                        if not QFontDatabase.isPrivateFamily(family))
    assert defaultFamily != randomFamily

    # Change font setting, and accept
    dlg = mainWindow.openPrefsDialog("font")
    fontPicker: FontPicker = dlg.findChild(FontPicker, "prefctl_font")
    assert not fontPicker.resetButton.isVisible()
    fontPicker.familyEdit.showPopup()
    fontPicker.familyEdit.setCurrentFont(QFont(randomFamily))
    fontPicker.familyEdit.hidePopup()
    assert fontPicker.resetButton.isVisible()
    dlg.accept()
    assert randomFamily == rw.diffView.document().defaultFont().family()

    dlg = mainWindow.openPrefsDialog("font")
    fontPicker: FontPicker = dlg.findChild(FontPicker, "prefctl_font")
    assert fontPicker.resetButton.isVisible()
    fontPicker.resetButton.click()
    assert not fontPicker.resetButton.isVisible()
    dlg.accept()
    assert defaultFamily == rw.diffView.document().defaultFont().family()


def testPrefsLanguageControl(tempDir, mainWindow):
    # Open a repo so that refreshPrefs functions are exercized in coverage
    wd = unpackRepo(tempDir)
    mainWindow.openRepo(wd)

    # Change font setting, and accept
    dlg = mainWindow.openPrefsDialog("language")
    comboBox: QComboBox = dlg.findChild(QWidget, "prefctl_language")
    qcbSetIndex(comboBox, "fran.ais")
    comboBox.activated.emit(comboBox.currentIndex())
    dlg.accept()
    acceptQMessageBox(mainWindow, "application des pr.f.rences")


def testPrefsRecreateDiffDocument(tempDir, mainWindow):
    wd = unpackRepo(tempDir)
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
