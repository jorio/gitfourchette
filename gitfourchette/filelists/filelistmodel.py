# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import os
from collections.abc import Iterable
from contextlib import suppress
from typing import Any

from gitfourchette import settings
from gitfourchette.gitdriver import VanillaDelta
from gitfourchette.localization import *
from gitfourchette.nav import NavContext
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables

logger = logging.getLogger(__name__)

STATUS_ICON_LETTERS = "xadmrxxatxu"
"""
Table of status_*.svg icons for each enum entry
in pygit2.enums.DeltaStatus.
"""


def deltaModeText(om: FileMode, nm: FileMode) -> str:
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
    return ""


def fileTooltip(repo: Repo, delta: VanillaDelta, navContext: NavContext, isCounterpart: bool = False):
    if not delta:
        return ""

    locale = QLocale()
    sc = delta.statusPerContext(navContext)

    text = "<table style='white-space: pre'>"

    def newLine(heading, caption):
        colon = _(':')
        color = mutedToolTipColorHex()
        return f"<tr><td style='color:{color}; text-align: right;'>{heading}{colon} </td><td>{caption}</td>"

    if sc == 'R':
        text += newLine(_("old name"), escape(delta.origPath))
        text += newLine(_("new name"), escape(delta.path))
    else:
        text += newLine(_("name"), escape(delta.path))

    # Status caption
    statusCaption = TrTables.diffStatusChar(sc)
    if sc not in '?U':  # show status char except for untracked and conflict
        statusCaption += f" ({sc})"
    if sc == 'U':  # conflict sides
        raise NotImplementedError("wrap conflict sides????")
        diffConflict = repo.wrap_conflict(delta.path)
        postfix = TrTables.enum(diffConflict.sides)
        statusCaption += f" ({postfix})"
    text += newLine(_("status"), statusCaption)

    # Similarity + Old name
    if sc == 'R':
        text += newLine(_("similarity"), f"{delta.similarity}%")

    # File Mode
    # TODO
    if sc not in 'DU':
        om, nm = delta.modesPerContext(navContext)
        om, nm = FileMode(om), FileMode(nm)
        if sc in 'A?':
            text += newLine(_("file mode"), TrTables.enum(nm))
        elif om != nm:
            text += newLine(_("file mode"), f"{TrTables.enum(om)} \u2192 {TrTables.enum(nm)}")

    # Size (if applicable)
    # TODO
    """
    if sc not in 'DU' and (nf.mode & FileMode.BLOB == FileMode.BLOB):
        if nf.flags & DiffFlag.VALID_SIZE:
            text += newLine(_("size"), locale.formattedDataSize(nf.size, 1))
        else:
            text += newLine(_("size"), _("(not computed)"))
    """

    # Modified time
    if navContext.isWorkdir() and sc not in 'DU':
        with suppress(OSError):
            fullPath = os.path.join(repo.workdir, delta.path)
            fileStat = os.stat(fullPath)
            timeQdt = QDateTime.fromSecsSinceEpoch(int(fileStat.st_mtime))
            timeText = locale.toString(timeQdt, settings.prefs.shortTimeFormat)
            text += newLine(_("modified"), timeText)

    # Blob/Commit IDs
    # TODO
    """
    if nf.mode != FileMode.TREE:  # untracked trees never have a valid ID
        oldId = shortHash(of.id) if of.flags & DiffFlag.VALID_ID else _("(not computed)")
        newId = shortHash(nf.id) if nf.flags & DiffFlag.VALID_ID else _("(not computed)")
        idLegend = _("commit hash") if nf.mode == FileMode.COMMIT else _("blob hash")
        text += newLine(idLegend, f"{oldId} \u2192 {newId}")
    """

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
    class Role:
        DeltaObject = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 0)
        FilePath = Qt.ItemDataRole(Qt.ItemDataRole.UserRole + 1)

    deltas: list[VanillaDelta]
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
        self.deltas = []
        self.fileRows = {}
        self.highlightedCounterpartRow = -1
        self.modelReset.emit()

    def setContents(self, deltas: Iterable[VanillaDelta]):
        self.beginResetModel()

        self.deltas.clear()
        self.fileRows.clear()

        for delta in deltas:
            if self.skipConflicts and delta.isConflict():
                continue
            self.fileRows[delta.path] = len(self.deltas)
            self.deltas.append(delta)

        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex_default) -> int:
        return len(self.deltas)

    def data(self, index: QModelIndex, role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole) -> Any:
        row = index.row()
        try:
            delta = self.deltas[row]
        except IndexError:
            delta = None

        if role == FileListModel.Role.DeltaObject:
            return delta

        elif role == FileListModel.Role.FilePath:
            # TODO: Canonical path for submodules?
            return delta.path

        elif role == Qt.ItemDataRole.DisplayRole:
            # TODO: Canonical path for submodules?
            text = abbreviatePath(delta.path, settings.prefs.pathDisplayStyle)

            # Show important mode info in brackets
            om, nm = delta.modesPerContext(self.navContext)
            modeInfo = deltaModeText(om, nm)
            if modeInfo:
                text = f"[{modeInfo}] {text}"

            return text

        elif role == Qt.ItemDataRole.DecorationRole:
            letter = delta.statusPerContext(self.navContext)
            if letter == "?":  # untracked, fake A
                letter = "A"
            letter = letter.lower()
            return stockIcon(f"status_{letter}")

        elif role == Qt.ItemDataRole.ToolTipRole:
            isCounterpart = row == self.highlightedCounterpartRow
            return fileTooltip(self.repo, delta, self.navContext, isCounterpart)

        elif role == Qt.ItemDataRole.SizeHintRole:
            return QSize(-1, self.parentWidget.fontMetrics().height())

        elif role == Qt.ItemDataRole.FontRole:
            if row == self.highlightedCounterpartRow:
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
