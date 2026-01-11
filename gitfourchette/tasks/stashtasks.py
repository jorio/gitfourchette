# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.forms.stashdialog import StashDialog
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskEffects, TaskPrereqs
from gitfourchette.toolbox import *
from gitfourchette.trash import Trash


def backupStash(repo: Repo, stashCommitId: Oid):
    trashFile = Trash.instance().newFile(repo.workdir, ext=".txt", originalPath="DELETED_STASH")

    if not trashFile:
        return

    text = F"""\
To recover this stash, paste the hash below into "Repo > Recall Lost Commit" in {qAppName()}:

{stashCommitId}

----------------------------------------

Original stash message below:

{repo.peel_commit(stashCommitId).message}
"""

    with open(trashFile, "w", encoding="utf-8") as f:
        f.write(text)


class NewStash(RepoTask):
    def prereqs(self):
        # libgit2 will refuse to create a stash if there are conflicts (NoConflicts)
        # libgit2 will refuse to create a stash if there are no commits at all (NoUnborn)
        return TaskPrereqs.NoConflicts | TaskPrereqs.NoUnborn

    def flow(self, paths: list[str] | None = None):
        status = self.repo.status(untracked_files="all", ignored=False)

        if not status:
            raise AbortTask(_("There are no uncommitted changes to stash."), "information")

        # Prevent stashing any submodules
        with Benchmark("Query submodules"):
            for submodulePath in self.repo.listall_submodules_fast():
                status.pop(submodulePath, None)

        if not status:
            raise AbortTask(_("There are no uncommitted changes to stash (submodules cannot be stashed)."), "information")

        dlg = StashDialog(status, paths or [], self.parentWidget())
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.show()
        yield from self.flowDialog(dlg)

        tickedFiles = dlg.tickedPaths()

        stashMessage = dlg.ui.messageEdit.text()
        keepIntact = dlg.ui.keepCheckBox.isChecked()
        dlg.deleteLater()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Refs

        self.repo.create_stash(stashMessage, paths=tickedFiles)

        if not keepIntact:
            self.effects |= TaskEffects.Workdir
            self.repo.restore_files_from_head(tickedFiles)

        self.postStatus = _n("File stashed.", "{n} files stashed.", len(tickedFiles))


class ApplyStash(RepoTask):
    def prereqs(self):
        # libgit2 will refuse to apply a stash if there are conflicts (NoConflicts)
        return TaskPrereqs.NoConflicts | TaskPrereqs.NoStagedChanges

    def flow(self, stashCommitId: Oid, tickDelete=True):
        stashCommit: Commit = self.repo.peel_commit(stashCommitId)
        stashMessage = strip_stash_message(stashCommit.message)

        question = _("Do you want to apply the changes stashed in {0} "
                     "to your working directory?", bquoe(stashMessage))

        qmb = asyncMessageBox(self.parentWidget(), 'question', self.name(), question,
                              QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                              deleteOnClose=False)

        def updateButtonText(ticked: bool):
            okButton = qmb.button(QMessageBox.StandardButton.Ok)
            okButton.setText(_("&Apply && Delete") if ticked else _("&Apply && Keep"))

        deleteCheckBox = QCheckBox(_("&Delete the stash if it applies cleanly"), qmb)
        deleteCheckBox.clicked.connect(updateButtonText)
        deleteCheckBox.setChecked(tickDelete)
        qmb.setCheckBox(deleteCheckBox)
        updateButtonText(tickDelete)
        yield from self.flowDialog(qmb)

        deleteAfterApply = deleteCheckBox.isChecked()
        qmb.deleteLater()

        self.jumpTo = NavLocator.inWorkdir()
        self.effects |= TaskEffects.Workdir

        if deleteAfterApply:
            self.effects |= TaskEffects.Refs
            backupStash(self.repo, stashCommitId)

        # Although 'git stash apply stash@{<FULL_COMMIT_ID>}' works fine,
        # 'git stash pop' and 'drop' won't delete the stash if we pass the full
        # commit id. So, use a stash number instead.
        stashIndex = self.repo.find_stash_index(stashCommitId)
        popOrApply = "pop" if deleteAfterApply else "apply"

        driver = yield from self.flowCallGit("stash", popOrApply, str(stashIndex), autoFail=False)

        self.repo.refresh_index()
        anyConflicts = self.repo.index.conflicts

        if driver.exitCode() == 0:
            if deleteAfterApply:
                self.postStatus = _("Stash {0} applied and deleted.", tquoe(stashMessage))
            else:
                self.postStatus = _("Stash {0} applied.", tquoe(stashMessage))

        elif anyConflicts:
            self.postStatus = _("Stash {0} applied, with conflicts.", tquoe(stashMessage))
            message = [_("Applying the stash {0} has caused merge conflicts "
                         "because your files have diverged since they were stashed.", bquoe(stashMessage))]
            if deleteAfterApply:
                message.append(_("The stash wasn’t deleted in case you need to re-apply it later."))
            showWarning(self.parentWidget(), _("Conflicts caused by stash application"), paragraphs(message))

        else:
            self.postStatus = _("Stash {0} couldn’t be applied.", tquoe(stashMessage))
            message = [self.postStatus]
            if deleteAfterApply:
                message.append(_("The stash wasn’t deleted in case you need to re-apply it later."))
            raise AbortTask(driver.htmlErrorText(paragraphs(message)), details=driver.formatCommandLine())


class DropStash(RepoTask):
    def flow(self, stashCommitId: Oid):
        stashCommit = self.repo.peel_commit(stashCommitId)
        stashMessage = strip_stash_message(stashCommit.message)
        yield from self.flowConfirm(
            text=_("Really delete stash {0}?", bquoe(stashMessage)),
            verb=_("Delete stash"),
            buttonIcon="SP_DialogDiscardButton")

        backupStash(self.repo, stashCommitId)

        self.effects |= TaskEffects.Refs
        stashIndex = self.repo.find_stash_index(stashCommitId)
        stashName = f"stash@{{{stashIndex}}}"  # 'git stash drop' doesn't support stash numbers
        yield from self.flowCallGit("stash", "drop", stashName)

        self.postStatus = _("Stash {0} deleted.", tquoe(stashMessage))
