# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import importlib
import logging
import sys


# For PyInstaller
def customStartModule():
    try:
        fullArg = sys.argv[1]
    except IndexError:
        return False

    magic = "--start-module="

    if not fullArg.startswith(magic):
        return False

    moduleName = fullArg.removeprefix(magic)
    if not moduleName.startswith("gitfourchette."):
        print("unsupported start module", file=sys.stderr)
        sys.exit(1)

    sys.argv.pop(1)
    sys.orig_argv.remove(fullArg)
    module = importlib.import_module(moduleName)
    module.main()
    return True


# Called from AppImage entry point
def main():
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.WARNING,
        format='%(levelname).1s %(asctime)s %(filename)-16s | %(message)s',
        datefmt="%H:%M:%S")
    logging.captureWarnings(True)

    from gitfourchette.application import GFApplication
    GFApplication.main()


if __name__ == "__main__":
    if not customStartModule():
        main()
