# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import logging
import os
import shutil
from contextlib import suppress
from pathlib import Path

from gitfourchette import settings
from gitfourchette.exttools.mergedriver import MergeDriver
from gitfourchette.gitdriver import argsIf, FatDelta, ABDelta
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

    def denyConflicts(self, patches: list[FatDelta], purpose: PatchPurpose):
        conflicts = [p for p in patches if p.isConflict()]

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
        message += toTightUL(p.path for p in conflicts)
        raise AbortTask(message)

    @staticmethod
    def filterSubmodules(deltas: list[FatDelta]) -> list[FatDelta]:
        submos = [p for p in deltas if p.isSubtreeCommitPatch()]
        return submos


class StageFiles(_BaseStagingTask):
    def flow(self, patches: list[FatDelta]):
        if not patches:  # Nothing to stage (may happen if user keeps pressing Enter in file list view)
            QApplication.beep()
            raise AbortTask()

        self.denyConflicts(patches, PatchPurpose.Stage)

        paths = [delta.path for delta in patches]

        self.effects |= TaskEffects.Workdir
        yield from self.flowCallGit("add", "--", *paths)

        yield from self.debriefPostStage(patches)

        self.postStatus = _n("File staged.", "{n} files staged.", len(patches))

    def debriefPostStage(self, patches: list[FatDelta]):
        debrief = {}

        for delta in patches:
            m = ""

            if delta.modeWorktree == FileMode.TREE:
                m = _("You’ve added another Git repo inside your current repo. "
                      "It is STRONGLY RECOMMENDED to absorb it as a submodule before committing.")
            # elif SubtreeCommitDiff.is_subtree_commit_patch(patch):
            elif delta.isSubtreeCommitPatch(): #delta.modeWorktree == FileMode.COMMIT or delta.modeIndex == FileMode.COMMIT:
                raise NotImplementedError("TODO: analyze subtree commit patch")
                """
                info = self.repo.analyze_subtree_commit_patch(patch, in_workdir=True)
                if info.is_del and info.was_registered:
                    m = _("Don’t forget to remove the submodule from {0} "
                          "to complete its deletion.", tquo(DOT_GITMODULES))
                elif not info.is_del and not info.is_trivially_indexable:
                    m = _("Uncommitted changes in the submodule can’t be staged from the parent repository.")
                """

            if m:
                debrief[delta.path] = m

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
    def flow(self, deltas: list[FatDelta]):
        textPara = []

        verb = _("Discard changes")

        if not deltas:  # Nothing to discard (may happen if user keeps pressing Delete in file list view)
            QApplication.beep()
            raise AbortTask()

        self.denyConflicts(deltas, PatchPurpose.Discard)

        submos = self.filterSubmodules(deltas)
        anySubmos = bool(submos)
        allSubmos = len(submos) == len(deltas)
        really = ""

        assert all(d.statusUnstaged for d in deltas), "expecting all files to discard to have an unstaged status"

        if len(deltas) == 1:
            delta = deltas[0]
            bpath = bquo(delta.path)
            if delta.isUntracked():
                really = _("Really delete {0}?", bpath)
                really += " " + _("Git isn’t tracking this file, so you may not be able to recover it from older commits.")
                verb = _("Delete")
            elif delta.modeWorktree == FileMode.COMMIT:
                really = _("Really discard changes in submodule {0}?", bpath)
            else:
                really = _("Really discard changes to {0}?", bpath)
        else:
            nFiles = len(deltas) - len(submos)
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

        self.effects |= TaskEffects.Workdir
        if submos:
            self.effects |= TaskEffects.Refs  # We don't have TaskEffects.Submodules so .Refs is the next best thing

        # Back up discarded patches
        if deltas:
            # TODO:
            print("TODO: Back up discarded patches")
            # yield from self.flowEnterWorkerThread()
            # Trash.instance().backupPatches(self.repo.workdir, patches)
            # yield from self.flowEnterUiThread()

        tracked = [d.path for d in deltas if not d.isUntracked()]
        untrackedFiles = [d.path for d in deltas if d.isUntracked() and d.modeWorktree != FileMode.TREE]
        untrackedTrees = [d.path for d in deltas if d.isUntracked() and d.modeWorktree == FileMode.TREE]

        # Discard untracked trees. They have already been backed up above,
        # but restore_files_from_index isn't capable of removing trees.
        for untrackedTree in untrackedTrees:
            untrackedTreePath = self.repo.in_workdir(untrackedTree)
            assert os.path.isdir(untrackedTreePath)
            shutil.rmtree(untrackedTreePath)

        if untrackedFiles:
            yield from self.flowCallGit("clean", "--force", "--", *untrackedFiles)
        if tracked:
            yield from self.flowCallGit("checkout", "--", *tracked)

        if submos:
            submoPaths = [delta.path for delta in submos]

            for submo in submoPaths:
                subWd = os.path.join(self.repo.workdir, submo)
                yield from self.flowCallGit("clean", "-d", "--force", workdir=subWd)

            yield from self.flowCallGit("submodule", "update", "--force", "--init", "--recursive", "--checkout", "--", *submoPaths)

        self.postStatus = _n("File discarded.", "{n} files discarded.", len(deltas))


