# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import html
import io
import re
import signal
from enum import StrEnum

from gitfourchette import colors
from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.porcelain import version_to_tuple
from gitfourchette.qt import *


def argsIf(condition: bool, *args: str) -> tuple[str, ...]:
    if condition:
        return args
    else:
        return ()


class VanillaFetchStatusFlag(StrEnum):
    FastForward = " "
    ForcedUpdate = "+"
    PrunedRef = "-"
    TagUpdate = "t"
    NewRef = "*"
    Rejected = "!"
    UpToDate = "="


class GitDriver(QProcess):
    _gitPath = "/usr/bin/git"
    _cachedGitVersion = ""

    progressMessage = Signal(str)
    progressFraction = Signal(int, int)

    @classmethod
    def setGitPath(cls, gitPath: str):
        cls._gitPath = gitPath
        cls._cachedGitVersion = ""

    @classmethod
    def gitVersion(cls) -> str:
        if cls._cachedGitVersion:
            return cls._cachedGitVersion

        text = ToolCommands.runSync(cls._gitPath, "version")
        text = text.removeprefix("git version").strip()
        cls._cachedGitVersion = text
        return text

    @classmethod
    def gitVersionTuple(cls) -> tuple[int, ...]:
        text = cls.gitVersion()
        try:
            numberStr = text.split(maxsplit=1)[0]
        except IndexError:
            numberStr = "0"
        return version_to_tuple(numberStr)

    @classmethod
    def supportsFetchPorcelain(cls) -> bool:
        # fetch --porcelain is only available since git 2.41 (June 2023)
        # Ubuntu 22.04 LTS ships with git 2.34.1.
        # macOS 15 ships with git 2.39.5.
        return cls.gitVersionTuple() >= (2, 41)

    @classmethod
    def parseTable(cls, pattern: str, stdout: str, linesep="\n", strict=True) -> list:
        table = []

        stdout = stdout.removesuffix(linesep)

        for line in stdout.split(linesep):
            match = re.match(pattern, line)

            if match is None:
                if strict:
                    raise ValueError("table line does not match pattern: " + line)
                else:
                    continue

            table.append(match.groups())

        return table

    @classmethod
    def parseProgress(cls, stderr: bytes | str) -> tuple[str, int, int]:
        text = ""
        num = -1
        denom = -1

        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        lines = stderr.splitlines()

        if lines:
            # Report last line
            text = lines[-1]

            # Look for a fraction, e.g. "(50/1000)"
            for line in lines:
                fractionMatch = re.search(r"\((\d+)/(\d+)\)", line)
                if fractionMatch:
                    num = int(fractionMatch.group(1))
                    denom = int(fractionMatch.group(2))

        return text, num, denom

    @classmethod
    def reformatHintText(cls, stderr: str):
        previousTag = ""
        parts = []

        for stderrLine in stderr.splitlines():
            try:
                tag, text = stderrLine.split(":", 1)
                tag = html.escape(tag)
                text = html.escape(text)
            except ValueError:
                tag, text = "", stderrLine

            if tag != previousTag:
                if parts:
                    parts.append("<br>")
                if tag:
                    parts.append(f"<b>{tag}:</b>")

            parts.append(text)
            previousTag = tag

        return "".join(parts)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.setObjectName("GitDriver")
        self.readyReadStandardError.connect(self._onReadyReadStandardError)
        self._stderrScrollback = io.BytesIO()
        self._stdout = None

    def _onReadyReadStandardError(self):
        raw = self.readAllStandardError().data()
        self._stderrScrollback.write(raw)

        text, num, denom = GitDriver.parseProgress(raw)
        if text:
            self.progressMessage.emit(text)
        if num >= 0 and denom >= 0:
            self.progressFraction.emit(num, denom)

    def stderrScrollback(self) -> str:
        return '\n'.join(
            line.rstrip().decode("utf-8", errors="replace")
            for line in self._stderrScrollback.getvalue().splitlines(keepends=True)
            if not line.endswith(b"\r")
        )

    def stdoutScrollback(self) -> str:
        if self._stdout is None:
            self._stdout = self.readAllStandardOutput().data().decode("utf-8", errors="replace")
        return self._stdout

    def readPostCommitInfo(self) -> tuple[str, str]:
        # [master 123abc]
        # [master (root-commit) 123abc]
        # [detached HEAD 123abc]
        stdout = self.stdoutScrollback()
        match = re.match(r"^\[(.+)\s+([\da-f]+)]", stdout, re.I)
        if not match:
            raise ValueError("couldn't parse post-commit stdout: " + stdout.splitlines()[0])
        branchName = match.group(1)
        commitHash = match.group(2)
        return branchName, commitHash

    def formatExitCode(self) -> str:
        code = self.exitCode()
        try:
            s = signal.Signals(code)
            return f"{code} ({s.name})"
        except ValueError:
            return f"{code}"

    def htmlErrorText(self, subtitle: str = "", reformatHintText=False) -> str:
        from gitfourchette.localization import _
        from gitfourchette.toolbox import escape

        stderr = self.stderrScrollback().strip()
        if reformatHintText:
            stderr = self.reformatHintText(stderr)
        elif stderr:
            stderr = escape(stderr)

        if subtitle:
            subtitle = f"<p>{subtitle}</p>"

        headerColor = colors.red if self.exitCode() != 0 else colors.olive

        return "".join([
            "<html style='white-space: pre-wrap;'>"
            f"<p style='color: {headerColor.name()};'>",
            _("Git command exited with code {0}.", self.formatExitCode()),
            "</p>",
            subtitle,
            "<small>",
            stderr,
            "</html>"
        ])
