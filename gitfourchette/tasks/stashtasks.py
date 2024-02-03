from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskEffects, TaskPrereqs
from gitfourchette.trash import Trash
from gitfourchette.toolbox import *
from gitfourchette.forms.stashdialog import StashDialog


def backupStash(repo: Repo, stashCommitId: Oid):
    trashFile = Trash.instance().newFile(repo.workdir, ext=".txt", originalPath="DELETED_STASH")

    if not trashFile:
        return

    text = F"""\
To recover this stash, paste the hash below into "Repo > Recall Lost Commit" in {qAppName()}:

{stashCommitId.hex}

----------------------------------------

Original stash message below:

{repo.peel_commit(stashCommitId).message}
"""

    with open(trashFile, 'wt', encoding="utf-8") as f:
        f.write(text)


class NewStash(RepoTask):
    def prereqs(self):
        # libgit2 will refuse to create a stash if there are conflicts (NoConflicts)
        # libgit2 will refuse to create a stash if there are no commits at all (NoUnborn)
        return TaskPrereqs.NoConflicts | TaskPrereqs.NoUnborn

    def effects(self):
        return TaskEffects.Workdir | TaskEffects.ShowWorkdir | TaskEffects.Refs

    def flow(self, paths: list[str] | None = None):
        status = self.repo.status(untracked_files="all", ignored=False)

        if not status:
            raise AbortTask(self.tr("There are no uncommitted changes to stash."), "information")

        # Prevent stashing any submodules
        with Benchmark("NewStash/Query submodules"):
            for submo in self.repo.listall_submodules():
                status.pop(submo, None)

        if not status:
            raise AbortTask(self.tr("There are no uncommitted changes to stash (submodules cannot be stashed)."), "information")

        dlg = StashDialog(status, paths, self.parentWidget())
        setWindowModal(dlg)
        dlg.show()
        # dlg.setMaximumHeight(dlg.height())
        yield from self.flowDialog(dlg)

        tickedFiles = dlg.tickedPaths()

        stashMessage = dlg.ui.messageEdit.text()
        keepIntact = not dlg.ui.cleanupCheckBox.isChecked()
        dlg.deleteLater()

        yield from self.flowEnterWorkerThread()
        self.repo.create_stash(stashMessage, paths=tickedFiles)
        if not keepIntact:
            self.repo.restore_files_from_head(tickedFiles)


class ApplyStash(RepoTask):
    def prereqs(self):
        # libgit2 will refuse to apply a stash if there are conflicts (NoConflicts)
        return TaskPrereqs.NoConflicts

    def effects(self):
        # Refs only change if the stash is deleted after a successful application.
        return TaskEffects.Workdir | TaskEffects.ShowWorkdir | TaskEffects.Refs

    def flow(self, stashCommitId: Oid, tickDelete=True):
        stashCommit: Commit = self.repo.peel_commit(stashCommitId)
        stashMessage = strip_stash_message(stashCommit.message)

        question = self.tr("Do you want to apply the changes stashed in {0} to your working directory?"
                           ).format(bquoe(stashMessage))

        qmb = asyncMessageBox(self.parentWidget(), 'question', self.name(), question,
                              QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                              deleteOnClose=False)

        def updateButtonText(ticked: bool):
            okButton = qmb.button(QMessageBox.StandardButton.Ok)
            okButton.setText(self.tr("&Apply && Delete") if ticked else self.tr("&Apply && Keep"))

        deleteCheckBox = QCheckBox(self.tr("&Delete the stash if it applies cleanly"), qmb)
        deleteCheckBox.clicked.connect(updateButtonText)
        deleteCheckBox.setChecked(tickDelete)
        qmb.setCheckBox(deleteCheckBox)
        updateButtonText(tickDelete)
        yield from self.flowDialog(qmb)

        deleteAfterApply = deleteCheckBox.isChecked()
        qmb.deleteLater()

        yield from self.flowEnterWorkerThread()
        self.repo.stash_apply_oid(stashCommitId)

        if self.repo.index.conflicts:
            yield from self.flowEnterUiThread()
            message = [self.tr("Applying the stash {0} has caused merge conflicts "
                               "because your files have diverged since they were stashed."
                               ).format(bquoe(stashMessage))]
            if deleteAfterApply:
                message.append(self.tr("The stash wasn’t deleted in case you need to re-apply it later."))
            showWarning(self.parentWidget(), self.tr("Conflicts caused by stash application"), paragraphs(message))
            return

        if deleteAfterApply:
            backupStash(self.repo, stashCommitId)
            self.repo.stash_drop_oid(stashCommitId)


class DropStash(RepoTask):
    def effects(self):
        return TaskEffects.Refs

    def flow(self, stashCommitId: Oid):
        stashCommit = self.repo.peel_commit(stashCommitId)
        stashMessage = strip_stash_message(stashCommit.message)
        yield from self.flowConfirm(
            text=self.tr("Really delete stash {0}?").format(bquoe(stashMessage)),
            verb=self.tr("Delete stash"),
            buttonIcon=QStyle.StandardPixmap.SP_DialogDiscardButton)

        yield from self.flowEnterWorkerThread()
        backupStash(self.repo, stashCommitId)
        self.repo.stash_drop_oid(stashCommitId)
