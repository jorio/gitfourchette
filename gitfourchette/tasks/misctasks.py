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
            gpgMarkup = tagify(_("(not signed)"), "<i>")
        else:
            gpgMarkup = gpg.iconHtml() + " " + _("Signed; {0}", TrTables.enum(gpg))

        # Assemble table rows
        table = tableRow(_("Hash"), commit.id)
        table += tableRow(parentTitle, parentMarkup)
        table += tableRow(_("Author"), self.formatSignature(commit.author))
        table += tableRow(_("Committer"), committerMarkup)
        table += tableRow(_("Signature"), gpgMarkup)

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
    GnupgLinePattern = re.compile(r"^\[GNUPG:]\s+(\w+)(|\s+.+)$")

    GnupgStatusTable = {
        "GOODSIG"   : GpgStatus.GOODSIG,
        "EXPSIG"    : GpgStatus.EXPSIG,
        "EXPKEYSIG" : GpgStatus.EXPKEYSIG,
        "REVKEYSIG" : GpgStatus.REVKEYSIG,
        "BADSIG"    : GpgStatus.BADSIG,
    }

    def flow(self, oid: Oid, dialogParent: QWidget | None = None):
        commit = self.repo.peel_commit(oid)

        gpgSignature, _gpgPayload = commit.gpg_signature
        if not gpgSignature:
            raise AbortTask(_("Commit {0} is not signed, so it cannot be verified.", tquo(shortHash(oid))))

        driver = yield from self.flowCallGit("verify-commit", "--raw", str(oid), autoFail=False)
        fail = driver.exitCode() != 0

        status, report = self.parseGpgScrollback(driver.stderrScrollback())

        # Update gpg status cache
        self.repoModel.gpgStatusCache[oid] = status

        paras = [f"{stockIconImgTag(status.iconName())} {TrTables.enum(status)}"]

        keyId = ""
        if "NO_PUBKEY" in report:
            keyId = report["NO_PUBKEY"].strip()
            paras.append(_("Hint: Public key {0} isn’t in your GPG keyring. "
                           "You can try to import it from a trusted source, "
                           "then verify this commit again.", f"<em>{escape(keyId)}</em>"))

        with suppress(StopIteration):
            interestingToken = next(k for k in self.GnupgStatusTable if k in report)
            paras.append(f"<small>{escape(report[interestingToken])}</small>")

        title = _("Verify signature in commit {0}", tquo(shortHash(oid)))
        mbIcon = ("information" if not fail else
                  "critical" if "BADSIG" in report else
                  "warning")
        qmb = asyncMessageBox(self.parentWidget(), mbIcon, title, paragraphs(paras),
                              QMessageBox.StandardButton.Ok)# | QMessageBox.StandardButton.Help)
        qmb.setDetailedText(driver.stderrScrollback())

        if keyId:
            hintButton = QPushButton(qmb)
            qmb.addButton(hintButton, QMessageBox.ButtonRole.HelpRole)
            hintButton.setText(_("Copy &Key ID"))
            hintButton.clicked.disconnect()  # Qt internally wires the button to close the dialog; undo that.

            def onCopyClicked():
                QApplication.clipboard().setText(keyId)
                QToolTip.showText(QCursor.pos(), _("{0} copied to clipboard.", tquo(keyId)))
            hintButton.clicked.connect(onCopyClicked)


        yield from self.flowDialog(qmb)

    @classmethod
    def parseGpgScrollback(cls, scrollback: str):
        # https://github.com/gpg/gnupg/blob/master/doc/DETAILS#general-status-codes
        # https://github.com/git/git/blob/v2.51.0/gpg-interface.c#L184
        # Warning: this returns Unverified for SSH signatures!

        report = {}
        for line in scrollback.splitlines():
            match = cls.GnupgLinePattern.match(line)
            if not match:
                continue
            token = match.group(1)
            blurb = match.group(2)
            report[token] = blurb

        try:
            status = next(value for name, value in cls.GnupgStatusTable.items() if name in report)
        except StopIteration:
            status = GpgStatus.Unverified

        if "KEYREVOKED" in report:
            status = GpgStatus.REVKEYSIG

        return status, report


class VerifyGpgQueue(RepoTask):
    def isFreelyInterruptible(self) -> bool:
        return True

    def flow(self):
        self.effects = TaskEffects.Nothing
        graphView = self.rw.graphView
        repoModel = self.repoModel

        while repoModel.gpgVerificationQueue:
            oid = repoModel.gpgVerificationQueue.pop()

            currentStatus = repoModel.gpgStatusCache.get(oid, GpgStatus.Unsigned)
            if currentStatus != GpgStatus.VerifyPending:
                continue

            visibleIndex = self.visibleIndex(oid)
            if visibleIndex is None:
                repoModel.gpgStatusCache[oid] = GpgStatus.VerifyPending
                continue

            try:
                driver = yield from self.flowCallGit("verify-commit", "--raw", str(oid), autoFail=False)
            except AbortTask:
                # This task may be issued repeatedly.
                # Don't let AbortTask spam dialog boxes if git failed to start.
                repoModel.gpgStatusCache[oid] = GpgStatus.ProcessError
                graphView.update(visibleIndex)
                continue

            stderr = driver.stderrScrollback()

            status, report = VerifyGpgSignature.parseGpgScrollback(stderr)
            repoModel.gpgStatusCache[oid] = status
            graphView.update(visibleIndex)

    def visibleIndex(self, oid: Oid):
        from gitfourchette.graphview.graphview import GraphView

        graphView = self.rw.graphView

        with suppress(GraphView.SelectCommitError):
            index = graphView.getFilterIndexForCommit(oid)

        if not index.isValid():
            return None

        top = graphView.indexAt(QPoint_zero)
        bottom = graphView.indexAt(graphView.rect().bottomLeft())

        topRow = top.row() if top.isValid() else 0
        bottomRow = bottom.row() if bottom.isValid() else 0x3FFFFFFF

        if topRow <= index.row() <= bottomRow:
            return index

        return None


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
