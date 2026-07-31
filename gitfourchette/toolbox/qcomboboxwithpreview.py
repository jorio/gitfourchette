# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *


class QComboBoxWithPreview(QComboBox):
    dataPicked = Signal(object)

    class Role:
        Data = Qt.ItemDataRole.UserRole + 0
        Preview = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.numPresets = 0
        self.captionWidth = 0
        self.previewWidth = 0
        delegate = QComboBoxWithPreviewDelegate(self)
        self.setItemDelegate(delegate)
        self.activated.connect(self.onActivated)

    def addItemWithPreview(self, caption: str, data: object, preview: str):
        i = self.count()
        self.addItem(caption)
        self.setItemData(i, data, QComboBoxWithPreview.Role.Data)
        self.setItemData(i, preview, QComboBoxWithPreview.Role.Preview)

        fontMetrics = self.fontMetrics()
        self.captionWidth = max(self.captionWidth, fontMetrics.horizontalAdvance(caption) + 20)
        self.previewWidth = max(self.previewWidth, fontMetrics.horizontalAdvance(preview) + 6)

        self.numPresets += 1

    def showPopup(self):
        # TODO: Where is QListView padding defined?
        self.view().setMinimumWidth(3 + self.captionWidth + self.previewWidth + 3)
        super().showPopup()

    def onActivated(self, index: int):
        # The signal may be sent for an index beyond the number of presets
        # when the user hits enter with a custom item.
        if index < 0 or index >= self.numPresets:
            return

        data = self.itemData(index, QComboBoxWithPreview.Role.Data)
        self.dataPicked.emit(data)

        if self.isEditable():
            self.setEditText(str(data))


class QComboBoxWithPreviewDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex):
        super().paint(painter, option, index)
        painter.save()

        pw = self.parent()
        assert isinstance(pw, QComboBoxWithPreview)

        rect = QRect(option.rect)
        rect.setLeft(rect.left() + 3 + pw.captionWidth)

        isSelected = bool(option.state & QStyle.StateFlag.State_Selected)
        colorRole = QPalette.ColorRole.PlaceholderText if not isSelected else QPalette.ColorRole.HighlightedText

        font: QFont = painter.font()
        font.setItalic(True)

        preview = index.data(QComboBoxWithPreview.Role.Preview)

        painter.setFont(font)
        painter.setPen(option.palette.color(QPalette.ColorGroup.Normal, colorRole))
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, str(preview))
        painter.restore()
