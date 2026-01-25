# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class ProtocolButton(QToolButton):
    protocolChanged = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedWidth(self.sizeHint().width() + self.fontMetrics().horizontalAdvance("--https--"))
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolTip(_("Change URL protocol"))

    def connectTo(self, lineEdit: QLineEdit):
        def onUrlProtocolChanged(newUrl: str):
            # This pushes the new text to the QLineEdit's undo stack
            # (whereas setText clears the undo stack).
            lineEdit.selectAll()
            lineEdit.insert(newUrl)

        lineEdit.textChanged.connect(self.onUrlChanged)
        self.protocolChanged.connect(onUrlProtocolChanged)

        # Prime state
        self.onUrlChanged(lineEdit.text())

    def onUrlChanged(self, url: str):
        """ Detect protocol when URL changes """

        url = url.strip()
        protocol = remoteUrlProtocol(url)

        if not protocol:  # unknown protocol, hide protocol button
            self.hide()
            return

        # Build alternate URL
        host, path = splitRemoteUrl(url)
        if protocol == "ssh":
            newUrl = f"https://{host}/{path}"
            newUrl = newUrl.removesuffix(".git")
        else:
            host = host.split(":", 1)[0]  # remove port, if any
            newUrl = f"git@{host}:{path}"

        self.show()
        self.setText(protocol)

        menu = ActionDef.makeQMenu(self, [ActionDef(newUrl, lambda: self.protocolChanged.emit(newUrl))])
        self.setMenu(menu)
