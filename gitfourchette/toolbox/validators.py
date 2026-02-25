# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import QValidator


class ReplaceSpacesWithDashes(QValidator):
    def validate(self, text: str, pos: int) -> tuple[QValidator.State, str, int]:
        text = text.replace(" ", "-")
        return QValidator.State.Acceptable, text, pos
