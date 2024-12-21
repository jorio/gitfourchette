# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------
import logging
import os
from dataclasses import dataclass
from typing import Literal

from gitfourchette import settings, colors
from gitfourchette.exttools import PREFKEY_MERGETOOL
from gitfourchette.forms.ui_conflictview import Ui_ConflictView
from gitfourchette.localization import *
from gitfourchette.mergedriver import MergeDriver
from gitfourchette.porcelain import NULL_OID, DiffConflict, ConflictSides, Repo
from gitfourchette.qt import *
from gitfourchette.tasks import HardSolveConflicts, AcceptMergeConflictResolution
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables

logger = logging.getLogger(__name__)


@dataclass
class ConflictViewKit:
    page: QWidget
    description: str = ""
    captionO: str = ""
    captionT: str = ""
    tipO: str = ""
    tipT: str = ""
    iconO: str = ""
    iconT: str = ""


class ConflictView(QWidget):
    openPrefs = Signal(str)

    repo: Repo | None
    currentConflict: DiffConflict | None
    currentMerge: MergeDriver | None
    currentMergeState: MergeDriver.State

    def __init__(self, parent=None):
        super().__init__(parent)

        self.repo = None  # will be set by RepoWidget
        self.currentConflict = None
        self.currentMerge = None
        self.currentMergeState = MergeDriver.State.Idle

        self.ui = Ui_ConflictView()
        self.ui.setupUi(self)

        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)

        tweakWidgetFont(self.ui.titleLabel, 130)
        tweakWidgetFont(self.ui.mergeToolButton, 88)

        self.ui.mergeToolButton.clicked.connect(lambda: self.openPrefs.emit(PREFKEY_MERGETOOL))
        self.ui.oursButton.clicked.connect(lambda: self.execute("ours"))
        self.ui.theirsButton.clicked.connect(lambda: self.execute("theirs"))
        self.ui.confirmDeletionButton.clicked.connect(lambda: self.execute("ancestor"))
        self.ui.mergeButton.clicked.connect(lambda: self.execute("merge"))
        self.ui.confirmMergeButton.clicked.connect(self.confirmMergeResolution)
        self.ui.discardMergeButton.clicked.connect(self.discardMergeResolution)
        self.ui.reworkMergeButton.clicked.connect(lambda: self.execute("remerge"))
        self.ui.cancelMergeInProgress.clicked.connect(self.cancelMergeInProgress)

        self.ui.confirmMergeButton.setIcon(stockIcon("SP_DialogSaveButton"))
        self.ui.discardMergeButton.setIcon(stockIcon("SP_DialogDiscardButton"))
        self.ui.reworkMergeButton.setIcon(stockIcon("SP_DialogRetryButton"))
        self.ui.cancelMergeInProgress.setIcon(stockIcon("SP_DialogCancelButton"))

    def execute(self, version: Literal["ours", "theirs", "merge", "remerge", "ancestor"]):
        conflict = self.currentConflict

        if not conflict:
            return

        elif conflict.deleted_by_us or conflict.added_by_them:
            assert conflict.theirs is not None
            assert version in ["ours", "theirs"]
            if version == "theirs":
                self.hardSolve(conflict.theirs.path, conflict.theirs.id)
            elif version == "ours":  # ignore incoming change, keep deletion
                self.hardSolve(conflict.theirs.path, NULL_OID)

        elif conflict.deleted_by_them or conflict.added_by_us:
            assert conflict.ours is not None
            assert version in ["ours", "theirs"]
            if version == "theirs":  # accept deletion
                self.hardSolve(conflict.ours.path, NULL_OID)
            elif version == "ours":  # ignore incoming deletion
                self.hardSolve(conflict.ours.path, conflict.ours.id)

        elif conflict.deleted_by_both:
            assert conflict.ancestor is not None
            assert version == "ancestor"
            self.hardSolve(conflict.ancestor.path, NULL_OID)

        elif conflict.modified_by_both or conflict.added_by_both:
            assert conflict.ours is not None
            assert conflict.theirs is not None
            assert version in ["ours", "theirs", "merge", "remerge"]
            if version == "ours":
                self.hardSolve(conflict.ours.path, conflict.ours.id)
            elif version == "theirs":
                self.hardSolve(conflict.ours.path, conflict.theirs.id)
            elif version == "merge":
                self.openMergeTool(conflict)
            elif version == "remerge":
                self.openMergeTool(conflict, True)

        else:
            raise NotImplementedError(f"unsupported conflict sides: {conflict.sides}")

    def hardSolve(self, path: str, oid=NULL_OID):
        HardSolveConflicts.invoke(self, {path: oid})

    def openMergeTool(self, conflict: DiffConflict, reopenWorkInProgress=False):
        mergeDriver = MergeDriver.findOngoingMerge(conflict)
        if mergeDriver is None:
            mergeDriver = MergeDriver(self, self.repo, conflict)
        mergeDriver.startProcess(reopenWorkInProgress)
        self.refresh()

    def onMergeDriverResponse(self):
        self.refresh()

    def invalidate(self):
        self.currentConflict = None

        if self.currentMerge is not None:
            self.currentMerge.statusChange.disconnect(self.onMergeDriverResponse)
            self.currentMerge = None

        self.currentMergeState = MergeDriver.State.Idle

    def refresh(self):
        if self.currentConflict is not None:
            self.displayConflict(self.currentConflict, forceRefresh=True)

    def displayConflict(self, conflict: DiffConflict, forceRefresh=False):
        assert conflict is not None, "don't call displayConflict with None"

        merge = MergeDriver.findOngoingMerge(conflict)

        # Don't bother refreshing if we're showing the exact same conflict
        if (not forceRefresh
                and conflict == self.currentConflict
                and merge is self.currentMerge
                and (merge.state if merge else MergeDriver.State.Idle) == self.currentMergeState):
            logger.debug("Don't need to refresh ConflictView")
            return

        self.invalidate()

        self.currentConflict = conflict
        self.currentMerge = merge
        if self.currentMerge:
            self.currentMerge.statusChange.connect(self.onMergeDriverResponse)
            self.currentMergeState = self.currentMerge.state
        else:
            self.currentMergeState = MergeDriver.State.Idle

        # Reset all text in widgets we can replace placeholder tokens.
        self.ui.retranslateUi(self)

        sides = conflict.sides
        kit = self.getKit(sides)

        isMergeBusy = merge and merge.state == MergeDriver.State.Busy
        isMergeFailed = merge and merge.state == MergeDriver.State.Fail
        isMergeReady = merge and merge.state == MergeDriver.State.Ready

        # Hide arrows if all we can do is pick ours/theirs.
        for w in self.ui.oursArrow, self.ui.theirsArrow:
            w.setVisible(kit.page is not self.ui.emptyPage)

        # Hide ours/theirs buttons if all we can do is confirm a deletion.
        for w in self.ui.oursButton, self.ui.theirsButton, self.ui.orLabel:
            w.setVisible(kit.page is not self.ui.confirmDeletionPage)

        # Reveal the page
        self.ui.stackedWidget.setCurrentWidget(kit.page)

        self.ui.oursButton.setText(kit.captionO)
        self.ui.oursButton.setToolTip(kit.tipO)
        self.ui.theirsButton.setText(kit.captionT)
        self.ui.theirsButton.setToolTip(kit.tipT)
        self.ui.explainer.setText(f"<b>{englishTitleCase(TrTables.conflictSides(sides))}.</b> {kit.description}")

        # Ours/theirs status icons
        iconOurs = stockIcon(kit.iconO).pixmap(QSize(16, 16), self.devicePixelRatio())
        iconTheirs = stockIcon(kit.iconT).pixmap(QSize(16, 16), self.devicePixelRatio())
        self.ui.oursIcon.setPixmap(iconOurs)
        self.ui.theirsIcon.setPixmap(iconTheirs)

        # Disable ours/theirs buttons while a merge process is running
        self.ui.oursButton.setEnabled(not isMergeBusy)
        self.ui.theirsButton.setEnabled(not isMergeBusy)

        # Format placeholders
        displayPath = os.path.basename(self.currentConflict.best_path)
        formatWidgetText(self.ui.titleLabel, lquo(displayPath))

        tool = lquoe(settings.getMergeToolName())
        for w in self.ui.mergeButton, self.ui.confirmMergeButton, self.ui.discardMergeButton, self.ui.reworkMergeButton:
            formatWidgetText(w, tool=tool)
            formatWidgetTooltip(w, tool=tool)

        # Process debriefing
        if isMergeFailed:
            self.ui.mergeToolStatus.setText(f"<b style='color: {colors.red.name()}'>{escape(merge.debrief)}</b>")
        else:
            self.ui.mergeToolStatus.setText("")

        # Merge busy/ready
        if isMergeBusy:
            assert merge.process is not None
            progressMessage = _("Waiting for you to finish merging this file in {0} (PID {1})…",
                                lquoe(merge.processName), merge.process.processId())
            self.ui.mergeInProgressLabel.setText(progressMessage)
            self.ui.stackedWidget.setCurrentWidget(self.ui.mergeInProgressPage)
        elif isMergeReady:
            self.ui.stackedWidget.setCurrentWidget(self.ui.mergeCompletePage)

    def refreshPrefs(self):
        if self.currentConflict:
            self.refresh()

    def confirmMergeResolution(self):
        merge = self.currentMerge
        assert merge is not None
        self.invalidate()
        AcceptMergeConflictResolution.invoke(self, merge)

    def discardMergeResolution(self):
        merge = self.currentMerge
        assert merge is not None
        merge.deleteNow()
        self.refresh()

    def cancelMergeInProgress(self):
        merge = self.currentMerge
        assert merge is not None
        merge.deleteNow()
        self.refresh()

    def getKit(self, sides: ConflictSides) -> ConflictViewKit:
        kitTable = {
            ConflictSides.MODIFIED_BY_BOTH: ConflictViewKit(
                page=self.ui.mergePage,
                description=_("This file has received changes from both <i>our</i> branch "
                                    "and <i>their</i> branch."),
                captionO=_("Keep OURS"),
                captionT=_("Accept THEIRS"),
                tipO=paragraphs(
                    _("Resolve the conflict by <b>rejecting incoming changes</b>."),
                    _("The file will remain unchanged from its state in HEAD.")),
                tipT=paragraphs(
                    _("Resolve the conflict by <b>accepting incoming changes</b>."),
                    _("The file will be <b>replaced</b> with the incoming version.")),
                iconO="status_m",
                iconT="status_m",
            ),

            ConflictSides.DELETED_BY_US: ConflictViewKit(
                page=self.ui.emptyPage,
                description=_("This file was deleted from <i>our</i> branch, "
                                    "but <i>their</i> branch kept it and made changes to it."),
                captionO=_("Keep OUR deletion"),
                captionT=_("Accept THEIR version"),
                tipO=paragraphs(
                    _("Resolve the conflict by <b>rejecting incoming changes</b>."),
                    _("The file won’t be added back to your branch.")),
                tipT=paragraphs(
                    _("Resolve the conflict by <b>accepting incoming changes</b>."),
                    _("The file will be restored to your branch with the incoming changes.")),
                iconO="status_d",
                iconT="status_m",
            ),

            ConflictSides.DELETED_BY_THEM: ConflictViewKit(
                page=self.ui.emptyPage,
                description=_("We’ve made changes to this file in <i>our</i> branch, "
                                    "but <i>their</i> branch has deleted it."),
                captionO=_("Keep OURS"),
                captionT=_("Accept deletion"),
                tipO=paragraphs(
                    _("Resolve the conflict by <b>rejecting the incoming deletion</b>."),
                    _("Our version of the file will be kept intact.")),
                tipT=paragraphs(
                    _("Resolve the conflict by <b>accepting the incoming deletion</b>."),
                    _("The file will be deleted.")),
                iconO="status_m",
                iconT="status_d",
            ),

            ConflictSides.ADDED_BY_US: ConflictViewKit(
                page=self.ui.emptyPage,
                description=_("No common ancestor."),
                captionO=_("Keep OURS"),
                captionT=_("Delete it"),
                iconO="status_a",
                iconT="status_missing",
            ),

            ConflictSides.ADDED_BY_THEM: ConflictViewKit(
                page=self.ui.emptyPage,
                description=_("No common ancestor."),
                captionO=_("Don’t add"),
                captionT=_("Accept THEIRS"),
                iconO="status_missing",
                iconT="status_a",
            ),

            ConflictSides.ADDED_BY_BOTH: ConflictViewKit(
                page=self.ui.mergePage,
                description=_("This file has been created in both <i>our</i> branch "
                                    "and <i>their</i> branch, independently from each other. "
                                    "There is no common ancestor."),
                captionO=_("Keep OURS"),
                captionT=_("Accept THEIRS"),
                tipO=paragraphs(
                    _("Resolve the conflict by <b>rejecting incoming changes</b>."),
                    _("The file will remain unchanged from its state in HEAD.")),
                tipT=paragraphs(
                    _("Resolve the conflict by <b>accepting incoming changes</b>."),
                    _("The file will be <b>replaced</b> with the incoming version.")),
                iconO="status_a",
                iconT="status_a",
            ),

            ConflictSides.DELETED_BY_BOTH: ConflictViewKit(
                page=self.ui.confirmDeletionPage,
                description=_("The file was deleted from <i>our</i> branch, "
                                    "and <i>their</i> branch has deleted it too."),
                iconO="status_d",
                iconT="status_d",
            ),
        }

        return kitTable[sides]

