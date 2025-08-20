# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette import colors
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
            parent: QWidget):
        super().__init__(parent)

        self.originalAuthorSignature = authorSignature
        self.originalCommitterSignature = committerSignature

        self.ui = Ui_CommitDialog()
        self.ui.setupUi(self)

        self.setupGpgControls(gpgFlag, gpgKey)

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
            self.setWindowTitle(_p("verb", "Commit"))

        warning = ""
        if repositoryState == RepositoryState.MERGE:
            warning = _("This commit will conclude the merge.")
        elif repositoryState == RepositoryState.CHERRYPICK:
            warning = _("This commit will conclude the cherry-pick.")
        elif repositoryState == RepositoryState.REVERT:
            warning = _("This commit will conclude the revert.")
        elif amendingCommitHash:
            warning = _("You are amending commit {0}.", lquo(amendingCommitHash))
        elif detachedHead:
            warning = _("<b>Detached HEAD</b> – You are not in any branch! "
                              "You should create a branch to keep track of your commit.")
        elif emptyCommit:
            warning = _("You are creating an empty commit (no staged changes).")

        self.ui.infoBox.setVisible(bool(warning))
        self.ui.infoText.setText(warning)
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

    def setupGpgControls(self, want: bool, key: str):
        hasKey = bool(key)

        if want and key:
            icon = stockIcon("gpgkey", f"gray={colors.olive.name()}")
            tip = _("This commit will be GPG-signed with key {yourkey}.")
        elif not want and key:
            icon = stockIcon("gpgkey")
            tip = _("Your signing key is set ({yourkey}), but your configuration "
                    "does not call for GPG-signing automatically.")
        elif want and not key:
            bg = self.palette().window().color().name()
            fg = self.palette().text().color().name()
            icon = stockIcon("gpgkey-what", f"black={fg} white={bg}")
            tip = _("Git is configured to GPG-sign commits ({flagconf}), "
                    "but your signing key ({keyconf}) is not set.")
        else:
            icon = stockIcon("gpgkey-no")
            tip = _("This commit will not be GPG-signed because your Git configuration doesn’t set {keyconf}.")

        tip = tip.format(flagconf=btag("commit.gpgSign"), keyconf=btag("user.signingKey"), yourkey=escape(key))

        button = self.ui.gpgButton
        label = self.ui.gpgLabel
        check = self.ui.gpgCheckBox

        button.setIcon(icon)
        button.setToolTip(tip)

        label.setToolTip(tip)
        label.setVisible(not key)

        check.setToolTip(tip)
        check.setVisible(hasKey)
        check.setEnabled(hasKey)
        check.setChecked(hasKey and want)
        check.toggled.connect(lambda t: button.setIcon(stockIcon("gpgkey", f"gray={colors.olive.name() if t else 'gray'}")))

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
        def formatSignatureForToolTip(sig: Signature):
            if sig is None:
                return "???"
            dateText = signatureDateFormat(sig)
            return f"{escape(sig.name)} &lt;{escape(sig.email)}&gt;<br><small>{escape(dateText)}</small>"

        author = self.getOverriddenAuthorSignature() or self.originalAuthorSignature
        committer = self.getOverriddenCommitterSignature() or self.originalCommitterSignature

        muted = mutedToolTipColorHex()

        tt = "<p style='white-space: pre'>"
        tt += f"<span style='color: {muted}'>" + _("Authored by:") + "</span> "
        tt += formatSignatureForToolTip(author)
        if not signatures_equalish(author, self.originalAuthorSignature):
            tt += "\n<span style='font-weight: bold'>" + _("(overridden manually)") + "</span>"

        tt += f"\n\n<span style='color: {muted}'>" + _("Committed by:") + "</span> "
        tt += formatSignatureForToolTip(committer)
        if not signatures_equalish(committer, self.originalCommitterSignature):
            tt += "\n<span style='font-weight: bold'>" + _("(overridden manually)") + "</span>"

        self.ui.signatureButton.setToolTip(tt)
        self.ui.revealSignature.setToolTip(tt)

    def explicitNoGpgSign(self):
        check = self.ui.gpgCheckBox
        return check.isEnabled() and not check.isChecked()

    def explicitGpgSign(self):
        check = self.ui.gpgCheckBox
        return check.isEnabled() and check.isChecked()
