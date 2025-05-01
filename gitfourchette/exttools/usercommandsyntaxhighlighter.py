# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import colors
from gitfourchette.qt import *
from gitfourchette.exttools.usercommand import UserCommand

try:
    from pygments.token import Token
except ImportError:  # pragma: no cover
    # If Pygments isn't available, UserCommandSyntaxHighlighter should never be instantiated!
    pass


class UserCommandSyntaxHighlighter(QSyntaxHighlighter):
    def __init__(self, parent):
        super().__init__(parent)

        from gitfourchette.syntax import LexerCache

        self.lexer = LexerCache.getLexerFromPath("GitFourchetteUserCommandsSyntaxHighlighter.bash", False)

        self.commentFormat = QTextCharFormat()
        self.commentFormat.setForeground(QColor(0x808080))

        self.titleFormat = QTextCharFormat(self.commentFormat)
        self.titleFormat.setFontWeight(QFont.Weight.Bold)
        self.titleFormat.setFontItalic(True)

        self.badTokenFormat = QTextCharFormat()
        self.badTokenFormat.setForeground(colors.red)

        self.goodTokenFormat = QTextCharFormat()
        self.goodTokenFormat.setForeground(colors.blue)
        self.goodTokenFormat.setFontWeight(QFont.Weight.Bold)

        self.acceleratorFormat = QTextCharFormat(self.titleFormat)
        self.acceleratorFormat.setFontUnderline(True)

    def highlightBlock(self, text: str):
        tokens = self.lexer.get_tokens(text)
        start = 0
        isCommandLine = False

        for tokenType, token in tokens:
            tokenLength = len(token)

            if token.startswith("$"):
                isValid = token in UserCommand.Token._value2member_map_
                self.setFormat(start, tokenLength,
                               self.goodTokenFormat if isValid else self.badTokenFormat)

            elif token.startswith(UserCommand.AlwaysConfirmPrefix) and not isCommandLine:
                self.setFormat(start, len(UserCommand.AlwaysConfirmPrefix), self.goodTokenFormat)

            elif tokenType == Token.Comment.Single:
                self.setFormat(start, tokenLength,
                               self.commentFormat if not isCommandLine else self.titleFormat)

                accelMatch = UserCommand.AcceleratorPattern.search(token)
                if accelMatch:
                    matchStart, matchEnd = accelMatch.span()
                    self.setFormat(start + matchStart, matchEnd - matchStart, self.acceleratorFormat)

            # Once we've seen at least one text token, we know that's a command line
            if tokenType == Token.Text:
                isCommandLine = True

            start += tokenLength
