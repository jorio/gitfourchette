# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from pygments.lexer import Lexer
from pygments.token import Token

from gitfourchette.qt import *
from gitfourchette.toolbox import benchmark


class LexJob(QObject):
    ChunkSize = 5000  # tokens
    ScheduleInitialDelay = 0  # ms
    ScheduleInterval = 0  # ms
    MaxLowQualityLines = 100
    MaxLowQualityLineLength = 200
    _EmptyTokenization = []

    pulse = Signal()

    def __init__(self, parent, lexer: Lexer, data: bytes):
        super().__init__(parent)
        self.setObjectName("LexJob")

        self.lexer = lexer
        self.lqTokenMap = {}
        self.hqTokenMap = {1: []}

        if not data:
            # Lexing complete on empty data
            self.currentLine = 0
            self.lexGen = None
        else:
            self.currentLine = 1
            self.lexGen = lexer.get_tokens(data)
        assert self.lexingComplete == (not data)

        self.scheduler = QTimer(self)
        self.scheduler.setSingleShot(True)
        self.scheduler.timeout.connect(self._chunk)

        self.requestedLine = 0

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
            if not self.scheduler.isActive():
                self.scheduler.start(LexJob.ScheduleInitialDelay)  # Initiate chunking

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
                lqTokens = [(t, len(v)) for _i, t, v in self.lexer.get_tokens_unprocessed(fallbackText)]
                self.lqTokenMap[lineNumber] = lqTokens
        return lqTokens

    def stop(self):
        self.scheduler.stop()

    @benchmark
    def _chunk(self, n: int = ChunkSize):
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

                # This looks optimizable, need to benchmark.
                if '\n' not in text:
                    tokens.append((ttype, len(text)))
                else:
                    for part in text.split('\n'):
                        if part:
                            tm[ln].append((ttype, len(part)))
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
            assert self.lexingComplete

        self.pulse.emit()
