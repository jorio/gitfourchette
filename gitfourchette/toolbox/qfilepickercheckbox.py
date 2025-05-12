# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox.pathutils import compactPath
from gitfourchette.toolbox.qelidedlabel import QElidedLabel
from gitfourchette.toolbox.qhintbutton import QHintButton
from gitfourchette.toolbox.qtutils import tweakWidgetFont, DisableWidgetUpdatesContext
from gitfourchette.toolbox.textutils import escamp


class QFilePickerCheckBox(QWidget):
    def __init__(self, parent, caption: str = ""):
        super().__init__(parent)

        self.cachedPath = ""

        self.checkBox = QCheckBox(caption)
        self.pathLabel = QElidedLabel(self)
        self.pathLabel.setTextFormat(Qt.TextFormat.PlainText)
        self.browseButton = QToolButton()
        self.browseButton.setText(_p("button to open a file browser to select a file", "Select…"))

        self.warningButton = QHintButton(self, iconKey="achtung")

        layout = QGridLayout(self)
        layout.setContentsMargins(QMargins())
        layout.setVerticalSpacing(0)
        layout.addWidget(self.checkBox,         0, 0, 1, 3)
        layout.addWidget(self.browseButton,     1, 0)
        layout.addWidget(self.warningButton,    1, 1)
        layout.addWidget(self.pathLabel,        1, 2)
        layout.setColumnStretch(2, 1)

        self.checkBox.toggled.connect(self.autoBrowse)
        self.browseButton.clicked.connect(self.browse)
        tweakWidgetFont(self.pathLabel, 90)
        f = tweakWidgetFont(self.browseButton, 90)
        lh = QFontMetrics(f).height() + 2
        self.browseButton.setMaximumHeight(lh)
        self.warningButton.setMaximumHeight(lh)
        self.updateControls()

    def fileDialog(self) -> QFileDialog:
        """ Override this function to bring up a custom QFileDialog. """
        raise NotImplementedError("override this")

    def validatePath(self, path: str) -> str:
        """ Override this function to display a validation warning when the user selects a file.
        Returning an empty string causes the warning to disappear. """
        raise NotImplementedError("override this")

    def makeFixedHeight(self):
        lh = self.browseButton.maximumHeight()
        self.layout().setRowMinimumHeight(1, lh)

    def setText(self, caption: str):
        self.checkBox.setText(caption)

    def isChecked(self) -> bool:
        return self.checkBox.isChecked()

    def path(self) -> str:
        return self.cachedPath if self.isChecked() else ""

    def autoBrowse(self):
        """ If checkbox is ticked and path is empty, bring up file browser. """
        if self.isChecked() and not self.cachedPath:
            self.browse()
        else:
            self.updateControls()

    def browse(self):
        qfd = self.fileDialog()
        qfd.fileSelected.connect(self.setPath)
        qfd.rejected.connect(self.onRejectFileDialog)
        qfd.show()

    def setPath(self, path: str):
        self.cachedPath = path
        self.warningButton.setToolTip(self.validatePath(path))

        with QSignalBlocker(self.checkBox):
            self.checkBox.setChecked(bool(path))
        self.updateControls()

    def onRejectFileDialog(self):
        # File browser canceled and lineedit empty, untick checkbox
        if not self.cachedPath:
            self.checkBox.setChecked(False)

    @DisableWidgetUpdatesContext.methodDecorator
    def updateControls(self):
        path = self.path()
        hasPath = bool(path)
        self.pathLabel.setText(escamp(compactPath(path)))
        self.browseButton.setVisible(hasPath)
        self.pathLabel.setVisible(hasPath)
        self.warningButton.setVisible(hasPath and bool(self.warningButton.toolTip()))
