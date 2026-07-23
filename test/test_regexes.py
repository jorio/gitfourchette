# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.gitdriver import GitDeltaSource, GitConflict, GitConflictSides, GitDelta
from gitfourchette.porcelain import FileMode, Signature
from gitfourchette.toolbox import abbreviatePerson, AuthorDisplayStyle
from gitfourchette.webhost import WebHost

from .util import pygit2OlderThan

EXAMPLE_REMOTE_URLS = [
    "https://example.com/user/repo",
    "https://personal!access_token-1234@example.com/user/repo",
    "example.com:user/repo",
    "example.com:user/repo.git",
    "git@example.com:user/repo",
    "git@example.com:user/repo.git",
    "git!1234@example.com:user/repo",
    "ssh://example.com/user/repo",
    "ssh://git@example.com/user/repo",
    "ssh://git@example.com:1234/user/repo",
    "ssh://git_1234@example.com:1234/user/repo",
    "ssh://git!1234@example.com:1234/user/repo",
    "git://example.com/user/repo",
    "git://example.com:1234/user/repo",
]


AUTHOR_ABBREVIATIONS = {
    "Jean-Machin Truc"      : ("JMT", "Jean-Machin", "Truc"),
    "Jean Machin Truc"      : ("JMT", "Jean", "Truc"),
    "J Machin Truc"         : ("JMT", "J Machin", "Truc"),
    "J Machin von Truc"     : ("JMvT", "J Machin", "Truc"),
    "J. Machin Truc"        : ("JMT", "J. Machin", "Truc"),
    "J.Machin Truc"         : ("JMT", "J.Machin", "Truc"),
    "J. Machin B. Truc"     : ("JMBT", "J. Machin", "Truc"),
    "J. Machin B.Truc"      : ("JMBT", "J. Machin", "B.Truc"),
    "J. Machin Bidu-Truc"   : ("JMBT", "J. Machin", "Bidu-Truc"),
    "Jean-Mac' Truc"        : ("JMT", "Jean-Mac'", "Truc"),
    "Jean Mac' Truc"        : ("JMT", "Jean", "Truc"),
    "Jean \"Mac\" Truc"     : ("JMT", "Jean", "Truc"),
    "Jean “Mac” Truc"       : ("JMT", "Jean", "Truc"),
    "’Ean Truc"             : ("ET",  "’Ean", "Truc"),
    "‘Ean Truc"             : ("ET",  "‘Ean", "Truc"),
    "“Jean” Truc"           : ("JT",  "“Jean”", "Truc"),
    ".Jean Truc"            : ("JT", ".Jean", "Truc"),
    "Je.an Truc"            : ("JaT", "Je.an", "Truc"),
    "Je'an Truc"            : ("JT", "Je'an", "Truc"),
    "Jean 'chin Truc"       : ("JcT", "Jean", "Truc"),
    "Jean-'chin Truc"       : ("JcT", "Jean-'chin", "Truc"),
    "abc"                   : ("a", "abc", "abc"),
    "."                     : (".", ".", "."),
    # Skipping cases like 'Ean Truc or "Jean" Truc because
    # pygit2.Signature eats first quote character in full names.
}


GIT_VERBS = {
    "git cherry-pick"                           : "cherry-pick",
    "git cherry-pick args"                      : "cherry-pick",
    "/usr/bin/git cherry-pick"                  : "cherry-pick",
    "'/usr/bin/git' cherry-pick"                : "cherry-pick",
    "git -c config.item cherry-pick"            : "cherry-pick",
    "'c:\\program files\\git.EXE' cherry-pick"  : "cherry-pick",
    '"c:\\program files\\git.exe" cherry-pick'  : "cherry-pick",
    "git lfs smudge"                            : "lfs smudge",
    "git submodule update"                      : "submodule update",
}


