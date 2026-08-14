# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations  # TODO: Remove once we can drop support for Python <= 3.13

import logging
import os
from dataclasses import dataclass
from typing import Literal, ClassVar
from weakref import ReferenceType

from gitfourchette import colors
from gitfourchette import trtables
from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.codeview.codewindow import CodeWindow
from gitfourchette.exttools.mergedriver import MergeDriver
from gitfourchette.exttools.toolprocess import ToolProcess
from gitfourchette.forms.ui_conflictview import Ui_ConflictView
from gitfourchette.gitdriver import GitConflict, GitConflictSides
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.repomodel import RepoModel
from gitfourchette.tasks import HardSolveConflicts, AcceptMergeConflictResolution, OpenMergeTool
from gitfourchette.tasks.indextasks import PreviewDeltaFile
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)


class ConflictView(QWidget):
    openPrefs = Signal(str)

    repoModel: RepoModel
    currentConflict: GitConflict | None
    currentMerge: MergeDriver | None
    currentMergeState: MergeDriver.State
    currentPreviewWindows: list[ReferenceType[QWidget]]

    def __init__(self, repoModel: RepoModel, parent=None):
        super().__init__(parent)

        self.repoModel = repoModel
        self.currentConflict = None
        self.currentMerge = None
        self.currentMergeState = MergeDriver.State.Idle
        self.currentPreviewWindows = []

        self.ui = Ui_ConflictView()
        self.ui.setupUi(self)

        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setAutoFillBackground(True)

        tweakWidgetFont(self.ui.titleLabel, 130)
        tweakWidgetFont(self.ui.mergeToolButton, 88)

        self.ui.oursPreviewButton.setIcon(stockIcon("view-visible"))
        self.ui.theirsPreviewButton.setIcon(stockIcon("view-visible"))
        self.ui.oursPreviewButton.clicked.connect(lambda: self.openPreview("ours"))
        self.ui.theirsPreviewButton.clicked.connect(lambda: self.openPreview("theirs"))

        self.ui.mergeToolButton.clicked.connect(lambda: self.openPrefs.emit(ToolProcess.PrefKeyMergeTool))
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

        GFApplication.instance().prefsChanged.connect(self.refreshPrefs)

    def execute(self, version: Literal["ours", "theirs", "merge", "remerge", "ancestor"]):
        conflict = self.currentConflict

        if not conflict:
            return

        S = GitConflictSides

        if conflict.sides in (S.DeletedByUs, S.AddedByThem):
            # Theirs: take incoming change. Ours: keep deletion.
            assert conflict.theirs
            assert version in ["ours", "theirs"]
            if version == "ours":
                # Ours - Keep deletion
                self.hardSolveRemove(conflict.theirs.path)
            else:
                # Theirs - Take incoming changes
                self.hardSolveTakeTheirs(conflict.theirs.path)

        elif conflict.sides in (S.DeletedByThem, S.AddedByUs):
            # Theirs: take incoming deletion. Ours: ignore deletion.
            assert conflict.ours
            assert version in ["ours", "theirs"]
            if version == "ours":
                # Ours - Ignore deletion
                self.hardSolveKeepOurs(conflict.ours.path)
            else:
                # Theirs - Take incoming deletion
                self.hardSolveRemove(conflict.ours.path)

        elif conflict.sides == S.BothDeleted:
            # Delete the file.
            assert conflict.ancestor
            assert version == "ancestor"
            self.hardSolveRemove(conflict.ancestor.path)

        elif conflict.sides in (S.BothModified, S.BothAdded):
            # Pick a side to keep, or merge.
            assert conflict.ours
            assert conflict.theirs
            assert version in ["ours", "theirs", "merge", "remerge"]
            if version == "ours":
                self.hardSolveKeepOurs(conflict.ours.path)
            elif version == "theirs":
                self.hardSolveTakeTheirs(conflict.theirs.path)
            else:
                reopen = version == "remerge"
                self.openMergeTool(conflict, reopen)

        else:
            raise NotImplementedError(f"unsupported conflict sides: {conflict.sides}")

    def hardSolveKeepOurs(self, path: str):
        HardSolveConflicts.invoke(self, [path], [], [])

    def hardSolveTakeTheirs(self, path: str):
        HardSolveConflicts.invoke(self, [], [path], [])

    def hardSolveRemove(self, path: str):
        HardSolveConflicts.invoke(self, [], [], [path])

    def openMergeTool(self, conflict: GitConflict, reopenWorkInProgress=False):
        OpenMergeTool.invoke(self, conflict, reopenWorkInProgress)
        self.refresh()

    def onMergeDriverResponse(self):
        self.refresh()

    def openPreview(self, oursOrTheirs: Literal["ours", "theirs"]):
        assert oursOrTheirs in ["ours", "theirs"]
        assert self.currentConflict is not None

        if oursOrTheirs == "ours":
            df = self.currentConflict.ours
            prefix = _p("ConflictView", "OUR version")
        else:
            df = self.currentConflict.theirs
            prefix = _p("ConflictView", "THEIR version")

        assert not df.isId0()
        PreviewDeltaFile.invoke(self, df, prefix, self.registerPreviewWindow)

    def registerPreviewWindow(self, preview: CodeWindow):
        self.currentPreviewWindows.append(ReferenceType(preview))
        self.destroyed.connect(preview.close)

    def invalidate(self):
        self.currentConflict = None

        if self.currentMerge is not None:
            self.currentMerge.statusChange.disconnect(self.onMergeDriverResponse)
            self.currentMerge = None

        self.currentMergeState = MergeDriver.State.Idle

        while self.currentPreviewWindows:
            previewWindowRef = self.currentPreviewWindows.pop()
            previewWindow = previewWindowRef()
            if previewWindow is not None:
                previewWindow.close()

    def refresh(self):
        if self.currentConflict is not None:
            self.displayConflict(self.currentConflict, forceRefresh=True)

    def displayConflict(self, conflict: GitConflict, forceRefresh=False):
        assert conflict is not None, "don't call displayConflict with None"

        merge = MergeDriver.findOngoingMerge(conflict)
        state = merge.state if merge else MergeDriver.State.Idle

        # Don't bother refreshing if we're showing the exact same conflict
        if (not forceRefresh
                and conflict == self.currentConflict
                and merge is self.currentMerge
                and state == self.currentMergeState
                and state != MergeDriver.State.Tentative
        ):
            logger.debug("Don't need to refresh ConflictView")
            return

        # If tentative, try to transition to Ready
        if state == MergeDriver.State.Tentative:
            assert merge is not None
            if not merge.checkUnchanged():
                state = MergeDriver.State.Ready
                merge.state = state
            else:
                logger.debug(f"Unchanged: {merge.paths.scratch} {merge.paths.target}")

        self.invalidate()

        self.currentConflict = conflict
        self.currentMerge = merge
        if self.currentMerge:
            self.currentMerge.statusChange.connect(self.onMergeDriverResponse)
            self.currentMergeState = self.currentMerge.state
        else:
            self.currentMergeState = MergeDriver.State.Idle

        sides = conflict.sides
        strings = GitConflictSidesLocalization.getStrings(sides)

        # Reset all text in widgets we can replace placeholder tokens.
        self.ui.retranslateUi(self)

        # Determine page.
        if sides.hasOurs() and sides.hasTheirs():
            page = self.ui.mergePage
        elif sides.hasOurs() or sides.hasTheirs():
            page = self.ui.emptyPage
        else:
            page = self.ui.confirmDeletionPage

        # Hide arrows if all we can do is pick ours/theirs.
        w: QWidget
        for w in self.ui.oursArrow, self.ui.theirsArrow:
            w.setVisible(page is not self.ui.emptyPage)

        # Hide ours/theirs buttons if all we can do is confirm a deletion.
        for w in self.ui.oursButton, self.ui.theirsButton, self.ui.orLabel:
            w.setVisible(page is not self.ui.confirmDeletionPage)

        # Reveal the page
        self.ui.stackedWidget.setCurrentWidget(page)

        self.ui.oursButton.setText(strings.actionOurs)
        self.ui.oursButton.setToolTip(strings.tipOurs)
        self.ui.theirsButton.setText(strings.actionTheirs)
        self.ui.theirsButton.setToolTip(strings.tipTheirs)
        self.ui.explainer.setText(f"<b>{strings.title}.</b> {strings.description}")

        self.ui.oursPreviewButton.setEnabled(sides.hasOurs())
        self.ui.theirsPreviewButton.setEnabled(sides.hasTheirs())

        # Disable ours/theirs buttons while a merge process is running
        self.ui.oursButton.setEnabled(state != MergeDriver.State.Busy)
        self.ui.theirsButton.setEnabled(state != MergeDriver.State.Busy)

        # Ours/theirs status icons
        iconO = "m" if sides.hasOurs() else "missing" if sides == sides.AddedByThem else "d"
        iconT = "m" if sides.hasTheirs() else "missing" if sides == sides.AddedByUs else "d"
        for iconLetter, label in ((iconO, self.ui.oursIcon), (iconT, self.ui.theirsIcon)):
            icon = stockIcon(f"status_{iconLetter}")
            pixmap = icon.pixmap(QSize(16, 16), self.devicePixelRatio())
            label.setPixmap(pixmap)

        # Format placeholders
        displayPath = os.path.basename(self.currentConflict.ours.path)
        formatWidgetText(self.ui.titleLabel, lquo(displayPath))

        tool = lquoe(settings.getMergeToolName())
        for w in self.ui.mergeButton, self.ui.confirmMergeButton, self.ui.discardMergeButton, self.ui.reworkMergeButton:
            formatWidgetText(w, tool=tool)
            formatWidgetTooltip(w, tool=tool)

        # Process debriefing
        if state == MergeDriver.State.Fail:
            self.ui.mergeToolStatus.setText(f"<b style='color: {colors.red.name()}'>{escape(merge.debrief)}</b>")
        else:
            self.ui.mergeToolStatus.setText("")

        # Merge busy/ready
        if state == MergeDriver.State.Busy:
            assert merge is not None
            assert merge.process is not None
            progressMessage = _("Waiting for you to finish merging this file in {0} (PID {1})…",
                                lquoe(merge.processName), merge.process.processId())
            self.ui.mergeInProgressLabel.setText(progressMessage)
            self.ui.stackedWidget.setCurrentWidget(self.ui.mergeInProgressPage)
        elif state == MergeDriver.State.Tentative:
            # Some merge tools like PyCharm may return 0 but postpone writing
            # the actual file from a different process some time later.
            confirmText = _("The file seems unchanged by {0}. Was the merge successful?", lquoe(merge.processName))
            confirmText = f"<b style='color: {colors.red.name()}'>{escape(confirmText)}</b>"
            self.ui.confirmMergeLabel.setText(confirmText)
            self.ui.stackedWidget.setCurrentWidget(self.ui.mergeCompletePage)
        elif state == MergeDriver.State.Ready:
            confirmText = _p("ConflictView", "It looks like you’ve finished merging this file.")
            self.ui.confirmMergeLabel.setText(confirmText)
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


