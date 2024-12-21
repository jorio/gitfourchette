# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *
from gitfourchette import colors


class DiffSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)

        self.highlightFormat = QTextCharFormat()
        self.highlightFormat.setBackground(colors.yellow)
        self.highlightFormat.setFontWeight(QFont.Weight.Bold)

        self.searchTerm = ""
        self.searching = False

    def setSearchTerm(self, term: str):
        self.searchTerm = term
        self.rehighlight()

    def setSearching(self, searching: bool):
        self.searching = searching
        self.rehighlight()

    def highlightBlock(self, text: str):
        if not self.searching or not self.searchTerm:
            return

        term = self.searchTerm
        termLength = len(term)

        text = text.lower()
        textLength = len(text)

        index = 0
        while index < textLength:
            index = text.find(term, index)
            if index < 0:
                break
            self.setFormat(index, termLength, self.highlightFormat)
            index += termLength
