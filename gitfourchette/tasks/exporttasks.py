# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from pathlib import Path

from gitfourchette.gitdriver import ABDelta
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.tasks.loadtasks import LoadPatch
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskEffects
from gitfourchette.toolbox import *


def savePatch(task: RepoTask, patch: str, fileName=""):
    if not patch:
        raise AbortTask(_("Nothing to export. The patch is empty."), icon="information")

    # Sanitize filename
    for c in "?/\\*~<>|:":
        fileName = fileName.replace(c, "_")

    qfd = PersistentFileDialog.saveFile(task.parentWidget(), "SaveFile", task.name(), fileName)
    savePath = yield from task.flowFileDialog(qfd)

    yield from task.flowEnterWorkerThread()
    Path(savePath).write_text(patch)

    if task.repo.is_in_workdir(savePath):
        task.effects |= TaskEffects.Workdir  # invalidate workdir if saved file to it


class ExportCommitAsPatch(RepoTask):
    def flow(self, oid: Oid, fileName=""):
        if not fileName:
            commit = self.repo.peel_commit(oid)
            summary, _dummy = messageSummary(commit.message, elision="")
            summary = summary[:50].strip()
            fileName = f"{self.repo.repo_name()} - {shortHash(oid)} - {summary}.patch"

        preamble = LoadPatch.diffCommandPreamble()
        driver = yield from self.flowCallGit(
            *preamble, "show", "--binary", "--diff-merges=1", "-p", "--format=", str(oid))
        patch = driver.stdoutScrollback()

        yield from savePatch(self, patch, fileName)


class ExportStashAsPatch(ExportCommitAsPatch):
    def flow(self, oid: Oid):
        commit = self.repo.peel_commit(oid)
        message = _p("patch file name, please keep it short",
                     "stashed on {commit}", commit=shortHash(commit.parent_ids[0]))
        summary = strip_stash_message(commit.message)[:50].strip()
        fileName = f"{self.repo.repo_name()} - {message} - {summary}.patch"
        yield from super().flow(oid, fileName)


class ExportWorkdirAsPatch(RepoTask):
    def flow(self):
        patches = []

        diffCommand = LoadPatch.diffCommandPreamble() + ["diff", "--binary"]

        # Diff the workdir to HEAD (except untracked files)
        driver = yield from self.flowCallGit(*diffCommand, "HEAD")
        patches.append(driver.stdoutScrollback())

        # Diff untracked files.
        # This requires fresh workdir status in RepoModel, which we probably have already
        # because this task requires the user to click on the workdir first.
        if not self.repoModel.workdirStatusReady or self.repoModel.workdirStale:
            raise NotImplementedError("Export workdir requires fresh status")

        for delta in self.repoModel.workdirUnstagedDeltas:
            if delta.status == "?":  # Scan for untracked files
                driver = yield from self.flowCallGit(*diffCommand, "--", "/dev/null", delta.new.path, autoFail=False)
                patches.append(driver.stdoutScrollback())

        # Compose the patch
        assert all(not patch or patch.endswith("\n") for patch in patches)
        patch = "".join(patches)

        # Compose filename
        message = _p("patch file name, please keep it short",
                     "uncommitted changes on {commit}", commit=shortHash(self.repo.head_commit_id))
        fileName = f"{self.repo.repo_name()} - {message}.patch"

        yield from savePatch(self, patch, fileName)


class ExportPatchCollection(RepoTask):
    def flow(self, deltas: list[ABDelta], commit: Oid):
        names = []
        patches = []

        for delta in deltas:
            # Get filename stem
            file = delta.old if delta.status == "D" else delta.new
            name = Path(file.path).stem
            names.append(name)

            # Get patch (run 'git diff')
            tokens = LoadPatch.buildDiffCommand(delta, commit, binary=True)
            driver = yield from self.flowCallGit(*tokens, autoFail=False)
            patch = driver.stdoutScrollback()
            patches.append(patch)

        # Compose patch and filename
        assert all(not patch or patch.endswith("\n") for patch in patches)
        composed = "".join(patches)
        fileName = ", ".join(names) + ".patch"

        yield from savePatch(self, composed, fileName)
