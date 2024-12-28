# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging

from gitfourchette.diffview.lexjob import LexJob
from gitfourchette.porcelain import Oid
from gitfourchette.toolbox import shortHash

logger = logging.getLogger(__name__)


class LexJobCache:
    MaxBudget = 1_048_576
    """
    Maximum total size, in bytes, of all the files being lexed.
    This figure sets an upper bound on the total footprint of lexed tokens
    (in the worst case scenario, there would be 1 token per source byte).
    """

    cache: dict[Oid, LexJob] = {}
    totalFileSize = 0

    @classmethod
    def put(cls, job: LexJob):
        fileKey = job.fileKey

        assert not job.scheduler.isActive()
        assert fileKey not in cls.cache, "LexJob already cached"

        # If the new file is larger than cache capacity, just bail
        if job.fileSize > cls.MaxBudget:
            logger.debug("File too large to fit in cache")
            return

        # Make room in FIFO
        keys = list(cls.cache)
        while cls.totalFileSize + job.fileSize > cls.MaxBudget:
            oldestKey = keys.pop(0)
            cls.evict(oldestKey)

        cls.cache[fileKey] = job
        cls.totalFileSize += job.fileSize
        logger.debug(f"Put {shortHash(fileKey)} (tot: {cls.totalFileSize>>10}K)")

    @classmethod
    def get(cls, fileKey: Oid):
        job = cls.cache.pop(fileKey)
        cls.cache[fileKey] = job  # Bump key
        logger.debug(f"Get {shortHash(fileKey)}")
        return job

    @classmethod
    def evict(cls, fileKey: Oid):
        job = cls.cache.pop(fileKey)
        cls.totalFileSize -= job.fileSize
        logger.debug(f"Del {shortHash(fileKey)} (tot: {cls.totalFileSize>>10:,}K)")
        return job
