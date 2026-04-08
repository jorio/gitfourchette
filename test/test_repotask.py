# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from collections.abc import Generator

import pytest

from gitfourchette.tasks import RepoTask, RepoTaskRunner
from .util import *


class SupportingWidget(QLabel):
    cleanup = Signal()

    def __init__(self):
        super().__init__(None)

        self.setContentsMargins(32, 32, 32, 32)
        self.setText("<h3>Supporting widget for RepoTaskRunner")

        self.taskRunner = RepoTaskRunner(self)
        self.cleanup.connect(self.taskRunner.prepareForDeletion)

    def closeEvent(self, event):
        self.cleanup.emit()
        super().closeEvent(event)


@pytest.fixture
def taskRunner(qapp) -> Generator[RepoTaskRunner, None, None]:
    widget = SupportingWidget()
    widget.show()
    assert not widget.taskRunner.isBusy()
    yield widget.taskRunner
    widget.deleteLater()


def testTaskKilled(taskRunner):
    parentWidget: QWidget = taskRunner.parent()

    class HelloA(RepoTask):
        def flow(self):
            yield from self.flowConfirm("HelloA-1")
            yield from self.flowConfirm("HelloA-2")

    HelloA.invoke(taskRunner)
    taskRunner.killCurrentTask()
    acceptQMessageBox(parentWidget, "HelloA-1")
    with pytest.raises(KeyError):
        acceptQMessageBox(parentWidget, "HelloA-2")


def testTaskKillOtherTask(taskRunner):
    parentWidget: QWidget = taskRunner.parent()

    class HelloA(RepoTask):
        def flow(self):
            yield from self.flowConfirm("HelloA-1")
            yield from self.flowConfirm("HelloA-2")

    class HelloB(RepoTask):
        def canKill(self, task: RepoTask) -> bool:
            return isinstance(task, HelloA)

        def flow(self):
            yield from self.flowConfirm("HelloB")

    HelloA.invoke(taskRunner)
    HelloB.invoke(taskRunner)

    acceptQMessageBox(parentWidget, "HelloA-1")
    acceptQMessageBox(parentWidget, "HelloB")


def testTaskQueueing(taskRunner):
    parentWidget: QWidget = taskRunner.parent()

    class HelloA(RepoTask):
        def flow(self):
            yield from self.flowConfirm("HelloA")

    class HelloB(RepoTask):
        def flow(self):
            yield from self.flowConfirm("HelloB")

    class HelloC(RepoTask):
        def flow(self):
            yield from self.flowConfirm("HelloC")

    HelloA.invoke(taskRunner)

    # Can only queue a single task at once - HelloC will override HelloB
    HelloB.invoke(taskRunner)
    HelloC.invoke(taskRunner)

    acceptQMessageBox(parentWidget, "HelloA")
    acceptQMessageBox(parentWidget, "HelloC")


def testTaskQueueingAbortedByClosedParent(taskRunner, taskThread):
    parentWidget: QWidget = taskRunner.parent()

    class HelloA(RepoTask):
        def flow(self):
            waitMillis = 3_000
            sleepUnit = 100
            for _dummy in range(waitMillis // sleepUnit):
                print("Waiting...", _dummy)
                yield from self.flowEnterWorkerThread()
                QThread.msleep(sleepUnit)
            yield from self.flowEnterUiThread()
            yield from self.flowConfirm("this should not appear A")

    class HelloB(RepoTask):
        def flow(self):
            yield from self.flowConfirm("this should not appear B")

    # Start HelloA, wait for background thread to start
    assert not taskRunner._workerThread.isRunning()
    HelloA.invoke(taskRunner)
    waitUntilTrue(taskRunner._workerThread.isRunning)

    # Enqueue HelloB
    HelloB.invoke(taskRunner)

    # While HelloA is still running and HelloB is pending, close the widget
    parentWidget.close()

    # Wait for task runner to wind down
    waitUntilTrue(lambda: not taskRunner.isBusy())
    assert not parentWidget.isVisible()

    # Make sure BOTH tasks were properly interrupted
    with pytest.raises(KeyError):
       acceptQMessageBox(parentWidget, "this should not appear")
