# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import enum
import logging
from pathlib import Path

from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)


class DropAction(enum.IntEnum):
    Deny = enum.auto()
    Open = enum.auto()
    Patch = enum.auto()
    Clone = enum.auto()
    Blame = enum.auto()


class DropZone(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        font: QFont = self.font()
        font.setPointSizeF(font.pointSizeF() * 2)
        self.setFont(font)
        self.message = ""
        self.icon = "action-unavailable"

    def install(self, action: DropAction, data: str):
        if action == DropAction.Open:
            path = Path(data)
            self.message = _("Drop here to open repo {0}", tquoe(path.name))
            self.icon = "git-folder"
        elif action == DropAction.Clone:
            self.message = _("Drop here to clone {0}", tquoe(data))
            self.icon = "git-remote"
        elif action == DropAction.Patch:
            path = Path(data)
            self.message = _("Drop here to apply patch {0}", tquoe(path.name))
            self.icon = "git-stage-lines"
        elif action == DropAction.Blame:
            path = Path(data)
            self.message = _("Drop here to blame {0}", tquoe(path.name))
            self.icon = "git-blame"
        else:  # Deny
            self.message = data
            self.icon = "action-unavailable"

        self.setFixedSize(self.window().geometry().size())
        self.setVisible(True)

    def paintEvent(self, event: QPaintEvent):
        gray = QColor(128, 128, 128, 230)
        white = Qt.GlobalColor.white
        pad = 32
        iconSize = 16 * 5
        iconPad = iconSize // 4

        painter = QPainter(self)
        painter.save()

        rect = QRectF(self.rect())

        painter.fillRect(rect, gray)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(white, 4, Qt.PenStyle.DotLine))

        iconRect = QRect(pad, pad, iconSize, iconSize)
        icon = stockIcon(self.icon, "gray=white")
        icon.paint(painter, iconRect)

        textOption = QTextOption()
        textOption.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        textOption.setWrapMode(QTextOption.WrapMode.WordWrap)
        textRect = QRectF(0, pad, rect.width(), iconRect.height())
        textRect.adjust(iconRect.right() + iconPad, -iconPad, -pad, iconPad)
        painter.drawText(textRect, self.message, textOption)

        rect.adjust(pad, pad, -pad, -pad)
        rect.setTop(iconRect.bottom() + iconPad)
        painter.drawRoundedRect(rect, pad, pad)

        painter.restore()
