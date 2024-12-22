# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os.path
from contextlib import suppress

import pygments.lexers
import pygments.styles
from pygments.lexer import Lexer
from pygments.token import Token

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

        self.lexer: Lexer | None = None
        self.scheme: dict[Token, QTextCharFormat] = {}

    def setSearchTerm(self, term: str):
        self.searchTerm = term
        self.rehighlight()

    def setSearching(self, searching: bool):
        self.searching = searching
        self.rehighlight()

    def setLexerFromPath(self, path: str):
        self.lexer = LexerCache.getLexerFromPath(path)

    def highlightBlock(self, text: str):
        if self.searching and self.searchTerm:
            # Highlight occurrences of search term
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
            # Pygments syntax highlighting
            column = 0
            scheme = self.scheme
            tokens = self.lexer.get_tokens(text)
            for tokenType, tokenValue in tokens:
                tokenLength = len(tokenValue)
                try:
                    charFormat = scheme[tokenType]
                    self.setFormat(column, tokenLength, charFormat)
                except KeyError:
                    continue
                finally:
                    column += tokenLength

    def setColorScheme(self, styleName='default'):
        self.scheme = {}
        style = pygments.styles.get_style_by_name(styleName)

        for tokenType, styleForToken in style:
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
            self.scheme[tokenType] = charFormat


class LexerCache:
    """
    Fast drop-in replacement for pygments.lexers.get_lexer_for_filename().
    """

    lexerAliases: dict[str, str] = {}
    " Lexer aliases by file extensions or verbatim file names "

    lexerInstances: dict[str, Lexer] = {}
    " Lexer instances by aliases "

    @classmethod
    @benchmark
    def getLexerFromPath(cls, path: str) -> Lexer | None:
        if not cls.lexerAliases:
            cls.warmUp()

        # Find lexer alias by extension
        _dummy, ext = os.path.splitext(path)
        try:
            alias = cls.lexerAliases[ext]
        except KeyError:
            # Try verbatim name (e.g. 'Makefile')
            fileName = os.path.basename(path)
            alias = cls.lexerAliases.get(fileName, "")

        # Bail early
        if not alias:
            return None

        # Get existing lexer instance
        with suppress(KeyError):
            return cls.lexerInstances[alias]

        # Instantiate new lexer.
        # (Passing in an alias from pygments' builtin lexers shouldn't
        # tap into Pygments plugins, so this should be fairly fast)
        lexer = pygments.lexers.get_lexer_by_name(alias)
        cls.lexerInstances[alias] = lexer
        return lexer

    @classmethod
    @benchmark
    def warmUp(cls):
        aliasTable = {}

        # Significant speedup with plugins=False
        for _name, aliases, patterns, _mimeTypes in pygments.lexers.get_all_lexers(plugins=False):
            if not patterns or not aliases:
                continue
            alias = aliases[0]
            for pattern in patterns:
                if pattern.startswith('*.') and not pattern.endswith('*'):
                    # Simple file extension
                    ext = pattern[1:]
                    aliasTable[ext] = alias
                elif '*' not in pattern:
                    # Verbatim file name
                    aliasTable[pattern] = alias

        # Patch missing extensions
        # TODO: What's pygments' rationale for omitting '*.svg'?
        with suppress(KeyError):
            aliasTable['.svg'] = aliasTable['.xml']

        cls.lexerAliases = aliasTable
