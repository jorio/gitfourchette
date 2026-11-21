# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", [
    "gitfourchette.diffview.specialdiff",
    "gitfourchette.graph.graphdiagram",
    "gitfourchette.syntax",
    "gitfourchette.tasks",
    "gitfourchette.toolbox",
])
def testImportFirstInFreshInterpreter(module):
    """ Circular imports may only surface if a module happens to be imported first. """
    result = subprocess.run([sys.executable, "-c", f"import {module}"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