class UnstageFiles(_BaseStagingTask):
    def flow(self, deltas: list[FatDelta]):
        if not deltas:  # Nothing to unstage (may happen if user keeps pressing Delete in file list view)
            QApplication.beep()
            raise AbortTask()

        paths = [delta.path for delta in deltas]
        self.effects |= TaskEffects.Workdir
        # Not using 'restore --staged' because it doesn't work in an empty repo
        yield from self.flowCallGit("reset", "--", *paths)

        self.postStatus = _n("File unstaged.", "{n} files unstaged.", len(deltas))


class DiscardModeChanges(_BaseStagingTask):
    def flow(self, deltas: list[FatDelta]):
        textPara = []

        if not deltas:  # Nothing to unstage (may happen if user keeps pressing Delete in file list view)
            QApplication.beep()
            raise AbortTask()
        elif len(deltas) == 1:
            path = deltas[0].path
            textPara.append(_("Really discard mode change in {0}?", bquo(path)))
        else:
            textPara.append(_("Really discard mode changes in <b>{n} files</b>?", n=len(deltas)))
        textPara.append(_("This cannot be undone!"))

        yield from self.flowConfirm(text=paragraphs(textPara), verb=_("Discard mode changes"), buttonIcon="git-discard")

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        paths = [delta.path for delta in deltas]
        self.repo.discard_mode_changes(paths)


class UnstageModeChanges(_BaseStagingTask):
    def flow(self, deltas: list[ABDelta]):
        if not deltas:  # Nothing to unstage (may happen if user keeps pressing Delete in file list view)
            QApplication.beep()
            raise AbortTask()

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        self.repo.refresh_index()
        index = self.repo.index
        for delta in deltas:
            of = delta.old
            nf = delta.new
            if (of.mode != nf.mode
                    and delta.status not in "AD?"  # ADDED, DELETED, UNTRACKED
                    and of.mode in [FileMode.BLOB, FileMode.BLOB_EXECUTABLE]):
                index.add(IndexEntry(nf.path, Oid(hex=nf.id), of.mode))
        index.write()


