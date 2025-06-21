# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.blame import *
from gitfourchette.blameview.blamemodel import BlameModel
from gitfourchette.localization import *
from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.repomodel import UC_FAKEID
from gitfourchette.tasks import RepoTask, TaskPrereqs
from gitfourchette.tasks.repotask import AbortTask
from gitfourchette.toolbox import *


class OpenBlame(RepoTask):
    TraceSkimInterval = 20

    def prereqs(self) -> TaskPrereqs:
        return TaskPrereqs.NoUnborn

    def flow(self, path: str, seed: Oid = NULL_OID):
        progress = _BlameProgressDialog(self.parentWidget())
        progress.setWindowTitle(_("Annotating {0}", tquo(path)))
        self.progressDialog = progress

        from gitfourchette.blameview.blamewindow import BlameWindow

        yield from self.flowEnterWorkerThread()
        repo = self.repo
        head = repo.head_commit_id
        showCommit = seed

        if seed == NULL_OID:
            fileStatus = repo.status_file(path)
            if fileStatus & (FileStatus.WT_NEW | FileStatus.INDEX_NEW):
                raise AbortTask(_("File {0} has no history in the repository.", hquoe(path)))

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

        seedCommit = repo.peel_commit(seed)

        if seed == head:
            try:
                seedCommit = Trace.makeWorkdirMockCommit(repo, path)
                seed = seedCommit.id
                assert seed == UC_FAKEID
            except KeyError:
                pass

        # Trace commit in branch
        with Benchmark("trace"):
            trace = Trace(path, seedCommit,
                          skimInterval=self.TraceSkimInterval,
                          progressCallback=progress.reportTraceProgress)

        yield from self.flowEnterUiThread()
        progress.setRange(0, len(trace))
        progress.setValue(0)

        # Annotate file
        yield from self.flowEnterWorkerThread()
        with Benchmark("blame"):
            trace.annotate(repo, progressCallback=progress.reportBlameProgress)

        blameModel = BlameModel(self.repoModel, trace, self.parentWidget())

        yield from self.flowEnterUiThread()

        blameWindow = BlameWindow(blameModel)

        try:
            startNode = blameModel.trace.nodeForCommit(showCommit)
        except KeyError:
            startNode = blameModel.trace.first
        blameWindow.setTraceNode(startNode)

        windowHeight = int(QApplication.primaryScreen().availableSize().height() * .8)
        windowWidth = blameWindow.textEdit.gutter.calcWidth() + blameWindow.textEdit.fontMetrics().horizontalAdvance("M" * 81) + blameWindow.textEdit.verticalScrollBar().width()
        blameWindow.resize(windowWidth, windowHeight)

        progress.close()
        blameWindow.show()

        self.postStatus = _n("{n} revision annotated.", "{n} revisions annotated.", n=len(trace))

    def onError(self, exc: Exception):
        # TODO: If the task emitted a finished signal, we wouldn't need to keep a reference to the progress dialog around.
        self.progressDialog.close()
        super().onError(exc)


class _BlameProgressDialog(QProgressDialog):
    traceProgress = Signal(int)
    blameProgress = Signal(int)

    def __init__(self, parent):
        super().__init__(parent)
        self.setLabelText(_("Please wait…"))
        self.setRange(0, 0)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(self.fontMetrics().horizontalAdvance('W' * 40))

        # Delay progress popup to avoid flashing when blaming is fast enough.
        # (In unit tests, show it immediately for code coverage.)
        self.delayedProgress = QTimer(self)
        self.delayedProgress.timeout.connect(self.show)
        self.delayedProgress.setSingleShot(True)
        self.delayedProgress.start(200 if not APP_TESTMODE else 0)

        self.traceProgress.connect(self._showTraceProgress)
        self.blameProgress.connect(self._showBlameProgress)

    def close(self) -> bool:
        assert onAppThread()
        self.delayedProgress.stop()
        didClose = super().close()
        if didClose:
            self.setParent(None)  # let it be garbage collected
        return didClose

    def reportTraceProgress(self, n):
        self._reportProgressFromWorkerThread(self.traceProgress, n)

    def reportBlameProgress(self, n):
        self._reportProgressFromWorkerThread(self.blameProgress, n)

    def _reportProgressFromWorkerThread(self, signal: Signal, *args):
        # If the user has hit the cancel button from the UI thread,
        # interrupt the worker thread.
        if self.wasCanceled():
            raise AbortTask()

        # Pass progress message to UI thread.
        signal.emit(*args)

        # Due to the GIL, only a single piece of Python code will ever run
        # simultaneously. This mini sleep (on the worker thread) gives some
        # breathing room for the UI thread to keep the progress dialog
        # responsive. This doesn't slow down the worker thread too much.
        QThread.msleep(1)

    def _showTraceProgress(self, n: int):
        assert onAppThread()
        if n > 0:
            self.setLabelText(_n("Found {n} revision…", "Found {n} revisions…", n=n))

    def _showBlameProgress(self, n: int):
        assert onAppThread()
        self.setLabelText(_("Annotating revision {0} of {1}…", n, self.maximum()))
        self.setValue(n)
