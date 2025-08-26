# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging

from gitfourchette import colors
from gitfourchette.syntax import ColorScheme, LexJob
from gitfourchette.qt import *
from gitfourchette.toolbox import benchmark, CallbackAccumulator

logger = logging.getLogger(__name__)


class CodeHighlighter(QSyntaxHighlighter):
    scheme: ColorScheme
    lexJobs: list[LexJob]

    def __init__(self, parent):
        super().__init__(parent)

        self.scheme = ColorScheme()
        self.lexJobs = []

        self.occurrenceFormat = QTextCharFormat()
        self.occurrenceFormat.setBackground(colors.yellow)
        self.occurrenceFormat.setForeground(colors.black)
        self.occurrenceFormat.setFontWeight(QFont.Weight.Bold)

        self.searchTerm = ""
        self.numOccurrences = 0

    def setSearchTerm(self, term: str) -> int:
        if self.searchTerm != term:
            self.searchTerm = term
            self.numOccurrences = 0
            self.rehighlight()
        return self.numOccurrences

    def installLexJob(self, job):
        job.pulse.connect(self.onLexPulse)
        self.lexJobs.append(job)

    def stopLexJobs(self):
        for job in self.lexJobs:
            job.stop()
            job.pulse.disconnect(self.onLexPulse)
        self.lexJobs.clear()

    def highlightBlock(self, text: str):
        if self.scheme and self.lexJobs:
            self.highlightSyntax(text)
        if self.searchTerm:
            self.highlightSearch(text)

    def highlightSearch(self, text: str):
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
            self.numOccurrences += 1

    def highlightSyntax(self, text: str):
        # Pygments syntax highlighting
        lineNumber = 1 + self.currentBlock().blockNumber()

        column = 0
        scheme = self.scheme.scheme
        lexJob = self.lexJobs[0]

        for tokenType, tokenLength in lexJob.tokens(lineNumber, text):
            try:
                charFormat = scheme[tokenType]
            except KeyError:
                charFormat = ColorScheme.fillInFallback(scheme, tokenType)
            self.setFormat(column, tokenLength, charFormat)
            column += tokenLength

    def setColorScheme(self, scheme: ColorScheme):
        self.scheme = scheme
        scheme.primeHighContrastVersion()

    @CallbackAccumulator.deferredMethod()
    @benchmark
    def onLexPulse(self):
        self.rehighlight()

    def onParentVisibilityChanged(self, visible: bool):
        """ Pause lexing when the parent DiffView is in the background """
        for job in self.lexJobs:
            if job.lexingComplete:
                pass
            elif visible:
                job.start()
            else:
                job.stop()
