# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from gitfourchette.qt import *
from gitfourchette.toolbox.iconbank import stockIcon


class ValidatorMultiplexer(QObject):
    """
    Provides input validation in multiple QLineEdits and manages the enabled
    state of a set of so-called "gated widgets" depending on the validity of
    the inputs.

    Each QLineEdit is associated to a separate validator function that takes an
    input string (the contents of the QLineEdit) and returns an error string.
    If the validator function returns an empty error string, the QLineEdit is
    deemed to have valid input.

    When the input in a QLineEdit is invalid, all gated widgets are disabled.
    The user can continue entering text into the QLineEdit, but a warning icon
    will appear in it, along with a tooltip reporting the error returned by the
    validator function.

    The gated widgets are enabled only if all QLineEdits contain valid input.

    A typical use case of this class is to disable the OK button in a QDialog
    until all QLineEdits in it are valid.
    """

    CallbackFunc = Callable[[str], str]

    @dataclass
    class Input:
        widget: QLineEdit
        validate: ValidatorMultiplexer.CallbackFunc
        showError: bool
        mustBeValid: bool
        errorButton: QAction
        error: str = ""

    gatedWidgets: list[QWidget]
    inputs: list[Input]
    toolTipDelay: QTimer

    def __init__(self, parent):
        super().__init__(parent)
        self.gatedWidgets = []
        self.inputs = []
        self.toolTipDelay = QTimer(self)
        self.toolTipDelay.setSingleShot(True)
        self.toolTipDelay.setInterval(500 if not APP_TESTMODE else 0)

    def setGatedWidgets(self, *args: QWidget):
        self.gatedWidgets = list(args)

    def connectInput(
            self,
            edit: QLineEdit,
            validate: Callable[[str], str],
            showError: bool = True,
            mustBeValid: bool = True):
        assert isinstance(edit, QLineEdit)
        assert callable(validate)

        errorButton: QAction = edit.addAction(stockIcon("achtung"), QLineEdit.ActionPosition.TrailingPosition)
        errorButton.setVisible(False)
        errorButton.setObjectName("ValidatorMultiplexerLineEditAction")

        newInput = ValidatorMultiplexer.Input(edit, validate, showError, mustBeValid, errorButton)

        self.inputs.append(newInput)
        edit.textChanged.connect(self.run)

        self.toolTipDelay.timeout.connect(lambda: self.showToolTip(newInput, False))
        errorButton.triggered.connect(lambda _: self.showToolTip(newInput, True))

    def run(self, silenceEmptyWarnings=False):
        self.toolTipDelay.stop()
        QToolTip.hideText()

        # Run validators on each input
        success = True
        for input in self.inputs:
            if not input.widget.isEnabled():  # Skip disabled inputs
                input.error = ""
                continue
            inputText = input.widget.text()
            input.error = input.validate(inputText)
            if input.error:
                success &= not input.mustBeValid
                if silenceEmptyWarnings and not inputText:
                    # Hide "cannot be empty" message, but do disable gated widgets if this input is required
                    input.error = ""

            input.errorButton.setToolTip(input.error)
            input.errorButton.setVisible(input.showError and bool(input.error))

            # Schedule tooltip only if failed input has focus
            if input.error and input.showError and input.widget.hasFocus():
                self.toolTipDelay.start()

        # Enable/disable gated widgets depending on validation success
        for w in self.gatedWidgets:
            w.setEnabled(success)

    def showToolTip(self, input: ValidatorMultiplexer.Input, atMousePosition=True):
        self.toolTipDelay.stop()  # Prevent delayed warning from appearing after clicking errorButton

        if not input.error:
            return

        if atMousePosition:
            pos = QCursor.pos()
        else:
            pos = QPoint(0, input.widget.height() // 2)
            pos = input.widget.mapToGlobal(pos)

        # Don't pass a parent widget to QToolTip.showText otherwise tooltip vanishes too quickly
        QToolTip.showText(pos, input.error)
