# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.localization import _
from gitfourchette.qt import *
from gitfourchette.toolbox.iconbank import stockIcon


class CommitInfoDialog(QDialog):
    """
    Rich summary (HTML) plus optional read-only body, in a resizable dialog.
    Used instead of QMessageBox.setDetailedText because QMessageBox forces a
    fixed size whenever its layout updates.
    """

    def __init__(
            self,
            parent: QWidget | None,
            title: str,
            summaryHtml: str,
            body: str = "",
    ):
        super().__init__(parent)

        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        pm = stockIcon("SP_MessageBoxInformation").pixmap(48, 48)
        iconLabel = QLabel(self)
        iconLabel.setPixmap(pm)
        iconLabel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.summaryLabel = QLabel(self)
        self.summaryLabel.setObjectName("commit_info_summary")
        self.summaryLabel.setTextFormat(Qt.TextFormat.RichText)
        self.summaryLabel.setText(summaryHtml)
        self.summaryLabel.setWordWrap(True)
        self.summaryLabel.setOpenExternalLinks(False)
        self.summaryLabel.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction)
        self.summaryLabel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self._detailsEdit: QPlainTextEdit | None = None
        self._detailsToggleButton: QAbstractButton | None = None

        textColumn = QVBoxLayout()
        textColumn.setSpacing(12)
        textColumn.addWidget(self.summaryLabel)
        if body:
            self._detailsEdit = QPlainTextEdit(self)
            self._detailsEdit.setPlainText(body)
            self._detailsEdit.setReadOnly(True)
            self._detailsEdit.setMinimumHeight(200)
            self._detailsEdit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            textColumn.addWidget(self._detailsEdit, stretch=1)

        row = QHBoxLayout()
        row.addWidget(iconLabel, alignment=Qt.AlignmentFlag.AlignTop)
        row.addLayout(textColumn, stretch=1)

        buttonBox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, parent=self)
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)
        ok = buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        if ok:
            ok.setDefault(True)

        if body:
            self._detailsToggleButton = buttonBox.addButton(
                _("Hide Details..."), QDialogButtonBox.ButtonRole.ActionRole)
            self._detailsToggleButton.clicked.connect(self._toggleDetailsPane)

        self._outerLayout = QVBoxLayout(self)
        self._outerLayout.addLayout(row, stretch=1 if body else 0)
        self._outerLayout.addWidget(buttonBox)

        self.setMinimumWidth(480)
        self._resizableMinimumSize = self.minimumSize()
        self._resizableMaximumSize = self.maximumSize()
        self._detailsVisible = bool(body)
        QTimer.singleShot(0, self._applyResizePolicy)

    def _toggleDetailsPane(self):
        if not self._detailsEdit or not self._detailsToggleButton:
            return
        show = not self._detailsEdit.isVisible()
        self._detailsEdit.setVisible(show)
        self._detailsVisible = show
        self._detailsToggleButton.setText(
            _("Hide Details...") if show else _("Show Details..."))

        # No extra vertical slack above the button row when details are hidden.
        self._outerLayout.setStretch(0, 1 if show else 0)
        self._outerLayout.activate()
        self.updateGeometry()

        self._applyResizePolicy()

    def _applyResizePolicy(self):
        minHint = self.minimumSizeHint()
        if self._detailsVisible:
            minSize = QSize(self._resizableMinimumSize)
            minSize.setWidth(max(480, minSize.width()))
            minSize.setHeight(max(minHint.height(), minSize.height()))
            self.setSizeGripEnabled(True)
            self.setMinimumSize(minSize)
            self.setMaximumSize(self._resizableMaximumSize)
            if self.height() < minSize.height():
                self.resize(max(self.width(), minSize.width()), minSize.height())
            return

        compactSize = QSize(minHint)
        compactSize.setWidth(max(480, compactSize.width()))
        self.setSizeGripEnabled(False)
        self.resize(compactSize)
        self.setMinimumSize(compactSize)
        self.setMaximumSize(compactSize)
