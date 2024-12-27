# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging

from pygments.style import StyleMeta
from pygments.token import Token

from gitfourchette.diffview.lexjobcache import LexJobCache
from gitfourchette import colors
from gitfourchette import settings
from gitfourchette.diffview.diffdocument import DiffDocument, LineData
from gitfourchette.diffview.lexjob import LexJob
from gitfourchette.qt import *
from gitfourchette.toolbox import benchmark, CallbackAccumulator

logger = logging.getLogger(__name__)


class DiffSyntaxHighlighter(QSyntaxHighlighter):
    diffDocument: DiffDocument | None
    scheme: dict[Token, QTextCharFormat]
    highContrastScheme: dict[Token, QTextCharFormat]
    oldLexJob: LexJob | None
    newLexJob: LexJob | None

    def __init__(self, parent):
        super().__init__(parent)

        self.diffDocument = None
        self.scheme: dict[Token, QTextCharFormat] = {}
        self.highContrastScheme: dict[Token, QTextCharFormat] = {}

        self.occurrenceFormat = QTextCharFormat()
        self.occurrenceFormat.setBackground(colors.yellow)
        self.occurrenceFormat.setFontWeight(QFont.Weight.Bold)

        self.searchTerm = ""
        self.searching = False

        self.oldLexJob = None
        self.newLexJob = None

    @benchmark
    def setDiffDocument(self, diffDocument: DiffDocument):
        self.diffDocument = diffDocument
        self.setDocument(diffDocument.document)

        # Prime lex jobs
        self.stopLexJobs()
        if diffDocument.lexer:
            try:
                self.oldLexJob = LexJobCache.checkOut(diffDocument.oldData)
                logger.debug("Reusing cached LexJob for old document")
            except KeyError:
                self.oldLexJob = LexJob(diffDocument.lexer, diffDocument.oldData)

            try:
                self.newLexJob = LexJobCache.checkOut(diffDocument.newData)
                logger.debug("Reusing cached LexJob for new document")
            except KeyError:
                self.newLexJob = LexJob(diffDocument.lexer, diffDocument.newData)

            for job in self.oldLexJob, self.newLexJob:
                job.pulse.connect(self.onLexPulse)

    def setSearchTerm(self, term: str):
        self.searchTerm = term
        self.rehighlight()

    def setSearching(self, searching: bool):
        self.searching = searching
        self.rehighlight()

    def stopLexJobs(self):
        for job in self.oldLexJob, self.newLexJob:
            if job is None:
                continue
            job.stop()
            job.pulse.disconnect(self.onLexPulse)
            LexJobCache.checkIn(job)
        self.oldLexJob = None
        self.newLexJob = None

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

        elif self.scheme and self.oldLexJob and self.newLexJob:
            # Pygments syntax highlighting
            blockNumber = self.currentBlock().blockNumber()

            lineData: LineData = self.diffDocument.lineData[blockNumber]
            diffLine = lineData.diffLine
            if diffLine is None:  # Hunk header, etc.
                return

            column = 0
            scheme = self.highContrastScheme if diffLine.origin in "+-" else self.scheme

            if diffLine.origin == '+':
                lexJob = self.newLexJob
                lineNumber = diffLine.new_lineno
            else:
                lexJob = self.oldLexJob
                lineNumber = diffLine.old_lineno

            boundary = len(text) - lineData.trailerLength

            for tokenType, tokenLength in lexJob.tokens(lineNumber, text):
                try:
                    charFormat = scheme[tokenType]
                    self.setFormat(column, tokenLength, charFormat)
                except KeyError:
                    pass
                column += tokenLength
                if column >= boundary:
                    break

            if settings.DEVDEBUG and lexJob.lexingComplete and column != boundary:  # pragma: no cover
                # Overstep may occur in low-quality lexing (not a big deal, so
                # we ignore that case) or when the file isn't decoded properly.
                logger.warning(f"Syntax highlighting overstep on line -{diffLine.old_lineno}+{diffLine.new_lineno} {column} != {boundary}")

    def setColorScheme(self, style: StyleMeta | None):
        self.scheme = {}
        self.highContrastScheme = {}

        if style is None:
            return

        # Unpack style colors
        # (Intentionally skipping 'bgcolor' to prevent confusion with red/green backgrounds)
        for tokenType, styleForToken in style:
            charFormat = QTextCharFormat()
            if styleForToken['color']:
                assert not styleForToken['color'].startswith('#')
                color = QColor('#' + styleForToken['color'])
                charFormat.setForeground(color)
            if styleForToken['bold']:
                charFormat.setFontWeight(QFont.Weight.Bold)
            if styleForToken['italic']:
                charFormat.setFontItalic(True)
            if styleForToken['underline']:
                charFormat.setFontUnderline(True)
            self.scheme[tokenType] = charFormat

        # Prepare a high-contrast alternative where colors pop against red/green backgrounds
        backgroundColor = QColor(style.background_color)
        isDarkBackground = backgroundColor.lightnessF() < .5

        for tokenType, lowContrastCharFormat in self.scheme.items():
            charFormat = QTextCharFormat(lowContrastCharFormat)

            fgColor = charFormat.foreground().color()
            if isDarkBackground:
                fgColor = fgColor.lighter(150)
            else:
                fgColor = fgColor.darker(130)

            charFormat.setForeground(fgColor)
            charFormat.clearBackground()

            self.highContrastScheme[tokenType] = charFormat

    @CallbackAccumulator.deferredMethod
    @benchmark
    def onLexPulse(self):
        self.rehighlight()

    def onParentVisibilityChanged(self, visible: bool):
        """ Pause lexing when the parent DiffView is in the background """
        for job in self.oldLexJob, self.newLexJob:
            if job and not job.lexingComplete:
                if visible:
                    job.start()
                else:
                    job.stop()
