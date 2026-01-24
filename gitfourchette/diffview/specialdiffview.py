# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import settings
from gitfourchette.application import GFApplication
from gitfourchette.diffview.specialdiff import SpecialDiffError, ImageDelta
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import stockIcon, escape, DocumentLinks


class SpecialDiffView(QTextBrowser):
    linkActivated = Signal(QUrl)

    documentLinks: DocumentLinks | None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.documentLinks = None
        self.anchorClicked.connect(self.onAnchorClicked)
        GFApplication.instance().restyle.connect(self.refreshPrefs)
        GFApplication.instance().prefsChanged.connect(self.refreshPrefs)
        self.refreshPrefs()

    def refreshPrefs(self):
        scheme = settings.prefs.syntaxHighlightingScheme()
        styleSheet = scheme.basicQss(self)
        self.setStyleSheet(styleSheet)
        self.htmlHeader = "<html><style>a { font-weight: bold; }</style>" + settings.prefs.addDelColorsStyleTag()

    def onAnchorClicked(self, link: QUrl):
        if self.documentLinks is not None and self.documentLinks.processLink(link):
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

        # Let DocumentLinks callbacks invoke RepoTasks using this QObject chain
        err.taskInvoker = document

    def displayImageDelta(self, d: ImageDelta):
        image = d.newImage or d.oldImage
        assert image is not None, "both image sides are None"

        markup = self.htmlHeader
        markup += "<table>"

        for i, size, tag, intro in [
            (d.oldImage, d.oldSize, "del", _("Old image:") if d.newImage else _("Deleted image:")),
            (d.newImage, d.newSize, "add", _("New image:"))
        ]:
            if i is None:
                continue

            c1 = f"<b><{tag}>{intro}</tag></b>"
            c2 = _("{w} × {h} pixels", w=i.width(), h=i.height())
            c3 = self.locale().formattedDataSize(size)

            c4 = ""
            if i is image and d.oldImage and d.newImage:
                c4 = f"<b><{tag}>{_('(shown below)')}</{tag}></b>"

            markup += (f"<tr><td>{c1} </td>"
                       f"<td style='text-align: right'>{c2}, </td>"
                       f"<td style='text-align: right'>{c3}</td>"
                       f"<td> {c4}</td></tr>")

        markup += "</table>"
        markup += "<p style='text-align: center'><img src='image' /></p>"

        image.setDevicePixelRatio(self.devicePixelRatio())

        document = QTextDocument(self)
        document.setObjectName("ImageDiffDocument")
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl("image"), image)
        document.setHtml(markup)

        self.replaceDocument(document)
