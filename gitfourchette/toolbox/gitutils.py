# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os
import re
from contextlib import suppress

from gitfourchette.porcelain import *
from gitfourchette.qt import *
from gitfourchette.trtables import TrTables

INITIALS_PATTERN = re.compile(r"(?:^|[\s\-.'‘’\"“”])+([^\s\-.'‘’\"“”])[^\s\-.]*")
FIRST_NAME_PATTERN = re.compile(r"(\S(\.?-|\.\s?|\s))*\S+")
WINDOWS_PATH_PATTERN = re.compile(r"^[A-Za-z]:[/\\]")

REMOTE_URL_PATTERNS = [
    # HTTP/HTTPS
    # http://example.com/user/repo
    # https://example.com/user/repo
    # https://personal_access_token@example.com/user/repo (GitHub write access over HTTPS)
    re.compile(r"^(?P<protocol>https?):\/\/(?P<user>[^@/]+@)?(?P<host>[^\/]+?)\/(?P<path>.+)"),

    # SSH (scp-like syntax)
    # example.com:user/repo
    # git@example.com:user/repo
    re.compile(r"^(?P<user>[^@/]+@)?(?P<host>[^\/]+?):(?!\/)(?P<path>.+)"),

    # SSH (full syntax)
    # ssh://example.com/user/repo
    # ssh://git@example.com/user/repo
    # ssh://git@example.com:1234/user/repo
    re.compile(r"^(?P<protocol>ssh):\/\/(?P<user>[^@/]+@)?(?P<host>[^\/]+?)(:\d+)?\/(?P<path>.+)"),

    # Git protocol
    # git://example.com/user/repo
    # git://example.com:1234/user/repo
    re.compile(r"^(?P<protocol>git):\/\/(?P<host>[^\/]+?)(:\d+)?\/(?P<path>.+)"),
]


class AuthorDisplayStyle(enum.IntEnum):
    FullName = 1
    FirstName = 2
    LastName = 3
    Initials = 4
    FullEmail = 5
    EmailUserName = 6


@enum.unique
class PatchPurpose(enum.IntFlag):
    Stage = enum.auto()
    Unstage = enum.auto()
    Discard = enum.auto()

    Lines = enum.auto()
    Hunk = enum.auto()
    File = enum.auto()

    VerbMask = Stage | Unstage | Discard


def abbreviatePerson(sig: Signature, style: AuthorDisplayStyle = AuthorDisplayStyle.FullName):
    with suppress(IndexError):
        if style == AuthorDisplayStyle.FullName:
            return sig.name

        elif style == AuthorDisplayStyle.FirstName:
            match = FIRST_NAME_PATTERN.match(sig.name)
            return match[0] if match is not None else sig.name

        elif style == AuthorDisplayStyle.LastName:
            return sig.name.rsplit(' ', maxsplit=1)[-1]

        elif style == AuthorDisplayStyle.Initials:
            return re.sub(INITIALS_PATTERN, r"\1", sig.name)

        elif style == AuthorDisplayStyle.FullEmail:
            return sig.email

        elif style == AuthorDisplayStyle.EmailUserName:
            emailParts = sig.email.split('@', 1)
            if len(emailParts) == 2 and emailParts[1] == "users.noreply.github.com":
                # Strip ID from GitHub noreply addresses (1234567+username@users.noreply.github.com)
                return emailParts[0].split('+', 1)[-1]
            else:
                return emailParts[0]

    return sig.email


def shortHash(oid: Oid | str) -> str:
    from gitfourchette.settings import prefs
    return str(oid)[:prefs.shortHashChars]


def dumpTempBlob(
        repo: Repo,
        dir: str,
        entry: DiffFile | IndexEntry | None,
        inBrackets: str):

    # In merge conflicts, the IndexEntry may be None (for the ancestor, etc.)
    if not entry:
        return ""

    blobId = entry.id
    blob = repo.peel_blob(blobId)
    name, ext = os.path.splitext(os.path.basename(entry.path))
    name = f"[{inBrackets}]{name}{ext}"
    path = os.path.join(dir, name)
    with open(path, "wb") as f:
        f.write(blob.data)

    """
    # Make it read-only (this will probably not work on Windows)
    mode = os.stat(path).st_mode
    readOnlyMask = ~(stat.S_IWRITE | stat.S_IWGRP | stat.S_IWOTH)
    os.chmod(path, mode & readOnlyMask)
    """

    return path


def nameValidationMessage(name: str, reservedNames: list[str], nameTakenMessage: str = "") -> str:
    try:
        validate_refname(name, reservedNames)
    except NameValidationError as exc:
        if exc.rule == NameValidationError.Rule.NAME_TAKEN_BY_REF and nameTakenMessage:
            return nameTakenMessage
        else:
            return TrTables.enum(exc.rule)

    return ""  # validation passed, no error


def simplifyOctalFileMode(m: int):
    if m in [FileMode.BLOB, FileMode.BLOB_EXECUTABLE]:
        m &= ~0o100000
    return m


def remoteUrlProtocol(url: str):
    # Bail early on Windows-style absolute paths (C:\Whatever) to avoid looking like an ssh url
    if WINDOWS_PATH_PATTERN.match(url):
        return ""

    for pattern in REMOTE_URL_PATTERNS:
        m = pattern.match(url)
        if m:
            try:
                return m.group("protocol")
            except IndexError:
                return "ssh"
    return ""


def splitRemoteUrl(url: str):
    for pattern in REMOTE_URL_PATTERNS:
        m = pattern.match(url)
        if m:
            host = m.group("host")
            path = m.group("path")
            return host, path
    return "", ""


def stripRemoteUrlPath(url: str):
    for pattern in REMOTE_URL_PATTERNS:
        m = pattern.match(url)
        if m:
            path = m.group("path")
            return url.removesuffix(path)
    return ""


def guessRemoteUrlFromText(text: str):
    if len(text) > 128:
        return ""

    text = text.strip()

    if any(c.isspace() for c in text):
        return ""

    host, path = splitRemoteUrl(text)
    if host and path:
        return text

    return ""


def formatTimeOffset(minutes: int):
    p = "-" if minutes < 0 else "+"
    h = abs(minutes) // 60
    m = abs(minutes) % 60
    return f"{p}{h:02}:{m:02}"


def signatureQDateTime(signature: Signature, localTime=False) -> QDateTime:
    if localTime:
        return QDateTime.fromSecsSinceEpoch(signature.time)
    else:
        return QDateTime.fromSecsSinceEpoch(signature.time, QTimeZone(signature.offset * 60))


def signatureDateFormat(
        signature: Signature,
        format: str | QLocale.FormatType = QLocale.FormatType.LongFormat,
        localTime=False
) -> str:
    dateTime = signatureQDateTime(signature, localTime)
    text = QLocale().toString(dateTime, format)
    if not localTime and format != QLocale.FormatType.LongFormat:
        text += f" ({formatTimeOffset(signature.offset)})"
    return text
