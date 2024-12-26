# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os.path
from contextlib import suppress

import pygments.lexers
from pygments.lexer import Lexer

from gitfourchette import settings
from gitfourchette.toolbox import benchmark


class LexerCache:
    """
    Fast drop-in replacement for pygments.lexers.get_lexer_for_filename().
    """

    lexerAliases: dict[str, str] = {}
    " Lexer aliases by file extensions or verbatim file names "

    lexerInstances: dict[str, Lexer] = {}
    " Lexer instances by aliases "

    @classmethod
    @benchmark
    def getLexerFromPath(cls, path: str) -> Lexer | None:
        # Empty path disables lexing
        if not path:
            return None

        if not cls.lexerAliases:
            cls.warmUp()

        # Find lexer alias by extension
        _dummy, ext = os.path.splitext(path)
        try:
            alias = cls.lexerAliases[ext]
        except KeyError:
            # Try verbatim name (e.g. 'Makefile')
            fileName = os.path.basename(path)
            alias = cls.lexerAliases.get(fileName, "")

        # Bail early
        if not alias:
            return None

        # Get existing lexer instance
        with suppress(KeyError):
            return cls.lexerInstances[alias]

        # Instantiate new lexer.
        # Notes:
        # - Passing in an alias from pygments' builtin lexers shouldn't
        #   tap into Pygments plugins, so this should be fairly fast.
        # - stripnl throws off highlighting in files that begin with
        #   whitespace.
        lexer = pygments.lexers.get_lexer_by_name(alias, stripnl=False)
        cls.lexerInstances[alias] = lexer
        return lexer

    @classmethod
    @benchmark
    def warmUp(cls):
        aliasTable = {}

        # Significant speedup with plugins=False
        for _name, aliases, patterns, _mimeTypes in pygments.lexers.get_all_lexers(plugins=settings.prefs.pygmentsPlugins):
            if not patterns or not aliases:
                continue
            alias = aliases[0]
            for pattern in patterns:
                if pattern.startswith('*.') and not pattern.endswith('*'):
                    # Simple file extension
                    ext = pattern[1:]
                    aliasTable[ext] = alias
                elif '*' not in pattern:
                    # Verbatim file name
                    aliasTable[pattern] = alias

        # Patch missing extensions
        # TODO: What's pygments' rationale for omitting '*.svg'?
        with suppress(KeyError):
            aliasTable['.svg'] = aliasTable['.xml']

        cls.lexerAliases = aliasTable
