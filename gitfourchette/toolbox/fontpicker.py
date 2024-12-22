# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Font family/size picker composed of a QFontComboBox, a QSpinBox and a reset button.
"""

from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox.iconbank import stockIcon
from gitfourchette.toolbox.qsignalblockercontext import QSignalBlockerContext


class FontPicker(QWidget):
    assign = Signal(str, int)

    def __init__(self, parent):
        from gitfourchette.settings import qtIsNativeMacosStyle

        super().__init__(parent)

        self.defaultFont = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.currentFont = QFont(self.defaultFont)

        self.familyEdit = FontPicker.FamilyComboBox(self)
        self.familyEdit.currentFontChanged.connect(self.updateFamily)
        self.familyEdit.setMaximumWidth(250)
        self.familyEdit.setMaxVisibleItems(25)
        self.familyEdit.setToolTip(_("Hold {key} to show proportional fonts.",
                                     key=QKeySequence("Shift").toString(QKeySequence.SequenceFormat.NativeText)))

        self.sizeEdit = QSpinBox(self)
        self.sizeEdit.setRange(6, 72)
        self.sizeEdit.valueChanged.connect(self.updateSize)
        if not qtIsNativeMacosStyle():
            self.sizeEdit.setMinimumHeight(self.familyEdit.height())
        self.sizeEdit.setSuffix(" " + _("pt"))

        self.resetButton = QToolButton(self)
        self.resetButton.setText(_p("reset font to default", "Reset"))
        self.resetButton.setIcon(stockIcon("SP_RestoreDefaultsButton"))
        self.resetButton.setAutoRaise(True)
        self.resetButton.setToolTip(_("Reset to system default monospace font"))
        self.resetButton.clicked.connect(self.resetFont)

        QTimer.singleShot(0, self.refreshControls)

        layout = QHBoxLayout(self)
        layout.addWidget(self.familyEdit)
        layout.addWidget(self.sizeEdit)
        layout.addWidget(self.resetButton)
        layout.setContentsMargins(0, 0, 0, 0)

    def setCurrentFont(self, family: str, size: int) -> QFont:
        font = QFont(self.defaultFont)
        if family:
            font.setFamily(family)
        if size > 0:
            font.setPointSize(size)
        self.currentFont = font
        self.refreshControls()
        return font

    def resetFont(self):
        self.currentFont = QFont(self.defaultFont)
        self.refreshControls()
        self.fireAssign()

    def updateFamily(self, newFont: QFont):
        self.currentFont.setFamily(newFont.family())
        self.refreshControls(updateFontComboBox=False)
        self.fireAssign()

    def updateSize(self, newSize: int):
        self.currentFont.setPointSize(newSize)
        self.refreshControls()
        self.fireAssign()

    def refreshControls(self, updateFontComboBox=True):
        self.resetButton.setVisible(not self.isDefault())
        font = self.currentFont
        with QSignalBlockerContext(self.sizeEdit):
            self.sizeEdit.setValue(font.pointSize())
        if updateFontComboBox:
            strippedFont = QFont(font)
            strippedFont.setPointSize(10)
            with QSignalBlockerContext(self.familyEdit):
                self.familyEdit.setCurrentFont(strippedFont)

    def isDefault(self):
        cf = self.currentFont
        df = self.defaultFont
        return cf.family() == df.family() and cf.pointSize() == df.pointSize()

    def fireAssign(self):
        if self.isDefault():
            self.assign.emit("", 0)
        else:
            cf = self.currentFont
            self.assign.emit(cf.family(), cf.pointSize())

    class FamilyComboBox(QFontComboBox):
        def showPopup(self):
            currentFamily = self.currentFont().family()
            showAll = QGuiApplication.keyboardModifiers() == Qt.KeyboardModifier.ShiftModifier

            families = QFontDatabase.families()
            if not showAll:
                families = [fam for fam in families
                            if fam == currentFamily or QFontDatabase.isFixedPitch(fam)]

            with QSignalBlockerContext(self):
                self.clear()
                self.addItems(families)
                self.setCurrentText(currentFamily)

            super().showPopup()
