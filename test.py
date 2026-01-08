#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import argparse
import importlib.util
import os
import sys
from pathlib import Path

import pytest


def run():
    thisFile = Path(__file__)
    os.chdir(thisFile.parent)

    parser = argparse.ArgumentParser(description="Kick off GitFourchette test suite",
                                     epilog="Additional arguments are forwarded to pytest (see: pytest --help).")
    parser.add_argument("--cov", action="store_true", help="produce coverage report")
    parser.add_argument("--visual", action="store_true", help="run tests visually (takes MUCH longer than offscreen!)")
    parser.add_argument("--qt", default="pyqt6", choices=["pyqt6", "pyside6", "pyqt5"], help="Qt bindings to use (pyqt6 by default)")
    parser.add_argument("-1", dest="single", action="store_true", help="run a single test at a time (don't use python-xdist)")
    parser.add_argument("--with-network", action="store_true", help="run tests that require network access")
    parser.add_argument("--with-fuse", action="store_true", help="run tests that require FUSE")
    parser.add_argument("-g", "--live-logging", action="store_true", help="enable live logging (recommended with -1)")
    args, forwardArgs = parser.parse_known_args()
    extraArgs = []

    if args.visual:
        args.single = True
    else:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    if args.with_network:
        os.environ["TESTNET"] = "1"

    if args.with_fuse:
        os.environ["TESTFUSE"] = "1"

    if args.single:
        pass
    elif importlib.util.find_spec("xdist"):
        extraArgs.extend(["-n", "auto"])
    else:
        print("*** NOTE: pytest-xdist is not installed. Tests will not be parallelized.")

    if args.live_logging:
        extraArgs.extend(["--log-cli-level=0"])

    if args.cov:
        extraArgs.extend(["--cov=gitfourchette", "--cov-report=term", "--cov-report=html"])

    os.environ["PYTEST_QT_API"] = args.qt
    exitCode = pytest.main(extraArgs + forwardArgs)
    sys.exit(exitCode)


if __name__ == '__main__':
    run()
