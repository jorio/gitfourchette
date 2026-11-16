# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import trtables, settings
from gitfourchette.forms.ui_rebasedialog import Ui_RebaseDialog
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.qt import *
from gitfourchette.rebase.rebasemodel import RebaseOp, RebaseOpColors, RebaseOpLetters, SupportedRebaseOps, TRebaseSequence
from gitfourchette.rebase.rebasesequencemodel import RebaseSequenceModel, RebaseUndoCommand
from gitfourchette.toolbox import *


class RebaseDialog(QDialog):
    LastGeometry = b""

    exploreCommit = Signal(NavLocator)

    initialSequence: TRebaseSequence
    rebaseDateArg: str
    undoStack: QUndoStack

    @property
    def sequenceModel(self) -> RebaseSequenceModel:
        return self.ui.sequence.sequenceModel

    def __init__(self, initialSequence: TRebaseSequence, parent: QWidget | None):
        super().__init__(parent)

        self.ui = Ui_RebaseDialog()
        self.ui.setupUi(self)

        self.rebaseDateArg = settings.prefs.rebaseDateArg
        self.undoStack = QUndoStack(self)

        # Install initial sequence into model
        self.initialSequence = initialSequence
        self.sequenceModel.replaceSequence(initialSequence)

        # When data changes, flag the sequence as modified so that reject() asks
        # for confirmation before closing.
        self.sequenceModel.rowsMoved.connect(self._onSequenceEdited)
        self.sequenceModel.dataChanged.connect(self._onSequenceEdited)
        self.sequenceModel.modelReset.connect(lambda: self._onSequenceEdited(pushUndo=False))  # emitted after undo/redo

        self.ui.sequence.customContextMenuRequested.connect(self.onContextMenuRequested)
        self.ui.sequence.opShortcut.connect(self.setCommandOnSelection)
        self.ui.sequence.commitSelected.connect(lambda oid: self.exploreCommit.emit(NavLocator.inCommit(oid)))

        # Restore window geometry (TODO: On GNOME, is issue #50 still relevant?)
        if not GNOME and RebaseDialog.LastGeometry:
            self.restoreGeometry(RebaseDialog.LastGeometry)

        self.finished.connect(self._onFinishedSaveGeometry)

        optionsMenu = self._makeOptionsMenu()
        self.ui.optionsButton.setMenu(optionsMenu)

        # Undo/redo keyboard shortcuts
        undoKS = QKeySequence(QKeySequence.StandardKey.Undo)
        redoKS = QKeySequence(QKeySequence.StandardKey.Redo)
        makeWidgetShortcut(self, self.undoStack.undo, undoKS, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        makeWidgetShortcut(self, self.undoStack.redo, redoKS, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

        undoText = undoKS.toString(QKeySequence.SequenceFormat.NativeText)
        redoText = redoKS.toString(QKeySequence.SequenceFormat.NativeText)
        directionText = _("bottom to top") if settings.prefs.rebaseBottomUp else _("top to bottom")
        self.ui.toolButton.setToolTip(paragraphs(
            _("Drag and drop lines to rearrange them. They will be executed {direction}.",
              direction=directionText),
            _("Right-click lines to change their operation. You can also select some lines then "
              "press the first letter of an operation (e.g. press {0} for {1}).",
              tquo("D"), tquo("drop")),
            _("You can undo/redo with {undo} and {redo}.", undo=undoText, redo=redoText),
        ))

        self.warningHint = QHintButton(self, iconKey="achtung")
        self.ui.buttonBox.addButton(self.warningHint, QDialogButtonBox.ButtonRole.ActionRole)
        self.warningHint.setVisible(False)

        # macOS: Adding warningHint to the buttonBox inexplicably moves focus to
        # the Cancel button, so focus the sequence instead.
        self.ui.sequence.setFocus()

    def rebaseExtraArgs(self) -> list[str]:
        args = []
        if self.rebaseDateArg:
            args.append(self.rebaseDateArg)
        return args

    def _onFinishedSaveGeometry(self):
        RebaseDialog.LastGeometry = self.saveGeometry().data()

    def reject(self):
        if not self.isWindowModified():
            super().reject()
            return

        def qmbFinished(result: int):
            if result == QMessageBox.StandardButton.Discard:
                self.setWindowModified(False)
                self.reject()

        qmb = asyncMessageBox(
            self,
            "question",
            _p("RebaseDialog", "Rebase"),
            _("Really discard this rebase plan? It won’t be saved."),
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        qmb.finished.connect(qmbFinished)
        qmb.show()

    def setCommandOnSelection(self, command: RebaseOp):
        assert command in SupportedRebaseOps, f"rebase op '{command}' not supported yet"

        indexes = self.ui.sequence.selectedIndexes()

        if not indexes:
            QApplication.beep()
            return

        for index in indexes:
            line = index.data(RebaseSequenceModel.RebaseLineRole)
            line.op = command

        self.sequenceModel.emitUserDataChanged(indexes)
        self.ui.sequence.viewport().update()

        # Spawn QLineEdit immediately if rewording
        if command.isEditable():
            self.ui.sequence.edit(indexes[0])

    def onContextMenuRequested(self, point: QPoint):
        menu = self.makeContextMenu()
        if menu is not None:
            menu.aboutToHide.connect(menu.deleteLater)
            menu.popup(self.mapToGlobal(point))

    def makeContextMenu(self):
        selectedLines = self.ui.sequence.selectedRebaseLines()
        selectedOps = {item.op for item in selectedLines}
        if not selectedOps:
            return None

        menu = QRichTextMenu(self)
        actionGroup = QActionGroup(menu)
        actionGroup.setExclusionPolicy(QActionGroup.ExclusionPolicy.Exclusive)

        for op in RebaseOp:
            if op not in SupportedRebaseOps:
                continue

            opColor = RebaseOpColors[op]
            opName = op.capitalize()
            opAccel = RebaseOpLetters.get(op, "")
            opHelp = trtables.enum(op)

            richLabel = f"<span style='color: {opColor.name()}; font-weight: bold;'>{opName}{_(':')}</span> {opHelp}"

            action = menu.addRichTextAction(richLabel, opAccel)
            action.setCheckable(True)
            action.setChecked(op in selectedOps)
            action.setActionGroup(actionGroup)
            action.triggered.connect(lambda _checked, c=op: self.setCommandOnSelection(c))
            menu.addAction(action)

        return menu

    def serializeSequence(self):
        text = "\n".join(str(i) for i in self.ui.sequence.effectiveSequence())
        return text

    # --------------------------------------------------------------------------
    # Options menu
    # --------------------------------------------------------------------------

    def _makeOptionsMenu(self):
        menu = QRichTextMenu(self)
        dateGroup = QActionGroup(menu)
        mutedColor = mutedTextColorHex(menu)

        for label, switch in [
            (_("Separate author/committer dates"), ""),
            (_("Set committer date to author date"), "--committer-date-is-author-date"),
            (_("Set author date to current time"), "--reset-author-date"),
        ]:
            markup = f"{label} <span style='font-size: small; white-space: pre; color: {mutedColor};'>    {switch}</span>"

            action = menu.addRichTextAction(markup)
            action.setCheckable(True)
            action.setChecked(switch == self.rebaseDateArg)
            action.toggled.connect(lambda checked, sw=switch: self._onToggleDateSwitch(checked, sw))
            action.setActionGroup(dateGroup)

        return menu

    def _onToggleDateSwitch(self, toggled: bool, switch: str):
        if toggled:
            self.rebaseDateArg = switch
            settings.prefs.rebaseDateArg = switch
            settings.prefs.setDirty()
        else:
            self.rebaseDateArg = ""

    # --------------------------------------------------------------------------
    # Sequence edit callbacks
    # --------------------------------------------------------------------------

    def _onSequenceEdited(self, pushUndo: bool = True):
        # Check that user hasn't introduced a dangling operation
        self.sequenceModel.refreshDanglingHash()
        dangling = self.sequenceModel.danglingHash

        self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not dangling)
        self.warningHint.setVisible(bool(dangling))

        if dangling:
            warning = _("Please review commit {0} before proceeding.", tquo(shortHash(dangling)))
            self.warningHint.setToolTip(warning)

        if not pushUndo:
            return

        # Have reject() show a confirmation dialog before closing.
        # On macOS, this also adds a dot to the window's close button.
        self.setWindowModified(True)

        # Figure out what sequence "undo" should restore
        undoIndex = self.undoStack.index()
        if undoIndex == 0:
            # This is the first command ever: "undo" returns to initial sequence
            undo = self.initialSequence
        else:
            # "Undo" returns to current state in undo stack
            topCommand = self.undoStack.command(undoIndex - 1)
            assert isinstance(topCommand, RebaseUndoCommand), repr(topCommand)
            undo = topCommand.redoSequence

        # "Redo" always restores current sequence
        redo = self.sequenceModel.sequence

        # Don't push no-op commands
        if undo != redo:
            undoCommand = RebaseUndoCommand(undo, redo, self.sequenceModel)
            self.undoStack.push(undoCommand)
