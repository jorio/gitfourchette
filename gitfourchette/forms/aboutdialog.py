# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import json
import sys
from textwrap import dedent

import pygit2
import pygments

from gitfourchette.forms.prefsdialog import availableLocaleCodes, localeCodeToLanguageName
from gitfourchette.forms.ui_aboutdialog import Ui_AboutDialog
from gitfourchette.gitdriver import GitDriver
from gitfourchette.localization import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *
from gitfourchette import settings

WEBSITE_URL = "https://gitfourchette.org"
USERS_GUIDE_URL = "https://gitfourchette.org/guide"
DONATE_URL = "https://ko-fi.com/jorio"
TRANSLATE_URL = "https://gitfourchette.org/localization"


class AboutDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)

        self.ui = Ui_AboutDialog()
        self.ui.setupUi(self)

        self.setWindowTitle(self.windowTitle().format(APP_DISPLAY_NAME))

        # ---------------------------------------------------------------------
        # Header

        buildInfoItems = [
            "Flatpak" if FLATPAK else "",
            "AppImage" if "APPIMAGE" in INITIAL_ENVIRONMENT else "",
            APP_FREEZE_DATE,
            APP_FREEZE_COMMIT[:7]
        ]
        buildInfoItems = [s for s in buildInfoItems if s]
        buildInfo = f"({', '.join(buildInfoItems)})" if buildInfoItems else ""

        headerText = dedent(f"""\
            <span style="font-size: x-large"><b>{APP_DISPLAY_NAME}</b></span>
            <br>{_("The comfortable Git UI for Linux.")}
            <br><a href="{WEBSITE_URL}">{WEBSITE_URL}</a>""")

        versionText = dedent(f"""\
            <span style='color: {mutedTextColorHex()}'>
                <b>{_("Version {0}", APP_VERSION)}</b> {buildInfo}
                <br>Copyright © 2026 Iliyas Jorio
            </span>""")

        # ---------------------------------------------------------------------
        # About page

        libgit2Features = ", ".join([f.name.lower() for f in pygit2.enums.Feature if f & pygit2.features])

        try:
            from gitfourchette.mount.treemount import fuse
            fuseInfo = _("with {0}", f"FUSE {fuse.fuse_version_major}.{fuse.fuse_version_minor}")
        except (ImportError, OSError, AttributeError):
            fuseInfo = _("(not available)")

        aboutHtml = dedent(f"""\
            <style>
                a {{ font-weight: bold; }}
                hr {{ background: gray; }}
                table {{ font-size: small; margin-top: 1em; }}
                th {{ text-align: left; padding-right: 1em; color: gray; }}
                img {{ float: right; }}
            </style>
            <p><img src="assets:icons/mug.png">{
                linkify(_("If {app} helps you get work done, "
                          "please consider [making a small donation].",
                          app=APP_DISPLAY_NAME), DONATE_URL)
            }</p>
            <p>{_("Thank you for your support!")}</p>
            <hr>
            <table cellspacing=0 cellpadding=0>
            <tr><th colspan=2>{APP_DISPLAY_NAME} {APP_VERSION}</th></tr>
            <tr><th>Git</th><td>{GitDriver.gitVersion() or _("(unknown version)")} ({settings.prefs.gitPath})</td></tr>
            <tr><th>LFS</th><td>{GitDriver.lfsVersion() or _("(not available)")}</td></tr>
            <tr><th>pygit2</th><td>{pygit2.__version__}</td></tr>
            <tr><th>libgit2</th><td>{pygit2.LIBGIT2_VERSION} ({libgit2Features})</td></tr>
            <tr><th>{QT_BINDING}</th><td>{QT_BINDING_VERSION}</td></tr>
            <tr><th>Qt</th><td>{qVersion()} ({QGuiApplication.platformName()})</td></tr>
            <tr><th>mfusepy</th><td>{fuseInfo}</td></tr>
            <tr><th>Pygments</th><td>{pygments.__version__}</td></tr>
            <tr><th>Python</th><td>{'.'.join(str(i) for i in sys.version_info)}</td></tr>
            </table>
        """)

        # ---------------------------------------------------------------------
        # Acknowledgments page

        contributors = assetsPath("contributors.txt").read_text("utf-8")
        contributors = contributors.removeprefix("Iliyas Jorio").strip()
        contributors = escape(contributors).replace("\n", "<br>")

        translatorCredits = json.loads(assetsPath("lang/credits.json").read_text("utf-8"))
        translatorFilter = availableLocaleCodes()
        translatorMarkup = "".join(
            f"<tr><th>{escape(localeCodeToLanguageName(lang))}:</th>"
            f"<td>{'<br>'.join(escape(p) for p in people)}</td></tr>"
            for lang, people in translatorCredits.items()
            if lang in translatorFilter
        )

        creditsHtml = dedent(f"""\
            <style>
                th {{ text-align: right; padding-right: 8px; color: gray; }}
            </style>
            <p>
                {_("Additional contributions by:")}
                <center>{contributors}</center>
            </p>
            <p>
                <a href="{TRANSLATE_URL}">{_("Translations welcome!")}</a>
                {_("Brought to your native language by:")}
                <center><table>{translatorMarkup}</table></center>
            </p>
            <p>{_("Special thanks to Marc-Alexandre Espiaut for beta testing.")}</p>
        """)

        # ---------------------------------------------------------------------
        # Changelog

        changelog = assetsPath("changelog.html").read_text("utf-8")
        changelog = dedent("""\
            <style>
                h2 { font-size: medium; font-weight: bold; background: gray; color: white; text-align: center; }
                ul { -qt-list-indent: 0; margin-left: 16px; }
                ul li { margin-bottom: 8px; }
            </style>
            <body>
            """) + changelog

        # ---------------------------------------------------------------------
        # License page

        licenseHtml = dedent(f"""\
            <p>{APP_DISPLAY_NAME} is free software: you can redistribute it and/or
            modify it under the terms of the GNU General Public License
            version 3 as published by the Free Software Foundation.</p>
            <p>{APP_DISPLAY_NAME} is distributed in the hope that it will be useful,
            but WITHOUT ANY WARRANTY; without even the implied warranty of
            MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. For more
            details, read the full terms of the
            <a href='https://www.gnu.org/licenses/gpl-3.0.txt'>GNU General
            Public License, version 3</a>.</p>""")

        # ---------------------------------------------------------------------
        # Donate button

        donateButton = self.ui.buttonBox.addButton(_("Donate"), QDialogButtonBox.ButtonRole.HelpRole)
        donateButton.setIcon(stockIcon("heart", "gray=#1a9cd2"))
        donateButton.setCursor(Qt.CursorShape.PointingHandCursor)
        donateButton.setToolTip(DONATE_URL)
        donateButton.clicked.connect(self.onDonateClicked)
        self.donateButton = donateButton

        guideButton = self.ui.buttonBox.addButton(_("User’s Guide"), QDialogButtonBox.ButtonRole.HelpRole)
        guideButton.setIcon(stockIcon("help-contents"))
        guideButton.setCursor(Qt.CursorShape.PointingHandCursor)
        guideButton.setToolTip(USERS_GUIDE_URL)
        guideButton.clicked.connect(self.onUsersGuideClicked)

        # Don't let Donate take over focus
        okButton = self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)
        okButton.setFocus()

        # ---------------------------------------------------------------------

        pixmap = QPixmap("assets:icons/gitfourchette")
        pixmap.setDevicePixelRatio(4)
        self.ui.logo.setPixmap(pixmap)

        self.ui.header.setText(headerText)
        self.ui.versionLabel.setText(versionText)

        self.addTab(_p("AboutDialog", "About"), aboutHtml)
        self.addTab(_p("AboutDialog", "Credits"), creditsHtml)
        self.addTab(_p("AboutDialog", "News"), changelog)
        self.addTab(_p("AboutDialog", "License"), licenseHtml)

        # Install QLabelExternalLinkToolTips after all the QLabels are set up.
        self.urlToolTip = QLabelExternalLinkToolTips(self)

    def addTab(self, title: str, markup: str):
        scrollArea = QScrollArea(self)
        scrollArea.setFrameShape(QFrame.Shape.NoFrame)
        scrollArea.setWidgetResizable(True)
        scrollArea.setBackgroundRole(QPalette.ColorRole.Base)

        wrapper = QWidget(scrollArea)
        scrollArea.setWidget(wrapper)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(32, 16, 32, 16)

        label = QLabel(wrapper)
        label.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction | Qt.TextInteractionFlag.TextSelectableByKeyboard | Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setOpenExternalLinks(True)
        label.setWordWrap(True)

        layout.addWidget(label)

        self.ui.tabWidget.addTab(scrollArea, title)

        # Setting the text AFTER the UI has been set up is much faster
        label.setText(markup)

    def onDonateClicked(self):
        QDesktopServices.openUrl(QUrl(DONATE_URL))
        self.donateButton.setText(_p("DonatePrompt", "THANK YOU!"))

    def onUsersGuideClicked(self):
        QDesktopServices.openUrl(QUrl(USERS_GUIDE_URL))

    @staticmethod
    def popUp(parent: QWidget, page: int = -1):
        dialog = AboutDialog(parent)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if page >= 0:
            dialog.ui.tabWidget.setCurrentIndex(page)
        dialog.show()
        return dialog