@pytest.mark.parametrize("exampleUrl", EXAMPLE_REMOTE_URLS)
def testWebHostRegexes(exampleUrl):
    remoteUrl = exampleUrl
    web, host = WebHost.makeLink(remoteUrl)
    assert host == "example.com"
    assert web == "https://example.com/user/repo"

    # Test fallback branch URL
    web, host = WebHost.makeLink(remoteUrl, "branch")
    assert host == "example.com"
    assert web == "https://example.com/user/repo/tree/branch"

    # Test a couple predefined hosts
    remoteUrl = exampleUrl.replace("example.com", "github.com")
    web, host = WebHost.makeLink(remoteUrl, "branch")
    assert host == "GitHub"
    assert web == "https://github.com/user/repo/tree/branch"

    remoteUrl = exampleUrl.replace("example.com", "codeberg.org")
    web, host = WebHost.makeLink(remoteUrl, "branch")
    assert host == "Codeberg"
    assert web == "https://codeberg.org/user/repo/src/branch/branch"


@pytest.mark.skipif(pygit2OlderThan("1.15.1"), reason="old pygit2")
@pytest.mark.parametrize("fullName", AUTHOR_ABBREVIATIONS.keys())
def testAuthorNameAbbreviation(fullName):
    initials, firstName, lastName = AUTHOR_ABBREVIATIONS[fullName]
    sig = Signature(fullName, "hello@example.com", 0, 0)

    assert abbreviatePerson(sig, AuthorDisplayStyle.FullName) == fullName
    assert abbreviatePerson(sig, AuthorDisplayStyle.FirstName) == firstName
    assert abbreviatePerson(sig, AuthorDisplayStyle.LastName) == lastName
    assert abbreviatePerson(sig, AuthorDisplayStyle.Initials) == initials
    assert abbreviatePerson(sig, AuthorDisplayStyle.FullEmail) == "hello@example.com"
    assert abbreviatePerson(sig, AuthorDisplayStyle.EmailUserName) == "hello"


@pytest.mark.parametrize("command", GIT_VERBS.keys())
def testGitVerbPattern(command):
    from gitfourchette.forms.statusform import _gitVerbPattern
    match = _gitVerbPattern.search(command)
    assert match
    assert match.group(1) == GIT_VERBS[command]


