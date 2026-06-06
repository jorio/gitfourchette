# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.ui_commitinfodialog import Ui_CommitInfoDialog
from gitfourchette.localization import _
from gitfourchette.qt import *
from gitfourchette.toolbox.iconbank import stockIcon


class CommitInfoDialog(QDialog):
    """
    Rich summary (HTML) plus optional read-only body, in a resizable dialog.
    Used instead of QMessageBox.setDetailedText because QMessageBox forces a
    fixed size whenever its layout updates.
    """

    _PreferredWidth = 512

    @property
    def summaryLabel(self):
        return self.ui.summaryLabel

    def __init__(
            self,
            parent: QWidget | None,
            title: str,
            summaryHtml: str,
            body: str = "",
    ):
        super().__init__(parent)

        self.ui = Ui_CommitInfoDialog()
        self.ui.setupUi(self)

        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.WindowModal)

        # Start without details box (we need to capture the packed size first)
        self.ui.detailsEdit.setVisible(False)

        pm = stockIcon("SP_MessageBoxInformation").pixmap(56, 56)
        self.ui.iconLabel.setPixmap(pm)
        self.ui.summaryLabel.setText(summaryHtml)
        self.ui.detailsEdit.setPlainText(body)

        self._detailsToggleButton = self.ui.buttonBox.addButton("...", QDialogButtonBox.ButtonRole.ActionRole)
        self._detailsToggleButton.clicked.connect(self._toggleDetailsPane)
        self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok).setFocus()

        # Pack the layout, then save the packed size
        self.setMinimumWidth(self._PreferredWidth)
        self.layout().activate()  # force layout
        self.adjustSize()
        self.packedSize = self.size()

        # Show details if any
        if body:
            self._toggleDetailsPane()  # pane currently hidden - show it
        else:
            self._detailsToggleButton.setVisible(False)

        self._applyResizePolicy()

    def isShowingDetails(self) -> bool:
        # isVisibleTo, not isVisible, so this is valid even before we're shown
        return self.ui.detailsEdit.isVisibleTo(self)

    def _toggleDetailsPane(self):
        show = not self.isShowingDetails()
        self.ui.detailsEdit.setVisible(show)
        self._detailsToggleButton.setText(_("Hide Full &Message") if show else _("Show Full &Message"))
        self._applyResizePolicy()

    def _applyResizePolicy(self):
        if self.isShowingDetails():
            self.setSizeGripEnabled(True)
            self.setMinimumSize(self._PreferredWidth, 0)
            self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
            self.adjustSize()
        else:
            self.setSizeGripEnabled(False)
            self.setFixedSize(self.packedSize)
