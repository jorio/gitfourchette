# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.tasks import RepoTask
from gitfourchette.toolbox import Benchmark
from gitfourchette.trace import traceFile


class OpenBlame(RepoTask):
    def flow(self, path: str, seed: Oid):
        from gitfourchette.blameview.blamewindow import BlameWindow

        blameWindow = BlameWindow(self.repoModel, self.parentWidget())
        blameWindow.setWindowFlag(Qt.WindowType.Window, True)
        blameWindow.resize(550, 700)
        blameWindow.setEnabled(False)
        blameWindow.show()

        yield from self.flowEnterWorkerThread()
        repo = self.repo
        head = repo.head_commit_id
        showCommit = seed

        # Get most recent seed as possible
        with Benchmark("get seed"):
            if seed == NULL_OID:
                seed = head
            elif seed == head:
                pass
            elif path in repo.head_tree and repo.descendant_of(head, seed):
                # TODO: this may occlude showCommit if it's on a branch that eventually gets merged
                seed = head
            else:
                pass

        # Trace commit in branch
        with Benchmark("trace"):
            trace = traceFile(path, repo.peel_commit(seed))

        yield from self.flowEnterUiThread()
        blameWindow.setTrace(trace, showCommit)
        blameWindow.setEnabled(True)