@dataclass
class GitConflictSidesLocalization:
    description: str
    actionOurs: str = ""
    actionTheirs: str = ""
    tipOurs: str = ""
    tipTheirs: str = ""
    title: str = "???"

    _cached: ClassVar[dict[GitConflictSides, GitConflictSidesLocalization]] = {}
    _cachedLanguage: ClassVar[str] = ""

    @classmethod
    def getStrings(cls, sides: GitConflictSides) -> GitConflictSidesLocalization:
        table = cls._cached

        if cls._cachedLanguage != settings.prefs.language:
            cls._cachedLanguage = settings.prefs.language
            table.clear()

        try:
            return table[sides]
        except KeyError:
            pass

        table[GitConflictSides.BothModified] = GitConflictSidesLocalization(
            _("This file has received changes from both "
              "<i>our</i> branch and <i>their</i> branch."),
            _("Keep OURS"),
            _("Accept THEIRS"),
            paragraphs(
                _("Resolve the conflict by <b>rejecting incoming changes</b>."),
                _("The file will remain unchanged from its state in HEAD.")),
            paragraphs(
                _("Resolve the conflict by <b>accepting incoming changes</b>."),
                _("The file will be <b>replaced</b> with the incoming version.")),
        )

        table[GitConflictSides.DeletedByUs] = GitConflictSidesLocalization(
            _("This file was deleted from <i>our</i> branch, "
              "but <i>their</i> branch kept it and made changes to it."),
            _("Keep OUR deletion"),
            _("Accept THEIR version"),
            paragraphs(
                _("Resolve the conflict by <b>rejecting incoming changes</b>."),
                _("The file won’t be added back to your branch.")),
            paragraphs(
                _("Resolve the conflict by <b>accepting incoming changes</b>."),
                _("The file will be restored to your branch with the incoming changes.")),
        )

        table[GitConflictSides.DeletedByThem] = GitConflictSidesLocalization(
            _("We’ve made changes to this file in <i>our</i> branch, "
              "but <i>their</i> branch has deleted it."),
            _("Keep OURS"),
            _("Accept deletion"),
            paragraphs(
                _("Resolve the conflict by <b>rejecting the incoming deletion</b>."),
                _("Our version of the file will be kept intact.")),
            paragraphs(
                _("Resolve the conflict by <b>accepting the incoming deletion</b>."),
                _("The file will be deleted.")),
        )

        table[GitConflictSides.AddedByUs] = GitConflictSidesLocalization(
            _("No common ancestor."),
            _("Keep OURS"),
            _("Delete it"),
        )

        table[GitConflictSides.AddedByThem] = GitConflictSidesLocalization(
            _("No common ancestor."),
            _("Don’t add"),
            _("Accept THEIRS"),
        )

        table[GitConflictSides.BothAdded] = GitConflictSidesLocalization(
            _("This file has been created in both <i>our</i> branch "
              "and <i>their</i> branch, independently from each other. "
              "There is no common ancestor."),
            _("Keep OURS"),
            _("Accept THEIRS"),
            paragraphs(
                _("Resolve the conflict by <b>rejecting incoming changes</b>."),
                _("The file will remain unchanged from its state in HEAD.")),
            paragraphs(
                _("Resolve the conflict by <b>accepting incoming changes</b>."),
                _("The file will be <b>replaced</b> with the incoming version.")),
        )

        table[GitConflictSides.BothDeleted] = GitConflictSidesLocalization(
            _("The file was deleted from <i>our</i> branch, "
              "and <i>their</i> branch has deleted it too."),
        )

        # Fill in titles
        for k, v in table.items():
            v.title = englishTitleCase(trtables.enum(k))

        return table[sides]
