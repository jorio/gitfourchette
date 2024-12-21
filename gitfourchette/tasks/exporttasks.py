# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import itertools
import re
from collections.abc import Iterable
from pathlib import Path

from gitfourchette import settings
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskEffects
from gitfourchette.toolbox import *


def contextLines():
    return settings.prefs.contextLines


class ComposePatch(RepoTask):
    def composePatch(self, patches: Iterable[Patch], fileName=""):
        yield from self.flowEnterWorkerThread()

        composed = b""
        names = set()
        skippedBinaryFiles = []

        for patch in patches:
            if not patch:
                continue
            if patch.delta.status == DeltaStatus.DELETED:
                diffFile = patch.delta.old_file
            else:
                diffFile = patch.delta.new_file

            data = patch.data

            if patch.delta.is_binary:
                startOfLastLine = data.rfind(b"\n", 0, -1) + 1
                lastLine = data[startOfLastLine:]
                if re.search(rb"^Binary files .+ and .+ differ", lastLine):
                    skippedBinaryFiles.append(diffFile.path)
                    continue

            diffPatchData = patch.data
            composed += diffPatchData
            assert composed.endswith(b"\n")
            names.add(Path(diffFile.path).stem)

        yield from self.flowEnterUiThread()

        if skippedBinaryFiles:
            sorry = _("{app} cannot export binary patches from a hand-picked selection of files.", app=qAppName())
            if not composed:
                raise AbortTask(sorry)
            sorry += " "
            sorry += _n("Binary file will be omitted from patch file:", "{n} binary files will be omitted from patch file:", len(skippedBinaryFiles))
            yield from self.flowConfirm(self.name(), sorry, detailList=skippedBinaryFiles, verb=_("Proceed"))

        if not composed:
            raise AbortTask(_("Nothing to export. The patch is empty."), icon="information")

        # Fallback filename
        if not fileName:
            fileName = ", ".join(sorted(names)) + ".patch"

        # Sanitize filename
        for c in "?/\\*~<>|:":
            fileName = fileName.replace(c, "_")

        qfd = PersistentFileDialog.saveFile(self.parentWidget(), "SaveFile", self.name(), fileName)
        yield from self.flowDialog(qfd)
        savePath = qfd.selectedFiles()[0]

        yield from self.flowEnterWorkerThread()
        with open(savePath, "wb") as f:
            f.write(composed)

        if self.repo.is_in_workdir(savePath):
            self.effects |= TaskEffects.Workdir  # invalidate workdir if saved file to it


class ExportCommitAsPatch(ComposePatch):
    def flow(self, oid: Oid):
        yield from self.flowEnterWorkerThread()

        diffs, _dummy = self.repo.commit_diffs(oid, show_binary=True, context_lines=contextLines())
        patches = itertools.chain.from_iterable((p for p in d) for d in diffs)

        commit = self.repo.peel_commit(oid)
        summary, _dummy = messageSummary(commit.message, elision="")
        summary = summary.strip()[:50].strip()
        initialName = f"{self.repo.repo_name()} - {shortHash(oid)} - {summary}.patch"

        yield from self.composePatch(patches, initialName)


class ExportStashAsPatch(ExportCommitAsPatch):
    def flow(self, oid: Oid):
        yield from self.flowEnterWorkerThread()

        diffs, _dummy = self.repo.commit_diffs(oid, show_binary=True, context_lines=contextLines())
        patches = itertools.chain.from_iterable((p for p in d) for d in diffs)

        commit = self.repo.peel_commit(oid)
        coreMessage = strip_stash_message(commit.message)
        initialName = f"{self.repo.repo_name()} - stashed on {shortHash(commit.parent_ids[0])} - {coreMessage}.patch"

        yield from self.composePatch(patches, initialName)


class ExportWorkdirAsPatch(ComposePatch):
    def flow(self):
        yield from self.flowEnterWorkerThread()

        diff = self.repo.get_uncommitted_changes(show_binary=True, context_lines=contextLines())
        patches = (p for p in diff)

        headId = self.repo.head_commit_id
        initialName = f"{self.repo.repo_name()} - uncommitted changes on {shortHash(headId)}.patch"

        yield from self.composePatch(patches, initialName)


class ExportPatchCollection(ComposePatch):
    def flow(self, patches: list[Patch]):
        yield from self.composePatch(patches)
