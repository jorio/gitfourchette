# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import itertools
import os
import re
import shlex
import shutil
import textwrap
from collections.abc import Sequence
from pathlib import Path

from gitfourchette.localization import *
from gitfourchette.qt import *

_placeholderPattern = re.compile(r"\$[_a-zA-Z0-9]+")


class ToolCommands:
    DefaultDiffPreset = ""
    DefaultMergePreset = ""
    DefaultTerminalPreset = ""
    FlatpakNamePrefix = "Flatpak: "

    EditorPresets = {
        "System default": "",
        "BBEdit"        : "bbedit",
        "GVim"          : "gvim",
        "Kate"          : "kate",
        "KWrite"        : "kwrite",
        "MacVim"        : "mvim",
        "VS Code"       : "code",
    }

    DiffPresets = {
        "Beyond Compare": "bcompare $L $R",
        "CLion"         : "clion diff $L $R",
        "DiffMerge"     : "diffmerge $L $R",
        "FileMerge"     : "opendiff $L $R",
        "GVim"          : "gvim -f -d $L $R",
        "IntelliJ IDEA" : "idea diff $L $R",
        "KDiff3"        : "kdiff3 $L $R",
        "MacVim"        : "mvim -f -d $L $R",
        "Meld"          : "meld $L $R",
        "P4Merge"       : "p4merge $L $R",
        "PyCharm"       : "pycharm diff $L $R",
        "VS Code"       : "code --new-window --wait --diff $L $R",
        "WinMerge"      : "winmergeu /u /wl /wr $L $R",
    }

    # $B: ANCESTOR/BASE/CENTER
    # $L: OURS/LOCAL/LEFT
    # $R: THEIRS/REMOTE/RIGHT
    # $M: MERGED/OUTPUT
    MergePresets = {
        "Beyond Compare": "bcompare $L $R $B $M",
        "CLion"         : "clion merge $L $R $B $M",
        "DiffMerge"     : "diffmerge --merge --result=$M $L $B $R",
        "FileMerge"     : "opendiff -ancestor $B $L $R -merge $M",
        "GVim"          : "gvim -f -d -c 'wincmd J' $M $L $B $R",
        "IntelliJ IDEA" : "idea merge $L $R $B $M",
        "KDiff3"        : "kdiff3 --merge $B $L $R --output $M",
        "MacVim"        : "mvim -f -d -c 'wincmd J' $M $L $B $R",
        "Meld"          : "meld --auto-merge $L $B $R --output=$M",
        "P4Merge"       : "p4merge $B $L $R $M",
        "PyCharm"       : "pycharm merge $L $R $B $M",
        "VS Code"       : "code --new-window --wait --merge $L $R $B $M",
        "WinMerge"      : "winmergeu /u /wl /wm /wr /am $B $L $R /o $M",
    }

    MacTerminalPresets = {
        "macOS Terminal": "assets:mac/terminal.scpt $COMMAND",
        "kitty"         : "kitty --single-instance $COMMAND",  # single instance looks better in dock
        "WezTerm"       : "wezterm start $COMMAND",  # 'start' instead of '-e' to reuse app instance
    }

    WindowsTerminalPresets = {
        "Command Prompt": "cmd /c start cmd",
        "Git Bash"      : "cmd /c start bash",
        "PowerShell"    : "cmd /c start powershell",
    }

    LinuxTerminalPresets = {
        "Alacritty"     : "alacritty -e $COMMAND",
        "Contour"       : "contour $COMMAND",
        "foot"          : "foot $COMMAND",
        "GNOME Terminal": "gnome-terminal -- $COMMAND",
        "kitty"         : "kitty $COMMAND",
        "Konsole"       : "konsole -e $COMMAND",
        "Ptyxis"        : "ptyxis -x $COMMAND",
        "st"            : "st -e $COMMAND",
        "urxvt"         : "urxvt -e $COMMAND",
        "WezTerm"       : "wezterm -e $COMMAND",
        "xterm"         : "xterm -e $COMMAND",
    }

    # Filled in depending on platform
    TerminalPresets = {
    }

    FlatpakIDs = {
        "CLion"             : ("CLion",         "com.jetbrains.CLion"),
        "GVim"              : ("GVim",          "org.vim.Vim"),
        "IntelliJ IDEA CE"  : ("IntelliJ IDEA", "com.jetbrains.IntelliJ-IDEA-Community"),
        "PyCharm CE"        : ("PyCharm",       "com.jetbrains.PyCharm-Community"),
        "Kate"              : ("Kate",          "org.kde.kate"),
        "KDiff3"            : ("KDiff3",        "org.kde.kdiff3"),
        "KWrite"            : ("KWrite",        "org.kde.kwrite"),
        "Meld"              : ("Meld",          "org.gnome.meld"),
        "VS Code"           : ("VS Code",       "com.visualstudio.code"),
        "VS Code OSS"       : ("VS Code",       "com.visualstudio.code-oss"),
        # Terminals
        "Konsole"           : ("Konsole",       "org.kde.konsole"),
    }

    @staticmethod
    def splitCommandTokens(command: str) -> list[str]:
        # Treat command as POSIX even on Windows!
        return shlex.split(command, posix=True)

    @classmethod
    def _filterToolPresets(cls):
        freedesktopTools = ["Kate", "KWrite"]
        macTools = ["FileMerge", "MacVim", "BBEdit"]
        winTools = ["WinMerge"]
        allPresetDicts = [cls.EditorPresets, cls.DiffPresets, cls.MergePresets, cls.TerminalPresets]

        if MACOS:
            excludeTools = winTools + freedesktopTools
            cls.TerminalPresets.update(cls.MacTerminalPresets)
            cls.DefaultDiffPreset = "FileMerge"
            cls.DefaultMergePreset = "FileMerge"
            cls.DefaultTerminalPreset = "macOS Terminal"
        elif WINDOWS:
            excludeTools = macTools + freedesktopTools
            cls.TerminalPresets.update(cls.WindowsTerminalPresets)
            cls.DefaultDiffPreset = "WinMerge"
            cls.DefaultMergePreset = "WinMerge"
            cls.DefaultTerminalPreset = "PowerShell"
        else:
            excludeTools = macTools + winTools
            cls.TerminalPresets.update(cls.LinuxTerminalPresets)

            terminalScores = dict.fromkeys(cls.LinuxTerminalPresets, 0)
            terminalScores["Ptyxis"]         = [-2, 2][GNOME]
            terminalScores["GNOME Terminal"] = [-1, 1][GNOME]

            cls.DefaultDiffPreset = "Meld"
            cls.DefaultMergePreset = "Meld"
            cls.DefaultTerminalPreset = cls._findBestCommand(cls.LinuxTerminalPresets, terminalScores, "Konsole")

        for key in excludeTools:
            for presets in allPresetDicts:
                try:
                    del presets[key]
                except KeyError:
                    pass

        if FREEDESKTOP:
            for name, (alias, flatpakId) in cls.FlatpakIDs.items():
                k2 = cls.FlatpakNamePrefix + name
                assert any(
                    alias in presets for presets in allPresetDicts), f"missing non-flatpak preset for {alias}"
                for presets in allPresetDicts:
                    try:
                        originalCommand = presets[alias]
                    except KeyError:
                        continue
                    newCommand = cls.replaceProgramTokenInCommand(originalCommand, "flatpak", "run", flatpakId)
                    presets[k2] = newCommand

        cls.DefaultDiffPreset = cls._postProcessDefault(cls.DefaultDiffPreset, cls.DiffPresets)
        cls.DefaultMergePreset = cls._postProcessDefault(cls.DefaultMergePreset, cls.MergePresets)
        cls.DefaultTerminalPreset = cls._postProcessDefault(cls.DefaultTerminalPreset, cls.TerminalPresets)

    @classmethod
    def _postProcessDefault(cls, baseKey, presets):
        assert baseKey in presets

        # If we're running as a Flatpak, use Flatpak as default tool as well
        if FLATPAK:
            flatpakKey = cls.FlatpakNamePrefix + baseKey
            if flatpakKey in presets:
                return flatpakKey

        return baseKey

    @classmethod
    def _findBestCommand(cls, presets, scores, fallback):
        assert set(scores.keys()) == set(presets.keys())

        sortedScores = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)

        for candidate, _dummyScore in sortedScores:
            if shutil.which(presets[candidate]):
                return candidate

        return fallback

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
    def getCommandName(cls, command: str, fallback = "", presets: dict[str, str] | None = None) -> str:
        if not command.strip():
            return fallback

        if presets is not None:
            presetName = next((k for k, v in presets.items() if v == command), "")
            if presetName:
                if presetName.startswith(cls.FlatpakNamePrefix):
                    presetName = presetName.removeprefix(cls.FlatpakNamePrefix)
                    presetName += " (Flatpak)"
                return presetName

        tokens = ToolCommands.splitCommandTokens(command)
        interestingToken = 0

        if FREEDESKTOP:
            interestingToken = cls.isFlatpakRunCommand(tokens)
            assert interestingToken >= 0

        try:
            name = tokens[interestingToken]
        except IndexError:
            return fallback

        name = os.path.basename(name)

        if MACOS:
            name = name.removesuffix(".app")

        return name

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

        for token in tokens:
            matches = list(_placeholderPattern.finditer(token))

            for match in reversed(matches):
                placeholder = match.group()
                try:
                    replacement = replacements[placeholder]
                except KeyError as replacementNotFoundError:
                    raise ValueError(_("Placeholder token {0} isn’t supported here.", placeholder)
                                     ) from replacementNotFoundError
                token = token[:match.start()] + replacement + token[match.end():]

            if token:
                newTokens.append(token)

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

        # macOS-specific wrapper:
        # - Launch ".app" bundles properly.
        # - Wait on opendiff (Xcode FileMerge).
        if MACOS:
            launcherScript = QFile("assets:mac/wrapper.sh")
            assert launcherScript.exists()
            tokens.insert(0, launcherScript.fileName())

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


ToolCommands._filterToolPresets()
