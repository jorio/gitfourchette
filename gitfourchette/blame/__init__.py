# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Trace the relevant commits in a file's history and annotate (blame) it.

This can be faster than libgit2's blame (as of libgit2 1.8), especially if you
need annotations at all points of the file's history.
"""

from gitfourchette.blame.annotatedfile import AnnotatedFile
from gitfourchette.blame.tracenode import TraceNode
from gitfourchette.blame.trace import Trace
