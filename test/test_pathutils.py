# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import os
from pathlib import Path

import pytest

from gitfourchette.toolbox.pathutils import HOME, disambiguateTabTitlesByPath


def _tabLabel(*parts: str) -> str:
    if len(parts) == 2:
        return str(Path(*parts))
    return str(Path(parts[0], "…", parts[-1]))


@pytest.mark.parametrize(
    "workdirs, labels",
    [
        pytest.param(
            ["/work/a/app", "/work/b/app"],
            [("a", "app"), ("b", "app")],
            id="adjacent-parent",
        ),
        pytest.param(
            ["/w/a/app", "/w/b/app", "/w/c/app"],
            [("a", "app"), ("b", "app"), ("c", "app")],
            id="three-tabs",
        ),
        pytest.param(
            ["/a/x/y/repo", "/b/x/y/repo"],
            [("a", "…", "repo"), ("b", "…", "repo")],
            id="middle-ellipsis",
        ),
        pytest.param(
            [
                os.path.join(HOME, "nested", "app"),
                os.path.abspath("/work/nested/app"),
            ],
            [("~", "…", "app"), ("work", "…", "app")],
            id="home-vs-absolute",
        ),
        pytest.param(
            ["/a/foo/app", "/b/foo/app"],
            [("a", "…", "app"), ("b", "…", "app")],
            id="shared-intermediate",
        ),
        pytest.param(
            ["/x/foo/v1/app", "/x/bar/v1/app"],
            [("foo", "…", "app"), ("bar", "…", "app")],
            id="deeper-disambiguator",
        ),
    ],
)
def testDisambiguateTabTitlesByPath(workdirs, labels):
    expected = [_tabLabel(*parts) for parts in labels]
    assert disambiguateTabTitlesByPath(workdirs) == expected
