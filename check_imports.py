#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Import every module of the gitfourchette package as if it were the first one,
to catch circular imports that the application's usual import order hides.
"""

import importlib
import importlib.util
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = REPO_DIR / "gitfourchette"

# Modules that need an optional dependency, which may not be installed
OPTIONAL_DEPENDENCIES = {
    "gitfourchette.mount.treemount": "mfusepy",
}


def listModules() -> list[str]:
    modules = []

    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        parts = path.relative_to(REPO_DIR).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules.append(".".join(parts))

    return modules


def importFirst(module: str) -> str:
    """
    Import a module after unloading the whole package, so that it runs first.
    Return the error, or an empty string if the import succeeded.
    """
    for name in list(sys.modules):
        if name == "gitfourchette" or name.startswith("gitfourchette."):
            del sys.modules[name]

    try:
        importlib.import_module(module)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"

    return ""


def main():
    # Import the code in this repo, not some other installed copy of gitfourchette
    sys.path.insert(0, str(REPO_DIR))

    failures = 0
    modules = listModules()

    for i, module in enumerate(modules, start=1):
        print(f"\r{100*i//len(modules):3}% ", end="")

        dependency = OPTIONAL_DEPENDENCIES.get(module)
        if dependency and importlib.util.find_spec(dependency) is None:
            continue

        error = importFirst(module)
        if error:
            print(f"\r{module}: {error}")
            failures += 1

    if failures:
        print(f"\n{failures} modules can't be imported first.")
        sys.exit(1)

    print("OK")


if __name__ == "__main__":
    main()
