# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import itertools
import logging
import os
import re
import shlex
import shutil
import sys
import textwrap
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from gitfourchette.localization import *
from gitfourchette.qt import *

_logger = logging.getLogger(__name__)

_placeholderPattern = re.compile(r"\$[_a-zA-Z0-9]+")

_whichPath = None


class ToolCommands:
    FlatpakSandboxedCommandPrefix = "flatpak:"

    @staticmethod
    def splitCommandTokens(command: str) -> list[str]:
        # Treat command as POSIX even on Windows!
        if WINDOWS:
            command = command.replace("\\", "/")
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

        # Launch macOS app bundle
        if MACOS and tokens and tokens[0].endswith(".app"):
            flags = "-nF"
            if not detached:
                flags += "W"
            tokens = ["/usr/bin/open", flags, tokens[0], "--args"] + tokens[1:]

        return tokens, directory

    @classmethod
    def setQProcessEnvironment(cls, process: QProcess, environment: dict[str, str] | None):
        if not environment:
            return
        processEnvironment = QProcessEnvironment.systemEnvironment()
        for k, v in environment.items():
            processEnvironment.insert(k, v)
        process.setProcessEnvironment(processEnvironment)

    @classmethod
    def filterQProcessEnvironment(cls, process: QProcess) -> dict[str, str]:
        processEnvironment = process.processEnvironment()
        env = {}
        for key in processEnvironment.keys():
            value = processEnvironment.value(key)
            if value != INITIAL_ENVIRONMENT.get(key, None):
                env[key] = value
        return env

    @classmethod
    def isFlatpakInstalled(cls, flatpakRef: str) -> bool:
        if not FREEDESKTOP:
            return False
        text = cls.runSync("flatpak", "info", "--show-ref", flatpakRef)
        return bool(text.strip())

    @classmethod
    def wrapFlatpakCommand(cls, process: QProcess, detached=False):
        if not FREEDESKTOP:  # pragma: no cover
            return

        program = process.program()

        if FLATPAK and program.startswith(cls.FlatpakSandboxedCommandPrefix):
            program = program.removeprefix(cls.FlatpakSandboxedCommandPrefix)
            process.setProgram(program)
            return

        tokens = [program] + process.arguments()
        directory = process.workingDirectory()

        # If we're running a "flatpak run" command, add --env, --cwd, and --filesystem.
        flatpakRun = cls.isFlatpakRunCommand(tokens)
        if flatpakRun != 0:
            extra = [f"--env={k}={v}" for k, v in cls.filterQProcessEnvironment(process).items()]

            # Expose directory
            if directory:
                extra += [f"--cwd={directory}", f"--filesystem={directory}"]

            tokens = tokens[:flatpakRun] + extra + tokens[flatpakRun:]

        # If GitFourchette itself is running as a Flatpak, launch the command with "flatpak-spawn".
        if FLATPAK:
            assert program != "flatpak-spawn", "process already flatpak-spawn compatible"

            # Run external tool via flatpak-spawn --host (outside flatpak sandbox).
            extra = ["flatpak-spawn", "--host"]

            # Set --watch-bus if we want the process to die with us.
            # If detached, don't set --watch-bus and DO NOT USE QProcess.startDetached()!
            # (Can't get return code otherwise.)
            if not detached:
                extra += ["--watch-bus"]

            if directory:
                extra += [f"--directory={directory}"]

            # Forward environment variables (only needed if not already done in `flatpak run`)
            if not flatpakRun:
                extra += [f"--env={k}={v}" for k, v in cls.filterQProcessEnvironment(process).items()]

            # Run command through `env` to get return code 127 if the command is missing.
            # (Note that running ANOTHER flatpak via 'flatpak run' won't return 127).
            if not flatpakRun:
                extra += ["/usr/bin/env"]

            extra += ["--"]

            tokens = extra + tokens

        process.setProgram(tokens[0])
        process.setArguments(tokens[1:])

    @classmethod
    def runSync(cls, *args: str, directory: str = "", strict=False) -> str:
        process = QProcess(None)
        process.setProgram(args[0])
        process.setArguments(args[1:])
        if directory:
            process.setWorkingDirectory(directory)
        cls.wrapFlatpakCommand(process)
        _logger.info(f"runSync: {shlex.join([process.program()] + process.arguments())}")
        process.setProcessChannelMode(QProcess.ProcessChannelMode.ForwardedErrorChannel)
        process.start()
        didFinish = process.waitForFinished()

        if strict:
            if not didFinish:
                raise ChildProcessError(f"process did not finish ({process.error()})")
            elif process.exitCode() != 0:
                raise ChildProcessError(f"process exited with code {process.exitCode()}")

        if not didFinish or process.exitCode() != 0:
            return ""

        return process.readAll().data().decode(errors="replace")

    @classmethod
    def which(cls, name: str):
        global _whichPath
        if FLATPAK and _whichPath is None:
            # Cache host's $PATH
            _whichPath = cls.runSync("sh", "-c", "echo $PATH").rstrip()
        return shutil.which(name, path=_whichPath)

    @classmethod
    def makeTerminalScript(cls, workdir: str, command: str) -> str:
        # While we could simply export the parameters as environment variables
        # then run termcmd.sh from the static assets, this approach fails if
        # the terminal is a Flatpak (custom env vars always seem to be erased).
        # That's why we generate a bespoke launcher script on the fly
        # (which sources termcmd.sh).

        # When running as a Flatpak, the assets folder lives in an app-specific
        # mount point. I don't think we can get its "real" path on the host.
        # So, copy termcmd.sh out of the assets folder before passing it to the
        # external terminal program.
        termcmdPath = Path(qTempDir()) / "termcmd.sh"
        if not termcmdPath.exists():
            termcmdSourcePath = QFile("assets:termcmd.sh").fileName()
            shutil.copyfile(termcmdSourcePath, termcmdPath)

        yKey = "y"
        nKey = "n"
        exitMessage = _("Command exited with code:")
        keyPrompt = _("Continue in a shell?") + f" [{yKey.upper()}/{nKey}]"

        script = textwrap.dedent(f"""\
            #!/usr/bin/env bash
            _GF_COMMAND="{command}"
            _GF_APPNAME={shlex.quote(qAppName())}
            _GF_YKEY={shlex.quote(yKey)}
            _GF_NKEY={shlex.quote(nKey)}
            _GF_EXITMESSAGE={shlex.quote(exitMessage)}
            _GF_KEYPROMPT={shlex.quote(keyPrompt)}
            _GF_WORKDIR={shlex.quote(workdir)}
            _GF_TESTMODE={"1" if APP_TESTMODE else "0"}
            source {shlex.quote(str(termcmdPath))}
        """)

        cacheKey = f"{hash(script):x}"
        path = Path(qTempDir()) / f"terminal_{cacheKey}.sh"
        if not path.exists():
            path.write_text(script, "utf-8")
            path.chmod(0o755)
        return str(path)

    @classmethod
    def spawnNewInstance(cls, module: str, sandbox: bool = True) -> list[str]:
        """
        Prepare a command to spawn another instance of this application.
        """
        assert module.startswith("gitfourchette"), module

        if FLATPAK and not sandbox:
            # Command to be called by host system's git, which lives outside the
            # flatpak sandbox. Spawn another instance of our flatpak.
            tokens = ["flatpak", "run", "--command=python", FLATPAK_ID, "-m", module]
        elif "APPIMAGE" in INITIAL_ENVIRONMENT:
            # AVOID "sys.executable" (path to .AppImage file) to spawn a child,
            # may cause SIGTTIN in parent process!
            python = sys.orig_argv[0]  # python in AppImage tmpfs mount
            tokens = [python, "-m", module]
        elif PYINSTALLER_MEIPASS:
            tokens = [sys.executable, f"--start-module={module}"]
        else:
            # Just spawn another Python interpreter.
            tokens = [sys.executable, "-m", module]

        # The new instance is supposed to be a child process, so it will inherit
        # the environment variables of the current process. We don't need to
        # explicitly copy them to 'env'. For reference, some of the relevant
        # variables for a successful child process include:
        # - PYTHONPATH (":".join(sys.path))
        # - For AppImage only: APPIMAGE, APPDIR, ARGV0, SSL_CERT_FILE
        # Without these, askpass.sh may fail to start unless it's a child
        # process of a GitFourchette instance.

        assert tokens
        return tokens
