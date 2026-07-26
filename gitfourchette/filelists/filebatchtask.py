# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from collections.abc import Callable
from typing import TypeAlias

from gitfourchette.gitdriver import *
from gitfourchette.porcelain import MultiFileError
from gitfourchette.tasks import RepoTask
from gitfourchette.tasks.repotask import showMultiFileErrorMessage
from gitfourchette.toolbox import tagify


class FileBatchTask(RepoTask):
    UnitFunc: TypeAlias = Callable[[RepoTask, GitDelta], RepoTask.Flow[None]]

    def flow(
            self,
            deltaList: list[GitDelta],
            unitFunc: UnitFunc,
            title: str,
            prompt: str,
            threshold=3,
    ):
        assert "#" in prompt

        numFiles = len(deltaList)

        if numFiles > threshold:
            prompt = tagify(prompt.replace("#", str(numFiles)), "<b>")
            detailList = [d.new.path for d in deltaList]
            yield from self.flowConfirm(title, prompt, detailList=detailList)

        errors = MultiFileError()

        for delta in deltaList:
            try:
                yield from unitFunc(self, delta)
                errors.add_file_success()
            except (OSError,  # typically FileNotFoundError
                    LfsObjectCacheMissingError
                    ) as exc:
                errors.add_file_error(delta.new.path, exc)

        if errors:
            showMultiFileErrorMessage(self.parentWidget(), errors, title)
