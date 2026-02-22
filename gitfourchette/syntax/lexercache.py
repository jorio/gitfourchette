# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import logging
import os.path
import re
from contextlib import suppress

try:
    import pygments.lexers
    from pygments.lexer import Lexer
    from pygments import __version__ as pygmentsVersion
    hasPygments = True
except ImportError:  # pragma: no cover
    hasPygments = False

from gitfourchette.toolbox.benchmark import benchmark

logger = logging.getLogger(__name__)

# Override Pygments priorities
_disambiguations = {
    ".ASM": "nasm",
    ".G": None,
    ".S": "gas",
    ".as": "actionscript3",
    ".asax": "aspx-cs",
    ".ascx": "aspx-cs",
    ".ashx": "aspx-cs",
    ".asm": "nasm",
    ".asmx": "aspx-cs",
    ".aspx": "aspx-cs",
    ".axd": "aspx-cs",
    ".bas": "qbasic",
    ".cl": "common-lisp",
    ".cp": "cpp",
    ".ecl": "prolog",
    ".fs": "fsharp",
    ".g": None,
    ".gd": "gdscript",
    ".h": "c",
    ".hh": "cpp",
    ".html": "html",
    ".inc": "php",
    ".inf": "ini",
    ".m": "objective-c",
    ".mm": "objective-c++",
    ".pl": "perl6",
    ".pm": "perl6",
    ".pro": "prolog",
    ".prolog": "prolog",
    ".rl": None,
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

# These are not defined by Pygments
_forcedAssociations = {
    ".gitmodules": "ini",
    ".svg": "xml",
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
        """
        Cache lexerAliases (map of filename patterns to lexer names).
        Turn off plugins for a significant speedup.
        """

        # Map lexer names to filename patterns
        lexers: dict[str, set[str]] = {}

        simpleExtension = re.compile(r'^\*\.[^.*\[]+$')
        for _name, aliases, patterns, _mimeTypes in pygments.lexers.get_all_lexers(plugins=allowPlugins):
            if not patterns or not aliases:  # Skip lexers without filename associations
                continue

            lexerName = aliases[0]
            patternSet = set()
            if lexerName in lexers:  # pragma: no cover
                logger.warning(f"Duplicated lexer name: {lexerName}")
            lexers[lexerName] = patternSet

            for pattern in patterns:
                if simpleExtension.match(pattern):  # *.ext
                    pattern = pattern[1:]  # Strip "*" prefix
                elif '*' in pattern:
                    # Skip anything else with a wildcard (keep verbatim filenames)
                    continue

                if lexerName == _disambiguations.get(pattern, lexerName):
                    patternSet.add(pattern)

        # Patch missing extensions
        for ext, lexerName in _forcedAssociations.items():
            try:
                lexers[lexerName].add(ext)
            except KeyError:  # pragma: no cover
                logger.warning(f"Missing lexer {lexerName}")

        # Avoid Pygments overhead for plaintext lexers
        lexers.pop("text", None)

        # Disable Lua syntax highlighting in bad Pygments versions (issue #55)
        if pygmentsVersion.startswith(("2.19.0", "2.19.1")):  # pragma: no cover
            logger.warning(f"Disabling Lua support in Pygments {pygmentsVersion} (issue #55)")
            lexers.pop("lua", None)

        # Map filename patterns to lexers
        patternsToLexers = {}
        for lexerName, patternSet in lexers.items():
            if False:  # pragma: no cover - replace with 'if True' to debug missing disambiguations
                overwrite = patternSet.intersection(patternsToLexers)
                if overwrite:
                    logger.warning(f"Missing disambiguation: Lexer '{lexerName}' will take precedence over { { p: patternsToLexers[p] for p in overwrite } }")

            patternsToLexers.update(dict.fromkeys(patternSet, lexerName))

        cls.lexerAliases = patternsToLexers
