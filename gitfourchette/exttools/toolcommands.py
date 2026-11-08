# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import importlib.util
import itertools
import logging
import os
import re
import shlex
import shutil
import sys
import textwrap
import warnings
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from gitfourchette.localization import *
from gitfourchette.qt import *
import gitfourchette.exttools.win32ctrlc

_logger = logging.getLogger(__name__)

_placeholderPattern = re.compile(r"\$[_a-zA-Z0-9]+")

_pythonpathCoreImports = ["gitfourchette", "pygit2", QT_BINDING]

_tamperProofFiles: dict[Path, int] = {}


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
        newCommand = re.sub(r" '(\$[0-9A-Z]+)'", r" \1", newCommand, flags=re.IGNORECASE)
        newCommand = re.sub(r" '(--?[a-z0-9\-_]+=\$[0-9A-Z]+)'", r" \1", newCommand, flags=re.IGNORECASE)

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

        # Flatpak: Explicitly forward any diffs from the initial environment
        # even if we inherit the parent environment. We want to pass these with
        # --env if we use flatpak-spawn.
        if FLATPAK and processEnvironment.inheritsFromParent():
            assert not bool(processEnvironment.keys())
            processEnvironment = QProcessEnvironment.systemEnvironment()

        env = {}
        for key in processEnvironment.keys():  # noqa: SIM118
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
    def whichOnHost(cls, name: str):
        if FLATPAK:
            # shutil.which() only looks inside the sandbox's filesystem, so it
            # won't pick up anything from the host (passing the host's $PATH
            # won't help). So, run 'which' on the host.
            return cls.runSync("which", name, strict=False).rstrip()

        return shutil.which(name)

    @classmethod
    def writeTamperProofScript(cls, path: Path, contents: str, mode: int = 0o500):
        b = contents.encode("utf-8")
        h = hash(b)
        path.write_bytes(b)
        path.chmod(mode)
        _tamperProofFiles[path] = h

    @classmethod
    def untamperedScriptExists(cls, path: Path) -> bool:
        try:
            knownHash = _tamperProofFiles[path]
            data = path.read_bytes()
        except (OSError, KeyError):
            return False

        newHash = hash(data)
        if knownHash != newHash:
            raise RuntimeError(f"Internal file altered by another process ({path}). Please restart the application.")

        return True

    @classmethod
    def makeTerminalScript(cls, workdir: str, commandTokens: list[str]) -> str:
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

        if not cls.untamperedScriptExists(termcmdPath):
            termcmdSourcePath = QFile("assets:termcmd.sh").fileName()
            termcmdText = Path(termcmdSourcePath).read_text("utf-8")
            cls.writeTamperProofScript(termcmdPath, termcmdText)

        yKey = "y"
        nKey = "n"
        exitMessage = _("Command exited with code:")
        keyPrompt = _("Continue in a shell?") + f" [{yKey.upper()}/{nKey}]"

        script = textwrap.dedent(f"""\
            #!/usr/bin/env bash
            _GF_COMMAND={shlex.quote(shlex.join(commandTokens))}
            _GF_APPNAME={shlex.quote(qAppName())}
            _GF_YKEY={shlex.quote(yKey)}
            _GF_NKEY={shlex.quote(nKey)}
            _GF_EXITMESSAGE={shlex.quote(exitMessage)}
            _GF_KEYPROMPT={shlex.quote(keyPrompt)}
            _GF_WORKDIR={shlex.quote(workdir)}
            _GF_TESTMODE={"1" if APP_TESTMODE else "0"}
            source {shlex.quote(str(termcmdPath))}
        """)

        path = Path(qTempDir(), f"terminal_{hash(script):x}.sh")

        if not cls.untamperedScriptExists(path):
            cls.writeTamperProofScript(path, script)

        return str(path)

    @classmethod
    def spawnNewInstance(
            cls,
            module: str,
            sandbox: bool = True,
            extraImports: list[str] | None = None,
    ) -> tuple[list[str], dict[str, str]]:
        """
        Prepare a command to spawn another instance of this application.
        Return the command (list of tokens) and environment variables (dict).
        """
        assert module.startswith("gitfourchette"), module

        # In test mode, check that the module exports a main() function so that
        # we can use it from a PyInstaller app bundle.
        if APP_TESTMODE:
            imported = importlib.import_module(module)
            exported = getattr(imported, "__all__", dir(imported))
            assert "main" in exported, f"{module} should export 'main' for PyInstaller compat!"

        # The new instance is supposed to be a child process, so it inherits
        # the current process's environment variables. We don't need to copy
        # them to 'env' explicitly. An exception to this is PYTHONPATH, which is
        # sanitized by our restrictive interpreter options. In the case of a
        # non-frozen install, we'll forward a minimal PYTHONPATH so the core
        # dependencies can be found in the user's site-packages.
        env = {}

        # APP_TESTMODE may be enabled for this process without an env var if we
        # found pytest. Since pytest won't be in the minimal PYTHONPATH, ensure
        # the new instance inherits our APP_TESTMODE.
        if APP_TESTMODE and "APP_TESTMODE" not in os.environ:
            env["APP_TESTMODE"] = "1"

        # -B: Don't write .pyc files on import
        # -P: Don't prepend potentially unsafe path to sys.path (Python 3.11+)
        # -s: Don't add user site directory to sys.path
        # -m: Module name
        interpreterOptions = f"-BPsm{module}"

        if FLATPAK and not sandbox:
            # Command to be called by host system's git, which lives outside the
            # flatpak sandbox. Spawn another instance of our flatpak.
            tokens = ["flatpak", "run", "--command=python", FLATPAK_ID, interpreterOptions]
        elif APPIMAGE:
            # AVOID "sys.executable" (path to .AppImage file) to spawn a child,
            # may cause SIGTTIN in parent process!
            python = sys.orig_argv[0]  # python in AppImage tmpfs mount
            tokens = [python, interpreterOptions]
        elif PYINSTALLER_MEIPASS:
            # App bundle: special case in our __main__.py
            # (Note: core env vars that child will inherit from us:
            # APPIMAGE, APPDIR, ARGV0, SSL_CERT_FILE)
            tokens = [sys.executable, f"--start-module={module}"]
        else:
            # Spawn another Python interpreter. Forward a minimal PYTHONPATH so
            # our core dependencies can be found even with -s.
            minimalImports = _pythonpathCoreImports + (extraImports or [])
            env["PYTHONPATH"] = cls._minimalPythonpath(minimalImports)
            tokens = [sys.executable, interpreterOptions]

        assert tokens
        return tokens, env

    @classmethod
    def _minimalPythonpath(cls, moduleNames: list[str]) -> str:
        paths: set[str] = set()

        for name in moduleNames:
            spec = importlib.util.find_spec(name)
            if spec.origin is None:
                raise ImportError(f"Missing module import path: {spec.origin}")

            p = Path(spec.origin)
            if p.name == "__init__.py":
                # Example: /home/u/.local/lib/python3.14/site-packages/mfusepy.py
                # -------> /home/u/.local/lib/python3.14/site-packages
                p = p.parent.parent
            elif p.suffix == ".py":
                # Example: /usr/lib/python3.14/site-packages/pygit2/__init__.py
                # -------> /usr/lib/python3.14/site-packages
                p = p.parent

            paths.add(str(p))

        return os.pathsep.join(paths)

    @classmethod
    def terminatePlus(cls, process: QProcess | None):
        """
        QProcess.terminate() plus Windows console-mode quirks
        """
        if process is None:
            return

        if process.state() == QProcess.ProcessState.NotRunning:
            return

        _logger.info(f"Terminating process {process.program()} (PID {process.processId()})")
        process.terminate()

        if WINDOWS:
            # Detect unit tests that aren't annotated with @pytest.mark.notParallelizableOnWindows
            if APP_TESTMODE and os.environ.get("PYTEST_XDIST_WORKER", ""):
                currentTest = os.environ.get("PYTEST_CURRENT_TEST", "???")
                exitMessage = (f"!!! '{currentTest}' is trying to kill a subprocess, so it should "
                               f"be annotated with @pytest.mark.notParellizableOnWindows !!!")
                warnings.warn(exitMessage)
                sys.modules["pytest"].exit(exitMessage, returncode=1)

            tokens, env = ToolCommands.spawnNewInstance(gitfourchette.exttools.win32ctrlc.__name__)
            tokens.append(str(process.processId()))

            ctrlC = QProcess(None)
            ctrlC.setObjectName("win32ctrlc")
            ctrlC.setProgram(tokens[0])
            ctrlC.setArguments(tokens[1:])
            cls.setQProcessEnvironment(ctrlC, env)
            ctrlC.startDetached()
