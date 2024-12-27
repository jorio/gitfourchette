# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
from typing import Any

from gitfourchette.diffview.lexjob import LexJob

logger = logging.getLogger(__name__)


class LexJobCache:
    MaxCachedLines = 100_000

    cache: dict[Any, LexJob] = {}
    totalLines = 0

    @classmethod
    def checkOut(cls, fileKey: Any):
        job = cls.cache[fileKey]
        del cls.cache[fileKey]
        cls.totalLines -= len(job.hqTokenMap)
        return job

    @classmethod
    def checkIn(cls, job: LexJob):
        assert not job.scheduler.isActive()

        fileKey = job.fileKey
        numLines = len(job.hqTokenMap)

        # If the new file is larger than cache capacity, just bail
        if numLines > cls.MaxCachedLines:
            logger.debug("File too large to fit in cache")
            return

        # Make room in FIFO
        keys = list(cls.cache)
        while cls.totalLines + numLines > cls.MaxCachedLines:
            oldestKey = keys.pop(0)
            cls.checkOut(oldestKey)
            logger.debug(f"Evicting file, {cls.totalLines}")

        cls.cache[fileKey] = job
        cls.totalLines += numLines
        logger.debug(f"{cls.totalLines} lines from {len(cls.cache)} files")
