# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *
from gitfourchette.toolbox import MultiShortcut, makeMultiShortcut


class GlobalShortcuts:
    NO_SHORTCUT: MultiShortcut = []

    find: MultiShortcut = NO_SHORTCUT
    refresh: MultiShortcut = NO_SHORTCUT
    openRepoFolder: MultiShortcut = NO_SHORTCUT
    openTerminal: MultiShortcut = NO_SHORTCUT

    stageHotkeys = [Qt.Key.Key_Return, Qt.Key.Key_Enter]  # Return: main keys; Enter: on keypad
    discardHotkeys = [Qt.Key.Key_Delete, Qt.Key.Key_Backspace]

    _initialized = False

    @classmethod
    def initialize(cls):
        if cls._initialized:
            return

        assert QApplication.instance(), "QApplication must have been created before instantiating QKeySequence"

        cls.find = makeMultiShortcut(QKeySequence.StandardKey.Find, "/")
        cls.refresh = makeMultiShortcut(QKeySequence.StandardKey.Refresh, "Ctrl+R", "F5")
        cls.openRepoFolder = makeMultiShortcut("Ctrl+Shift+O")
        cls.openTerminal = makeMultiShortcut("Ctrl+Alt+O")

        cls._initialized = True
