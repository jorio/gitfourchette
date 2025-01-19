# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.qt import *
from gitfourchette.toolbox import ValidatorMultiplexer, setTabOrder


class TextInputDialog(QDialog):
    textAccepted = Signal(str)

    def __init__(self, parent: QWidget, title: str, label: str, subtitle: str = ""):
        super().__init__(parent)

        self.setWindowTitle(title)
        self.validator: ValidatorMultiplexer | None = None

        self.lineEdit = QLineEdit(self)

        self.buttonBox = QDialogButtonBox(self)
        self.buttonBox.setStandardButtons(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)

        layout = QGridLayout(self)

        if label:
            promptLabel = QLabel(label, parent=self)
            promptLabel.setTextFormat(Qt.TextFormat.AutoText)
            promptLabel.setWordWrap(True)
            layout.addWidget(promptLabel, 0, 0)

        layout.addWidget(self.lineEdit, 1, 0)
        layout.addWidget(self.buttonBox, 3, 0, 1, -1)
        # Leave row 2 free for setExtraWidget
        self.contentsLayout = layout

        convertToBrandedDialog(self, subtitleText=subtitle)

        self.lineEdit.setFocus()

        # This size isn't guaranteed. But it'll expand the dialog horizontally if the label is shorter.
        self.setMinimumWidth(512)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        # Connect signals
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.accepted.connect(lambda: self.textAccepted.emit(self.lineEdit.text()))

    def setText(self, text: str):
        assert self.validator is None, "initial text value must be set before installing the validator"
        self.lineEdit.setText(text)
        self.lineEdit.selectAll()

    def setValidator(self, validate: ValidatorMultiplexer.CallbackFunc):
        assert self.validator is None, "validator is already set!"
        validator = ValidatorMultiplexer(self)
        validator.setGatedWidgets(self.okButton)
        validator.connectInput(self.lineEdit, validate)
        validator.run()
        self.validator = validator

    def setExtraWidget(self, widget: QWidget):
        self.contentsLayout.addWidget(widget, 2, 0)
        setTabOrder(self.lineEdit, widget, self.buttonBox)

    @property
    def okButton(self) -> QPushButton:
        return self.buttonBox.button(QDialogButtonBox.StandardButton.Ok)

    def show(self):
        super().show()
        self.setMaximumHeight(self.height())
