# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from pygments.lexer import Lexer

from gitfourchette.qt import *
from gitfourchette.toolbox import benchmark


class LexJob(QObject):
    ChunkSize = 5000  # tokens
    ScheduleInterval = 0  # ms

    pulse = Signal()

    def __init__(self, parent, lexer: Lexer, data: bytes):
        super().__init__(parent)
        self.setObjectName("LexJob")

        self.fullyLexed = not data
        self.lexGen = lexer.get_tokens(data)
        self.tokens = []
        self.lineStartTokens = [0, 0]  # start line numbering at 1 to match libgit2

        self.scheduler = QTimer(self)
        self.scheduler.setSingleShot(True)
        self.scheduler.timeout.connect(self._chunk)

        self.requestedLine = 0

    def getLineStartToken(self, lineNumber: int):
        if not self.fullyLexed:
            try:
                # Make sure the next line is complete
                self.requestedLine = max(self.requestedLine, lineNumber + 1)
                _dummy = self.lineStartTokens[self.requestedLine]
            except IndexError:
                if not self.scheduler.isActive():
                    # Initiate chunking
                    self.scheduler.start(0)
                return -1

        try:
            return self.lineStartTokens[lineNumber]
        except IndexError:
            return -1

    @benchmark
    def _chunk(self, n: int = ChunkSize):
        assert not self.fullyLexed, "lexing complete, no need to keep chunking"

        lexGen = self.lexGen
        tokens = self.tokens
        lineStarts = self.lineStartTokens

        try:
            for _i in range(n):
                ttype, text = next(lexGen)

                # This looks optimizable, need to benchmark.
                if '\n' not in text:
                    tokens.append((ttype, len(text)))
                else:
                    for part in text.split('\n'):
                        if part:
                            tokens.append((ttype, len(part)))
                        lineStarts.append(len(tokens))
                    lineStarts.pop()  # for loop inserts one too many lines

            if self.requestedLine >= len(self.lineStartTokens):
                assert not self.scheduler.isActive()
                self.scheduler.start(LexJob.ScheduleInterval)

        except StopIteration:
            self.fullyLexed = True
            self.scheduler.stop()

        self.pulse.emit()

    def stop(self):
        self.scheduler.stop()
