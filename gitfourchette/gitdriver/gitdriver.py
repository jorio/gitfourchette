# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

import html
import io
import logging
import re
import shlex
import signal
from enum import StrEnum

from gitfourchette import settings
from gitfourchette.exttools.toolcommands import ToolCommands
from gitfourchette.gitdriver.gitdelta import GitDelta
from gitfourchette.gitdriver.parsers import parseGitStatus, parseGitShow
from gitfourchette.nav import NavContext
from gitfourchette.porcelain import version_to_tuple, Commit, Oid
from gitfourchette.qt import *

logger = logging.getLogger(__name__)


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
    _commandStem = ["/usr/bin/git"]

    _cachedGitVersionValid = False
    _cachedGitVersion = ""
    _cachedGitVersionTuple = (0,)

    progressMessage = Signal(str)
    progressFraction = Signal(int, int)

    @classmethod
    def runSync(
            cls,
            *args: str,
            directory: str = "",
            strict: bool = False
    ):
        return ToolCommands.runSync(*cls._commandStem, *args, directory=directory, strict=strict)

    @classmethod
    def setGitPath(cls, gitPath: str):
        cls._commandStem = ToolCommands.splitCommandTokens(gitPath)
        cls._cachedGitVersionValid = False

    @classmethod
    def _cacheGitVersion(cls, rawVersionText: str = ""):
        if cls._cachedGitVersionValid:
            return

        if not rawVersionText:
            rawVersionText = cls.runSync("version")
        text = rawVersionText.removeprefix("git version").strip()

        try:
            numberStr = text.split(maxsplit=1)[0]
        except IndexError:
            numberStr = "0"

        cls._cachedGitVersionValid = True
        cls._cachedGitVersion = text
        cls._cachedGitVersionTuple = version_to_tuple(numberStr)

    @classmethod
    def gitVersion(cls) -> str:
        cls._cacheGitVersion()
        return cls._cachedGitVersion

    @classmethod
    def gitVersionTuple(cls) -> tuple[int, ...]:
        cls._cacheGitVersion()
        return cls._cachedGitVersionTuple

    @classmethod
    def supportsFetchPorcelain(cls) -> bool:
        # fetch --porcelain is only available since git 2.41 (June 2023)
        # Ubuntu 22.04 LTS ships with git 2.34.1.
        # Debian 12 and macOS 15 ship with git 2.39.5.
        return cls.gitVersionTuple() >= (2, 41)

    @classmethod
    def supportsDashDashBeforePositionalArgs(cls) -> bool:
        """
        True if git commands that ONLY take positional arguments (no switches)
        will accept a double dash before the argument list.
        Example: 'git remote remove -- <name>'
        (Note: Commands that accept switches always accept '--')
        """
        # Note: I haven't bothered bisecting the exact version of git that
        # introduced support for this. It appeared somewhere between 2.34 and
        # 2.39 (the next version above 2.34 that I easily had access to).
        return cls.gitVersionTuple() >= (2, 39)

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

    def __init__(self, *args: str, parent: QObject | None = None):
        super().__init__(parent)

        self.setObjectName("GitDriver")

        tokens = GitDriver._commandStem + list(args)
        self.setProgram(tokens[0])
        self.setArguments(tokens[1:])

        self.readyReadStandardError.connect(self._onReadyReadStandardError)
        self._stderrScrollback = io.BytesIO()
        self._stdout = None

    def stdoutTable(self, pattern: str, linesep="\n", strict=True) -> list:
        stdout = self.stdoutScrollback()
        return self.parseTable(pattern, stdout, linesep, strict)

    def stdoutTableNumstatZ(self, strict=True) -> list[tuple[str, str, str]]:
        pattern = r"^(-|\d+)\t(-|\d+)\t(.+)$"
        stdout = self.stdoutScrollback()
        return self.parseTable(pattern, stdout, "\0", strict)

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

    def readFetchPorcelainUpdatedRefs(self) -> dict[str, tuple[str, Oid, Oid]]:
        """
        Read a table of updated refs from the output of "git fetch --porcelain".
        Requires git 2.41.
        """
        assert self.supportsFetchPorcelain(), "did you forget to gate this call with GitDriver.supportsFetchPorcelain()?"

        table = self.stdoutTable(r"^(.) ([\da-f]+) ([\da-f]+) (.+)$", strict=False)

        return {
            localRef: (flag, Oid(hex=oldHex), Oid(hex=newHex))
            for flag, oldHex, newHex, localRef in table
        }

    def readStatusPorcelainV2Z(self) -> tuple[int, list[GitDelta], list[GitDelta]]:
        stdout = self.stdoutScrollback()
        parser = parseGitStatus(stdout, self.workingDirectory())
        stagedDeltas = []
        unstagedDeltas = []
        numEntries = 0
        for staged, unstaged in parser:
            numEntries += 1
            if staged is not None:
                stagedDeltas.append(staged)
            if unstaged is not None:
                unstagedDeltas.append(unstaged)
        return numEntries, stagedDeltas, unstagedDeltas

    @classmethod
    def buildShowCommand(cls, oid: Oid):
        return [
            "-c", "core.abbrev=no",
            "show",
            "--diff-merges=1",
            "-z",
            "--raw",
            "--format=",  # skip info about the commit itself
            str(oid),
        ]

    def readShowRawZ(self) -> list[GitDelta]:
        stdout = self.stdoutScrollback()
        deltas = list(parseGitShow(stdout))
        return deltas

    @classmethod
    def buildDiffCommand(
            cls,
            delta: GitDelta | None,
            commit: Commit | None = None,
            binary=True
    ) -> list[str]:
        tokens = [
            "-c", "core.abbrev=no",
            "-c", f"diff.context={settings.prefs.contextLines}",
            "diff",
            *argsIf(binary, "--binary"),
            *argsIf(delta is not None and delta.context == NavContext.STAGED, "--staged"),
        ]

        # Append commits
        if commit is not None:
            assert delta is None or delta.context == NavContext.COMMITTED
            try:
                # Compare to first parent
                firstParent = commit.parent_ids[0]
            except IndexError:
                # Root commit: compare to empty tree (sha1(b"tree \0"))
                firstParent = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
            tokens.append(str(firstParent))
            tokens.append(str(commit.id))

        # Append paths
        if delta is not None:
            if delta.status == "?":  # untracked, compare to nothing
                # --no-index is mandatory on Windows here
                tokens += ["--no-index", "--", "/dev/null", delta.new.path]
            elif delta.old.path != delta.new.path:
                tokens += ["--", delta.old.path, delta.new.path]
            else:
                tokens += ["--", delta.new.path]

        return tokens

    def formatExitCode(self) -> str:
        code = self.exitCode()

        if FLATPAK and code > 128 and self.program() == "flatpak-spawn":
            # flatpak-spawn may shift SIG numbers by 128
            # (for example: 143-128=15, a.k.a. SIGTERM)
            codeForName = code - 128
        else:
            codeForName = code

        if WINDOWS:
            code32 = code & 0xFFFFFFFF
            if code32 == 0xC000013A:
                return f"SIGTERM equivalent (0x{code32:08X})"
            elif code32 == 0xF291:
                return f"SIGKILL equivalent (0x{code32:08X})"
            else:
                return f"{code}"

        try:
            s = signal.Signals(codeForName)
            return f"{code} ({s.name})"
        except ValueError:
            pass

        return f"{code}"

    def formatCommandLine(self):
        return shlex.join([self.program()] + self.arguments())

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

        exitText = self.formatExitCode()
        if self.exitCode() == 0:
            exitText = f"<b><add>{exitText}</b></add>"
        else:
            exitText = f"<b><del>{exitText}</b></del>"

        return "".join([
            "<html style='white-space: pre-wrap;'>",
            settings.prefs.addDelColorsStyleTag(),
            "<p>",
            _("Git command exited with code {0}.", exitText),
            "</p>",
            subtitle,
            "<small>",
            stderr,
            "</html>"
        ])
