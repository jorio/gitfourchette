# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging

from gitfourchette import colors
from gitfourchette import settings
from gitfourchette.diffview.diffdocument import DiffDocument, LineData
from gitfourchette.syntax import ColorScheme, LexJob
from gitfourchette.qt import *
from gitfourchette.toolbox import benchmark, CallbackAccumulator

logger = logging.getLogger(__name__)


class DiffSyntaxHighlighter(QSyntaxHighlighter):
    diffDocument: DiffDocument | None
    scheme: ColorScheme
    oldLexJob: LexJob | None
    newLexJob: LexJob | None

    def __init__(self, parent):
        super().__init__(parent)

        self.diffDocument = None
        self.scheme = ColorScheme()

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
        self.oldLexJob = diffDocument.oldLexJob
        self.newLexJob = diffDocument.newLexJob
        for job in self.oldLexJob, self.newLexJob:
            if job is not None:
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

        elif self.scheme and (self.oldLexJob or self.newLexJob):
            # Pygments syntax highlighting
            blockNumber = self.currentBlock().blockNumber()

            lineData: LineData = self.diffDocument.lineData[blockNumber]
            diffLine = lineData.diffLine
            if diffLine is None:  # Hunk header, etc.
                return

            column = 0
            scheme = self.scheme.highContrastScheme if diffLine.origin in "+-" else self.scheme.scheme

            if diffLine.origin == '+':
                lexJob = self.newLexJob
                lineNumber = diffLine.new_lineno
            else:
                lexJob = self.oldLexJob
                lineNumber = diffLine.old_lineno

            # While oldLexJob or newLexJob may be None in the case of a NULL_OID revision
            # (e.g. the 'old' revision of an untracked file), there shouldn't be any lines
            # from that revision in the diff.
            assert lexJob is not None

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

    def setColorScheme(self, scheme: ColorScheme):
        self.scheme = scheme
        scheme.primeHighContrastVersion()

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
