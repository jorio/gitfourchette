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
            recentMessages: list[str],
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

        # For each replaceMessage call: the editors it changed and the text they had afterwards,
        # so that a single Ctrl+Z can undo the whole call
        self.linkedUndos: list[tuple[list[QLineEdit | QPlainTextEdit], str, str]] = []
        self.ui.summaryEditor.installEventFilter(self)
        self.ui.descriptionEditor.installEventFilter(self)

        self.setUpRecentMessages(recentMessages)

        summary, details = splitMessage(initialText)
        self.ui.summaryEditor.setText(summary)
        self.ui.descriptionEditor.setPlainText(details)

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

    def setUpRecentMessages(self, messages: list[str]):
        editor = self.ui.summaryEditor

        actions = []
        for message in messages:
            summary, _junk = messageSummary(message)
            caption = elide(summary, Qt.TextElideMode.ElideRight, ems=50)
            actions.append(ActionDef(escamp(caption), lambda m=message: self.useRecentMessage(m)))
        self.recentMessagesMenu = ActionDef.makeQMenu(editor, actions)

        # Pop up the menu ourselves: Qt 5 ignores a menu set on a QLineEdit action
        action = editor.addAction(stockIcon("go-older", "#d1812f=gray"), QLineEdit.ActionPosition.TrailingPosition)
        action.setText(_("Reuse a recent commit message"))
        action.setShortcut(QKeySequence("Alt+Down"))  # Like a combo box; the icon can't take keyboard focus
        action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        action.setToolTip(appendShortcutToToolTipText(action.text(), action.shortcut()))
        action.setVisible(bool(messages))
        action.triggered.connect(lambda: self.recentMessagesMenu.popup(editor.mapToGlobal(editor.rect().bottomLeft())))
        actionButton = next(b for b in editor.findChildren(QToolButton) if b.defaultAction() is action)
        actionButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recentMessagesAction = action

    def useRecentMessage(self, message: str):
        summary, details = splitMessage(message)
        self.replaceMessage(summary, details)
        self.ui.summaryEditor.setFocus()

    def replaceMessage(self, summary: str, details: str):
        if not self.isAtLinkedUndo():
            self.linkedUndos.clear()

        # This pushes the new text to each editor's undo stack
        # (whereas setText clears the undo stack).
        # Skip unchanged editors: they'd get an undo step that does nothing.
        editedEditors: list[QLineEdit | QPlainTextEdit] = []
        if summary != self.ui.summaryEditor.text():
            self.ui.summaryEditor.selectAll()
            self.ui.summaryEditor.insert(summary)  # Replacing the selection ends the undo step before it
            # Keep typing after it out of the same undo step, like QLineEdit's own paste does.
            # Moving the cursor is the public way to end an undo step.
            self.ui.summaryEditor.home(False)
            self.ui.summaryEditor.end(False)
            editedEditors.append(self.ui.summaryEditor)
        if details != self.ui.descriptionEditor.toPlainText():
            self.ui.descriptionEditor.selectAll()
            self.ui.descriptionEditor.insertPlainText(details)
            editedEditors.append(self.ui.descriptionEditor)

        if editedEditors:
            self.linkedUndos.append((editedEditors, self.ui.summaryEditor.text(), self.ui.descriptionEditor.toPlainText()))
            self.markLinkedUndo()

    def markLinkedUndo(self):
        # The "modified" flags compare each editor's undo position with this mark (neither editor reads them).
        # Clearing the description's flag also stops QTextDocument from merging further typing into the last undo step.
        self.ui.summaryEditor.setModified(False)
        self.ui.descriptionEditor.document().setModified(False)

    def isAtLinkedUndo(self) -> bool:
        """ Whether neither editor's undo stack has moved since the last replaceMessage call. """
        if not self.linkedUndos:
            return False
        _editors, summary, details = self.linkedUndos[-1]
        # Also compare the text: after an undo, new edits in a QLineEdit can bring its undo position back to the mark.
        return (not self.ui.summaryEditor.isModified()
                and not self.ui.descriptionEditor.document().isModified()
                and summary == self.ui.summaryEditor.text()
                and details == self.ui.descriptionEditor.toPlainText())

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (isinstance(event, QKeyEvent)
                and event.type() == QEvent.Type.KeyPress
                and event.matches(QKeySequence.StandardKey.Undo)
                and self.isAtLinkedUndo()):
            editors, _summary, _details = self.linkedUndos.pop()
            for editor in editors:
                editor.undo()
            self.markLinkedUndo()  # We're now right after the previous replaceMessage call, if any
            return True
        return super().eventFilter(watched, event)

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
        self.replaceMessage(summary, details)

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
