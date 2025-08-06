# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import os
import re
import shutil
from contextlib import suppress

from gitfourchette import reverseunidiff, settings
from gitfourchette.exttools.mergedriver import MergeDriver
from gitfourchette.localization import *
from gitfourchette.nav import NavLocator
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskEffects
from gitfourchette.toolbox import *
from gitfourchette.trash import Trash
from gitfourchette.trtables import TrTables

logger = logging.getLogger(__name__)


class _BaseStagingTask(RepoTask):
    def canKill(self, task: RepoTask):
        # Jump/Refresh tasks shouldn't prevent a staging task from starting
        # when the user holds down RETURN/DELETE in a FileListView
        # to stage/unstage a series of files.
        from gitfourchette import tasks
        return isinstance(task, tasks.Jump | tasks.RefreshRepo)

    def denyConflicts(self, patches: list[Patch], purpose: PatchPurpose):
        conflicts = [p for p in patches if p.delta.status == DeltaStatus.CONFLICTED]

        if not conflicts:
            return

        numPatches = len(patches)
        numConflicts = len(conflicts)

        if numPatches == numConflicts:
            intro = _n("You have selected an unresolved merge conflict.",
                       "You have selected {n} unresolved merge conflicts.", numConflicts)
        else:
            intro = _n("There is an unresolved merge conflict among your selection.",
                       "There are {n} unresolved merge conflicts among your selection.", numConflicts)

        if purpose == PatchPurpose.Stage:
            please = _np("please fix (the merge conflicts)", "Please fix it before staging:", "Please fix them before staging:", numConflicts)
        else:
            please = _np("please fix (the merge conflicts)", "Please fix it before discarding:", "Please fix them before discarding:", numConflicts)

        message = paragraphs(intro, please)
        message += toTightUL(p.delta.new_file.path for p in conflicts)
        raise AbortTask(message)

    @staticmethod
    def filterSubmodules(patches: list[Patch]) -> list[Patch]:
        submos = [p for p in patches if SubtreeCommitDiff.is_subtree_commit_patch(p)]
        return submos


class StageFiles(_BaseStagingTask):
    def flow(self, patches: list[Patch]):
        if not patches:  # Nothing to stage (may happen if user keeps pressing Enter in file list view)
            QApplication.beep()
            raise AbortTask()

        self.denyConflicts(patches, PatchPurpose.Stage)

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        self.repo.stage_files(patches)

        yield from self.debriefPostStage(patches)

        self.postStatus = _n("File staged.", "{n} files staged.", len(patches))

    def debriefPostStage(self, patches: list[Patch]):
        debrief = {}

        for patch in patches:
            newFile: DiffFile = patch.delta.new_file
            m = ""

            if newFile.mode == FileMode.TREE:
                m = _("You’ve added another Git repo inside your current repo. "
                      "It is STRONGLY RECOMMENDED to absorb it as a submodule before committing.")
            elif SubtreeCommitDiff.is_subtree_commit_patch(patch):
                info = self.repo.analyze_subtree_commit_patch(patch, in_workdir=True)
                if info.is_del and info.was_registered:
                    m = _("Don’t forget to remove the submodule from {0} "
                          "to complete its deletion.", tquo(DOT_GITMODULES))
                elif not info.is_del and not info.is_trivially_indexable:
                    m = _("Uncommitted changes in the submodule can’t be staged from the parent repository.")

            if m:
                debrief[newFile.path] = m

        if not debrief:
            return

        # For better perceived responsivity, show message box asynchronously
        # so that RefreshRepo occurs in the background after the task completes
        yield from self.flowEnterUiThread()
        qmb = asyncMessageBox(
            self.parentWidget(),
            'information',
            self.name(),
            _n("An item requires your attention after staging:", "{n} items require your attention after staging:", len(debrief)))
        addULToMessageBox(qmb, [f"{btag(path)}: {issue}" for path, issue in debrief.items()])
        qmb.show()


