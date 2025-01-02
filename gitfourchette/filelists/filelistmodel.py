# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import os
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from gitfourchette import settings
from gitfourchette.localization import *
from gitfourchette.nav import NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables

logger = logging.getLogger(__name__)


def deltaModeText(delta: DiffDelta):
    if not delta:
        return "NO DELTA"

    om = delta.old_file.mode
    nm = delta.new_file.mode

    if om != 0 and nm != 0 and om != nm:
        # Mode change
        if nm == FileMode.BLOB_EXECUTABLE:
            return "+x"
        elif om == FileMode.BLOB_EXECUTABLE:
            return "-x"
        elif nm != FileMode.BLOB:
            return TrTables.shortFileModes(nm)
        else:
            return ""
    elif om == 0:
        # New file
        return TrTables.shortFileModes(nm)


def fileTooltip(repo: Repo, delta: DiffDelta, navContext: NavContext, isCounterpart: bool = False):
    if not delta:
        return ""

    locale = QLocale()
    of: DiffFile = delta.old_file
    nf: DiffFile = delta.new_file

    sc = delta.status_char()
    if delta.status == DeltaStatus.CONFLICTED:  # libgit2 should arguably return "U" (unmerged) for conflicts, but it doesn't
        sc = "U"

    text = "<table style='white-space: pre'>"

    def newLine(heading, caption):
        colon = _(':')
        color = mutedToolTipColorHex()
        return f"<tr><td style='color:{color}; text-align: right;'>{heading}{colon} </td><td>{caption}</td>"

    if sc == 'R':
        text += newLine(_("old name"), escape(of.path))
        text += newLine(_("new name"), escape(nf.path))
    else:
        text += newLine(_("name"), escape(nf.path))

    # Status caption
    statusCaption = TrTables.diffStatusChar(sc)
    if sc not in '?U':  # show status char except for untracked and conflict
        statusCaption += f" ({sc})"
    if sc == 'U':  # conflict sides
        diffConflict = repo.wrap_conflict(nf.path)
        postfix = TrTables.enum(diffConflict.sides)
        statusCaption += f" ({postfix})"
    text += newLine(_("status"), statusCaption)

    # Similarity + Old name
    if sc == 'R':
        text += newLine(_("similarity"), f"{delta.similarity}%")

    # File Mode
    if sc not in 'DU':
        legend = _("file mode")
        if sc in 'A?':
            text += newLine(legend, TrTables.enum(nf.mode))
        elif of.mode != nf.mode:
            text += newLine(legend, f"{TrTables.enum(of.mode)} &rarr; {TrTables.enum(nf.mode)}")

    # Size (if available)
    if sc not in 'DU' and nf.size != 0 and (nf.mode & FileMode.BLOB == FileMode.BLOB):
        text += newLine(_("size"), locale.formattedDataSize(nf.size, 1))

    # Modified time
    if navContext.isWorkdir() and sc not in 'DU':
        with suppress(OSError):
            fullPath = os.path.join(repo.workdir, nf.path)
            fileStat = os.stat(fullPath)
            timeQdt = QDateTime.fromSecsSinceEpoch(int(fileStat.st_mtime))
            timeText = locale.toString(timeQdt, settings.prefs.shortTimeFormat)
            text += newLine(_("modified"), timeText)

    # Blob IDs (DEVDEBUG only)
    if settings.DEVDEBUG:
        nChars = settings.prefs.shortHashChars
        oldBlobId = shortHash(of.id) if of.flags & DiffFlag.VALID_ID else "?" * nChars
        newBlobId = shortHash(nf.id) if nf.flags & DiffFlag.VALID_ID else "?" * nChars
        text += newLine(_("blob id"), f"{oldBlobId} &rarr; {newBlobId}")

    if isCounterpart:
        if navContext == NavContext.UNSTAGED:
            counterpartText = _("Currently viewing diff of staged changes in this file; "
                                "it also has <u>unstaged</u> changes.")
        else:
            counterpartText = _("Currently viewing diff of unstaged changes in this file; "
                                "it also has <u>staged</u> changes.")
        text += f"<p>{counterpartText}</p>"

    return text


