# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import glob
import re
from pathlib import Path

from gitfourchette.forms.brandeddialog import convertToBrandedDialog
from gitfourchette.forms.ui_ignorepatterndialog import Ui_IgnorePatternDialog
from gitfourchette.localization import *
from gitfourchette.pycompat import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class IgnorePatternDialog(QDialog):
    def __init__(self, path: str, parent: QWidget):
        super().__init__(parent)

        ui = Ui_IgnorePatternDialog()
        ui.setupUi(self)
        self.ui = ui

        self.seedPath = path

        for k, v in self._samplePatternOptions(path).items():
            ui.patternEdit.addItemWithPreview(k, k, v)
        ui.patternEdit.setEditText("/" + path)

        for patternFile, patternFileDescription in self._excludePathOptions().items():
            ui.fileEdit.addItemWithPreview(patternFile, patternFile, patternFileDescription)

        validator = ValidatorMultiplexer(self)
        validator.connectInput(ui.patternEdit.lineEdit(), self.validate)
        validator.run(silenceEmptyWarnings=True)

        subtitle = _("Based off: {0}", hquo(path))
        convertToBrandedDialog(self, subtitleText=subtitle)

    @property
    def pattern(self) -> str:
        return self.ui.patternEdit.currentText()

    @property
    def excludePath(self) -> str:
        return self.ui.fileEdit.currentData(Qt.ItemDataRole.UserRole)

    def validate(self, pattern: str):
        if not pattern:
            return _("Please fill in this field.")

        seedPath = self.seedPath

        # Doctor the pattern to match glob rules
        if "/" not in pattern:
            pattern = "**/" + pattern
        else:
            pattern = pattern.removeprefix("/")

        regex1 = glob.translate(pattern, recursive=True, include_hidden=True)
        regex2 = glob.translate(pattern.removesuffix("/") + "/**", recursive=True, include_hidden=True)

        if re.match(regex1, seedPath):
            return ""

        if re.match(regex2, seedPath):
            return ""

        return _("This pattern doesn’t match the file that you selected.")

    @staticmethod
    def _samplePatternOptions(rawPath: str):
        path = Path(rawPath)

        samples = {
            "/" + rawPath: _("Just this specific path"),
        }

        # pd = str(pp.parent)
        absParent = "/" if str(path.parent) == "." else f"/{path.parent}/"
        if absParent != "/":
            samples[absParent] = _("Everything in this directory")

        suffix = path.suffix
        if suffix:
            wildSuffix = f"*{suffix}"
            samples[f"{absParent}**/{wildSuffix}"] = _("All {0} files in this directory tree", wildSuffix)
            samples[wildSuffix] = _("Any {0} file", wildSuffix)

        samples[path.name] = _("Any file with this exact name")

        return samples

    @staticmethod
    def _excludePathOptions():
        return {
            ".gitignore": _("Share pattern with other contributors"),
            ".git/info/exclude": _("Keep pattern private on this machine")
        }
