# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

try:
    from pygments.lexer import Lexer
    from pygments.token import Token
except ImportError:  # pragma: no cover
    # If Pygments isn't available, LexJob should never be instantiated!
    pass

from gitfourchette.qt import *
from gitfourchette.toolbox.benchmark import benchmark
from gitfourchette.toolbox.textutils import qstringLength


class LexJob(QObject):
    KeyType = str
    ChunkSize = 5000  # tokens
    ScheduleInitialDelay = 0  # ms
    ScheduleInterval = 0  # ms
    MaxLowQualityLines = 100
    MaxLowQualityLineLength = 200
    _EmptyTokenization = []

    pulse = Signal()

    def __init__(self, lexer: Lexer, data: bytes, fileKey: KeyType):
        # Don't bind the QObject to a parent to allow Python's refcounting to
        # purge evicted cache entries that are not currently in use by the UI.
        super().__init__(None)
        self.setObjectName("LexJob")

        assert fileKey
        assert data, "don't create a LexJob without some data"

        self.lexer = lexer
        self.lqTokenMap = {}
        self.hqTokenMap = {1: []}
        self.fileKey = fileKey
        self.fileSize = len(data)

        self.currentLine = 1
        self.lexGen = lexer.get_tokens(data)

        self.scheduler = QTimer(self)
        self.scheduler.setSingleShot(True)
        self.scheduler.timeout.connect(self.lexChunk)

        self.requestedLine = 0
        assert not self.lexingComplete

    @property
    def lexingComplete(self):
        return self.currentLine == 0

    def tokens(self, lineNumber: int, fallbackText: str) -> list[tuple[Token, int]]:
        if self.lexingComplete or self.currentLine > lineNumber:
            return self.hqTokenMap[lineNumber]

        # Lex job hasn't reached this line yet.
        # Schedule high-quality lexing up to this line.
        if self.requestedLine < lineNumber:
            self.requestedLine = lineNumber
            self.start()  # Initiate chunking

        # Fall back to low-quality lexing on this line
        # to minimize flashing while the job is busy.
        try:
            lqTokens = self.lqTokenMap[lineNumber]
        except KeyError:
            if (len(self.lqTokenMap) > LexJob.MaxLowQualityLines
                    or len(fallbackText) > LexJob.MaxLowQualityLineLength):
                # To ease CPU load, skip long lines and stop LQ-lexing "below the fold".
                lqTokens = LexJob._EmptyTokenization
            else:
                # Perform low-quality lexing and cache the result.
                lqTokens = [(t, qstringLength(v)) for _i, t, v in self.lexer.get_tokens_unprocessed(fallbackText)]
                self.lqTokenMap[lineNumber] = lqTokens
        return lqTokens

    def start(self):
        assert not self.lexingComplete
        if self.scheduler.isActive():
            return
        self.scheduler.start(LexJob.ScheduleInitialDelay)  # Initiate chunking

    def stop(self):
        self.scheduler.stop()
        assert not self.scheduler.isActive()

    @benchmark
    def lexChunk(self, n: int = ChunkSize):
        assert not self.lexingComplete, "lexing complete, no need to keep chunking"
        assert self.lexGen is not None

        lexGen = self.lexGen
        tm = self.hqTokenMap
        ln = self.currentLine

        # Resume lexing current line
        tokens = tm[ln]

        try:
            for _i in range(n):
                ttype, text = next(lexGen)

                if '\n' not in text:
                    tokens.append((ttype, qstringLength(text)))
                else:
                    for part in text.split('\n'):
                        if part:
                            tm[ln].append((ttype, qstringLength(part)))
                        ln += 1
                        tm[ln] = []
                    ln -= 1  # for loop above inserts one too many lines
                    tokens = tm[ln]  # cache current line for next iteration

            self.currentLine = ln
            if self.requestedLine >= ln:
                assert not self.scheduler.isActive()
                self.scheduler.start(LexJob.ScheduleInterval)

        except StopIteration:
            self.currentLine = 0
            self.scheduler.stop()
            self.lqTokenMap = {}  # we won't need LQ tokens anymore - free some mem
            self.lexGen = None
            assert self.lexingComplete

        self.pulse.emit()