class DiscardFiles(_BaseStagingTask):
    def flow(self, patches: list[Patch]):
        textPara = []

        verb = _("Discard changes")

        if not patches:  # Nothing to discard (may happen if user keeps pressing Delete in file list view)
            QApplication.beep()
            raise AbortTask()

        self.denyConflicts(patches, PatchPurpose.Discard)

        submos = self.filterSubmodules(patches)
        anySubmos = bool(submos)
        allSubmos = len(submos) == len(patches)
        really = ""

        if len(patches) == 1:
            patch = patches[0]
            bpath = bquo(patch.delta.new_file.path)
            if patch.delta.status == DeltaStatus.UNTRACKED:
                really = _("Really delete {0}?", bpath)
                really += " " + _("Git isn’t tracking this file, so you may not be able to recover it from older commits.")
                verb = _("Delete")
            elif patch.delta.new_file.mode == FileMode.COMMIT:
                really = _("Really discard changes in submodule {0}?", bpath)
            else:
                really = _("Really discard changes to {0}?", bpath)
        else:
            nFiles = len(patches) - len(submos)
            nSubmos = len(submos)
            if allSubmos:
                really = _("Really discard changes in {n} submodules?", n=nSubmos)
            elif anySubmos:
                really = _("Really discard changes to {nf} files and in {ns} submodules?", nf=nFiles, ns=nSubmos)
            else:
                really = _("Really discard changes to {n} files?", n=nFiles)

        textPara.append(really)
        if anySubmos:
            submoPostamble = _n(
                "Any uncommitted changes in the submodule will be <b>cleared</b> and the submodule’s HEAD will be reset.",
                "Any uncommitted changes in {n} submodules will be <b>cleared</b> and the submodules’ HEAD will be reset.",
                len(submos))
            textPara.append(submoPostamble)

        textPara.append(_("This cannot be undone!"))
        text = paragraphs(textPara)

        yield from self.flowConfirm(text=text, verb=verb, buttonIcon="git-discard")

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        paths = [patch.delta.new_file.path for patch in patches
                 if patch not in submos]

        # Restore files from index
        if paths:
            Trash.instance().backupPatches(self.repo.workdir, patches)
            self.repo.restore_files_from_index(paths)

        # Discard untracked trees. They have already been backed up above,
        # but restore_files_from_index isn't capable of removing trees.
        untrackedTrees = [patch.delta.new_file.path for patch in patches
                          if patch.delta.status == DeltaStatus.UNTRACKED and patch.delta.new_file.mode == FileMode.TREE]
        for untrackedTree in untrackedTrees:
            untrackedTreePath = self.repo.in_workdir(untrackedTree)
            assert os.path.isdir(untrackedTreePath)
            shutil.rmtree(untrackedTreePath)

        # Restore submodules
        if submos:
            self.effects |= TaskEffects.Refs  # We don't have TaskEffects.Submodules so .Refs is the next best thing
            for patch in submos:
                self.restoreSubmodule(patch)

        self.postStatus = _n("File discarded.", "{n} files discarded.", len(patches))

    def restoreSubmodule(self, patch: Patch):
        path = patch.delta.new_file.path
        submodule = self.repo.submodules[path]

        if patch.delta.status == DeltaStatus.DELETED:
            didRestore = self.repo.restore_submodule_gitlink(path)
            if not didRestore:
                raise AbortTask(_("Couldn’t restore gitlink file for submodule {0}.", lquo(path)))

        with RepoContext(self.repo.in_workdir(path), RepositoryOpenFlag.NO_SEARCH) as subRepo:
            # Reset HEAD to the target commit
            subRepo.reset(submodule.head_id, ResetMode.HARD)
            # Nuke uncommitted files as well
            subRepo.checkout_head(strategy=CheckoutStrategy.REMOVE_UNTRACKED | CheckoutStrategy.FORCE | CheckoutStrategy.RECREATE_MISSING)
            # TODO: Recurse?