class FileListModel(QAbstractListModel):
    @dataclass
    class Entry:
        delta: DiffDelta
        diff: Diff
        patchNo: int
        canonicalPath: str

        @property
        def patch(self) -> Patch | None:
            try:
                patch: Patch = self.diff[self.patchNo]
                return patch
            except (GitError, OSError) as e:
                # GitError may occur if patch data is outdated.
                # OSError may rarely occur if the file happens to be recreated.
                logger.warning(f"Failed to get patch: {type(e).__name__}", exc_info=True)
                return None

    class Role:
        PatchObject = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 0)
        FilePath = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 1)

    entries: list[Entry]
    fileRows: dict[str, int]
    highlightedCounterpartRow: int
    navContext: NavContext

    def __init__(self, parent: QWidget, navContext: NavContext):
        super().__init__(parent)
        self.navContext = navContext
        self.clear()

    @property
    def skipConflicts(self) -> bool:
        # Hide conflicts from staged file list
        return self.navContext == NavContext.STAGED

    @property
    def repo(self) -> Repo:
        return self.parent().repo

    @property
    def parentWidget(self) -> QWidget:
        parentWidget = self.parent()
        assert isinstance(parentWidget, QWidget)
        return parentWidget

    def clear(self):
        self.entries = []
        self.fileRows = {}
        self.highlightedCounterpartRow = -1
        self.modelReset.emit()

    def setDiffs(self, diffs: list[Diff]):
        self.beginResetModel()

        self.entries.clear()
        self.fileRows.clear()

        for diff in diffs:
            for patchNo, delta in enumerate(diff.deltas):
                if self.skipConflicts and delta.status == DeltaStatus.CONFLICTED:
                    continue
                path = delta.new_file.path
                path = path.removesuffix("/")  # trees (submodules) have a trailing slash - remove for NavLocator consistency
                self.fileRows[path] = len(self.entries)
                self.entries.append(FileListModel.Entry(delta, diff, patchNo, path))

        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex_default) -> int:
        return len(self.entries)

    def data(self, index: QModelIndex, role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == FileListModel.Role.PatchObject:
            entry = self.entries[index.row()]
            return entry.patch

        elif role == FileListModel.Role.FilePath:
            entry = self.entries[index.row()]
            return entry.canonicalPath

        elif role == Qt.ItemDataRole.DisplayRole:
            entry = self.entries[index.row()]
            text = abbreviatePath(entry.canonicalPath, settings.prefs.pathDisplayStyle)

            # Show important mode info in brackets
            modeInfo = deltaModeText(entry.delta)
            if modeInfo:
                text = f"[{modeInfo}] {text}"

            return text

        elif role == Qt.ItemDataRole.DecorationRole:
            entry = self.entries[index.row()]
            delta = entry.delta
            if not delta:
                iconName = "status_x"
            elif delta.status == DeltaStatus.UNTRACKED:
                iconName = "status_a"
            elif delta.status == DeltaStatus.CONFLICTED:
                iconName = "status_u"
            else:
                iconName = "status_" + delta.status_char().lower()
            return stockIcon(iconName)

        elif role == Qt.ItemDataRole.ToolTipRole:
            entry = self.entries[index.row()]
            delta = entry.delta
            isCounterpart = index.row() == self.highlightedCounterpartRow
            return fileTooltip(self.repo, delta, self.navContext, isCounterpart)

        elif role == Qt.ItemDataRole.SizeHintRole:
            return QSize(-1, self.parentWidget.fontMetrics().height())

        elif role == Qt.ItemDataRole.FontRole:
            if index.row() == self.highlightedCounterpartRow:
                font = self.parentWidget.font()
                font.setUnderline(True)
                return font

        return None

    def getRowForFile(self, path: str) -> int:
        """
        Get the row number for the given path.
        Raise KeyError if the path is absent from this model.
        """
        return self.fileRows[path]

    def getFileAtRow(self, row: int) -> str:
        """
        Get the path corresponding to the given row number.
        Return an empty string if the row number is invalid.
        """
        if row < 0 or row >= self.rowCount():
            return ""
        return self.data(self.index(row), FileListModel.Role.FilePath)

    def hasFile(self, path: str) -> bool:
        """
        Return True if the given path is present in this model.
        """
        return path in self.fileRows
