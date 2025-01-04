# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os.path
from contextlib import suppress

try:
    import pygments.lexers
    from pygments.lexer import Lexer
    hasPygments = True
except ImportError:  # pragma: no cover
    hasPygments = False

from gitfourchette.toolbox import benchmark

logger = logging.getLogger(__name__)

# Override Pygments priorities
extensionDisambiguations = {
    ".G": "",
    ".S": "gas",
    ".aspx": "aspx-cs",
    ".bas": "qbasic",
    ".cp": "cpp",
    ".ecl": "prolog",
    ".g": "",
    ".gd": "gdscript",
    ".h": "c",
    ".hh": "cpp",
    ".html": "html",
    ".inc": "php",
    ".inf": "ini",
    ".m": "objective-c",
    ".pl": "perl6",
    ".pm": "perl6",
    ".pro": "prolog",
    ".prolog": "prolog",
    ".rl": "",
    ".s": "gas",
    ".sql": "sql",
    ".t": "perl6",
    ".toc": "tex",
    ".tst": "scilab",
    ".ttl": "turtle",
    ".v": "verilog",
    ".xml": "xml",
    ".xsl": "xslt",
    ".xslt": "xslt",
}


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
    def getLexerFromPath(cls, path: str, allowPlugins: bool) -> Lexer | None:
        assert path

        if not hasPygments:  # pragma: no cover
            return None

        if not cls.lexerAliases:
            cls.warmUp(allowPlugins)

        # Find lexer alias by verbatim filename or extension
        try:
            # Try verbatim name (e.g. 'CMakeLists.txt')
            fileName = os.path.basename(path)
            alias = cls.lexerAliases[fileName]
        except KeyError:
            # Find lexer alias by extension
            _dummy, ext = os.path.splitext(path)
            alias = cls.lexerAliases.get(ext, "")

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
    def warmUp(cls, allowPlugins: bool):
        aliasTable = {}

        def shouldKeep(contenderAlias, contenderExtension):
            if contenderExtension in extensionDisambiguations:
                return contenderAlias == extensionDisambiguations[contenderExtension]

            try:
                aliasTable[contenderExtension]
            except KeyError:
                return True

            # print(contenderExtension, existingAlias, "vs", contenderAlias)
            # existing = pygments.lexers.find_lexer_class_by_name(existingAlias)  # slow!
            # contender = pygments.lexers.find_lexer_class_by_name(contenderAlias)  # slow!
            # return contender.priority > existing.priority
            return False

        # Significant speedup with plugins=False
        for _name, aliases, patterns, _mimeTypes in pygments.lexers.get_all_lexers(plugins=allowPlugins):
            if not patterns or not aliases:
                continue
            alias = aliases[0]
            for pattern in patterns:
                if pattern.startswith('*.') and not pattern.endswith('*') and pattern.count('.') == 1 and '[' not in pattern:
                    # Simple file extension
                    ext = pattern[1:]
                    if shouldKeep(alias, ext):
                        aliasTable[ext] = alias
                elif '*' not in pattern:
                    # Verbatim file name
                    aliasTable[pattern] = alias

        # Patch missing extensions
        # TODO: What's pygments' rationale for omitting '*.svg'?
        with suppress(KeyError):
            aliasTable['.svg'] = aliasTable['.xml']

        # No Pygments overhead for null lexers
        aliasTable = {ext: alias for ext, alias in aliasTable.items() if alias != 'text'}

        cls.lexerAliases = aliasTable