class UnstageFiles(_BaseStagingTask):
    def flow(self, patches: list[Patch]):
        if not patches:  # Nothing to unstage (may happen if user keeps pressing Delete in file list view)
            QApplication.beep()
            raise AbortTask()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        self.repo.unstage_files(patches)

        self.postStatus = _n("File unstaged.", "{n} files unstaged.", len(patches))


class DiscardModeChanges(_BaseStagingTask):
    def flow(self, patches: list[Patch]):
        textPara = []

        if not patches:  # Nothing to unstage (may happen if user keeps pressing Delete in file list view)
            QApplication.beep()
            raise AbortTask()
        elif len(patches) == 1:
            path = patches[0].delta.new_file.path
            textPara.append(_("Really discard mode change in {0}?", bquo(path)))
        else:
            textPara.append(_("Really discard mode changes in <b>{n} files</b>?", n=len(patches)))
        textPara.append(_("This cannot be undone!"))

        yield from self.flowConfirm(text=paragraphs(textPara), verb=_("Discard mode changes"), buttonIcon="git-discard")

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        paths = [patch.delta.new_file.path for patch in patches]
        self.repo.discard_mode_changes(paths)


class UnstageModeChanges(_BaseStagingTask):
    def flow(self, patches: list[Patch]):
        if not patches:  # Nothing to unstage (may happen if user keeps pressing Delete in file list view)
            QApplication.beep()
            raise AbortTask()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        self.repo.unstage_mode_changes(patches)


class ApplyPatch(RepoTask):
    def flow(self, fullPatch: Patch, subPatch: bytes, purpose: PatchPurpose):
        if not subPatch:
            QApplication.beep()
            verb = TrTables.enum(purpose & PatchPurpose.VerbMask).lower()
            message = _("Can’t {verb} the selection because no red/green lines are selected.", verb=verb)
            raise AbortTask(message, asStatusMessage=True)

        if purpose & PatchPurpose.Discard:
            title = TrTables.enum(purpose)
            textPara = []
            if purpose & PatchPurpose.Hunk:
                textPara.append(_("Really discard this hunk?"))
            else:
                textPara.append(_("Really discard the selected lines?"))
            textPara.append(_("This cannot be undone!"))
            yield from self.flowConfirm(title, text=paragraphs(textPara), verb=title, buttonIcon="git-discard-lines")

            Trash.instance().backupPatch(self.repo.workdir, subPatch, fullPatch.delta.new_file.path)
            applyLocation = ApplyLocation.WORKDIR
        else:
            applyLocation = ApplyLocation.INDEX

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        self.repo.apply(subPatch, applyLocation)

        self.postStatus = TrTables.patchPurposePastTense(purpose)


class RevertPatch(RepoTask):
    def flow(self, fullPatch: Patch, patchData: bytes):
        if not patchData:
            raise AbortTask(_("There’s nothing to revert in the selection."))

        diff = self.repo.applies_breakdown(patchData, location=ApplyLocation.WORKDIR)
        if not diff:
            raise AbortTask(_("Couldn’t revert this patch.") + "<br>" +
                            _("The code may have diverged too much from this revision."))

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        diff = self.repo.apply(diff, location=ApplyLocation.WORKDIR)

        # After the task, jump to a NavLocator that points to any file that was modified by the patch
        for p in diff:
            if p.delta.status != DeltaStatus.DELETED:
                self.jumpTo = NavLocator.inUnstaged(p.delta.new_file.path)
                break


