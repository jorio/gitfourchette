# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import itertools
import os
import shlex
import shutil
from collections.abc import Sequence

from gitfourchette.localization import *
from gitfourchette.qt import *


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
        "Terminal.app"  : "/System/Applications/Utilities/Terminal.app $P",
    }

    WindowsTerminalPresets = {
        "Command Prompt": "cmd /c start cmd",
        "Git Bash"      : "cmd /c start bash",
        "PowerShell"    : "cmd /c start powershell",
    }

    LinuxTerminalPresets = {
        "Debian default terminal": "x-terminal-emulator",  # only on Debian and derivatives
        "GNOME Terminal": "gnome-terminal",
        "Konsole"       : "konsole",
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
            cls.DefaultTerminalPreset = "Terminal.app"
        elif WINDOWS:
            excludeTools = macTools + freedesktopTools
            cls.TerminalPresets.update(cls.WindowsTerminalPresets)
            cls.DefaultDiffPreset = "WinMerge"
            cls.DefaultMergePreset = "WinMerge"
            cls.DefaultTerminalPreset = "PowerShell"
        else:
            excludeTools = macTools + winTools
            cls.TerminalPresets.update(cls.LinuxTerminalPresets)
            cls.DefaultDiffPreset = "Meld"
            cls.DefaultMergePreset = "Meld"
            cls.DefaultTerminalPreset = "Konsole"

            # Default to 'x-terminal-emulator' on Debian derivatives
            debianPreset = "Debian default terminal"
            if shutil.which(cls.LinuxTerminalPresets[debianPreset]):  # pragma: no cover
                cls.DefaultTerminalPreset = debianPreset
            else:
                excludeTools.append(debianPreset)
                if "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", ""):  # pragma: no cover
                    cls.DefaultTerminalPreset = "GNOME Terminal"

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

        tokens = shlex.split(command, posix=not WINDOWS)
        interestingToken = 0

        if FREEDESKTOP:
            interestingToken = cls.isFlatpakRunCommand(tokens)
            assert interestingToken >= 0

        try:
            name = tokens[interestingToken]
        except IndexError:
            return fallback

        name = name.removeprefix('"').removeprefix("'")
        name = name.removesuffix('"').removesuffix("'")
        name = os.path.basename(name)

        if MACOS:
            name = name.removesuffix(".app")

        return name

    @classmethod
    def replaceProgramTokenInCommand(cls, command: str, *newProgramTokens: str):
        tokens = shlex.split(command, posix=not WINDOWS)
        tokens = list(newProgramTokens) + tokens[1:]

        newCommand = shlex.join(tokens)

        # Remove single quotes added around our placeholders by shlex.join()
        # (e.g. '$L' --> $L, '--output=$M' --> $M)
        import re
        newCommand = re.sub(r" '(\$[0-9A-Z])'", r" \1", newCommand, flags=re.I | re.A)
        newCommand = re.sub(r" '(--?[a-z]+=\$[0-9A-Z])'", r" \1", newCommand, flags=re.I | re.A)

        return newCommand

    @classmethod
    def checkCommand(cls, command: str, *placeholders: str) -> str:
        try:
            cls.compileCommand(command, {k: "PLACEHOLDER" for k in placeholders}, [])
            return ""
        except ValueError as e:
            return str(e)

    @classmethod
    def compileCommand(cls, command: str, replacements: dict[str, str], positional: list[str]) -> tuple[list[str], str]:
        tokens = shlex.split(command, posix=not WINDOWS)

        for placeholder, replacement in replacements.items():
            mandatory = not placeholder.endswith("?")
            placeholder = placeholder.removesuffix("?")
            for i, tok in enumerate(tokens):  # noqa: B007
                if tok.endswith(placeholder):
                    prefix = tok.removesuffix(placeholder)
                    break
            else:
                if mandatory:
                    raise ValueError(_("Placeholder token {0} missing.", placeholder))
                else:
                    continue
            if replacement:
                tokens[i] = prefix + replacement
            else:
                del tokens[i]

        # Just append other paths to end of command line...
        tokens.extend(positional)

        # Find appropriate workdir
        workingDirectory = ""
        for argument in itertools.chain(replacements.values(), positional):
            if not argument:
                continue
            workingDirectory = os.path.dirname(argument)
            if os.path.isdir(workingDirectory):
                break

        # If we're running a Flatpak, expose the working directory to its sandbox.
        # (Inject '--filesystem=...' argument after 'flatpak run')
        indexAfterFlatpakRun = cls.isFlatpakRunCommand(tokens)
        if indexAfterFlatpakRun > 0:
            tokens.insert(indexAfterFlatpakRun, "--filesystem=" + workingDirectory)

        # macOS-specific wrapper:
        # - Launch ".app" bundles properly.
        # - Wait on opendiff (Xcode FileMerge).
        if MACOS:
            launcherScript = QFile("assets:mactool.sh")
            assert launcherScript.exists()
            tokens.insert(0, launcherScript.fileName())

        # Flatpak-specific wrapper:
        # - Run external tool outside flatpak sandbox.
        # - Set workdir via flatpak-spawn because QProcess.setWorkingDirectory won't work.
        # - Run command through `env` to get return code 127 if the command is missing.
        #   (note that running ANOTHER flatpak via 'flatpak run' won't return 127).
        if FLATPAK:
            spawner = [
                "flatpak-spawn", "--watch-bus", "--host", f"--directory={workingDirectory}",
                "/usr/bin/env", "--"
            ]
            tokens = spawner + tokens

        return tokens, workingDirectory

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


ToolCommands._filterToolPresets()
