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
from gitfourchette.repomodel import UC_FAKEID, BEGIN_SSH_SIGNATURE, GpgStatus
from gitfourchette.tasks import TaskEffects
from gitfourchette.tasks.repotask import RepoTask, AbortTask
from gitfourchette.toolbox import *
from gitfourchette.trtables import TrTables

logger = logging.getLogger(__name__)


class EditRepoSettings(RepoTask):
    def flow(self):
        repo = self.repo
        repoPrefs = self.repoModel.prefs

        dlg = RepoSettingsDialog(repo, repoPrefs, self.parentWidget())
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        yield from self.flowDialog(dlg)

        localName, localEmail = dlg.localIdentity()
        nickname = dlg.ui.nicknameEdit.text()
        customKeyFile = dlg.ui.keyFilePicker.privateKeyPath()
        dlg.deleteLater()

        configObject = repo.config
        for key, value in [("user.name", localName), ("user.email", localEmail)]:
            if value:
                configObject[key] = value
            else:
                with suppress(KeyError):
                    del configObject[key]
        repo.scrub_empty_config_section("user")

        if customKeyFile != repoPrefs.customKeyFile:
            repoPrefs.customKeyFile = customKeyFile
            repoPrefs.setDirty()

        if nickname != settings.history.getRepoNickname(self.repo.workdir, strict=True):
            settings.history.setRepoNickname(self.repo.workdir, nickname)
            settings.history.setDirty()
            self.rw.nameChange.emit()

        repoPrefs.write()


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
        gpgStatus, gpgKeyInfo = self.repoModel.getCachedGpgStatus(commit)
        if gpgStatus == GpgStatus.Unsigned:
            gpgMarkup = tagify(_("(not signed)"), "<i>")
        elif gpgKeyInfo:
            gpgMarkup = f"{gpgStatus.iconHtml()} {TrTables.enum(gpgStatus)}<br><small>{escape(gpgKeyInfo)}</small>"
        else:
            gpgMarkup = f"{gpgStatus.iconHtml()} {TrTables.enum(gpgStatus)}"

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
    _GnupgLinePattern = re.compile(r"^\[GNUPG:]\s+(\w+)\s*(.*)$")

    _GnupgStatusTable = {
        # The order in this table is significant for parseGnupgVerification
        "NO_PUBKEY" : GpgStatus.MissingKey,
        "GOODSIG"   : GpgStatus.GoodUntrusted,
        "EXPSIG"    : GpgStatus.ExpiredSig,
        "EXPKEYSIG" : GpgStatus.ExpiredKey,
        "REVKEYSIG" : GpgStatus.RevokedKey,
        "KEYREVOKED": GpgStatus.RevokedKey,
        "BADSIG"    : GpgStatus.Bad,
    }

    _SshGoodTrustedPattern = re.compile(r'^Good "git" signature for (\S+) with \S+ key (.+)')
    _SshGoodUntrustedPattern = re.compile(r'^Good "git" signature with \S+ key (.+)')

    def flow(self, oid: Oid, dialogParent: QWidget | None = None):
        commit = self.repo.peel_commit(oid)

        gpgSignature, _gpgPayload = commit.gpg_signature
        if not gpgSignature:
            raise AbortTask(_("Commit {0} is not signed, so it cannot be verified.", tquo(shortHash(oid))))

        isSsh = gpgSignature.startswith(BEGIN_SSH_SIGNATURE)

        driver = yield from self.flowCallGit("verify-commit", "--raw", str(oid), autoFail=False)
        fail = driver.exitCode() != 0
        stderr = driver.stderrScrollback()

        status, keyInfo = self.parseScrollback(stderr, isSsh)

        # Update gpg status cache
        self.repoModel.cacheGpgStatus(oid, status, keyInfo)

        paras = [f"{stockIconImgTag(status.iconName())} {TrTables.enum(status)}"]

        if status == GpgStatus.MissingKey:
            paras.append(_("Hint: Public key {0} isn’t in your GPG keyring. "
                           "You can try to import it from a trusted source, "
                           "then verify this commit again.", f"<em>{escape(keyInfo)}</em>"))

        if keyInfo:
            paras.append(f"<i>{escape(keyInfo)}</i>")

        title = _("Verify signature in commit {0}", tquo(shortHash(oid)))
        mbIcon = ("information" if not fail else
                  "critical" if status in [GpgStatus.RevokedKey, GpgStatus.Bad] else
                  "warning")
        qmb = asyncMessageBox(self.parentWidget(), mbIcon, title, paragraphs(paras),
                              QMessageBox.StandardButton.Ok)# | QMessageBox.StandardButton.Help)
        qmb.setDetailedText(driver.stderrScrollback())

        if keyInfo:
            hintButton = QPushButton(qmb)
            qmb.addButton(hintButton, QMessageBox.ButtonRole.HelpRole)
            hintButton.setText(_("Copy &Key ID"))
            hintButton.clicked.disconnect()  # Qt internally wires the button to close the dialog; undo that.

            def onCopyClicked():
                QApplication.clipboard().setText(keyInfo)
                QToolTip.showText(QCursor.pos(), _("{0} copied to clipboard.", tquo(keyInfo)))
            hintButton.clicked.connect(onCopyClicked)

            # Adding an extra button seems to remove the OK button's Escape key mapping
            qmb.setEscapeButton(qmb.button(QMessageBox.StandardButton.Ok))

        yield from self.flowDialog(qmb)

    @classmethod
    def parseScrollback(cls, scrollback: str, isSsh: bool) -> tuple[GpgStatus, str]:
        if isSsh:
            return cls.parseSshVerification(scrollback)
        else:
            return cls.parseGnupgVerification(scrollback)

    @classmethod
    def parseGnupgVerification(cls, scrollback: str) -> tuple[GpgStatus, str]:
        # https://github.com/gpg/gnupg/blob/master/doc/DETAILS#general-status-codes
        # https://github.com/git/git/blob/v2.51.0/gpg-interface.c#L184

        report = {}
        for line in scrollback.splitlines():
            match = cls._GnupgLinePattern.match(line)
            if not match:
                continue
            token = match.group(1)
            blurb = match.group(2)
            report[token] = blurb

        # Find the most significant status.
        # The order of the keys in _GnupgStatusTable is significant!
        try:
            status = next(status
                          for token, status in cls._GnupgStatusTable.items()
                          if token in report)
        except StopIteration:
            status = GpgStatus.CantCheck

        # Bump GoodUntrusted to GoodTrusted if we trust this
        if status == GpgStatus.GoodUntrusted and ("TRUST_ULTIMATE" in report) or ("TRUST_FULLY" in report):
            status = GpgStatus.GoodTrusted

        # Try to extract a key ID or fingerprint for informative purposes
        keyInfo = ""
        for token in cls._GnupgStatusTable:
            keyInfo = report.get(token, "")
            if keyInfo:
                break

        return status, keyInfo

    @classmethod
    def parseSshVerification(cls, scrollback: str) -> tuple[GpgStatus, str]:
        lines = scrollback.splitlines()

        if not lines:
            return GpgStatus.CantCheck, ""

        match = cls._SshGoodTrustedPattern.match(lines[0])
        if match:
            assert "No principal matched." not in lines
            keyInfo = f"{match.group(1)} {match.group(2)}"
            return GpgStatus.GoodTrusted, keyInfo

        match = cls._SshGoodUntrustedPattern.match(lines[0])
        if match:
            assert "No principal matched." in lines
            keyInfo = _("(Not found in SSH allowed signers file)") + " " + match.group(1)
            return GpgStatus.GoodUntrusted, keyInfo

        if lines[0].startswith("Could not verify signature."):
            return GpgStatus.Bad, ""

        return GpgStatus.CantCheck, ""


