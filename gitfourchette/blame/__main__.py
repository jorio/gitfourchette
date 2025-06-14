# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations as _annotations

import logging as _logging
from contextlib import suppress
from pathlib import Path

from gitfourchette.blame import *
from gitfourchette.porcelain import *
from gitfourchette.toolbox.benchmark import BENCHMARK_LOGGING_LEVEL, Benchmark


def traceCommandLineTool():  # pragma: no cover
    from argparse import ArgumentParser
    from timeit import timeit
    from sys import stderr

    parser = ArgumentParser(description="GitFourchette trace/blame tool")
    parser.add_argument("path", help="File path")
    parser.add_argument("-t", "--trace", action="store_true", help="Print trace (file history)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Don't print annotations")
    parser.add_argument("-s", "--skim", action="store", type=int, default=0, help="Skimming interval")
    parser.add_argument("-m", "--max-level", action="store", type=int, default=0x3FFFFFFF, help="Max breadth level")
    parser.add_argument("-b", "--benchmark", action="store_true", help="Benchmark mode")
    args = parser.parse_args()

    _logging.basicConfig(level=BENCHMARK_LOGGING_LEVEL)
    _logging.captureWarnings(True)

    repo = Repo(args.path)
    relPath = Path(args.path)
    with suppress(ValueError):
        relPath = relPath.relative_to(repo.workdir)

    topCommit = makeWorkdirMockCommit(repo, str(relPath))

    with Benchmark("Trace"):
        trace = traceFile(str(relPath), topCommit, skimInterval=args.skim, maxLevel=args.max_level,
                          progressCallback=lambda n: print(f"\rTrace {n}...", end="", file=stderr))

    if args.trace:
        trace.dump()

    with Benchmark("Blame"):
        blameCollection = blameFile(repo, trace, topCommit.id,
                                    progressCallback=lambda n: print(f"\rBlame {n}...", end="", file=stderr))

    if not args.quiet:
        rootBlame = blameCollection[trace.first.blobId]
        print(rootBlame.toPlainText(repo))

    if args.benchmark:
        global APP_DEBUG
        APP_DEBUG = False
        N = 10
        print("Benchmarking...")
        elapsed = timeit(lambda: traceFile(str(relPath), topCommit, skimInterval=args.skim, maxLevel=args.max_level), number=N)
        print(f"Trace: {elapsed*1000/N:.0f} ms avg")
        elapsed = timeit(lambda: blameFile(repo, trace, topCommit.id), number=N)
        print(f"Blame: {elapsed*1000/N:.0f} ms avg")


if __name__ == '__main__':
    traceCommandLineTool()
