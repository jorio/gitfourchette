# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import colors
from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.diffview.diffdocument import SpecialDiffError
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.toolbox import stockIcon, escape, DocumentLinks


class SpecialDiffView(QTextBrowser):
    linkActivated = Signal(QUrl)

    documentLinks: DocumentLinks | None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.documentLinks = None
        self.anchorClicked.connect(self.onAnchorClicked)
        self.refreshPrefs()
        GFApplication.instance().restyle.connect(self.refreshPrefs)

    def refreshPrefs(self):
        styleSheet = settings.prefs.basicQssForPygmentsStyle(self)
        self.setStyleSheet(styleSheet)

        if settings.prefs.colorblind:
            addColor = colors.teal
            delColor = colors.orange
        else:
            addColor = colors.olive
            delColor = colors.red

        self.htmlHeader = f"""\
        <html>
        <style>
        del {{ color: {delColor.name()}; }}
        add {{ color: {addColor.name()}; }}
        a {{ font-weight: bold; }}
        </style>"""

    def onAnchorClicked(self, link: QUrl):
        if self.documentLinks is not None and self.documentLinks.processLink(link, self):
            return
        self.linkActivated.emit(link)

    def replaceDocument(self, newDocument: QTextDocument):
        self.documentLinks = None

        if self.document():
            self.document().deleteLater()

        self.setDocument(newDocument)
        self.clearHistory()

        self.setOpenLinks(False)

    def displaySpecialDiffError(self, err: SpecialDiffError):
        document = QTextDocument(self)
        document.setObjectName("DiffErrorDocument")

        icon = stockIcon(err.icon)
        pixmap: QPixmap = icon.pixmap(48, 48)
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl("icon"), pixmap)

        markup = (
            f"{self.htmlHeader}"
            "<table width='100%'>"
            "<tr>"
            f"<td width='{pixmap.width()}px'><img src='icon'/></td>"
            "<td width='100%' style='padding-left: 8px; padding-top: 8px;'>"
            f"<big>{err.message}</big>"
            f"<br/>{err.details}"
            "</td>"
            "</tr>"
            "</table>")

        if err.preformatted:
            markup += F"<pre>{escape(err.preformatted)}</pre>"

        markup += err.longform

        document.setHtml(markup)
        self.replaceDocument(document)

        assert self.documentLinks is None
        self.documentLinks = err.links

    def displayImageDiff(self, delta: DiffDelta, imageA: QImage, imageB: QImage):
        document = QTextDocument(self)
        document.setObjectName("ImageDiffDocument")

        humanSizeA = self.locale().formattedDataSize(delta.old_file.size)
        humanSizeB = self.locale().formattedDataSize(delta.new_file.size)

        textA = _("Old:") + " " + _("{w}×{h} pixels, {size}", w=imageA.width(), h=imageA.height(), size=humanSizeA)
        textB = _("New:") + " " + _("{w}×{h} pixels, {size}", w=imageB.width(), h=imageB.height(), size=humanSizeB)

        if delta.old_file.id == NULL_OID:
            header = f"<add>{textB}</add>"
            image = imageB
        elif delta.new_file.id == NULL_OID:
            header = f"<del>{textA} " + _("(<b>deleted file</b> displayed below)") + "</del>"
            image = imageA
        else:
            header = f"<del>{textA}</del><br><add>{textB} " + _("(<b>new file</b> displayed below)") + "</add>"
            image = imageB

        image.setDevicePixelRatio(self.devicePixelRatio())
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl("image"), image)

        document.setHtml(
            f"{self.htmlHeader}"
            f"<p>{header}</p>"
            "<p style='text-align: center'><img src='image' /></p>")

        self.replaceDocument(document)
