#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import argparse
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
    parser.add_argument("-1", dest="single", action="store_true", help="run a single test at a time (no parallel tests)")
    parser.add_argument("--with-network", action="store_true", help="run tests that require network access")
    parser.add_argument("--with-flatpak", action="store_true", help="run tests that require the flatpak executable")
    args, forwardArgs = parser.parse_known_args()

    if args.visual:
        args.single = True
    else:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    if args.with_network:
        os.environ["TESTNET"] = "1"

    if args.with_flatpak or os.environ.get("FLATPAK_ID", ""):
        os.environ["TESTFLATPAK"] = "1"

    if not args.single:
        forwardArgs = ["-n", "auto"] + forwardArgs

    if args.cov:
        forwardArgs = ["--cov=gitfourchette", "--cov-report=term", "--cov-report=html"] + forwardArgs

    os.environ["PYTEST_QT_API"] = args.qt
    exitCode = pytest.main(forwardArgs)
    sys.exit(exitCode)


if __name__ == '__main__':
    run()