class VerifyGpgQueue(RepoTask):
    def isFreelyInterruptible(self) -> bool:
        return True

    def flow(self):
        self.effects = TaskEffects.Nothing
        graphView = self.rw.graphView
        repoModel = self.repoModel

        while repoModel.gpgVerifyQueue:
            oid = repoModel.gpgVerifyQueue.pop()

            currentStatus, keyInfo = repoModel.gpgStatusCache.get(oid, (GpgStatus.Unsigned, ""))
            if currentStatus != GpgStatus.Pending:
                continue

            try:
                visibleIndex = self.visibleIndex(oid)
            except LookupError:
                continue

            try:
                driver = yield from self.flowCallGit("verify-commit", "--raw", str(oid), autoFail=False)
            except AbortTask:
                # This task may be issued repeatedly.
                # Don't let AbortTask spam dialog boxes if git failed to start.
                repoModel.cacheGpgStatus(oid, GpgStatus.ProcessError)
                graphView.update(visibleIndex)
                continue

            stderr = driver.stderrScrollback()
            isSsh = keyInfo == "ssh"

            status, keyInfo = VerifyGpgSignature.parseScrollback(stderr, isSsh)
            repoModel.cacheGpgStatus(oid, status, keyInfo)
            graphView.update(visibleIndex)

    def visibleIndex(self, oid: Oid) -> QModelIndex:
        graphView = self.rw.graphView

        index = graphView.getFilterIndexForCommit(oid)  # raises SelectCommitError (LookupError) if hidden
        assert index.isValid()

        top = graphView.indexAt(QPoint_zero)
        bottom = graphView.indexAt(graphView.rect().bottomLeft())

        topRow = top.row() if top.isValid() else 0
        bottomRow = bottom.row() if bottom.isValid() else 0x3FFFFFFF

        if topRow <= index.row() <= bottomRow:
            return index

        raise IndexError()


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
