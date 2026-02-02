# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.gitmoji.gitmojimodel import GitmojiModel
from gitfourchette.qt import *
from gitfourchette.settings import GitmojiCompletion


class GitmojiCompleter(QObject):
    AcceptKeys = {Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}

    def __init__(self, lineEdit: QLineEdit):
        super().__init__(lineEdit)
        self.lineEdit = lineEdit

        model = GitmojiModel(lineEdit)
        self.completer = QCompleter(model)

        lineEdit.setCompleter(self.completer)
        self.completer.popup().setItemDelegate(GitmojiItemDelegate(self))
        self.destroyed.connect(self.onDestroy)

        if settings.prefs.gitmoji == GitmojiCompletion.Emoji:
            self.completer.activated.connect(self.onCompleterActivated)

        QApplication.instance().installEventFilter(self)

    def onDestroy(self):
        QApplication.instance().removeEventFilter(self)

    # Defer to next event loop so that QCompleter gets to insert its plaintext
    # entry first, and then we'll override it with an emoji (and not the other
    # way around)
    def onCompleterActivated(self, text: str):
        gitmoji = GitmojiModel.GitmojiTable[text]
        def doIt():
            self.lineEdit.selectAll()
            self.lineEdit.insert(gitmoji.emoji + " ")
        QTimer.singleShot(0, doIt)

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.KeyPress
                and event.key() in GitmojiCompleter.AcceptKeys
                and self.completer.popup().isVisible()):
            popup = self.completer.popup()
            token = popup.currentIndex().data(self.completer.completionRole()) or self.completer.currentCompletion()
            self.completer.activated.emit(token)
            popup.close()
            return True
        return False


class GitmojiItemDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        super().paint(painter, option, index)
        painter.save()

        rect = QRect(option.rect)
        rect.setLeft(painter.fontMetrics().horizontalAdvance(index.data(Qt.ItemDataRole.DisplayRole)))

        font = painter.font()
        font.setItalic(True)
        painter.setFont(font)

        tip = index.data(Qt.ItemDataRole.ToolTipRole)
        tip = painter.fontMetrics().elidedText(tip, option.textElideMode, rect.width())

        isSelected = bool(option.state & QStyle.StateFlag.State_Selected)
        colorRole = QPalette.ColorRole.PlaceholderText if not isSelected else QPalette.ColorRole.HighlightedText
        painter.setPen(option.palette.color(QPalette.ColorGroup.Normal, colorRole))
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, tip)
        painter.restore()
