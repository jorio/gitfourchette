# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os.path

import pygments.formatter
import pygments.lexer
import pygments.lexers
import pygments.style
import pygments.styles

from gitfourchette import colors
from gitfourchette.qt import *
from gitfourchette.toolbox import benchmark


class DiffSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)

        self.occurrenceFormat = QTextCharFormat()
        self.occurrenceFormat.setBackground(colors.yellow)
        self.occurrenceFormat.setFontWeight(QFont.Weight.Bold)

        self.searchTerm = ""
        self.searching = False

        self.lexer = None
        self.formatter = PygmentsFormatter(self)

        self.lexerClassCache = {}
        self.lexerInstanceCache = {}

    def setSearchTerm(self, term: str):
        self.searchTerm = term
        self.rehighlight()

    def setSearching(self, searching: bool):
        self.searching = searching
        self.rehighlight()

    @benchmark
    def setLexerFromPath(self, path: str):
        path = os.path.basename(path)
        if path.endswith(".svg"):  # help out pygments a bit here
            path += ".xml"

        # Find lexer class
        try:
            lexerClass = self.lexerClassCache[path]
        except KeyError:
            lexerClass = pygments.lexers.find_lexer_class_for_filename(path)
            self.lexerClassCache[path] = lexerClass

        # Find lexer instance
        if not lexerClass:
            self.lexer = None
        else:
            try:
                self.lexer = self.lexerInstanceCache[lexerClass]
            except KeyError:
                self.lexer = lexerClass()
                self.lexerInstanceCache[lexerClass] = self.lexer

    def highlightBlock(self, text: str):
        if self.searching and self.searchTerm:
            term = self.searchTerm
            termLength = len(term)

            text = text.lower()
            textLength = len(text)

            index = 0
            while index < textLength:
                index = text.find(term, index)
                if index < 0:
                    break
                self.setFormat(index, termLength, self.occurrenceFormat)
                index += termLength
        elif self.lexer is not None:
            pygments.highlight(text, self.lexer, self.formatter)


class PygmentsFormatter(pygments.formatter.Formatter):
    def __init__(self, highlighter: QSyntaxHighlighter):
        super().__init__()
        self.highlighter = highlighter
        self.colorscheme = {}

        syntaxStyle: pygments.style.StyleMeta = pygments.styles.get_style_by_name('default')

        for tokenType, styleForToken in syntaxStyle:
            charFormat = QTextCharFormat()
            if styleForToken['color']:
                color = QColor('#' + styleForToken['color'])
                charFormat.setForeground(color)
            # if styleForToken['bgcolor']:
            #     color = QColor('#' + styleForToken['bgcolor'])
            #     charFormat.setBackground(color)
            if styleForToken['bold']:
                charFormat.setFontWeight(QFont.Weight.Bold)
            if styleForToken['italic']:
                charFormat.setFontItalic(True)
            if styleForToken['underline']:
                charFormat.setFontUnderline(True)
            self.colorscheme[tokenType] = charFormat

    def format_unencoded(self, tokenSource, _outfile):
        column = 0
        highlighter = self.highlighter
        scheme = self.colorscheme
        for tokenType, value in tokenSource:
            tokenLength = len(value)
            try:
                charFormat = scheme[tokenType]
                highlighter.setFormat(column, tokenLength, charFormat)
            except KeyError:
                pass
            column += tokenLength
