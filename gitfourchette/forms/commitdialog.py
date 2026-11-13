# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import trtables
from gitfourchette.forms.signatureform import SignatureOverride
from gitfourchette.forms.ui_commitdialog import Ui_CommitDialog
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.toolbox import *


class CommitDialog(QDialog):
    InfoIconSize = 16

    @property
    def acceptButton(self) -> QPushButton:
        return self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok)

    def __init__(
            self,
            initialText: str,
            authorSignature: Signature,
            committerSignature: Signature,
            amendingCommitHash: str,
            detachedHead: bool,
            repositoryState: RepositoryState,
            emptyCommit: bool,
            gpgFlag: bool,
            gpgKey: str,
            hooks: list[str],
            parent: QWidget):
        super().__init__(parent)

        self.originalAuthorSignature = authorSignature
        self.originalCommitterSignature = committerSignature
        self.isAmending = bool(amendingCommitHash)

        self.ui = Ui_CommitDialog()
        self.ui.setupUi(self)
        self.ui.gpg.setup(gpgFlag, gpgKey)
        self.ui.hookButton.setup(hooks)

        for button in (self.ui.gpg, self.ui.signoffButton, self.ui.hookButton):
            button.setAutoRaise(True)

        self.ui.signatureButton.setIcon(stockIcon("view-visible"))

        self.ui.signature.setSignature(authorSignature)
        self.ui.signature.signatureChanged.connect(self.refreshSignaturePreview)

        # Make summary text edit font larger
        tweakWidgetFont(self.ui.summaryEditor, 130)

        if amendingCommitHash:
            prompt = _("Amend commit message")
            buttonCaption = _("A&mend")
            self.setWindowTitle(_("Amend Commit {0}", amendingCommitHash))
        else:
            prompt = _("Enter commit summary")
            buttonCaption = _("Co&mmit")
            self.setWindowTitle(englishTitleCase(_("New commit")))

        infoMessage = self._infoMessage(amendingCommitHash, detachedHead, repositoryState, emptyCommit)
        self.ui.infoBox.setVisible(bool(infoMessage))
        self.ui.infoText.setText(infoMessage)
        self.ui.infoIcon.setPixmap(stockIcon("SP_MessageBoxInformation").pixmap(self.InfoIconSize))
        self.ui.infoIcon.setMaximumWidth(self.InfoIconSize)

        self.acceptButton.setText(buttonCaption)
        self.ui.summaryEditor.setPlaceholderText(prompt)

        self.ui.counterLabel.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.ui.counterLabel.setMinimumWidth(self.ui.counterLabel.fontMetrics().horizontalAdvance('000'))
        self.ui.counterLabel.setMaximumWidth(self.ui.counterLabel.minimumWidth())

        self.validator = ValidatorMultiplexer(self)
        self.validator.setGatedWidgets(self.ui.buttonBox.button(QDialogButtonBox.StandardButton.Ok))
        self.validator.connectInput(self.ui.summaryEditor, self.hasNonBlankSummary, showError=False)
        self.ui.signature.installValidator(self.validator)

        self.ui.summaryEditor.textEdited.connect(self.sanitizeLineBreaksInSummary)
        self.ui.summaryEditor.textChanged.connect(self.updateCounterLabel)
        self.ui.revealSignature.checkStateChanged.connect(lambda: self.validator.run())
        self.ui.revealSignature.checkStateChanged.connect(lambda: self.refreshSignaturePreview())

        split = initialText.split('\n', 1)
        if len(split) >= 1:
            self.ui.summaryEditor.setText(split[0].strip())
        if len(split) >= 2:
            self.ui.descriptionEditor.setPlainText(split[1].strip())

        self.ui.revealSignature.setChecked(False)
        self.ui.signatureBox.setVisible(False)

        self.updateCounterLabel()
        self.validator.run()
        self.refreshSignaturePreview()

        # Focus on summary editor before showing
        self.ui.summaryEditor.setFocus()

        # Pack the layout
        packDialog(self)
        self.resize(self.width(), self.minimumSizeHint().height())

    def sanitizeLineBreaksInSummary(self, text: str):
        if '\n' not in text:
            return

        # Walk back undo stack to get rid of the operation that inserted linebreaks.
        # This way, this callback won't run again when the user presses Ctrl+Z.
        with QSignalBlockerContext(self.ui.summaryEditor):
            self.ui.summaryEditor.undo()

        summary, details = text.split('\n', 1)
        summary = summary.rstrip()
        details = details.lstrip()

        # This pushes the new text to the QLineEdit's undo stack
        # (whereas setText clears the undo stack).
        self.ui.summaryEditor.selectAll()
        self.ui.summaryEditor.insert(summary)
        self.ui.descriptionEditor.selectAll()
        self.ui.descriptionEditor.insertPlainText(details)

    def updateCounterLabel(self):
        text = self.ui.summaryEditor.text()
        self.ui.counterLabel.setText(str(len(text)))

    def hasNonBlankSummary(self, text):
        if bool(text.strip()):
            return ""
        else:
            return _("Cannot be empty.")

    def getFullMessage(self) -> str:
        summary = self.ui.summaryEditor.text()
        details = self.ui.descriptionEditor.toPlainText()

        hasDetails = bool(details.strip())

        if not hasDetails:
            message = summary
        else:
            message = f"{summary}\n\n{details}"

        if not message:
            return ""

        # Vanilla git enforces a final newline in commit messages whether we want it or not,
        # so just add one ourselves so that we get the same outcome with libgit2.
        if not message.endswith("\n"):
            message += "\n"

        return message

    def getOverriddenSignatureKind(self):
        if self.ui.revealSignature.isChecked() and self.ui.signature.getSignature():
            return self.ui.signature.replaceWhat()
        return SignatureOverride.Nothing

    def getOverriddenAuthorSignature(self):
        if self.getOverriddenSignatureKind() in [SignatureOverride.Author, SignatureOverride.Both]:
            return self.ui.signature.getSignature()
        else:
            return None

    def getOverriddenCommitterSignature(self):
        if self.getOverriddenSignatureKind() in [SignatureOverride.Committer, SignatureOverride.Both]:
            return self.ui.signature.getSignature()
        else:
            return None

    def refreshSignaturePreview(self):
        def formatSignatureForToolTip(sig: Signature, showDate: bool):
            if sig is None:
                return "???"
            text = f"{escape(sig.name)} &lt;{escape(sig.email)}&gt;"
            if showDate:
                text += f"<br><small>{escape(signatureDateFormat(sig))}</small>"
            return text

        overriddenAuthor = self.getOverriddenAuthorSignature()
        overriddenCommitter = self.getOverriddenCommitterSignature()
        author = overriddenAuthor or self.originalAuthorSignature
        committer = overriddenCommitter or self.originalCommitterSignature

        # Git dates a signature that isn't overridden when it makes the commit,
        # so we can't show that date yet. Amending keeps the original author date.
        showAuthorDate = overriddenAuthor is not None or self.isAmending
        showCommitterDate = overriddenCommitter is not None

        muted = mutedToolTipColorHex()

        tt = "<p style='white-space: pre'>"
        tt += f"<span style='color: {muted}'>" + _("Authored by:") + "</span> "
        tt += formatSignatureForToolTip(author, showAuthorDate)
        if not signatures_equalish(author, self.originalAuthorSignature):
            tt += "\n<span style='font-weight: bold'>" + _("(overridden manually)") + "</span>"

        tt += f"\n\n<span style='color: {muted}'>" + _("Committed by:") + "</span> "
        tt += formatSignatureForToolTip(committer, showCommitterDate)
        if not signatures_equalish(committer, self.originalCommitterSignature):
            tt += "\n<span style='font-weight: bold'>" + _("(overridden manually)") + "</span>"

        self.ui.signatureButton.setToolTip(tt)
        self.ui.revealSignature.setToolTip(tt)

    @classmethod
    def _infoMessage(cls, amendingCommitHash: str, detachedHead: bool,
                     repositoryState: RepositoryState, emptyCommit: bool):
        info = ""
        isRebasing = repositoryState == RepositoryState.REBASE_INTERACTIVE

        # Default message during a rebase (can be replaced by "amending" or
        # "inserting an empty commit")
        if isRebasing:
            info = _("Inserting a new commit.")

        if repositoryState == RepositoryState.MERGE:
            info = _("This commit will conclude the merge.")
        elif repositoryState == RepositoryState.CHERRYPICK:
            info = _("This commit will conclude the cherry-pick.")
        elif repositoryState == RepositoryState.REVERT:
            info = _("This commit will conclude the revert.")
        elif amendingCommitHash and emptyCommit:
            info = _("Amending commit {0} without changing its contents (no staged changes).",
                        lquo(amendingCommitHash))
        elif amendingCommitHash:
            info = _("Amending commit {0}.", lquo(amendingCommitHash))
        elif detachedHead and not isRebasing:
            info = _("<b>Detached HEAD</b> – You are not in any branch! "
                        "You should create a branch to keep track of your commit.")
        elif emptyCommit and not isRebasing:
            info = _("Creating an empty commit (no staged changes).")
        elif emptyCommit and isRebasing:
            info = _("Inserting an empty commit (no staged changes).")

        # Add "Rebasing" prefix during a rebase
        if isRebasing:
            info = f"<b>{trtables.enum(RepositoryState.REBASE)}</b> – {info}"

        return info
