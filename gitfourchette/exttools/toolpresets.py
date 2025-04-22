# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os
import shutil

from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.qt import *


class ToolPresets:
    DefaultDiffCommand = ""
    DefaultMergeCommand = ""
    DefaultTerminalCommand = ""
    FlatpakNamePrefix = "Flatpak: "

    Editors = {
        "System default": "",
        "BBEdit"        : "bbedit",
        "GVim"          : "gvim",
        "Kate"          : "kate",
        "KWrite"        : "kwrite",
        "MacVim"        : "mvim",
        "VS Code"       : "code",
    }

    DiffTools = {
        "Beyond Compare": "bcompare $L $R",
        "CLion"         : "clion diff $L $R",
        "DiffMerge"     : "diffmerge $L $R",
        "FileMerge"     : "assets:mac/opendiff.sh $L $R",
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
    MergeTools = {
        "Beyond Compare": "bcompare $L $R $B $M",
        "CLion"         : "clion merge $L $R $B $M",
        "DiffMerge"     : "diffmerge --merge --result=$M $L $B $R",
        "FileMerge"     : "assets:mac/opendiff.sh -ancestor $B $L $R -merge $M",
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

    _macTerminals = {
        "macOS Terminal": "assets:mac/terminal.scpt $COMMAND",
        "kitty"         : "kitty --single-instance $COMMAND",  # single instance looks better in dock
        "WezTerm"       : "wezterm start $COMMAND",  # 'start' instead of '-e' to reuse app instance
    }

    _windowsTerminals = {
        "Command Prompt": "cmd /c start cmd",
        "Git Bash"      : "cmd /c start bash",
        "PowerShell"    : "cmd /c start powershell",
    }

    _freedesktopTerminals = {
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
    Terminals = {
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
        allPresetDicts = [cls.Editors, cls.DiffTools, cls.MergeTools, cls.Terminals]

        if MACOS:
            excludeTools = winTools + freedesktopTools
            cls.Terminals.update(cls._macTerminals)
            defaultDiffPreset = "FileMerge"
            defaultMergePreset = "FileMerge"
            defaultTerminalPreset = "macOS Terminal"
        elif WINDOWS:
            excludeTools = macTools + freedesktopTools
            cls.Terminals.update(cls._windowsTerminals)
            defaultDiffPreset = "WinMerge"
            defaultMergePreset = "WinMerge"
            defaultTerminalPreset = "PowerShell"
        else:
            excludeTools = macTools + winTools
            cls.Terminals.update(cls._freedesktopTerminals)

            terminalScores = dict.fromkeys(cls._freedesktopTerminals, 0)
            terminalScores["Ptyxis"]         = [-2, 2][GNOME]  # Fedora
            terminalScores["GNOME Terminal"] = [-1, 1][GNOME]

            defaultDiffPreset = "Meld"
            defaultMergePreset = "Meld"
            defaultTerminalPreset = cls._findBestPreset(cls._freedesktopTerminals, terminalScores, "Konsole")

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
                    newCommand = ToolCommands.replaceProgramTokenInCommand(originalCommand, "flatpak", "run", flatpakId)
                    presets[k2] = newCommand

        cls.DefaultDiffCommand = cls._postProcessDefaultPreset(defaultDiffPreset, cls.DiffTools)
        cls.DefaultMergeCommand = cls._postProcessDefaultPreset(defaultMergePreset, cls.MergeTools)
        cls.DefaultTerminalCommand = cls._postProcessDefaultPreset(defaultTerminalPreset, cls.Terminals)

    @classmethod
    def _findBestPreset(cls, presets, scores, fallback):
        assert set(scores.keys()) == set(presets.keys())

        sortedScores = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)

        for candidate, _dummyScore in sortedScores:
            if shutil.which(presets[candidate]):
                return candidate

        return fallback

    @classmethod
    def _postProcessDefaultPreset(cls, key, presets):
        assert key in presets

        # If we're running as a Flatpak, use Flatpak as default tool as well
        if FLATPAK:
            flatpakKey = cls.FlatpakNamePrefix + key
            if flatpakKey in presets:
                key = flatpakKey

        return presets[key]

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
            interestingToken = ToolCommands.isFlatpakRunCommand(tokens)
            assert interestingToken >= 0

        try:
            name = tokens[interestingToken]
        except IndexError:
            return fallback

        name = os.path.basename(name)

        if MACOS:
            name = name.removesuffix(".app")

        return name


ToolPresets._filterToolPresets()
