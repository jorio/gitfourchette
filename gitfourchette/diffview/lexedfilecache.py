# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
from typing import Any

from pygments.token import Token

logger = logging.getLogger(__name__)


class LexedFileCache:
    MaxCachedLines = 100_000

    cache = {}
    totalLines = 0

    @classmethod
    def get(cls, fileKey: Any):
        value = cls.cache[fileKey]

        # Bump key in FIFO
        del cls.cache[fileKey]
        cls.cache[fileKey] = value

        return value

    @classmethod
    def put(cls, fileKey: Any, tokens: dict[int, list[tuple[Token, int]]]):
        numLines = len(tokens)

        # If new file is larger than cache, just bail
        if numLines > cls.MaxCachedLines:
            logger.debug("File too large to fit in cache")
            return

        # Make room in FIFO
        keys = list(cls.cache.keys())
        while cls.totalLines + numLines > cls.MaxCachedLines:
            k = keys.pop(0)
            logger.debug("Evicting file")
            cls.totalLines -= len(cls.cache[k])
            del cls.cache[k]

        cls.cache[fileKey] = tokens
        cls.totalLines += numLines
        logger.debug(f"{cls.totalLines} lines from {len(cls.cache)} files")
