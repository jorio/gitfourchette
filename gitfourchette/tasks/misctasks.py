# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
from contextlib import suppress

from gitfourchette import settings
from gitfourchette.forms.reposettingsdialog import RepoSettingsDialog
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import Oid, Signature
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID
from gitfourchette.tasks.repotask import RepoTask
from gitfourchette.toolbox import *

logger = logging.getLogger(__name__)


class EditRepoSettings(RepoTask):
    def flow(self):
        dlg = RepoSettingsDialog(self.repo, self.parentWidget())
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        yield from self.flowDialog(dlg)

        localName, localEmail = dlg.localIdentity()
        nickname = dlg.ui.nicknameEdit.text()
        dlg.deleteLater()

        configObject = self.repo.config
        for key, value in [("user.name", localName), ("user.email", localEmail)]:
            if value:
                configObject[key] = value
            else:
                with suppress(KeyError):
                    del configObject[key]
        self.repo.scrub_empty_config_section("user")

        if nickname != settings.history.getRepoNickname(self.repo.workdir, strict=True):
            settings.history.setRepoNickname(self.repo.workdir, nickname)
            settings.history.setDirty()
            self.rw.nameChange.emit()


class GetCommitInfo(RepoTask):
    @staticmethod
    def formatSignature(sig: Signature):
        dateText = signatureDateFormat(sig)
        return f"{escape(sig.name)} &lt;{escape(sig.email)}&gt;<br><small>{escape(dateText)}</small>"

    def flow(self, oid: Oid, withDebugInfo=False):
        links = DocumentLinks()

        def commitLink(commitId):
            if commitId == UC_FAKEID:
                commitLocator = NavLocator.inWorkdir()
            else:
                commitLocator = NavLocator.inCommit(commitId)
            link = links.new(lambda invoker: self.saveLocator(commitLocator))
            html = linkify(shortHash(commitId), link)
            return html

        def tableRow(th, td):
            colon = _(":")
            return f"<tr><th>{th}{colon}</th><td>{td}</td></tr>"

        repo = self.repo
        repoModel = self.repoModel
        commit = repo.peel_commit(oid)

        # Break down commit message into summary/details
        summary, contd = messageSummary(commit.message)
        details = commit.message if contd else ""

        # Parent commits
        parentHashes = [commitLink(p) for p in commit.parent_ids]
        numParents = len(parentHashes)
        parentTitle = _n("Parent", "{n} Parents", numParents)
        if numParents > 0:
            parentMarkup = ', '.join(parentHashes)
        elif not repo.is_shallow:
            parentMarkup = "-"
        else:
            shallowCloneBlurb = _("You’re working in a shallow clone. This commit may actually have parents in the full history.")
            parentMarkup = tagify(shallowCloneBlurb, "<p><em>")

        # Committer
        if commit.author == commit.committer:
            committerMarkup = tagify(_("(same as author)"), "<i>")
        else:
            committerMarkup = self.formatSignature(commit.committer)

        # Assemble table rows
        table = tableRow(_("Hash"), commit.id)
        table += tableRow(parentTitle, parentMarkup)
        table += tableRow(_("Author"), self.formatSignature(commit.author))
        table += tableRow(_("Committer"), committerMarkup)

        # Graph debug info
        if withDebugInfo:
            graph = repoModel.graph
            seqIndex = graph.getCommitRow(oid)
            frame = graph.getFrame(seqIndex)
            homeChain = frame.homeChain()
            homeChainTopId = graph.getFrame(int(homeChain.topRow)).commit
            homeChainTopStr = commitLink(homeChainTopId) if type(homeChainTopId) is Oid else str(homeChainTopId)
            table += tableRow("Graph row", repr(graph.commitRows[oid]))
            table += tableRow("Home chain", f"{repr(homeChain.topRow)} {homeChainTopStr} ({id(homeChain) & 0xFFFFFFFF:X})")
            table += tableRow("Arcs", f"{len(frame.openArcs)} open, {len(frame.solvedArcs)} solved")
            # table += tableRow("View row", self.rw.graphView.currentIndex().row())
            details = str(frame) + "\n\n" + details

        title = _("Commit info: {0}", shortHash(commit.id))

        markup = f"""\
        <style>
            table {{ margin-top: 16px; }}
            th, td {{ padding-bottom: 4px; }}
            th {{
                text-align: right;
                padding-right: 8px;
                font-weight: normal;
                white-space: pre;
                color: {mutedTextColorHex(self.parentWidget())};
            }}
        </style>
        <big>{summary}</big>
        <table>{table}</table>
        """

        messageBox = asyncMessageBox(
            self.parentWidget(), 'information', title, markup, macShowTitle=False,
            buttons=QMessageBox.StandardButton.Ok)

        if details:
            messageBox.setDetailedText(details)

            # Pre-click "Show Details" button
            for button in messageBox.buttons():
                role = messageBox.buttonRole(button)
                if role == QMessageBox.ButtonRole.ActionRole:
                    button.click()
                elif role == QMessageBox.ButtonRole.AcceptRole:
                    messageBox.setDefaultButton(button)

        # Bind links to callbacks
        label: QLabel = messageBox.findChild(QLabel, "qt_msgbox_label")
        assert label
        label.setOpenExternalLinks(False)
        label.linkActivated.connect(lambda url: links.processLink(url, self))
        label.linkActivated.connect(lambda: messageBox.accept())

        yield from self.flowDialog(messageBox)

    def saveLocator(self, locator):
        self.jumpTo = locator
