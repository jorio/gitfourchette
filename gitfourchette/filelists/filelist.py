# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os
from collections.abc import Callable, Generator
from contextlib import suppress

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.exttools.toolprocess import ToolProcess
from gitfourchette.exttools.usercommand import UserCommand
from gitfourchette.filelists.filelistmodel import FileListModel
from gitfourchette.forms.searchbar import SearchBar
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator, NavContext, NavFlags
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks import *
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables


class SelectedFileBatchError(Exception):
    pass


class FileListDelegate(QStyledItemDelegate):
    """
    Item delegate for QListView that supports highlighting search terms from a SearchBar
    """

    def searchTerm(self, option: QStyleOptionViewItem):
        assert isinstance(option.widget, FileList)
        searchBar: SearchBar = option.widget.searchBar
        return searchBar.searchTerm if searchBar.isVisible() else ""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        hasFocus = option.state & QStyle.StateFlag.State_HasFocus
        isSelected = option.state & QStyle.StateFlag.State_Selected
        style = option.widget.style()
        colorGroup = QPalette.ColorGroup.Normal if hasFocus else QPalette.ColorGroup.Inactive
        searchTerm = self.searchTerm(option)

        painter.save()

        # Prepare icon and text rects
        icon: QIcon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is not None and not icon.isNull():
            iconRect = QRect(option.rect.topLeft() + QPoint(2, 0), option.decorationSize)
        else:
            iconRect = QRect()

        textRect = QRect(option.rect)
        textRect.setLeft(iconRect.right() + 4)
        textRect.setRight(textRect.right() - 2)

        # Set highlighted text color if this item is selected
        if isSelected:
            painter.setPen(option.palette.color(colorGroup, QPalette.ColorRole.HighlightedText))

        # Draw default background
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget)

        # Draw icon
        if not iconRect.isEmpty():
            icon.paint(painter, iconRect, option.decorationAlignment)

        # Draw text
        font: QFont = index.data(Qt.ItemDataRole.FontRole)
        if font:
            painter.setFont(font)
        fullText = index.data(Qt.ItemDataRole.DisplayRole)
        text = painter.fontMetrics().elidedText(fullText, option.textElideMode, textRect.width())
        painter.drawText(textRect, option.displayAlignment, text)

        # Highlight search term
        if searchTerm and searchTerm in fullText.lower():
            needlePos = text.lower().find(searchTerm)
            if needlePos < 0:
                needlePos = text.find("\u2026")  # unicode ellipsis character (...)
                needleLen = 1
            else:
                needleLen = len(searchTerm)

            SearchBar.highlightNeedle(painter, textRect, text, needlePos, needleLen)

        painter.restore()