class HardSolveConflicts(RepoTask):
    def flow(self, conflictedFiles: dict[str, Oid]):
        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        repo = self.repo
        repo.refresh_index()
        index = repo.index
        conflicts = index.conflicts
        assert conflicts is not None

        assert isinstance(conflictedFiles, dict)
        for path, keepId in conflictedFiles.items():
            assert type(path) is str
            assert type(keepId) is Oid
            assert path in conflicts

            with suppress(FileNotFoundError):  # ignore FileNotFoundError for DELETED_BY_US conflicts
                Trash.instance().backupFile(repo.workdir, path)

            fullPath = repo.in_workdir(path)

            # TODO: we should probably set the modes correctly and stuff as well
            if keepId == NULL_OID:
                if os.path.isfile(fullPath):  # the file may not exist in DELETED_BY_BOTH conflicts
                    os.unlink(fullPath)
            else:
                blob = repo.peel_blob(keepId)
                with open(fullPath, "wb") as f:
                    f.write(blob.data)

            del conflicts[path]
            assert path not in conflicts

            if keepId != NULL_OID:
                # Stage the file so it doesn't show up in both file lists
                index.add(path)

                # Jump to staged file after the task
                self.jumpTo = NavLocator.inStaged(path)

        # Write index modifications to disk
        index.write()

        self.postStatus = _n("Conflict resolved.", "{n} conflicts resolved.", len(conflictedFiles))


class MarkConflictSolved(RepoTask):
    def flow(self, path: str):
        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        repo = self.repo

        repo.refresh_index()
        assert (repo.index.conflicts is not None) and (path in repo.index.conflicts)

        del repo.index.conflicts[path]
        assert (repo.index.conflicts is None) or (path not in repo.index.conflicts)
        repo.index.write()


class AcceptMergeConflictResolution(RepoTask):
    def canKill(self, task: RepoTask) -> bool:
        from gitfourchette.tasks import RefreshRepo, Jump
        return isinstance(task, RefreshRepo | Jump)

    def flow(self, mergeDriver: MergeDriver):
        path = mergeDriver.relativeTargetPath

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        mergeDriver.copyScratchToTarget()
        mergeDriver.deleteNow()

        del self.repo.index.conflicts[path]
        self.repo.index.add(path)

        # Jump to staged file after confirming conflict resolution
        self.jumpTo = NavLocator.inStaged(path)
        self.postStatus = _("Merge conflict resolved in {0}.", tquo(path))


