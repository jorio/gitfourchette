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

    def displayImageDelta(self, delta: ImageDelta, swap=False):
        if not swap:
            image = delta.new.image or delta.old.image
        else:
            image = delta.old.image or delta.new.image
        hasBothSides = delta.old.image and delta.new.image
        showLfsStatus = delta.old.deltaFile.lfs or delta.new.deltaFile.lfs

        green, red = settings.prefs.addDelColors()
        borderColor = red if image is delta.old.image else green

        links = DocumentLinks()
        swapLink = links.new(lambda: self.displayImageDelta(delta, swap=not swap))

        markup = self.htmlHeader + "<center><table>"

        for file in delta.old, delta.new:
            if file.image is None:
                continue

            tag = "add" if file is delta.new else "del"

            name = (_("New image") if file is delta.new else
                    _("Old image") if delta.new.image else
                    _("Deleted image"))

            # Show LFS info if either side is an LFS pointer:
            if showLfsStatus and not file.deltaFile.lfs.isTentative():
                lfsInfo = "LFS" if file.deltaFile.lfs else _("not LFS")
                name = f"{name}, {lfsInfo}"
            name += _(":")

            if hasBothSides and file.image is not image:
                c1 = f"<a href='{swapLink}'>{name}</a>"
            else:
                c1 = f"<b><{tag}>{name}</{tag}></b>"

            c2 = f"{file.image.width()} &times; {file.image.height()} {_('pixels')},"
            c3 = self.locale().formattedDataSize(file.size)

            if hasBothSides and file.image is image:
                c4 = f"<b><{tag}>&darr; {_('shown below')} &darr;</{tag}></b>"
            else:
                c4 = ""

            markup += (f"<tr><td>{c1} </td>"
                       f"<td style='text-align: right'>{c2} </td>"
                       f"<td style='text-align: right'>{c3} </td>"
                       f"<td style='text-align: center'> {c4}</td>"
                       f"</tr>")

        markup += (
            "</table>"
            f"<table style='border: 4px solid {borderColor.name()}; border-collapse: collapse;'>"
            "<tr><td><img src='image'/></tr></td>"
            "</table>"
            "</center>")

        document = QTextDocument(self)
        document.setObjectName("ImageDiffDocument")
        document.setHtml(markup)

        if image is not None:
            image.setDevicePixelRatio(self.devicePixelRatio())
            document.addResource(QTextDocument.ResourceType.ImageResource, QUrl("image"), image)

        self.replaceDocument(document)

        assert self.documentLinks is None
        self.documentLinks = links
