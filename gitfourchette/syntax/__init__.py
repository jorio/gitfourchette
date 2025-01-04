# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from .colorscheme import ColorScheme, PygmentsPresets
from .lexercache import LexerCache
from .lexjob import LexJob
from .lexjobcache import LexJobCache

try:
    import pygments
    pygmentsVersion = pygments.__version__
    syntaxHighlightingAvailable = True
except ImportError:  # pragma: no cover
    pygmentsVersion = ""
    syntaxHighlightingAvailable = False
