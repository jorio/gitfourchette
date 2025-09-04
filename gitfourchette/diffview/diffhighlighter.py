# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging

from gitfourchette.appconsts import *
from gitfourchette.codeview.codehighlighter import CodeHighlighter
from gitfourchette.diffview.diffdocument import DiffDocument, LineData
from gitfourchette.syntax import LexJob, ColorScheme
from gitfourchette.toolbox import utf16Length

logger = logging.getLogger(__name__)


class DiffHighlighter(CodeHighlighter):
    oldLexJob: LexJob | None
    newLexJob: LexJob | None

    def __init__(self, parent):
        super().__init__(parent)
        self.diffDocument = None
        self.oldLexJob = None
        self.newLexJob = None

    def setDiffDocument(self, diffDocument: DiffDocument):
        self.diffDocument = diffDocument
        self.setDocument(diffDocument.document)

        # Prime lex jobs
        self.stopLexJobs()
        self.oldLexJob = diffDocument.oldLexJob
        self.newLexJob = diffDocument.newLexJob
        for job in self.oldLexJob, self.newLexJob:
            if job is not None:
                self.installLexJob(job)

    def highlightSyntax(self, text: str):
        # Pygments syntax highlighting
        blockNumber = self.currentBlock().blockNumber()

        lineData: LineData = self.diffDocument.lineData[blockNumber]
        diffLine = lineData.diffLine
        if diffLine is None:  # Hunk header, etc.
            return

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

        column = 0
        scheme = self.scheme.highContrastScheme if diffLine.origin in "+-" else self.scheme.scheme
        boundary = len(text) - lineData.trailerLength

        for tokenType, tokenLength in lexJob.tokens(lineNumber, text):
            try:
                charFormat = scheme[tokenType]
            except KeyError:
                charFormat = ColorScheme.fillInFallback(scheme, tokenType)
            self.setFormat(column, tokenLength, charFormat)
            column += tokenLength
            if column >= boundary:
                break

        if APP_DEBUG and lexJob.lexingComplete and column != boundary:  # pragma: no cover
            # Overstep may occur in low-quality lexing (not a big deal, so
            # we ignore that case) or when the file isn't decoded properly.
            logger.warning(f"Syntax highlighting overstep on line -{diffLine.old_lineno}+{diffLine.new_lineno} {column} != {boundary}")
