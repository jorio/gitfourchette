# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import stockIcon


class SidebarFilter(QWidget):
    textChanged = Signal(str)

    @property
    def lineEdit(self) -> QLineEdit:
        return self._lineEdit

    @property
    def filterText(self) -> str:
        return self._lineEdit.text()

    def __init__(self, parent: QWidget):
        super().__init__(parent)

        self.setObjectName("SidebarFilter")

        self._lineEdit = QLineEdit(self)
        self._lineEdit.setPlaceholderText(_("Filter branches, tags, stashes…"))
        self._lineEdit.setClearButtonEnabled(True)
        self._lineEdit.setStyleSheet("border: 1px solid gray; border-radius: 5px;")
        self._lineEdit.addAction(stockIcon("magnifying-glass"), QLineEdit.ActionPosition.LeadingPosition)
        self._lineEdit.textChanged.connect(self._onTextChanged)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._lineEdit)

    def _onTextChanged(self, text: str):
        self.textChanged.emit(text)

    def clear(self):
        self._lineEdit.clear()

    def setFocus(self):
        self._lineEdit.setFocus()
        self._lineEdit.selectAll()
