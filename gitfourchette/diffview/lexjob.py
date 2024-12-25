# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from pygments.lexer import Lexer


class LexJob:
    def __init__(self, lexer: Lexer, data: bytes):
        self.ready = not data
        self.lexGen = lexer.get_tokens(data)
        self.tokens = []
        self.lineStartTokens = [0, 0]  # start line numbering at 1 to match libgit2

        # TODO TEMP - don't chunk everything!
        if not self.ready:
            self.chunk(1 << 32)

    def chunk(self, n: int):
        assert not self.ready, "lex job ready, no need to keep chunking"

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

        except StopIteration:
            self.ready = True
