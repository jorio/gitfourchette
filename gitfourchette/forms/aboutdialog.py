# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import sys
from textwrap import dedent

import pygit2

from gitfourchette.forms.ui_aboutdialog import Ui_AboutDialog
from gitfourchette.qt import *
from gitfourchette.toolbox import *

WEBSITE_URL = "https://gitfourchette.org"
DONATE_URL = "https://ko-fi.com/jorio"


def getPygit2FeatureStrings():
    return [f.name.lower() for f in pygit2.enums.Feature if f & pygit2.features]


def simpleLink(url):
    return f"<a href='{url}'>{url}</a>"


class AboutDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)

        self.ui = Ui_AboutDialog()
        self.ui.setupUi(self)

        self.urlToolTip = UrlToolTip(self)
        self.urlToolTip.install()

        appVersion = QApplication.applicationVersion()
        appName = qAppName()

        self.setWindowTitle(self.windowTitle().format(appName))

        buildInfoItems = [
            "Flatpak" if FLATPAK else "",
            APP_FREEZE_DATE,
            APP_FREEZE_COMMIT[:7]
        ]
        buildInfoItems = [s for s in buildInfoItems if s]
        buildInfo = f"({', '.join(buildInfoItems)})" if buildInfoItems else ""

        tagline = tr("The comfortable Git UI for Linux.")

        # ---------------------------------------------------------------------
        # Header

        pixmap = QPixmap("assets:icons/gitfourchette")
        pixmap.setDevicePixelRatio(4)
        self.ui.iconLabel.setPixmap(pixmap)

        self.ui.header.setText(dedent(f"""\
            <span style="font-size: x-large"><b>{appName}</b></span>
            <br>{tagline}
            <br>{simpleLink(WEBSITE_URL)}"""))

        versionText = self.tr("Version {0}").format(appVersion)
        self.ui.versionLabel.setText(dedent(f"""\
            <span style='color:{mutedTextColorHex(self)}'><b>{versionText}</b> {buildInfo}
            <br>Copyright © 2024 Iliyas Jorio"""))

        # ---------------------------------------------------------------------
        # About page

        self.ui.mugshot.setText("")
        self.ui.mugshot.setPixmap(QPixmap("assets:icons/mug"))

        self.ui.aboutBlurb.setText(paragraphs(
            linkify(self.tr("If {app} helps you get work done, please consider [making a small donation]."), DONATE_URL),
            self.tr("Thank you for your support!")
        ).format(app=appName))

        # ---------------------------------------------------------------------
        # Components page

        qtBindingSuffix = ""

        poweredByTitle = self.tr("Powered by:")
        self.ui.componentsBlurb.setText(dedent(f"""<html>\
            {appName} {appVersion}
            {buildInfo}
            <br>{poweredByTitle}
            <ul style='margin: 0'>
            <li><b>pygit2</b> {pygit2.__version__}
            <li><b>libgit2</b> {pygit2.LIBGIT2_VERSION} <small>({', '.join(getPygit2FeatureStrings())})</small>
            <li><b>{QT_BINDING}</b> {QT_BINDING_VERSION}{qtBindingSuffix}
            <li><b>Qt</b> {qVersion()}
            <li><b>Python</b> {'.'.join(str(i) for i in sys.version_info)}
            </ul>
        """))

        # ---------------------------------------------------------------------
        # Acknowledgments page

        ackText = [
            self.tr("Special thanks to Marc-Alexandre Espiaut for beta testing."),
            linkify(
                self.tr("Portions of this software are based on [{lib}], used under [{lic} license], {copyright}."),
                "https://github.com/z3ntu/QtWaitingSpinner", "https://github.com/z3ntu/QtWaitingSpinner/blob/055517b18/LICENSE.md"
            ).format(lib="QtWaitingSpinner", lic="MIT", copyright="© Alexander Turkin, William Hallatt, Jacob Dawid, Luca Weiss")
        ]

        self.ui.ackBlurb.setText(paragraphs(ackText))

        # ---------------------------------------------------------------------
        # License page

        self.ui.licenseBlurb.setText(dedent(f"""\
            <p>{appName} is free software: you can redistribute it and/or
            modify it under the terms of the GNU General Public License
            version 3 as published by the Free Software Foundation.</p>
            <p>{appName} is distributed in the hope that it will be useful,
            but WITHOUT ANY WARRANTY; without even the implied warranty of
            MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. For more
            details, read the full terms of the
            <a href='https://www.gnu.org/licenses/gpl-3.0.txt'>GNU General
            Public License, version 3</a>.</p>"""))

    @staticmethod
    def popUp(parent: QWidget):
        dialog = AboutDialog(parent)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()
        return dialog
