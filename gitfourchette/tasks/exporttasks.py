import itertools
import re
from pathlib import Path
from typing import Iterable

from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette import settings
from gitfourchette.tasks.repotask import AbortTask, RepoTask, TaskEffects
from gitfourchette.toolbox import *


def contextLines():
    return settings.prefs.contextLines


class ComposePatch(RepoTask):
    def effects(self):
        return TaskEffects.Nothing

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
            print(data)

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
            sorry = translate("ComposePatch", "{app} cannot export binary patches from a hand-picked selection of files.").format(app=qAppName())
            if not composed:
                raise AbortTask(sorry)
            sorry += " " + translate("ComposePatch", "%n binary files will be omitted from the patch file:", "", len(skippedBinaryFiles))
            yield from self.flowConfirm(self.name(), sorry, detailList=skippedBinaryFiles, verb=translate("ComposePatch", "Proceed"))

        if not composed:
            raise AbortTask(translate("ComposePatch", "Nothing to export. The patch is empty."), icon="information")

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


class ExportCommitAsPatch(ComposePatch):
    def flow(self, oid: Oid):
        yield from self.flowEnterWorkerThread()

        diffs, _ = self.repo.commit_diffs(oid, show_binary=True, context_lines=contextLines())
        patches = itertools.chain.from_iterable((p for p in d) for d in diffs)

        commit = self.repo.peel_commit(oid)
        summary, _ = messageSummary(commit.message, elision="")
        summary = summary.strip()[:50].strip()
        initialName = f"{self.repo.repo_name()} - {shortHash(oid)} - {summary}.patch"

        yield from self.composePatch(patches, initialName)


class ExportStashAsPatch(ExportCommitAsPatch):
    def flow(self, oid: Oid):
        yield from self.flowEnterWorkerThread()

        diffs, _ = self.repo.commit_diffs(oid, show_binary=True, context_lines=contextLines())
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

        headOid = self.repo.head_commit_oid
        initialName = f"{self.repo.repo_name()} - uncommitted changes on {shortHash(headOid)}.patch"

        yield from self.composePatch(patches, initialName)


class ExportPatchCollection(ComposePatch):
    def flow(self, patches: list[Patch]):
        yield from self.composePatch(patches)
