# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import os
import time

BENCHMARK_LOGGING_LEVEL = 5

logger = logging.getLogger(__name__)
logging.addLevelName(BENCHMARK_LOGGING_LEVEL, "BENCHMARK")

try:
    import psutil
except ModuleNotFoundError:
    psutil = None


def getRSS():
    if psutil:
        return psutil.Process(os.getpid()).memory_info().rss
    else:
        return 0


class Benchmark:
    """ Context manager that reports how long a piece of code takes to run. """

    nesting: list[str] = []

    def __init__(self, name: str):
        self.name = name
        self.phase = ""
        self.startTime = 0.0
        self.startBytes = 0

    def enter(self, phase=""):
        if self.startTime:
            self.exit()

        Benchmark.nesting.append(self.name)
        self.startBytes = getRSS()
        self.startTime = time.perf_counter()
        self.phase = phase

    def exit(self):
        ms = 1000 * (time.perf_counter() - self.startTime)
        kb = (getRSS() - self.startBytes) // 1024

        description = "/".join(Benchmark.nesting)
        if self.phase:
            description += f" ({self.phase})"
        logger.log(BENCHMARK_LOGGING_LEVEL, f"{ms:8.2f} ms {kb:6,d}K {description}")

        Benchmark.nesting.pop()
        self.startTime = 0.0
        self.phase = ""

    def __enter__(self):
        self.enter()
        return self

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        self.exit()


def benchmark(func):
    """ Function decorator that reports how long the function takes to run. """
    def wrapper(*args, **kwargs):
        with Benchmark(func.__qualname__):
            return func(*args, **kwargs)
    return wrapper
