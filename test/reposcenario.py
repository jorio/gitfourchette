# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from .util import *
from gitfourchette.porcelain import *


def fileWithStagedAndUnstagedChanges(path):
    shell("""
        echo 'a1\nstaged change' > a/a1.txt
        git add a/a1.txt
        echo 'a1\nUNSTAGED CHANGE TO REVERT\nstaged change' > a/a1.txt
    """, path)


def stagedNewEmptyFile(path):
    shell("""
        touch SomeNewFile.txt
        git add SomeNewFile.txt
    """, path)


def stashedChange(path):
    shell("""
        echo 'a1\nPENDING CHANGE' > a/a1.txt
        git stash -m 'helloworld'
    """, path)


def statelessConflictingChange(path):
    """
    Cause a conflict via a stash in order to keep RepositoryState.NONE
    """
    shell("""
        echo 'a1\nPENDING CHANGE' > a/a1.txt
        git stash -m 'helloworld'
        echo 'a1\nCONFLICTING CHANGE' > a/a1.txt
        git add a/a1.txt
        git commit -m 'conflicting thing'
        git stash pop || true
    """, path)


def submodule(path: str, absorb=False) -> tuple[str, Oid]:
    subPath = os.path.join(path, "submodir")
    shutil.copytree(path, subPath)

    # Make bare copy of submodule so that we can use it as a remote and test UpdateSubmodule
    subRemotePath = makeBareCopy(subPath, "submo-localfs", preFetch=True, barePath=f"{path}/../submodule-bare-copy.git")

    shell("""
        git remote remove origin || true  # nuke origin remote to prevent net access in UpdateSubmodule
        git branch --set-upstream-to=submo-localfs/master master
    """, subPath)

    shell(f"""
        # Give submodule a custom name that is different from the path to reveal edge cases
        git submodule add --name submoname -- {shlex.quote(subRemotePath)} submodir
        # Absorb (commented out if absorb=False)
        {"#" if not absorb else ""} git submodule absorbgitdirs -- submodir
        git commit -m 'Add Submodule for Test Purposes'
    """, path)

    with RepoContext(path) as repo:
        subAddCommit = repo.head_commit_id

    if WINDOWS:
        subPath = subPath.replace("\\", "/")

    return subPath, subAddCommit
