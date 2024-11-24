# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os

from gitfourchette import settings, colors
from gitfourchette.exttools import PREFKEY_MERGETOOL
from gitfourchette.forms.ui_conflictview import Ui_ConflictView
from gitfourchette.mergedriver import MergeDriver
from gitfourchette.porcelain import NULL_OID, DiffConflict, ConflictSides
from gitfourchette.qt import *
from gitfourchette.tasks import HardSolveConflicts, AcceptMergeConflictResolution
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables


class ConflictView(QWidget):
    openPrefs = Signal(str)
    linkActivated = Signal(str)

    currentConflict: DiffConflict | None

    def __init__(self, parent=None):
        super().__init__(parent)

        self.currentConflict = None

        self.ui = Ui_ConflictView()
        self.ui.setupUi(self)

        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)

        self.buttonGroups = {
            ConflictSides.DELETED_BY_US: self.ui.radioGroupDbu,
            ConflictSides.DELETED_BY_THEM: self.ui.radioGroupDbt,
            ConflictSides.DELETED_BY_BOTH: self.ui.radioGroupDbb,
            ConflictSides.MODIFIED_BY_BOTH: self.ui.radioGroupBoth,
            ConflictSides.ADDED_BY_BOTH: self.ui.radioGroupBoth,  # reuse same group as MODIFIED_BY_BOTH
            ConflictSides.ADDED_BY_THEM: self.ui.radioGroupDbu,  # TODO: flavor text for dbu isn't great for this one
            ConflictSides.ADDED_BY_US: self.ui.radioGroupDbt,  # TODO: flavor text for dbt isn't great for this one
        }

        for radio in self.ui.groupBox.findChildren(QRadioButton):
            radio.clicked.connect(self.onRadioClicked)

        tweakWidgetFont(self.ui.titleLabel, 130)
        tweakWidgetFont(self.ui.explainer, 90)

        self.ui.explainer.linkActivated.connect(self.linkActivated)
        self.ui.confirmButton.clicked.connect(self.onConfirm)

        self.reformatWidgetText()

    def onConfirm(self):
        conflict = self.currentConflict

        if not conflict:
            return

        elif conflict.deleted_by_us or conflict.added_by_them:
            b = self.ui.radioGroupDbu.checkedButton()
            if not b:
                pass
            elif b is self.ui.radioDbuTheirs:
                self.hardSolve(conflict.theirs.path, conflict.theirs.id)
            elif b is self.ui.radioDbuOurs:  # ignore incoming change, keep deletion
                self.hardSolve(conflict.theirs.path, NULL_OID)

        elif conflict.deleted_by_them or conflict.added_by_us:
            b = self.ui.radioGroupDbt.checkedButton()
            if not b:
                pass
            elif b is self.ui.radioDbtTheirs:  # accept deletion
                self.hardSolve(conflict.ours.path, NULL_OID)
            elif b is self.ui.radioDbtOurs:  # ignore incoming deletion
                self.hardSolve(conflict.ours.path, conflict.ours.id)

        elif conflict.deleted_by_both:
            self.hardSolve(conflict.ancestor.path, NULL_OID)

        elif conflict.modified_by_both or conflict.added_by_both:
            b = self.ui.radioGroupBoth.checkedButton()
            if b is self.ui.radioOurs:
                self.hardSolve(conflict.ours.path, conflict.ours.id)
            elif b is self.ui.radioTheirs:
                self.hardSolve(conflict.ours.path, conflict.theirs.id)
            elif b is self.ui.radioTool:
                self.openMergeTool(conflict)

    def onMergeFailed(self, conflict: DiffConflict, code: int):
        if conflict != self.currentConflict:
            return

        if code < 0:
            message = self.tr("The merge tool failed to start.") + " " + self._selectMergeToolLink()
        else:
            message = self.tr("The merge tool exited without completing the merge (exit code {0})."
                              ).format(code)

        self.ui.explainer.setText(f"<b style='color: {colors.red.name()}'>" + message)

    def hardSolve(self, path: str, oid=NULL_OID):
        HardSolveConflicts.invoke(self, {path: oid})

    def openMergeTool(self, conflict: DiffConflict):
        self.ui.explainer.setText(self.tr("Waiting for merge tool..."))
        mergeDriver = MergeDriver(self, self.repo, conflict)
        mergeDriver.mergeComplete.connect(lambda: AcceptMergeConflictResolution.invoke(self, mergeDriver))
        mergeDriver.mergeFailed.connect(lambda code: self.onMergeFailed(conflict, code))
        mergeDriver.startProcess()

    def clear(self):
        self.currentConflict = None

    def displayConflict(self, conflict: DiffConflict, forceRefresh=False):
        assert conflict is not None, "don't call displayConflict with None"

        # Don't lose captions & focused widget if we're showing the exact same conflict
        if not forceRefresh and conflict == self.currentConflict:
            return

        self.currentConflict = conflict

        # Reset buttons
        for group in self.buttonGroups.values():
            group.setExclusive(False)  # must do this to actually be able to uncheck individual radios
            for b in group.buttons():
                b.setChecked(False)
                b.setVisible(False)
            group.setExclusive(True)
        self.ui.confirmButton.setEnabled(False)

        self.ui.retranslateUi(self)
        self.reformatWidgetText()

        if not conflict:
            return

        sides = conflict.sides
        group = self.buttonGroups[sides]
        for radio in group.buttons():
            radio.setVisible(True)

        sidesName = TrTables.conflictSides(sides)
        sidesName = sidesName[0].upper() + sidesName[1:]
        sidesHelp = TrTables.conflictSidesDescription(sides)
        helpText = f"<b>{sidesName}</b> – {sidesHelp}"
        self.ui.subtitleLabel.setText(helpText)

    def reformatWidgetText(self):
        formatWidgetText(self.ui.radioTool, tool=settings.getMergeToolName())

        if not self.currentConflict:
            return

        displayPath = os.path.basename(self.currentConflict.best_path)
        formatWidgetText(self.ui.titleLabel, lquo(displayPath))

    def onRadioClicked(self):
        assert self.currentConflict
        sides = self.currentConflict.sides
        group = self.buttonGroups[sides]

        radio: QRadioButton = group.checkedButton()
        assert isinstance(radio, QRadioButton)

        name = radio.objectName().removeprefix("radio").lower()
        help = TrTables.conflictHelp(name)
        help = help.format(app=qAppName(), tool=settings.getMergeToolName())
        if radio is self.ui.radioTool:
            help += " " + self._selectMergeToolLink()
        self.ui.explainer.setText(help)

        self.ui.confirmButton.setText(self.tr("Resolve Conflict"))
        self.ui.confirmButton.setEnabled(True)

    def refreshPrefs(self):
        if self.currentConflict:
            self.displayConflict(self.currentConflict, True)

    def _selectMergeToolLink(self):
        text = self.tr("Select another merge tool...")
        href = makeInternalLink("prefs", PREFKEY_MERGETOOL)
        return f"<a href='{href}'>{text}</a>"
