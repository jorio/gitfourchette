# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import pytest

from gitfourchette.toolbox import abbreviatePerson, AuthorDisplayStyle
from gitfourchette.webhost import WebHost
from pygit2 import Signature

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
