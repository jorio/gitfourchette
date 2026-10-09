# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Exercise ProcessWrapper (via RepoTask.flowStartProcess) with arbitrary
(non-Git) processes that fail in various ways.
"""

import sys

import pytest

from gitfourchette.tasks import RepoTask
from .util import *


class RunPythonProcess(RepoTask):
    """
    Run a Python snippet in a child process. The outcome is recorded in
    the `results` list passed to the task.
    """

    def flow(self, results: list, script: str, autoFail: bool = True, stdin: str = "", program: str = ""):
        process = QProcess(self)
        process.setProgram(program or sys.executable)
        process.setArguments(["-c", script])
        yield from self.flowStartProcess(process, autoFail=autoFail, stdin=stdin)
        stdout = process.readAllStandardOutput().data().decode()
        results.append((process.exitStatus(), process.exitCode(), stdout))


class RunPythonProcessInterruptible(RunPythonProcess):
    """
    Freely-interruptible tasks don't wait synchronously for the process to
    start or finish, so this forces the coroutine to pause/resume.
    """

    def isFreelyInterruptible(self) -> bool:
        return True


TaskClasses = [RunPythonProcess, RunPythonProcessInterruptible]


def runTask(rw, taskClass, *args, **kwargs) -> list:
    results = []
    taskClass.invoke(rw, results, *args, **kwargs)
    waitUntilTrue(lambda: not rw.taskRunner.isBusy())
    return results


@pytest.mark.parametrize("taskClass", TaskClasses)
def testProcessSucceeds(tempDir, mainWindow, taskClass):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    script = "import time; time.sleep(.2); print('hello')"
    results = runTask(rw, taskClass, script)
    assert results == [(QProcess.ExitStatus.NormalExit, 0, "hello\n")]


@pytest.mark.parametrize("taskClass", TaskClasses)
def testProcessWithStdin(tempDir, mainWindow, taskClass):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    # The child reads stdin to EOF, so the write channel must be closed for the process to finish
    script = "import sys; sys.stdout.write(sys.stdin.read().upper())"
    results = runTask(rw, taskClass, script, stdin="hello stdin")
    assert results == [(QProcess.ExitStatus.NormalExit, 0, "HELLO STDIN")]


@pytest.mark.parametrize("taskClass", TaskClasses)
@pytest.mark.parametrize("stderr", ["", "something went horribly wrong"])
def testProcessFailsWithAutoFail(tempDir, mainWindow, taskClass, stderr):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    script = f"import sys, time; time.sleep(.1); sys.stderr.write({stderr!r}); sys.exit(3)"
    results = runTask(rw, taskClass, script)

    # The task must have been aborted before recording any results
    assert results == []

    qmb = findQMessageBox(rw, r"process.+exited with code 3")
    assert ("horribly wrong" in qmb.text()) == bool(stderr)
    assert "-c" in qmb.detailedText()  # full command line in details
    qmb.accept()


@pytest.mark.parametrize("taskClass", TaskClasses)
def testProcessFailsWithoutAutoFail(tempDir, mainWindow, taskClass):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    script = "import sys; print('partial output'); sys.stderr.write('oops'); sys.exit(5)"
    results = runTask(rw, taskClass, script, autoFail=False)

    # The task carries on despite the non-zero exit code, without any dialogs
    assert results == [(QProcess.ExitStatus.NormalExit, 5, "partial output\n")]
    with pytest.raises(KeyError):
        findQMessageBox(rw, "exited with code")


@pytest.mark.skipif(WINDOWS, reason="POSIX signals")
@pytest.mark.parametrize("taskClass", TaskClasses)
def testProcessCrashes(tempDir, mainWindow, taskClass):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    script = "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"

    # Without autoFail, the task can inspect the crash itself
    results = runTask(rw, taskClass, script, autoFail=False)
    assert len(results) == 1
    assert results[0][0] == QProcess.ExitStatus.CrashExit

    # With autoFail, a crashed process (non-zero exit code) aborts the task
    results = runTask(rw, taskClass, script)
    assert results == []
    acceptQMessageBox(rw, r"process.+exited with code")


@pytest.mark.parametrize("taskClass", TaskClasses)
def testProcessFailsToStart(tempDir, mainWindow, taskClass):
    wd = unpackRepo(tempDir)
    rw = mainWindow.openRepo(wd)

    bogusProgram = f"{tempDir.name}/this-program-does-not-exist"
    results = runTask(rw, taskClass, "print('hello')", program=bogusProgram)
    assert results == []

    qmb = findQMessageBox(rw, r"couldn.t start process")
    assert "this-program-does-not-exist" in qmb.text()
    qmb.accept()
