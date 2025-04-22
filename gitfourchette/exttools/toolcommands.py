# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import itertools
import os
import re
import shlex
import textwrap
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from gitfourchette.localization import *
from gitfourchette.qt import *

_placeholderPattern = re.compile(r"\$[_a-zA-Z0-9]+")


class ToolCommands:
    @staticmethod
    def splitCommandTokens(command: str) -> list[str]:
        # Treat command as POSIX even on Windows!
        return shlex.split(command, posix=True)

    @classmethod
    def isFlatpakRunCommand(cls, tokens: Sequence[str]):
        """
        Return the index of the REF token (application ID) in a "flatpak run" command.
        Return 0 if this isn't a valid "flatpak run" command.

        For example, this function would return 4 for "flatpak --verbose run --arch=aarch64 com.example.app"
        because "com.example.app" is token #4.
        """

        i = 0

        try:
            # First token must be flatpak or *bin/flatpak
            if not (tokens[i] == "flatpak" or tokens[i].endswith("bin/flatpak")):
                return 0
            i += 1

            # First positional argument must be `run`
            while tokens[i].startswith("-"):  # Skip switches
                i += 1
            if tokens[i] != "run":
                return 0
            i += 1

            # Get ref token (force IndexError if there's none)
            while tokens[i].startswith("-"):  # Skip switches
                i += 1
            _dummy = tokens[i]
            return i

        except IndexError:
            return 0

    @classmethod
    def replaceProgramTokenInCommand(cls, command: str, *newProgramTokens: str):
        tokens = ToolCommands.splitCommandTokens(command)
        tokens = list(newProgramTokens) + tokens[1:]

        newCommand = shlex.join(tokens)

        # Remove single quotes added around our placeholders by shlex.join()
        # (e.g. '$L' --> $L, '--output=$M' --> $M)
        newCommand = re.sub(r" '(\$[0-9A-Z]+)'", r" \1", newCommand, flags=re.I | re.A)
        newCommand = re.sub(r" '(--?[a-z0-9\-_]+=\$[0-9A-Z]+)'", r" \1", newCommand, flags=re.I | re.A)

        return newCommand

    @classmethod
    def checkCommand(cls, command: str, *placeholders: str) -> str:
        try:
            cls.compileCommand(command, dict.fromkeys(placeholders, "PLACEHOLDER"), [])
            return ""
        except ValueError as e:
            return str(e)

    @classmethod
    def findPlaceholderTokens(cls, originalTokens: list[str]):
        for token in originalTokens:
            yield from _placeholderPattern.findall(token)

    @classmethod
    def injectReplacements(cls, tokens: list[str], replacements: dict[str, str]) -> list[str]:
        newTokens = []

        mandatoryTokensRemaining = list(replacements.keys())

        for token in tokens:
            matches = list(_placeholderPattern.finditer(token))

            for match in reversed(matches):
                placeholder = match.group()
                try:
                    replacement = replacements[placeholder]
                except KeyError as replacementNotFoundError:
                    raise ValueError(_("Unknown placeholder: {0}", placeholder)
                                     ) from replacementNotFoundError
                with suppress(ValueError):
                    mandatoryTokensRemaining.remove(placeholder)
                token = token[:match.start()] + replacement + token[match.end():]

            if token:
                newTokens.append(token)

        if mandatoryTokensRemaining:
            raise ValueError(_n("Missing placeholder:", "Missing placeholders:", len(mandatoryTokensRemaining))
                             + " " + ", ".join(mandatoryTokensRemaining))

        return newTokens

    @classmethod
    def compileCommand(
            cls,
            command: str,
            replacements: dict[str, str],
            positional: list[str],
            directory: str = "",
            detached: bool = True,
    ) -> tuple[list[str], str]:
        tokens = ToolCommands.splitCommandTokens(command)
        tokens = ToolCommands.injectReplacements(tokens, replacements)
        tokens.extend(positional)  # Append other paths to end of command line

        if tokens and tokens[0].startswith("assets:"):
            internalAssetFile = QFile(tokens[0])
            tokens[0] = internalAssetFile.fileName()

        # Find appropriate workdir
        if not directory:
            for argument in itertools.chain(replacements.values(), positional):
                if not argument:
                    continue
                directory = os.path.dirname(argument)
                if os.path.isdir(directory):
                    break

        # If we're running a Flatpak, expose the working directory to its sandbox.
        # (Inject '--filesystem=...' argument after 'flatpak run')
        flatpakRefTokenIndex = cls.isFlatpakRunCommand(tokens)
        if flatpakRefTokenIndex > 0:
            tokens.insert(flatpakRefTokenIndex, f"--filesystem={directory}")

        # Launch macOS app bundle
        if MACOS and tokens and tokens[0].endswith(".app"):
            flags = "-nF"
            if not detached:
                flags += "W"
            tokens = ["/usr/bin/open", flags, tokens[0], "--args"] + tokens[1:]

        # Flatpak-specific wrapper:
        # - Run external tool outside flatpak sandbox.
        # - Set workdir via flatpak-spawn because QProcess.setWorkingDirectory won't work.
        # - Run command through `env` to get return code 127 if the command is missing.
        #   (note that running ANOTHER flatpak via 'flatpak run' won't return 127).
        # - If detaching, don't set --watch-bus, and don't use QProcess.startDetached!
        #   (Can't get return code otherwise.)
        if FLATPAK:
            spawner = [
                "flatpak-spawn", "--host", f"--directory={directory}",
                "/usr/bin/env", "--"
            ]
            if not detached:
                spawner.insert(1, "--watch-bus")
            tokens = spawner + tokens

        return tokens, directory

    @classmethod
    def isFlatpakInstalled(cls, flatpakRef, parent) -> bool:
        tokens = ["flatpak", "info", "--show-ref", flatpakRef]
        if FLATPAK:
            tokens = ["flatpak-spawn", "--host", "--"] + tokens
        process = QProcess(parent)
        process.setProgram(tokens.pop(0))
        process.setArguments(tokens)
        process.start(mode=QProcess.OpenModeFlag.Unbuffered)
        process.waitForFinished()
        return process.exitCode() == 0

    @classmethod
    def makeTerminalScript(cls, workdir: str, command: str, shell: str = ""):
        # While we could simply export the parameters as environment variables
        # then run termcmd.sh from the static assets, this approach fails if
        # the terminal is a Flatpak (custom env vars always seem to be erased).
        # That's why we generate a bespoke launcher script on the fly.

        shell = shell or cls.defaultShell()
        shellKey = " "
        wrapperPath = QFile("assets:termcmd.sh").fileName()
        exitMessage = _("Command exited with code:")
        keyPrompt = _("Hit {0} to continue in a shell, or any other key to exit:"
                      ).format(QKeySequence(shellKey).toString(QKeySequence.SequenceFormat.NativeText))

        script = textwrap.dedent(f"""\
            #!/usr/bin/env bash
            _GF_COMMAND="{command}"
            _GF_APPNAME={shlex.quote(qAppName())}
            _GF_SHELL={shlex.quote(shell)}
            _GF_SHELLKEY={shlex.quote(shellKey)}
            _GF_EXITMESSAGE={shlex.quote(exitMessage)}
            _GF_KEYPROMPT={shlex.quote(keyPrompt)}
            _GF_WORKDIR={shlex.quote(workdir)}
            source {shlex.quote(wrapperPath)}
        """)

        cacheKey = f"{hash(script):x}"
        path = Path(qTempDir()) / f"terminal_{cacheKey}.sh"
        if not path.exists():
            path.write_text(script, "utf-8")
            path.chmod(0o755)
        return str(path)

    @classmethod
    def defaultShell(cls) -> str:
        return os.environ.get("SHELL", "/usr/bin/sh")
