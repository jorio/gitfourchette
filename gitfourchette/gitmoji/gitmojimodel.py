# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import json
from pathlib import Path

from gitfourchette.qt import *


@dataclasses.dataclass
class GitmojiItem:
    emoji: str
    description: str


class GitmojiModel(QAbstractItemModel):
    GitmojiTable = {}
    GitmojiKeys = []

    def __init__(self, parent: QObject):
        super().__init__(parent)

        if self.GitmojiTable:
            return

        jsonPath = Path(QFile("assets:gitmojis.json").fileName())
        jsonBlob = jsonPath.read_text()
        jsonData = json.loads(jsonBlob)
        rawTable = {j["code"]: GitmojiItem(j["emoji"], j["description"])
                    for j in jsonData["gitmojis"]}
        GitmojiModel.GitmojiKeys = sorted(rawTable.keys())
        GitmojiModel.GitmojiTable = {k: rawTable[k] for k in GitmojiModel.GitmojiKeys}

    def rowCount(self, parent = ...):
        return len(self.GitmojiKeys)

    def index(self, row, column, parent = ...):
        assert parent.row() == -1
        return self.createIndex(row, column)

    def columnCount(self, parent = ...):
        return 1

    def parent(self, index):
        return QModelIndex()

    def data(self, index: QModelIndex, role: Qt.ItemDataRole = Qt.ItemDataRole.DisplayRole):
        code = self.GitmojiKeys[index.row()]
        gitmoji = self.GitmojiTable[code]
        if role == Qt.ItemDataRole.DisplayRole:
            return gitmoji.emoji + "  " + code + "    "
        elif role == Qt.ItemDataRole.EditRole:
            return code
        elif role == Qt.ItemDataRole.ToolTipRole:
            return gitmoji.description
        return None