class ApplyPatchFile(RepoTask):
    def flow(self, reverse: bool = False, path: str = ""):
        if reverse:
            title = _("Revert patch file")
            verb = _("Revert")
        else:
            title = _("Apply patch file")
            verb = _("Apply")

        patchFileCaption = _("Patch file")
        allFilesCaption = _("All files")

        if not path:
            qfd = PersistentFileDialog.openFile(
                self.parentWidget(), "OpenPatch", title, filter=F"{patchFileCaption} (*.patch);;{allFilesCaption} (*)")

            yield from self.flowDialog(qfd)

            path = qfd.selectedFiles()[0]

        impl = self._withGit if settings.prefs.vanillaGit else self._withLibgit2
        yield from impl(reverse, path, title, verb)

    def _withGit(self, reverse: bool, path: str, title: str, verb: str):
        # Do a dry run first.
        command = ["apply", "-z", "--numstat", "--check", path]
        if reverse:
            command.append("--reverse")
        driver = yield from self.flowCallGit(*command)
        stdout = driver.readAll().data().removesuffix(b'\0')

        details = []
        firstFile = ""
        for bline in stdout.split(b'\0'):
            match = re.match(rb"(-|\d+)\t(-|\d+)\t(.+)", bline)
            adds = match.group(1).decode(errors="replace")
            dels = match.group(2).decode(errors="replace")
            patchFile = match.group(3).decode(errors="replace")
            if adds == "-" or dels == "-":
                details.append(_("(binary)") + " " + escape(patchFile))
            else:
                details.append(f"(+{adds} -{dels}) {escape(patchFile)}")
            firstFile = firstFile or patchFile

        text = paragraphs(
            _("Do you want to {verb} patch file {path}?",
              verb=btag(verb.lower()), path=bquoe(os.path.basename(path))),
            _n("<b>{n}</b> file will be modified in your working directory:",
               "<b>{n}</b> files will be modified in your working directory:", n=len(details))
        )

        yield from self.flowConfirm(title, text, verb=verb, detailList=details)

        # Dry run confirmed, go ahead
        self.effects |= TaskEffects.Workdir

        command = ["apply", path]
        if reverse:
            command.append("--reverse")
        yield from self.flowCallGit(*command)

        self.jumpTo = NavLocator.inUnstaged(firstFile)

    def _withLibgit2(self, reverse: bool, path: str, title: str, verb: str):
        yield from self.flowEnterWorkerThread()

        with open(path, encoding='utf-8') as patchFile:
            patchData = patchFile.read()

        # May raise:
        # - OSError
        # - GitError
        # - UnicodeDecodeError (if passing in a random binary file)
        # - KeyError ('no patch found')
        loadedDiff: Diff = Diff.parse_diff(patchData)

        # Reverse the patch if user wants to.
        if reverse:
            patchData = reverseunidiff.reverseUnidiff(loadedDiff.patch)
            loadedDiff = Diff.parse_diff(patchData)

        # Do a dry run first so we don't litter the workdir with a patch that failed halfway through.
        # If the patch doesn't apply, this raises a MultiFileError.
        diff = self.repo.applies_breakdown(patchData)
        deltas = list(diff.deltas)

        yield from self.flowEnterUiThread()

        text = paragraphs(
            _("Do you want to {verb} patch file {path}?",
              verb=btag(verb.lower()), path=bquoe(os.path.basename(path))),
            _n("<b>{n}</b> file will be modified in your working directory:",
               "<b>{n}</b> files will be modified in your working directory:", n=len(deltas))
        )
        details = [f"({d.status_char()}) {escape(d.new_file.path)}" for d in deltas]

        yield from self.flowConfirm(title, text, verb=verb, detailList=details)

        self.effects |= TaskEffects.Workdir

        self.repo.apply(loadedDiff, ApplyLocation.WORKDIR)
        self.jumpTo = NavLocator.inUnstaged(deltas[0].new_file.path)


class ApplyPatchFileReverse(ApplyPatchFile):
    def flow(self, path: str = ""):
        yield from ApplyPatchFile.flow(self, reverse=True, path=path)


class ApplyPatchData(RepoTask):
    def flow(self, patchData: str, reverse: bool):
        yield from self.flowEnterWorkerThread()

        if reverse:
            patchData = reverseunidiff.reverseUnidiff(patchData)
        loadedDiff: Diff = Diff.parse_diff(patchData)

        # Do a dry run first so we don't litter the workdir with a patch that failed halfway through.
        # If the patch doesn't apply, this raises a MultiFileError.
        diff = self.repo.applies_breakdown(patchData)
        deltas = list(diff.deltas)

        yield from self.flowEnterUiThread()

        title = _("Revert patch") if reverse else _("Apply patch")
        verb = _("Revert") if reverse else _("Apply")

        text = paragraphs(
            _("Do you want to {verb} this patch?", verb=btag(verb.lower())),
            _n("<b>{n}</b> file will be modified in your working directory:",
               "<b>{n}</b> files will be modified in your working directory:", n=len(deltas))
        )
        details = [f"({d.status_char()}) {escape(d.new_file.path)}" for d in deltas]

        yield from self.flowConfirm(title, text, verb=verb, detailList=details)

        self.effects |= TaskEffects.Workdir
        self.repo.apply(loadedDiff, ApplyLocation.WORKDIR)
        self.jumpTo = NavLocator.inUnstaged(deltas[0].new_file.path)