def testGitStatusPatterns(tempDir):
    from gitfourchette.gitdriver.parsers import parseGitStatus
    from gitfourchette.gitdriver import GitDeltaFile

    aaaa = 'a'*40
    bbbb = 'b'*40
    ffff = 'f'*40
    zzzz = '0'*40
    FM = FileMode
    S = GitDeltaSource

    status = (
        f"1 M. N... 100644 100755 100755 {aaaa} {bbbb} hello world\x00"
        f"2 R. N... 100644 100644 100644 {aaaa} {bbbb} R66 new name\x00old name\x00"
        f"1 MD N... 100644 100644 000000 {aaaa} {bbbb} foo\x00"
        f"1 .M S..U 160000 160000 160000 {aaaa} {aaaa} submo1\x00"
        f"1 .M SC.. 160000 160000 160000 {aaaa} {aaaa} submo2\x00"
        f"1 MM S.M. 160000 160000 160000 {aaaa} {bbbb} submo3\x00"
        f"u AA N... 000000 100644 120000 100755 {zzzz} {aaaa} {bbbb} added by both\x00"
        f"? untracked file\x00"
        f"! ignored file\x00"
    )

    result = list(parseGitStatus(status, tempDir.name))

    (
        result_1_Mx,
        result_2_Rx,
        result_1_MD,
        result_1_xM_SxxU,
        result_1_xM_SCxx,
        result_1_MM_SxMx,
        result_conflict,
        result_untracked,
        result_ignored,
    ) = result

    sd, ud = result_1_Mx
    assert sd == GitDelta(
        "M",
        GitDeltaFile("hello world", aaaa, FM.BLOB, S.Commit),
        GitDeltaFile("hello world", bbbb, FM.BLOB_EXECUTABLE, S.Index))
    assert ud is None

    sd, ud = result_2_Rx
    assert sd == GitDelta(
        "R",
        GitDeltaFile("old name", aaaa, FM.BLOB, S.Commit),
        GitDeltaFile("new name", bbbb, FM.BLOB, S.Index),
        similarity=66)
    assert ud is None

    sd, ud = result_1_MD
    assert sd == GitDelta(
        "M",
        GitDeltaFile("foo", aaaa, FM.BLOB, S.Commit),
        GitDeltaFile("foo", bbbb, FM.BLOB, S.Index))
    assert ud == GitDelta(
        "D",
        GitDeltaFile("foo", bbbb, FM.BLOB, S.Index),
        GitDeltaFile("foo", zzzz, FM.UNREADABLE, S.Dirty))

    sd, ud = result_1_xM_SxxU
    assert sd is None
    assert ud == GitDelta(
        "M",
        GitDeltaFile("submo1", aaaa, FM.COMMIT, S.Index),
        GitDeltaFile("submo1", ffff, FM.COMMIT, S.Dirty),
        submoduleStatus="S..U")
    assert ud.submoduleWorkdirDirty
    # TODO: Is FFFF misleading here? The head did not move ("C" not in submoduleStatus)

    sd, ud = result_1_xM_SCxx
    assert sd is None
    assert ud == GitDelta(
        "M",
        GitDeltaFile("submo2", aaaa, FM.COMMIT, S.Index),
        GitDeltaFile("submo2", ffff, FM.COMMIT, S.Dirty),
        submoduleStatus="SC..")
    assert not ud.submoduleWorkdirDirty

    sd, ud = result_1_MM_SxMx
    assert sd == GitDelta(
        "M",
        GitDeltaFile("submo3", aaaa, FM.COMMIT, S.Commit),
        GitDeltaFile("submo3", bbbb, FM.COMMIT, S.Index))
    assert ud == GitDelta(
        "M",
        GitDeltaFile("submo3", bbbb, FM.COMMIT, S.Index),
        GitDeltaFile("submo3", ffff, FM.COMMIT, S.Dirty),
        submoduleStatus="S.M.")
    assert not sd.submoduleWorkdirDirty
    assert ud.submoduleWorkdirDirty

    sd, ud = result_conflict
    assert sd is None
    assert ud == GitDelta(
        "U",
        GitDeltaFile("added by both", zzzz, FM.UNREADABLE, S.Index),
        GitDeltaFile("added by both", ffff, FM.BLOB_EXECUTABLE, S.Dirty),
        conflict=GitConflict(
            GitConflictSides.BothAdded,
            GitDeltaFile("added by both", zzzz, FM.UNREADABLE),
            GitDeltaFile("added by both", aaaa, FM.BLOB),
            GitDeltaFile("added by both", bbbb, FM.LINK)),
    )

    sd, ud = result_untracked
    assert sd is None
    assert ud == GitDelta(
        "?",
        GitDeltaFile("untracked file", zzzz, FM.UNREADABLE, S.Index),
        GitDeltaFile("untracked file", ffff, FM.UNREADABLE, S.Dirty))

    sd, ud = result_ignored
    assert sd is None
    assert ud == GitDelta(
        "!",
        GitDeltaFile("ignored file", zzzz, FM.UNREADABLE, S.Index),
        GitDeltaFile("ignored file", ffff, FM.UNREADABLE, S.Dirty))


def testBadGitStatusPatterns(tempDir):
    from gitfourchette.gitdriver.parsers import parseGitStatus

    aaaa = 'a'*40
    bbbb = 'b'*40

    badStatus = [
        "X bad ident\x00",
        "1 M. N... 100644 100644 100644 bad hash pattern\x00",
        f"1 M. N... 990644 100644 100644 {aaaa} {bbbb} bad octal mode\x00",
        f"1 M. N... 100644 100644 100644 {aaaa} {bbbb} bad terminator\n",
    ]

    for s in badStatus:
        with pytest.raises(ValueError):
            _dummy = list(parseGitStatus(s, tempDir.name))
