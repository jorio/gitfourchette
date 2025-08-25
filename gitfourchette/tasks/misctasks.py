# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import re
from contextlib import suppress
from pathlib import Path

from gitfourchette import settings
from gitfourchette.forms.ignorepatterndialog import IgnorePatternDialog
from gitfourchette.forms.reposettingsdialog import RepoSettingsDialog
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import Oid, Signature
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID, GpgStatus
from gitfourchette.tasks import TaskEffects
from gitfourchette.tasks.repotask import RepoTask, AbortTask
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables

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

    def flow(self, oid: Oid, withDebugInfo=False, dialogParent: QWidget | None = None):
        def commitLink(commitId):
            if commitId == UC_FAKEID:
                commitLocator = NavLocator.inWorkdir()
            else:
                commitLocator = NavLocator.inCommit(commitId)
            link = commitLocator.url()
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

        # GPG
        gpg = self.repoModel.getCachedGpgStatus(commit)
        if not gpg:
            gpgMarkup = tagify(_("(not GPG-signed)"), "<i>")
        else:
            gpgIcon = f"<img src='assets:icons/{gpg.iconName()}' style='vertical-align: bottom'/> "
            gpgMarkup = gpgIcon + _("GPG-signed; {0}", TrTables.enum(gpg))

        # Assemble table rows
        table = tableRow(_("Hash"), commit.id)
        table += tableRow(parentTitle, parentMarkup)
        table += tableRow(_("Author"), self.formatSignature(commit.author))
        table += tableRow(_("Committer"), committerMarkup)
        table += tableRow(_("Trust"), gpgMarkup)

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

        dialogParent = dialogParent or self.parentWidget()
        messageBox = asyncMessageBox(
            dialogParent, 'information', title, markup, macShowTitle=False,
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
        label.linkActivated.connect(self.rw.processInternalLink)
        label.linkActivated.connect(messageBox.accept)

        messageBox.show()

        # Instead of yielding `flowDialog`, let `messageBox` outlive the task so
        # that the user can trigger other tasks while `messageBox` is open above
        # a non-MainWindow (like BlameWindow). We still need a dummy yield here
        # to satisfy the requirement that `flow` be a generator.
        yield from self.flowEnterUiThread()


class VerifyGpgSignature(RepoTask):
    def flow(self, oid: Oid, dialogParent: QWidget | None = None):
        prettyHash = hquo(shortHash(oid))
        commit = self.repo.peel_commit(oid)

        gpgSignature, gpgPayload = commit.gpg_signature
        if not gpgSignature:
            raise AbortTask(_("Commit {0} is not GPG-signed, so it cannot be verified.", prettyHash))

        driver = yield from self.flowCallGit("verify-commit", "--raw", str(oid), autoFail=False)
        fail = driver.exitCode() != 0

        # Update gpg status cache
        self.repoModel.gpgStatusCache[oid] = GpgStatus.Unverified if fail else GpgStatus.Good

        if fail:
            paras = [_("Commit {0} is GPG-signed, but it couldn’t be verified.", prettyHash)]

            tokenParsers = {
                "VALIDSIG": _("The signature itself is good, but verification failed."),
                "NO_PUBKEY": _("Hint: Public key {capture} isn’t in your keyring. "
                               "You can try to import it from a trusted source, then verify this commit again."),
                "EXPKEYSIG": _("Key has expired: {capture}"),
            }
            foundTokens = set()

            for token, hint in tokenParsers.items():
                match = re.search(rf"^\[GNUPG:]\s+{token}($|\s+.+$)", driver.stderrScrollback(), re.M)
                if match:
                    foundTokens.add(token)
                    capture = match.group(1)
                    paras.append(hint.format(capture=f"<i>{escape(capture)}</i>"))

            if "VALIDSIG" in foundTokens and "EXPKEYSIG" in foundTokens:
                self.repoModel.gpgStatusCache[oid] = GpgStatus.Expired

            raise AbortTask(paragraphs(paras), details=driver.stderrScrollback())

        message = "<html>"
        message += _("GPG-signed commit {0} verified successfully.", prettyHash)

        match = re.search(r"^\[GNUPG:]\s+GOODSIG\s+.+$", driver.stderrScrollback(), re.M)
        if match:
            message += "<br><br><small>" + escape(match.group(0))

        qmb = asyncMessageBox(self.parentWidget(), "information", self.name(), message)
        qmb.setDetailedText(driver.stderrScrollback())
        yield from self.flowDialog(qmb)


class NewIgnorePattern(RepoTask):
    def flow(self, seedPath: str):
        dlg = IgnorePatternDialog(seedPath, self.parentWidget())
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        yield from self.flowDialog(dlg)

        pattern = dlg.pattern
        if not pattern:
            raise AbortTask()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        relativeExcludePath = dlg.excludePath
        excludePath = Path(self.repo.in_workdir(relativeExcludePath))

        # Read existing exclude text
        excludeText = ""
        if excludePath.exists():
            excludeText = excludePath.read_text("utf-8")
            if not excludeText.endswith("\n"):
                excludeText += "\n"

        excludeText += pattern + "\n"
        excludePath.write_text(excludeText, "utf-8")

        self.postStatus = _("Added to {file}: {pattern}", pattern=pattern, file=relativeExcludePath)

        # Jump to .gitignore
        if self.repo.is_in_workdir(str(excludePath)):
            self.jumpTo = NavLocator.inUnstaged(str(excludePath))
