# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import html
import io
import re
import shlex
from enum import StrEnum

from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.porcelain import version_to_tuple
from gitfourchette.qt import *


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

        tokens = [cls._gitPath, "version"]
        if FLATPAK:
            tokens = ToolCommands.wrapFlatpakSpawn(tokens, detached=False)

        process = QProcess(None)
        process.setProgram(tokens[0])
        process.setArguments(tokens[1:])
        process.start()
        process.waitForFinished()
        text = process.readAll().data().decode(errors="replace")
        text = text.removeprefix("git version")
        text = text.strip()
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
    def parseTable(cls, pattern: str, stdout: bytes | str, linesep="\n", strict=True) -> list:
        table = []

        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
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
            stderr = stderr.decode(errors="replace")
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
    def reformatHintText(cls, stderr: bytes | str):
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")

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

    @classmethod
    def customSshKeyPreamble(cls, keyFilePath: str, sshCommandBase: str = ""):
        if sshCommandBase:
            sshCommandTokens = shlex.split(sshCommandBase, posix=True)
        else:
            sshCommandTokens = ["/usr/bin/ssh"]
        sshCommand = shlex.join(sshCommandTokens + ["-i", keyFilePath])
        return ["-c", f"core.sshCommand={sshCommand}"]

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.readyReadStandardError.connect(self._onReadyReadStandardError)
        self._stderrScrollback = io.BytesIO()

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
            line.rstrip().decode(errors="replace")
            for line in self._stderrScrollback.getvalue().splitlines(keepends=True)
            if not line.endswith(b"\r")
        )