class ApplyPatch(RepoTask):
    def flow(self, fullPatch: Patch, subPatch: str, purpose: PatchPurpose):
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

            # TODO:
            print("TODO: Back up discarded patches")
            #Trash.instance().backupPatch(self.repo.workdir, subPatch, fullPatch.delta.new_file.path)

            applyLocation = ApplyLocation.WORKDIR
        else:
            applyLocation = ApplyLocation.INDEX

        yield from self.flowEnterWorkerThread()
        self.effects |= TaskEffects.Workdir

        # libgit2's index must be fresh in order to apply a partial patch to the index.
        if applyLocation == ApplyLocation.INDEX:
            self.repo.refresh_index()

        self.repo.apply(subPatch, applyLocation)

        self.postStatus = TrTables.patchPurposePastTense(purpose)


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
            verb, title = _("revert"), _("Revert patch file")
        else:
            verb, title = _("apply"), _("Apply patch file")

        patchFileCaption = _("Patch file")
        allFilesCaption = _("All files")

        if not path:
            qfd = PersistentFileDialog.openFile(
                self.parentWidget(), "OpenPatch", title,
                filter=f"{patchFileCaption} (*.patch);;{allFilesCaption} (*)")
            path = yield from self.flowFileDialog(qfd)

        question = _("Do you want to {verb} patch file {path}?",
                     verb=btag(verb), path=bquoe(os.path.basename(path)))

        yield from ApplyPatchFile.do(self, reverse, -1, path, title, question)

    @staticmethod
    def do(task: RepoTask, reverse: bool, context: int, path: str, title: str, question: str):
        stem = [
            "apply",
            *argsIf(reverse, "--reverse"),
            *argsIf(context >= 0, f"-C{context}"),
            path
        ]

        # Do a dry run first.
        driver = yield from task.flowCallGit(*stem, "--numstat", "-z", "--check")

        table = driver.stdoutTableNumstatZ()
        numFiles = len(table)
        details = []
        firstFile = ""
        for adds, dels, patchFile in table:
            if adds == "-" or dels == "-":
                details.append(_("(binary)") + " " + escape(patchFile))
            else:
                details.append(f"(<add>+{adds}</add> <del>-{dels}</del>) {escape(patchFile)}")
            firstFile = firstFile or patchFile

        addDelStyle = settings.prefs.addDelColorsStyleTag()
        listIntro = _n("<b>{n}</b> file will be modified in your working directory:",
                       "<b>{n}</b> files will be modified in your working directory:", n=numFiles)
        confirmText = addDelStyle + paragraphs(question, listIntro)

        yield from task.flowConfirm(title, confirmText, verb=_("Apply"), detailList=details)

        # Dry run confirmed, go ahead
        task.effects |= TaskEffects.Workdir

        yield from task.flowCallGit(*stem)

        task.jumpTo = NavLocator.inUnstaged(firstFile)
        task.postStatus = _n("{n} file modified in the working directory.",
                             "{n} files modified in the working directory.",
                             n=numFiles)


class ApplyPatchFileReverse(ApplyPatchFile):
    def flow(self, path: str = ""):
        yield from ApplyPatchFile.flow(self, reverse=True, path=path)


class ApplyPatchData(RepoTask):
    def flow(self, patchData: str, title: str, question: str, reverse: bool = False, context: int = -1):
        assert isinstance(patchData, str), "patchData should be str"

        if not patchData:
            raise AbortTask(_("There’s nothing to apply in the selection."))

        template = os.path.join(qTempDir(), self.__class__.__name__ + "-XXXXXX.patch")
        tempPatch = QTemporaryFile(template, self)
        tempPatch.open()
        tempPatch.write(patchData.encode("utf-8"))
        tempPatch.close()
        path = tempPatch.fileName()

        yield from ApplyPatchFile.do(self, reverse, context, path, title, question)


class RestoreRevisionToWorkdir(RepoTask):
    def flow(self, delta: ABDelta, old: bool):
        if old:
            preposition = _p("preposition slotted into '...BEFORE this commit'", "before")
            diffFile = delta.old
            delete = delta.status == "A"
        else:
            preposition = _p("preposition slotted into '...AT this commit'", "at")
            diffFile = delta.new
            delete = delta.status == "D"

        path = self.repo.in_workdir(diffFile.path)
        pathObj = Path(path)
        existsNow = pathObj.is_file()

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
            pathObj.unlink()
        else:
            data = diffFile.read(self.repo)
            pathObj.parent.mkdir(parents=True, exist_ok=True)
            pathObj.write_bytes(data)
            pathObj.chmod(diffFile.mode)

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
            gitCommand = ["cherry-pick", "--abort"]
        elif isMerging:
            clause = _("abort the ongoing merge")
            title = _("Abort merge")
            postStatus = _("Merge aborted.")
            gitCommand = ["merge", "--abort"]
        elif isReverting:
            clause = _("abort the ongoing revert")
            title = _("Abort revert")
            postStatus = _("Revert aborted.")
            gitCommand = ["revert", "--abort"]
        else:
            clause = _("reset the index")
            title = _("Reset index")
            postStatus = _("Index reset.")
            gitCommand = ["reset", "--merge"]

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

        yield from self.flowCallGit(*gitCommand)
        # self.repo.reset_merge()
        # self.repo.state_cleanup()

        self.postStatus = postStatus

        # Clear draft commit message that was set in CherrypickCommit/RevertCommit/MergeBranch
        if isCherryPicking or isReverting or isMerging:
            self.repoModel.prefs.clearDraftCommit()