class RestoreRevisionToWorkdir(RepoTask):
    def flow(self, patch: Patch, old: bool):
        if old:
            preposition = _p("preposition slotted into '...BEFORE this commit'", "before")
            diffFile = patch.delta.old_file
            delete = patch.delta.status == DeltaStatus.ADDED
        else:
            preposition = _p("preposition slotted into '...AT this commit'", "at")
            diffFile = patch.delta.new_file
            delete = patch.delta.status == DeltaStatus.DELETED

        path = self.repo.in_workdir(diffFile.path)
        existsNow = os.path.isfile(path)

        if not existsNow and delete:
            message = _("Your working copy of {path} already matches the revision {preposition} this commit.",
                        path=bquo(diffFile.path), preposition=preposition)
            raise AbortTask(message, icon="information")

        if not existsNow:
            actionVerb = _("recreated")
        elif delete:
            actionVerb = _("deleted")
        else:
            actionVerb = _("overwritten")
        prompt = paragraphs(
            _("Do you want to restore {path} as it was {preposition} this commit?",
              path=bquo(diffFile.path), preposition=preposition),
            _("This file will be {processed} in your working directory.", processed=actionVerb))

        yield from self.flowConfirm(text=prompt, verb=_("Restore"))

        self.effects |= TaskEffects.Workdir

        if delete:
            os.unlink(path)
        else:
            blob = self.repo.peel_blob(diffFile.id)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(blob.data)
            os.chmod(path, diffFile.mode)

        self.postStatus = _("File {path} {processed}.", path=tquoe(diffFile.path), processed=actionVerb)
        self.jumpTo = NavLocator.inUnstaged(diffFile.path)


class AbortMerge(RepoTask):
    def flow(self):
        self.repo.refresh_index()

        isMerging = self.repo.state() == RepositoryState.MERGE
        isCherryPicking = self.repo.state() == RepositoryState.CHERRYPICK
        isReverting = self.repo.state() == RepositoryState.REVERT
        anyConflicts = self.repo.index.conflicts

        if not (isMerging or isCherryPicking or isReverting or anyConflicts):
            raise AbortTask(_("No abortable state is in progress."), icon='information')

        if isCherryPicking:
            clause = _("abort the ongoing cherry-pick")
            title = _("Abort cherry-pick")
            postStatus = _("Cherry-pick aborted.")
        elif isMerging:
            clause = _("abort the ongoing merge")
            title = _("Abort merge")
            postStatus = _("Merge aborted.")
        elif isReverting:
            clause = _("abort the ongoing revert")
            title = _("Abort revert")
            postStatus = _("Revert aborted.")
        else:
            clause = _("reset the index")
            title = _("Reset index")
            postStatus = _("Index reset.")

        try:
            abortList = self.repo.get_reset_merge_file_list()
        except MultiFileError as exc:
            exc.message = _n(
                "Cannot {verb} right now, because a file contains both staged and unstaged changes.",
                "Cannot {verb} right now, because {n} files contain both staged and unstaged changes.",
                n=len(exc.file_exceptions), verb=clause)
            exc.message += " " + _("Please unstage the changes and try again.")
            raise exc

        lines = [_("Do you want to {0}?", clause)]

        if not abortList:
            lines.append(_("No files are affected."))
        else:
            if anyConflicts:
                lines.append(_("All conflicts will be cleared and all <b>staged</b> changes will be lost."))
            else:
                lines.append(_("All <b>staged</b> changes will be lost."))
            lines.append(_n("This file will be reset:", "{n} files will be reset:", len(abortList)))

        yield from self.flowConfirm(title=title, text=paragraphs(lines), verb=englishTitleCase(title),
                                    detailList=[escape(f) for f in abortList])

        self.effects |= TaskEffects.DefaultRefresh

        self.repo.reset_merge()
        self.repo.state_cleanup()

        self.postStatus = postStatus

        # Clear draft commit message that was set in CherrypickCommit/RevertCommit/MergeBranch
        if isCherryPicking or isReverting or isMerging:
            self.repoModel.prefs.clearDraftCommit()