class FileList(QListView):
    nothingClicked = Signal()
    selectedCountChanged = Signal(int)
    openDiffInNewWindow = Signal(Patch, NavLocator)
    openSubRepo = Signal(str)
    statusMessage = Signal(str)

    repo: Repo

    navContext: NavContext
    """
    COMMITTED, STAGED or DIRTY.
    Does not change throughout the lifespan of this FileList.
    """

    commitId: Oid
    """
    The commit that is currently being shown.
    Only valid if navContext == COMMITTED.
    """

    skippedRenameDetection: bool
    """
    In large diffs, we skip rename detection.
    """

    _selectionBackup: list[str]
    """
    Backup of selected paths before refreshing the view.
    """

    def __init__(self, parent: QWidget, navContext: NavContext):
        super().__init__(parent)

        self.repo = None

        flModel = FileListModel(self, navContext)
        self.setModel(flModel)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        self.navContext = navContext
        self.commitId = NULL_OID
        self.skippedRenameDetection = False
        self._selectionBackup = []

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        iconSize = self.fontMetrics().height()
        self.setIconSize(QSize(iconSize, iconSize))
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # prevent editing text after double-clicking
        self.setUniformItemSizes(True)  # potential perf boost with many files

        searchBarPlaceholder = toLengthVariants(_("Find a file by path|Find file"))
        self.searchBar = SearchBar(self, searchBarPlaceholder)
        self.searchBar.setUpItemViewBuddy()
        self.searchBar.ui.forwardButton.hide()
        self.searchBar.ui.backwardButton.hide()
        self.searchBar.hide()
        flModel.modelAboutToBeReset.connect(self.searchBar.invalidateBadStem)

        # Search result highlighter
        self.setItemDelegate(FileListDelegate(self))

        self.refreshPrefs()

        makeWidgetShortcut(self, self.searchBar.hideOrBeep, "Escape")
        makeWidgetShortcut(self, self.copyPaths, QKeySequence.StandardKey.Copy)

    def refreshPrefs(self):
        self.setVerticalScrollMode(settings.prefs.listViewScrollMode)

    @property
    def flModel(self) -> FileListModel:
        model = self.model()
        assert isinstance(model, FileListModel)
        return model

    def isEmpty(self):
        return self.model().rowCount() == 0

    def setContents(self, diffs: list[Diff], skippedRenameDetection: bool):
        self.flModel.setDiffs(diffs)
        self.skippedRenameDetection = skippedRenameDetection
        self.updateFocusPolicy()

    def clear(self):
        self.flModel.clear()
        self.commitId = NULL_OID
        self.skippedRenameDetection = False
        assert self.isEmpty()
        self.updateFocusPolicy()

    def updateFocusPolicy(self):
        focusPolicy = Qt.FocusPolicy.StrongFocus if not self.isEmpty() else Qt.FocusPolicy.ClickFocus
        self.setFocusPolicy(focusPolicy)

    # -------------------------------------------------------------------------
    # Context menu

    def makeContextMenu(self):
        patches = list(self.selectedPatches())
        if len(patches) == 0:
            return None

        actions = self.contextMenuActions(patches)
        menu = ActionDef.makeQMenu(self, actions)
        menu.setObjectName("FileListContextMenu")
        return menu

    def contextMenuEvent(self, event: QContextMenuEvent):
        try:
            menu = self.makeContextMenu()
        except Exception as exc:
            # Avoid exceptions in contextMenuEvent at all costs to prevent a crash
            # (endless loop of "This exception was delayed").
            excMessageBox(exc, message="Failed to create FileList context menu")
            return

        if not menu:
            return

        menu.exec(event.globalPos())

        # Can't set WA_DeleteOnClose because this crashes on macOS e.g. when exporting a patch.
        # (Context menu gets deleted while callback is running)
        # Qt docs say: "for the object to be deleted, the control must return to the event loop from which deleteLater()
        # was called" -- I suppose this means the context menu won't be deleted until the FileList has control again.
        menu.deleteLater()

    def contextMenuActions(self, patches: list[Patch]) -> list[ActionDef]:
        """ To be overridden """

        def pathDisplayStyleAction(pds: PathDisplayStyle):
            def setIt():
                settings.prefs.pathDisplayStyle = pds
                settings.prefs.setDirty()
            isCurrent = settings.prefs.pathDisplayStyle == pds
            name = englishTitleCase(TrTables.enum(pds))
            return ActionDef(name, setIt, checkState=isCurrent)

        n = len(patches)

        actions = [
            ActionDef.SEPARATOR,

            ActionDef(
                _n("Open &Folder", "Open {n} &Folders", n),
                self.showInFolder,
                "SP_DirIcon",
            ),

            ActionDef(
                _n("&Copy Path", "&Copy {n} Paths", n),
                self.copyPaths,
                shortcuts=QKeySequence.StandardKey.Copy,
            ),

            ActionDef(
                englishTitleCase(_("Path display style")),
                submenu=[pathDisplayStyleAction(style) for style in PathDisplayStyle],
            ),
        ]

        actions.extend(GFApplication.instance().mainWindow.contextualUserCommands(
            UserCommand.Token.File,
            UserCommand.Token.FileDir,
            UserCommand.Token.FileAbs,
            UserCommand.Token.FileDirAbs,
        ))

        return actions

    def contextMenuActionStash(self):
        return ActionDef(
            _("Stas&h Changes…"),
            self.wantPartialStash,
            icon="git-stash-black",
            shortcuts=TaskBook.shortcuts.get(NewStash, []))

    def contextMenuActionRevertMode(self, patches, callback: Callable):
        n = len(patches)
        action = ActionDef(_n("Revert Mode Changes…", "Revert Mode Change…", n), callback, enabled=False)

        for patch in patches:
            if not patch:  # stale diff
                break
            om = patch.delta.old_file.mode
            nm = patch.delta.new_file.mode
            if (patch.delta.status in [DeltaStatus.MODIFIED, DeltaStatus.RENAMED]
                    and om != nm
                    and nm in [FileMode.BLOB, FileMode.BLOB_EXECUTABLE]):
                action.enabled = True
                if n == 1:
                    if nm == FileMode.BLOB_EXECUTABLE:
                        action.caption = _("Revert Mode to Non-Executable…")
                    elif nm == FileMode.BLOB:
                        action.caption = _("Revert Mode to Executable…")

        return action

    def contextMenuActionsDiff(self, patches):
        n = len(patches)

        return [
            ActionDef(
                _("Open Diff in {0}", settings.getDiffToolName()),
                self.wantOpenInDiffTool,
                icon="vcs-diff"),

            ActionDef(
                _n("E&xport Diff As Patch…", "E&xport Diffs As Patch…", n),
                self.savePatchAs),
        ]

    def contextMenuActionsEdit(self, patches):
        n = len(patches)

        return [
            ActionDef(
                _("&Edit in {tool}", tool=settings.getExternalEditorName()),
                self.openWorkdirFile,
                icon="SP_FileIcon"),

            ActionDef(
                _n("Edit &HEAD Version in {tool}", "Edit &HEAD Versions in {tool}", n=n, tool=settings.getExternalEditorName()),
                self.openHeadRevision),
        ]

    # -------------------------------------------------------------------------

    def confirmBatch(self, callback: Callable[[Patch], None], title: str, prompt: str, threshold: int = 3):
        patches = list(self.selectedPatches())

        def runBatch():
            errors = []

            for patch in patches:
                try:
                    callback(patch)
                except SelectedFileBatchError as exc:
                    errors.append(str(exc))

            if errors:
                showWarning(self, title, "<br>".join(errors))

        if len(patches) <= threshold:
            runBatch()
        else:
            numFiles = len(patches)

            qmb = askConfirmation(
                self,
                title,
                prompt.format(n=numFiles),
                runBatch,
                QMessageBox.StandardButton.YesAll | QMessageBox.StandardButton.Cancel,
                show=False)

            addULToMessageBox(qmb, [p.delta.new_file.path for p in patches])

            qmb.button(QMessageBox.StandardButton.YesAll).clicked.connect(runBatch)
            qmb.show()

    def openWorkdirFile(self):
        def run(patch: Patch):
            entryPath = self.repo.in_workdir(patch.delta.new_file.path)
            ToolProcess.startTextEditor(self, entryPath)

        self.confirmBatch(run, _("Open in external editor"),
                          _("Really open <b>{n} files</b> in external editor?"))

    def wantOpenInDiffTool(self):
        self.confirmBatch(self._openInDiffTool, _("Open in external diff tool"),
                          _("Really open <b>{n} files</b> in external diff tool?"))

    def _openInDiffTool(self, patch: Patch):
        if patch.delta.new_file.id == NULL_OID:
            raise SelectedFileBatchError(
                _("{0}: Can’t open external diff tool on a deleted file.", patch.delta.new_file.path))

        if patch.delta.old_file.id == NULL_OID:
            raise SelectedFileBatchError(
                _("{0}: Can’t open external diff tool on a new file.", patch.delta.new_file.path))

        oldDiffFile = patch.delta.old_file
        newDiffFile = patch.delta.new_file

        diffDir = qTempDir()

        if self.navContext == NavContext.UNSTAGED:
            # Unstaged: compare indexed state to workdir file
            oldPath = dumpTempBlob(self.repo, diffDir, oldDiffFile, "INDEXED")
            newPath = self.repo.in_workdir(newDiffFile.path)
        elif self.navContext == NavContext.STAGED:
            # Staged: compare HEAD state to indexed state
            oldPath = dumpTempBlob(self.repo, diffDir, oldDiffFile, "HEAD")
            newPath = dumpTempBlob(self.repo, diffDir, newDiffFile, "STAGED")
        else:
            # Committed: compare parent state to this commit
            oldPath = dumpTempBlob(self.repo, diffDir, oldDiffFile, "OLD")
            newPath = dumpTempBlob(self.repo, diffDir, newDiffFile, "NEW")

        return ToolProcess.startDiffTool(self, oldPath, newPath)

    def showInFolder(self):
        def run(entry: Patch):
            path = self.repo.in_workdir(entry.delta.new_file.path)
            path = os.path.normpath(path)  # get rid of any trailing slashes (submodules)
            if not os.path.exists(path):  # check exists, not isfile, for submodules
                raise SelectedFileBatchError(_("{0}: This file doesn’t exist at this path anymore.", entry.delta.new_file.path))
            showInFolder(path)

        self.confirmBatch(run, _("Open paths"),
                          _("Really open <b>{n} folders</b>?"))

    def copyPaths(self):
        text = '\n'.join(self.repo.in_workdir(path) for path in self.selectedPaths())
        if not text:
            return

        if WINDOWS:  # Ensure backslash directory separators
            from pathlib import Path
            path = Path(text)
            text = str(path)

        QApplication.clipboard().setText(text)
        self.statusMessage.emit(clipboardStatusMessage(text))

    def selectRow(self, rowNumber=0):
        if self.model().rowCount() == 0:
            self.nothingClicked.emit()
            self.clearSelection()
        else:
            self.setCurrentIndex(self.model().index(rowNumber or 0, 0))

    def selectionChanged(self, justSelected: QItemSelection, justDeselected: QItemSelection):
        super().selectionChanged(justSelected, justDeselected)

        # We're the active FileList, clear counterpart.
        self._setCounterpart(-1)

        # Don't bother emitting signals if we're blocked
        if self.signalsBlocked():
            return

        selectedIndexes = self.selectedIndexes()
        numSelectedTotal = len(selectedIndexes)

        justSelectedIndexes = list(justSelected.indexes())
        if justSelectedIndexes:
            current = justSelectedIndexes[0]
        else:
            # Deselecting (e.g. with shift/ctrl) doesn't necessarily mean that the selection has been emptied.
            # Find an index that is still selected to keep the DiffView in sync with the selection.
            current = self.currentIndex()

            if current.isValid() and selectedIndexes:
                # currentIndex may be outside the selection, find the selected index that is closest to currentIndex.
                current = min(selectedIndexes, key=lambda index: abs(index.row() - current.row()))
            else:
                current = None

        self.selectedCountChanged.emit(numSelectedTotal)

        if current and current.isValid():
            locator = self.getNavLocatorForIndex(current)
            locator = locator.withExtraFlags(NavFlags.AllowMultiSelect)
            Jump.invoke(self, locator)
        else:
            self.nothingClicked.emit()

    def highlightCounterpart(self, loc: NavLocator):
        try:
            row = self.flModel.getRowForFile(loc.path)
        except KeyError:
            row = -1
        self._setCounterpart(row)

    def _setCounterpart(self, newRow: int):
        model = self.flModel
        oldRow = model.highlightedCounterpartRow

        if oldRow == newRow:
            return

        model.highlightedCounterpartRow = newRow

        if oldRow >= 0:
            oldIndex = model.index(oldRow, 0)
            self.update(oldIndex)

        if newRow >= 0:
            newIndex = model.index(newRow, 0)
            self.selectionModel().setCurrentIndex(newIndex, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.update(newIndex)

    def getNavLocatorForIndex(self, index: QModelIndex):
        filePath = index.data(FileListModel.Role.FilePath)
        return NavLocator(self.navContext, self.commitId, filePath)

    def mouseMoveEvent(self, event: QMouseEvent):
        """
        By default, ExtendedSelection lets the user select multiple items by
        holding down LMB and dragging. This event handler enforces single-item
        selection unless the user holds down Shift or Ctrl.
        """
        isLMB = bool(event.buttons() & Qt.MouseButton.LeftButton)
        isShift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        isCtrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)

        if isLMB and not isShift and not isCtrl:
            self.mousePressEvent(event)  # re-route event as if it were a click event
            self.scrollTo(self.indexAt(event.pos()))  # mousePressEvent won't scroll to the item on its own
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        super().mouseReleaseEvent(event)  # Let standard QListView selection occur first
        if event.button() == Qt.MouseButton.MiddleButton:
            self.onSpecialMouseClick()

    def onSpecialMouseClick(self):
        """ Override this if you want to react to a middle click. """
        pass

    def selectedPatches(self) -> Generator[Patch, None, None]:
        index: QModelIndex
        for index in self.selectedIndexes():
            patch: Patch = index.data(FileListModel.Role.PatchObject)
            if not patch or not patch.delta:
                raise ValueError(_("This file appears to have been modified by another application. Try refreshing the window."))
            assert isinstance(patch, Patch)
            yield patch

    def selectedPaths(self) -> Generator[str, None, None]:
        index: QModelIndex
        for index in self.selectedIndexes():
            path: str = index.data(FileListModel.Role.FilePath)
            if not path:
                continue
            yield path

    def earliestSelectedRow(self):
        try:
            return list(self.selectedIndexes())[0].row()
        except IndexError:
            return -1

    def latestSelectedRow(self):
        try:
            return list(self.selectedIndexes())[-1].row()
        except IndexError:
            return -1

    def savePatchAs(self):
        patches = list(self.selectedPatches())
        ExportPatchCollection.invoke(self, patches)

    def revertPaths(self):
        patches = list(self.selectedPatches())
        assert len(patches) == 1
        ApplyPatchData.invoke(self, patches[0].text, reverse=True)

    def firstPath(self) -> str:
        index: QModelIndex = self.flModel.index(0)
        if index.isValid():
            return index.data(FileListModel.Role.FilePath)
        else:
            return ""

    def paths(self) -> Generator[str, None, None]:
        flModel = self.flModel
        for row in range(flModel.rowCount()):
            index = flModel.index(row)
            yield index.data(FileListModel.Role.FilePath)

    def selectFile(self, file: str) -> bool:
        if not file:
            return False

        try:
            row = self.flModel.getRowForFile(file)
        except KeyError:
            return False

        if self.selectionModel().isRowSelected(row):
            # Re-selecting an already selected row may deselect it??
            return True

        self.selectRow(row)
        return True

    def getPatchForFile(self, file: str):
        try:
            row = self.flModel.getRowForFile(file)
            return self.flModel.entries[row].patch
        except KeyError:
            return None

    def openHeadRevision(self):
        def run(patch: Patch):
            tempPath = dumpTempBlob(self.repo, qTempDir(), patch.delta.old_file, "HEAD")
            ToolProcess.startTextEditor(self, tempPath)

        self.confirmBatch(run, _("Open HEAD version of file"),
                          _("Really open <b>{n} files</b> in external editor?"))

    def wantPartialStash(self):
        paths = set()
        for patch in self.selectedPatches():
            # Add both old and new paths so that both are pre-selected
            # if we're stashing a rename.
            paths.add(patch.delta.old_file.path)
            paths.add(patch.delta.new_file.path)
        NewStash.invoke(self, list(paths))

    def openSubmoduleTabs(self):
        patches = [p for p in self.selectedPatches() if p.delta.new_file.mode in [FileMode.COMMIT]]
        for patch in patches:
            self.openSubRepo.emit(patch.delta.new_file.path)

    def searchRange(self, searchRange: range) -> QModelIndex | None:
        model = self.model()  # to filter out hidden rows, don't use self.clModel directly

        term = self.searchBar.searchTerm
        assert term
        assert term == term.lower(), "search term should have been sanitized"

        for i in searchRange:
            index = model.index(i, 0)
            path = model.data(index, FileListModel.Role.FilePath)
            if path and term in path.lower():
                return index

        return None

    def backUpSelection(self):
        oldSelected = list(self.selectedPaths())
        self._selectionBackup = oldSelected

    def clearSelectionBackup(self):
        self._selectionBackup = []

    def restoreSelectionBackup(self):
        if not self._selectionBackup:
            return False

        paths = self._selectionBackup
        self._selectionBackup = []

        currentIndex: QModelIndex = self.currentIndex()
        cPath = currentIndex.data(FileListModel.Role.FilePath)

        if cPath not in paths:
            # Don't attempt to restore if we've jumped to another file
            return False

        if len(paths) == 1 and paths[0] == cPath:
            # Don't bother if the one file that we've selected is still the current one
            return False

        flModel = self.flModel
        selectionModel = self.selectionModel()
        SF = QItemSelectionModel.SelectionFlag

        with QSignalBlockerContext(self):
            # If we directly manipulate the QItemSelectionModel by calling .select() row-by-row,
            # then shift-selection may act counter-intuitively if the selection was discontiguous.
            # Preparing a QItemSelection upfront mitigates the strange shift-select behavior.
            newItemSelection = QItemSelection()
            for path in paths:
                with suppress(KeyError):
                    row = flModel.fileRows[path]
                    index = flModel.index(row, 0)
                    newItemSelection.select(index, index)
            selectionModel.clearSelection()
            selectionModel.select(newItemSelection, SF.Rows | SF.Select)
            selectionModel.setCurrentIndex(currentIndex, SF.Rows | SF.Current)

        return True
