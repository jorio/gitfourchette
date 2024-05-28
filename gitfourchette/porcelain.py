from __future__ import annotations as _annotations

import configparser as _configparser
import dataclasses as _dataclasses
import datetime
import enum
import logging as _logging
import os as _os
import re as _re
import shutil as _shutil
import typing as _typing
import warnings
from contextlib import suppress as _suppress
from os.path import (
    abspath as _abspath,
    basename as _basename,
    dirname as _dirname,
    exists as _exists,
    isabs as _isabs,
    isfile as _isfile,
    join as _joinpath,
    normpath as _normpath,
    relpath as _relpath,
)
from pathlib import Path as _Path

from pygit2 import (
    Blob,
    Branch,
    CheckoutCallbacks,
    Commit,
    Config as GitConfig,
    Diff,
    DiffDelta,
    DiffFile,
    DiffLine,
    DiffHunk,
    GitError,
    Keypair,
    IndexEntry,
    InvalidSpecError,
    Oid,
    Patch,
    Remote,
    RemoteCallbacks,
    Repository as _VanillaRepository,
    Signature,
    Stash,
    StashApplyCallbacks,
    Submodule,
    Tree,
    Walker,

    __version__ as PYGIT2_VERSION,
    LIBGIT2_VERSION,
    settings as GitSettings,
)

from pygit2.enums import (
    ApplyLocation,
    BranchType,
    CheckoutNotify,
    CheckoutStrategy,
    ConfigLevel as GitConfigLevel,
    CredentialType,
    DeltaStatus,
    DiffFlag,
    DiffOption,
    FileStatus,
    FileMode,
    FetchPrune,
    MergeAnalysis,
    MergePreference,
    ObjectType,
    RepositoryOpenFlag,
    RepositoryState,
    ReferenceType,
    ResetMode,
    SortMode,
)

from pygit2.remotes import TransferProgress


_logger = _logging.getLogger(__name__)

NULL_OID = Oid(raw=b'')
DOT_GITMODULES = ".gitmodules"

CORE_STASH_MESSAGE_PATTERN = _re.compile(r"^On ([^\s:]+|\(no branch\)): (.+)")
WINDOWS_RESERVED_FILENAMES_PATTERN = _re.compile(r"(.*/)?(AUX|COM[1-9]|CON|LPT[1-9]|NUL|PRN)($|\.|/)", _re.IGNORECASE)
DIFF_HEADER_PATTERN = _re.compile(r"^diff --git (\"?\w/[^\"]+\"?) (\"?\w/[^\"]+\"?)")

SUBPROJECT_COMMIT_MINUS_PATTERN = _re.compile(r"^-Subproject commit (.+)$", _re.M)
SUBPROJECT_COMMIT_PLUS_PATTERN = _re.compile(r"^\+Subproject commit (.+)$", _re.M)

SUBMODULE_CONFIG_KEY_PATTERN = _re.compile(r"^submodule\.(.+)\.path$")

FileStatus_INDEX_MASK = (
        FileStatus.INDEX_NEW
        | FileStatus.INDEX_MODIFIED
        | FileStatus.INDEX_DELETED
        | FileStatus.INDEX_RENAMED
        | FileStatus.INDEX_TYPECHANGE)

FileStatus_WT_MASK = (
        FileStatus.WT_NEW
        | FileStatus.WT_MODIFIED
        | FileStatus.WT_DELETED
        | FileStatus.WT_TYPECHANGE
        | FileStatus.WT_RENAMED
        | FileStatus.WT_UNREADABLE)

_RESTORE_STRATEGY = (
        CheckoutStrategy.FORCE
        | CheckoutStrategy.REMOVE_UNTRACKED
        | CheckoutStrategy.DISABLE_PATHSPEC_MATCH)


class RefPrefix:
    HEADS = "refs/heads/"
    REMOTES = "refs/remotes/"
    TAGS = "refs/tags/"

    @classmethod
    def split(cls, refname: str) -> tuple[str, str]:
        for prefix in cls.HEADS, cls.REMOTES, cls.TAGS:
            if refname.startswith(prefix):
                return prefix, refname[len(prefix):]
        return "", refname


class NameValidationError(ValueError):
    CANNOT_BE_EMPTY = 0
    ILLEGAL_NAME = 1
    ILLEGAL_PREFIX = 2
    ILLEGAL_SUFFIX = 3
    CONTAINS_ILLEGAL_CHAR = 4
    CONTAINS_ILLEGAL_SEQ = 5
    NOT_WINDOWS_FRIENDLY = 6
    NAME_TAKEN_BY_REF = 7
    NAME_TAKEN_BY_FOLDER = 8

    def __init__(self, code: int):
        super().__init__(F"Name validation failed ({code})")
        self.code = code


class DivergentBranchesError(Exception):
    def __init__(self, local_branch: Branch, remote_branch: Branch):
        super().__init__()
        self.local_branch = local_branch
        self.remote_branch = remote_branch

    def __repr__(self):
        return f"DivergentBranchesError(local: {self.local_branch.shorthand}, remote: {self.remote_branch.shorthand})"


class ConflictError(Exception):
    def __init__(self, conflicts: list[str], description="Conflicts"):
        super().__init__(description)
        self.description = description
        self.conflicts = conflicts

    def __repr__(self):
        return f"ConflictError({len(self.conflicts)}, {self.description})"


class MultiFileError(Exception):
    file_exceptions: dict[str, Exception]

    def __init__(self):
        self.file_exceptions = {}

    def add_file_error(self, path: str, exc: Exception):
        self.file_exceptions[path] = exc

    def __bool__(self):
        return bool(self.file_exceptions)


class CheckoutBreakdown(CheckoutCallbacks):
    status: dict[str, CheckoutNotify]

    def __init__(self):
        super().__init__()
        self.status = dict()

    def checkout_notify(self, why: CheckoutNotify, path: str, baseline=None, target=None, workdir=None):
        self.status[path] = why

    def get_conflicts(self):
        return [path for path in self.status
                if self.status[path] == CheckoutNotify.CONFLICT]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not exc_type:
            return False
        if issubclass(exc_type, GitError):
            message = str(exc_val)
            if "prevents checkout" in message or "prevent checkout" in message:
                conflicts = self.get_conflicts()
                if conflicts:
                    raise ConflictError(conflicts, "workdir")
        return False  # let error propagate


class StashApplyBreakdown(StashApplyCallbacks, CheckoutBreakdown):
    def stash_apply_progress(self, pr):
        _logger.info(f"stash apply progress: {pr}")


def _version_at_least(
        package_name: str,
        required_version_string: str,
        current_version_string: str,
        raise_error=True,
        feature_name="This feature"
):
    def version_to_tuple(s: str):
        v = []
        for n in s.split("."):
            try:
                v.append(int(n))
            except ValueError:
                v.append(0)
        # Trim trailing zeros to ease comparison
        while v and v[-1] == 0:
            v.pop()
        return tuple(v)

    required_version = version_to_tuple(required_version_string)
    current_version = version_to_tuple(current_version_string)

    if tuple(current_version) >= tuple(required_version):
        return True

    message = (f"{feature_name} requires {package_name} v{required_version_string} or later "
               f"(you have v{current_version_string}).")
    if raise_error:
        raise NotImplementedError(message)
    else:
        _logger.warning(message)
        return False


def pygit2_version_at_least(required_version: str, raise_error=True, feature_name="This feature"):
    return _version_at_least(
        package_name="pygit2",
        required_version_string=required_version,
        current_version_string=PYGIT2_VERSION,
        raise_error=raise_error,
        feature_name=feature_name)


def libgit2_version_at_least(required_version: str, raise_error=True, feature_name="This feature"):
    return _version_at_least(
        package_name="libgit2",
        required_version_string=required_version,
        current_version_string=LIBGIT2_VERSION,
        raise_error=raise_error,
        feature_name=feature_name)


def split_remote_branch_shorthand(remote_branch_name: str) -> tuple[str, str]:
    """
    Extract the remote name and branch name from a remote branch shorthand
    string such as "origin/master".

    The input string must not start with "refs/remotes/".

    Note: results can be flaky if the remote contains a slash in its name.
    """

    if remote_branch_name.startswith("refs/"):
        raise ValueError("remote branch shorthand name must not start with refs/")

    # TODO: extraction of branch name is flaky if remote name or branch name contains slashes
    try:
        remote_name, branchName = remote_branch_name.split("/", 1)
        return remote_name, branchName
    except ValueError:
        # `git svn clone` creates .git/refs/remotes/git-svn, which trips up pygit2
        return remote_branch_name, ""


def validate_refname(name: str, reserved_names: list[str]):
    """
    Checks the validity of a ref name according to `man git-check-ref-format`.
    Raises NameValidationError if the name is incorrect.
    """

    E = NameValidationError

    # Can't be empty
    if not name:
        raise E(E.CANNOT_BE_EMPTY)

    # Rule 9: can't be single character '@'
    elif name == '@':
        raise E(E.ILLEGAL_NAME)

    # Rule 4: forbid space, tilde, caret, colon
    # Rule 5: forbid question mark, asterisk, open bracket
    # Rule 10: forbid backslash
    elif any(c in " ~^:[?*\\" for c in name):
        raise E(E.CONTAINS_ILLEGAL_CHAR)

    # Rule 1: slash-separated components can't start with dot or end with .lock
    # Rule 3: forbid consecutive dots
    # Rule 6: forbid consecutive slashes
    # Rule 8: forbid '@{'
    elif any(seq in name for seq in ["/.", ".lock/", "..", "//", "@{"]):
        raise E(E.CONTAINS_ILLEGAL_SEQ)

    # Rule 1: can't start with dot
    # Rule 6: can't start with slash
    elif name.startswith((".", "/")):
        raise E(E.ILLEGAL_PREFIX)

    # Rule 1: can't end with .lock
    # Rule 6: can't end with slash
    # Rule 7: can't end with dot
    elif name.endswith((".lock", "/", ".")):
        raise E(E.ILLEGAL_SUFFIX)

    # Prevent filenames that are reserved on Windows
    elif WINDOWS_RESERVED_FILENAMES_PATTERN.match(name):
        raise E(E.NOT_WINDOWS_FRIENDLY)

    # Don't clash with existing refs
    elif name.lower() in (n.lower() for n in reserved_names):
        raise E(E.NAME_TAKEN_BY_REF)

    # Don't clash with ref folders. If you attempt to rename a branch to the
    # name of an existing folder, libgit2 first deletes the branch, then errors
    # out with "cannot lock ref 'refs/heads/folder', there are refs beneath
    # that folder". So, let's avoid losing the branch.
    else:
        folder = name.lower() + "/"
        if any(n.lower().startswith(folder) for n in reserved_names):
            raise E(E.NAME_TAKEN_BY_FOLDER)


def validate_signature_item(s: str):
    """
    Checks the validity of the name or email in a signature according to `libgit2/signature.c`.
    Raises NameValidationError if the item is incorrect.
    """

    E = NameValidationError

    # Angle bracket characters are not allowed
    if "<" in s or ">" in s:
        raise E(E.CONTAINS_ILLEGAL_CHAR)

    # Trim crud from name
    def is_crud(c: str):
        return ord(c) <= 32 or c in ".,:;<>\"\\'"

    start = 0
    end = len(s)
    while end > 0 and is_crud(s[end-1]):
        end -= 1
    while start < end and is_crud(s[start]):
        start += 1
    trimmed = s[start:end]

    # Cannot be empty after trimming
    if not trimmed:
        raise E(E.CANNOT_BE_EMPTY)


def signatures_equalish(a: Signature, b: Signature):
    """
    Sometimes two signature objects differ only by the encoding field.
    """

    if a == b:
        return True

    if a._encoding == b._encoding:
        # If the encodings match and a != b, then the signatures are really different
        return False

    return (a.email == b.email
        and a.name == b.name
        and a.raw_email == b.raw_email
        and a.raw_name == b.raw_name
        and a.time == b.time
        and a.offset == b.offset
    )


def get_git_global_identity() -> tuple[str, str]:
    """
    Returns the name and email set in the global `.gitconfig` file.
    If the global identity isn't set, this function returns blank strings.
    """

    name = ""
    email = ""

    try:
        global_config = GitConfig.get_global_config()
    except OSError:
        # "The global file '.gitconfig' doesn't exist: No such file or directory
        return name, email

    with _suppress(KeyError):
        name = global_config["user.name"]

    with _suppress(KeyError):
        email = global_config["user.email"]

    return name, email


def ensure_git_config_file(level=GitConfigLevel.GLOBAL) -> GitConfig:
    try:
        if level == GitConfigLevel.GLOBAL:
            return GitConfig.get_global_config()
        elif level == GitConfigLevel.SYSTEM:
            return GitConfig.get_system_config()
        elif level == GitConfigLevel.XDG:
            return GitConfig.get_xdg_config()
        else:
            raise NotImplementedError("ensure_git_config_file: unsupported level")
    except OSError:
        # Last resort, create file
        pass

    search_paths = GitSettings.search_path[level]

    # Several paths may be concatenated with GIT_PATH_LIST_SEPARATOR,
    # which git2/common.h defines as ":" (or ";" on Windows).
    # pygit2 doesn't expose this, but it appears to match os.pathsep.
    for path in search_paths.split(_os.pathsep):
        if path and _os.path.isdir(path):
            break
    else:
        raise NotImplementedError("no valid search path found for global git config")

    path = _joinpath(path, ".gitconfig")
    _logger.info(f"Initializing {level} git config at {path}")
    return GitConfig(path)


def DiffFile_compare(f1: DiffFile, f2: DiffFile):
    # TODO: pygit2 ought to implement DiffFile.__eq__
    same = f1.id == f2.id
    same &= f1.mode == f2.mode
    same &= f1.flags == f2.flags
    same &= f1.raw_path == f2.raw_path
    if same:
        assert f1.path == f2.path
        assert f1.size == f2.size
    return same


def strip_stash_message(stash_message: str) -> str:
    m = CORE_STASH_MESSAGE_PATTERN.match(stash_message)
    if m:
        return m.group(2)
    else:
        return stash_message


def parse_submodule_patch(text: str) -> tuple[Oid, Oid, bool]:
    def parse_subproject_line(match: _re.Match):
        dirty = False
        if not match:
            oid = NULL_OID
        else:
            capture = match.group(1)
            if capture.endswith("-dirty"):
                capture = capture.removesuffix("-dirty")
                dirty = True
            oid = Oid(hex=capture)
        return oid, dirty

    old_match = SUBPROJECT_COMMIT_MINUS_PATTERN.search(text)
    new_match = SUBPROJECT_COMMIT_PLUS_PATTERN.search(text)
    old_id, _ = parse_subproject_line(old_match)
    new_id, new_dirty = parse_subproject_line(new_match)
    return old_id, new_id, new_dirty


class GitConfigHelper:
    @staticmethod
    def is_empty(config_path: str):
        with open(config_path, "rt") as f:
            data = f.read()
        return not data or data.isspace()

    @staticmethod
    def delete_section(config_path: str, *section_key_tokens: str):
        config = GitConfig(config_path)

        assert len(section_key_tokens) == 2
        section_key = ".".join(section_key_tokens)
        section_prefix = section_key + "."

        to_delete = [entry.name for entry in config if entry.name.startswith(section_prefix)]

        for entry_name in to_delete:
            del config[entry_name]

        GitConfigHelper.scrub_empty_section(config_path, *section_key_tokens)

        return bool(to_delete)

    @staticmethod
    def scrub_empty_section(config_path: str, *section_key_tokens: str):
        num_tokens = len(section_key_tokens)
        if num_tokens == 1:
            section_key = section_key_tokens[0]
        elif num_tokens == 2:
            prefix, name = section_key_tokens
            name = name.replace('"', r'\"')
            section_key = f'{prefix} "{name}"'
        else:
            raise NotImplementedError("scrub_empty_section: section key must be 1 or 2 tokens")

        ini = _configparser.ConfigParser()
        ini.read(config_path)

        if not ini.has_section(section_key):
            # Section doesn't appear in file, let it be
            _logger.debug(f".git/config: Section [{section_key}] doesn't appear, no scrubbing needed")
            return

        section = ini[section_key]
        assert isinstance(section, _configparser.SectionProxy)

        if len(section) != 0:
            # Section isn't empty, leave it alone
            _logger.debug(f".git/config: Section [{section_key}] isn't empty, won't scrub")
            return

        _logger.debug(f".git/config: Scrubbing empty section [{section_key}]")

        # We could call ini.remove_section(section_key) and then write the ini back to disk.
        # But this destroys the file's formatting. So, remove the offending line surgically.
        with open(config_path, "rt") as f:
            lines = f.readlines()
        try:
            lines.remove(f"[{section_key}]\n")
        except ValueError:
            _logger.warning(f".git/config: Standalone section line not found: [{section_key}]")
            return

        timestamp = datetime.datetime.now().timestamp()
        temp_path = config_path + f".{timestamp}.new.tmp"
        backup_path = config_path + f".{timestamp}.old.tmp"

        with open(temp_path, "wt") as f:
            f.writelines(lines)

        _os.rename(config_path, backup_path)
        _os.rename(temp_path, config_path)
        _os.unlink(backup_path)


class Repo(_VanillaRepository):
    """
    Drop-in replacement for pygit2.Repository with convenient front-ends to common git operations.
    """

    def __del__(self):
        _logger.debug("__del__ Repo")
        self.free()

    @property
    def head_tree(self) -> Tree:
        return self.head.peel(Tree)

    @property
    def head_commit(self) -> Commit:
        return self.head.peel(Commit)

    @property
    def head_commit_id(self) -> Oid:
        return self.head_commit.id

    @property
    def head_commit_message(self) -> str:
        return self.head_commit.message

    @property
    def head_branch_shorthand(self) -> str:
        return self.head.shorthand

    @property
    def head_branch_fullname(self) -> str:
        return self.head.name

    def peel_commit(self, commit_id: Oid) -> Commit:
        return self[commit_id].peel(Commit)

    def peel_blob(self, blob_id: Oid) -> Blob:
        return self[blob_id].peel(Blob)

    def peel_tree(self, tree_id: Oid) -> Tree:
        return self[tree_id].peel(Tree)

    def in_workdir(self, path: str) -> str:
        """Return an absolutized version of `path` within this repo's workdir."""
        assert not _isabs(path)
        p = _joinpath(self.workdir, path)
        if not p.startswith(self.workdir):
            raise ValueError("Won't create absolute path outside workdir")
        return p

    def refresh_index(self, force: bool = False):
        """
        Reload the index. Call this before manipulating the staging area
        to ensure any external modifications are taken into account.

        This is a fairly cheap operation if the index hasn't changed on disk,
        unless you pass force=True.
        """
        self.index.read(force)

    def get_uncommitted_changes(self, show_binary: bool = False, context_lines: int = 3) -> Diff:
        """
        Get a Diff of all uncommitted changes in the working directory,
        compared to the commit at HEAD.

        In other words, this function compares the workdir to HEAD.
        """

        flags = (DiffOption.INCLUDE_UNTRACKED
                 | DiffOption.RECURSE_UNTRACKED_DIRS
                 | DiffOption.SHOW_UNTRACKED_CONTENT
                 | DiffOption.INCLUDE_TYPECHANGE
                 )

        if show_binary:
            flags |= DiffOption.SHOW_BINARY

        dirty_diff = self.diff('HEAD', None, cached=False, flags=flags, context_lines=context_lines)
        dirty_diff.find_similar()
        return dirty_diff

    def get_unstaged_changes(self, update_index: bool = False, show_binary: bool = False, context_lines: int = 3) -> Diff:
        """
        Get a Diff of unstaged changes in the working directory.

        In other words, this function compares the workdir to the index.
        """

        flags = (DiffOption.INCLUDE_UNTRACKED
                 | DiffOption.RECURSE_UNTRACKED_DIRS
                 | DiffOption.SHOW_UNTRACKED_CONTENT
                 | DiffOption.INCLUDE_TYPECHANGE
                 )

        # Don't attempt to update the index if the repo is locked for writing,
        # or the index is locked by another program
        update_index &= (_os.access(self.path, _os.W_OK) \
            and not _exists(_joinpath(self.path, "index.lock")))

        # UPDATE_INDEX may improve performance for subsequent diffs if the
        # index was stale, but this requires the repo to be writable.
        if update_index:
            _logger.debug("UPDATE_INDEX")
            flags |= DiffOption.UPDATE_INDEX

        if show_binary:
            flags |= DiffOption.SHOW_BINARY

        dirty_diff = self.diff(None, None, flags=flags, context_lines=context_lines)
        # dirty_diff.find_similar()  #-- it seems that find_similar cannot find renames in unstaged changes, so don't bother
        return dirty_diff

    def get_staged_changes(self, fast: bool = False, show_binary: bool = False, context_lines: int = 3) -> Diff:
        """
        Get a Diff of the staged changes.

        In other words, this function compares the index to HEAD.
        """

        flags = DiffOption.INCLUDE_TYPECHANGE

        if show_binary:
            flags |= DiffOption.SHOW_BINARY

        if self.head_is_unborn:  # can't compare against HEAD (empty repo or branch pointing nowhere)
            index_tree_id = self.index.write_tree()
            tree = self.peel_tree(index_tree_id)
            return tree.diff_to_tree(swap=True, flags=flags, context_lines=context_lines)
        else:
            # compare HEAD to index
            stage_diff: Diff = self.diff('HEAD', None, cached=True, flags=flags, context_lines=context_lines)
            if not fast:
                stage_diff.find_similar()
            return stage_diff

    @property
    def any_conflicts(self) -> bool:
        """True if there are any conflicts in the index."""
        return bool(self.index.conflicts)

    @property
    def any_staged_changes(self) -> bool:
        """True if there are any staged changes in the index."""
        return 0 != len(self.get_staged_changes(fast=True, context_lines=0))
        # ---This also works, but it's slower.
        # status = repo.status(untracked_files="no")
        # return any(0 != (flag & FileStatus.INDEX_MASK) for flag in status.values())

    def commit_diffs(self, commit_id: Oid, show_binary: bool = False, find_similar_threshold: int = -1, context_lines: int = 3
                     ) -> tuple[list[Diff], bool]:
        """
        Get a list of Diffs of a commit compared to its parents.
        Return tuple[list[Diff], bool]. The bool in the returned tuple indicates whether find_similar was skipped.
        """
        flags = DiffOption.INCLUDE_TYPECHANGE

        if show_binary:
            flags |= DiffOption.SHOW_BINARY

        commit: Commit = self.get(commit_id)
        skipped_find_similar = False

        if commit.parents:
            all_diffs = []

            parent: Commit
            for i, parent in enumerate(commit.parents):
                if i == 0:
                    diff = self.diff(parent, commit, flags=flags, context_lines=context_lines)
                    if find_similar_threshold < 0 or len(diff) < find_similar_threshold:
                        diff.find_similar()
                    else:
                        skipped_find_similar = True
                    all_diffs.append(diff)
                elif not parent.parents:
                    # This parent is parentless: assume merging in new files from this parent
                    # (e.g. "untracked files on ..." parents of stash commits)
                    tree: Tree = parent.peel(Tree)
                    diff = tree.diff_to_tree(swap=True, flags=flags, context_lines=context_lines)
                    all_diffs.append(diff)
                else:
                    # Skip non-parentless parent in merge commits
                    pass

        else:
            # Parentless commit: diff with empty tree
            # (no tree passed to diff_to_tree == force diff against empty tree)
            diff = commit.tree.diff_to_tree(swap=True, flags=flags, context_lines=context_lines)
            all_diffs = [diff]

        return all_diffs, skipped_find_similar

    def checkout_local_branch(self, name: str):
        """Switch to a local branch."""
        branch = self.branches.local[name]
        refname = branch.name
        self.checkout_ref(refname)

    def checkout_ref(self, refname: str):
        """Enter detached HEAD on the commit pointed to by a ref."""
        with CheckoutBreakdown() as callbacks:
            self.checkout(refname, callbacks=callbacks)

    def checkout_commit(self, commit_id: Oid):
        """Enter detached HEAD on a commit."""
        commit = self.peel_commit(commit_id)
        with CheckoutBreakdown() as callbacks:
            self.checkout_tree(commit.tree, callbacks=callbacks)
            self.set_head(commit_id)

    def revert_commit_in_workdir(self, commit_id: Oid):
        """Revert a commit and check out the reverted index if there are no conflicts
        with the workdir."""

        trash_commit = self.peel_commit(commit_id)
        head_commit = self.head_commit
        revert_index = self.revert_commit(trash_commit, head_commit)

        if revert_index.conflicts:
            early_conflicts = []
            for common_ancestor, ours, theirs in revert_index.conflicts:
                # Figure out a path to display (note that elements of the 3-tuple may be None!)
                for candidate in [common_ancestor, ours, theirs]:
                    if candidate and candidate.path:
                        early_conflicts.append(candidate.path)
                        break
            raise ConflictError(early_conflicts, "HEAD")

        with CheckoutBreakdown() as callbacks:
            self.checkout_index(revert_index, callbacks=callbacks)

    def rename_local_branch(self, name: str, new_name: str) -> Branch:
        """Rename a local branch."""
        # TODO: if the branch tracks an upstream branch, issue a warning that it won't be renamed on the server
        branch = self.branches.local[name]
        branch.rename(new_name)
        self.scrub_empty_config_section("branch", name)
        return branch

    def delete_local_branch(self, name: str):
        """Delete a local branch."""
        # TODO: if remote-tracking, let user delete upstream too?
        self.branches.local.delete(name)
        self.scrub_empty_config_section("branch", name)

    def scrub_empty_config_section(self, *section_key_tokens: str):
        """
        libgit2 leaves behind empty sections in the config file after deleting
        or renaming a remote or branch. Over time, this litters the config
        file with empty entries, which slows down operations that parse the
        config. So, use this function to nip that in the bud.
        """
        config_path = _joinpath(self.path, "config")
        GitConfigHelper.scrub_empty_section(config_path, *section_key_tokens)

    def create_branch_on_head(self, name: str) -> Branch:
        """Create a local branch pointing to the commit at the current HEAD."""
        return self.create_branch(name, self.head_commit)

    def create_branch_tracking(self, name: str, remote_branch_name: str) -> Branch:
        """Create a local branch pointing to the commit at the tip of a remote branch,
        and set up the local branch to track the remote branch."""
        remote_branch = self.branches.remote[remote_branch_name]
        commit: Commit = remote_branch.peel(Commit)
        branch = self.create_branch(name, commit)
        branch.upstream = remote_branch
        return branch

    def create_branch_from_commit(self, name: str, commit_id: Oid) -> Branch:
        """Create a local branch pointing to the given commit id."""
        commit = self.peel_commit(commit_id)
        branch = self.create_branch(name, commit)
        return branch

    def listall_remote_branches(self, value_style: _typing.Literal["strip", "shorthand", "refname"] = "strip") -> dict[str, list[str]]:
        names = {}

        # Create empty lists for all remotes (including branchless remotes)
        for remote in self.remotes:
            names[remote.name] = []

        for refname in self.listall_references():
            prefix, shorthand = RefPrefix.split(refname)

            if prefix != RefPrefix.REMOTES:
                continue

            if refname.endswith("/HEAD"):
                # Skip refs/remotes/*/HEAD (the remote's default branch).
                # The ref file (.git/refs/remotes/*/HEAD) is created ONCE when first cloning the repository,
                # and it's never updated again automatically, even if the default branch has changed on the remote.
                # It's a symbolic branch, so looking up a stale version of the remote's HEAD may raise KeyError.
                # It's just not worth the trouble.
                # See: https://stackoverflow.com/questions/8839958
                continue

            remote_name, branch_name = split_remote_branch_shorthand(shorthand)
            if value_style == "strip":
                value = branch_name
            elif value_style == "shorthand":
                value = shorthand
            elif value_style == "refname":
                value = refname
            else:
                raise NotImplementedError(f"unsupported value_style {value_style}")
            names[remote_name].append(value)

        return names

    def listall_tags(self) -> list[str]:
        return [
            name.removeprefix(RefPrefix.TAGS)
            for name in self.listall_references()
            if name.startswith(RefPrefix.TAGS)
        ]

    def edit_upstream_branch(self, local_branch_name: str, remote_branch_name: str):
        local_branch = self.branches.local[local_branch_name]
        if remote_branch_name:
            remote_branch = self.branches.remote[remote_branch_name]
            local_branch.upstream = remote_branch
        else:
            if local_branch.upstream is not None:
                local_branch.upstream = None

    def create_remote(self, name: str, url: str):
        self.remotes.create(name, url)

    def edit_remote(self, name: str, new_name: str, new_url: str):
        self.remotes.set_url(name, new_url)
        if name != new_name:
            self.remotes.rename(name, new_name)  # rename AFTER setting everything else!
            self.scrub_empty_config_section("remote", name)

    def delete_remote(self, name: str):
        self.remotes.delete(name)
        self.scrub_empty_config_section("remote", name)

    def delete_remote_branch(self, remote_branch_name: str, remoteCallbacks: RemoteCallbacks):
        remoteName, branchName = split_remote_branch_shorthand(remote_branch_name)

        refspec = f":{RefPrefix.HEADS}{branchName}"
        _logger.info(f"Delete remote branch: refspec: \"{refspec}\"")

        remote = self.remotes[remoteName]
        remote.push([refspec], callbacks=remoteCallbacks)

    def rename_remote_branch(self, old_remote_branch_name: str, new_name: str, remote_callbacks: RemoteCallbacks):
        """
        Warning: this function does not refresh the state of the remote branch before renaming it!
        """
        remoteName, oldBranchName = split_remote_branch_shorthand(old_remote_branch_name)

        # First, make a new branch pointing to the same ref as the old one
        refspec1 = f"{RefPrefix.REMOTES}{old_remote_branch_name}:{RefPrefix.HEADS}{new_name}"

        # Next, delete the old branch
        refspec2 = f":{RefPrefix.HEADS}{oldBranchName}"

        _logger.info(f"Rename remote branch: remote: {remoteName}; refspec: {[refspec1, refspec2]}")

        remote = self.remotes[remoteName]
        remote.push([refspec1, refspec2], callbacks=remote_callbacks)

    def delete_stale_remote_head_symbolic_ref(self, remote_name: str):
        """
        Delete `refs/remotes/{remoteName}/HEAD` to work around a bug in libgit2
        where `git_revwalk__push_glob` errors out on that symbolic ref
        if it points to a branch that doesn't exist anymore.

        This bug may prevent fetching.
        """

        head_refname = f"{RefPrefix.REMOTES}{remote_name}/HEAD"
        head_ref = self.references.get(head_refname)

        # Only risk deleting remote HEAD if it's symbolic
        if head_ref and head_ref.type == ReferenceType.SYMBOLIC:
            try:
                head_ref.resolve()
            except KeyError:  # pygit2 wraps GIT_ENOTFOUND with KeyError
                # Stale -- nuke it
                self.references.delete(head_refname)
                _logger.info("Deleted stale remote HEAD symbolic ref: " + head_refname)

    def fetch_remote(self, remote_name: str, remote_callbacks: RemoteCallbacks) -> TransferProgress:
        # Delete `refs/remotes/{remoteName}/HEAD` before fetching.
        # See docstring for that function for why.
        self.delete_stale_remote_head_symbolic_ref(remote_name)

        remote = self.remotes[remote_name]
        transfer = remote.fetch(callbacks=remote_callbacks, prune=FetchPrune.PRUNE)
        return transfer

    def fetch_remote_branch(
            self, remote_branch_name: str, remote_callbacks: RemoteCallbacks
    ) -> TransferProgress:
        """
        Fetch a remote branch.
        Prunes the remote branch if it has disappeared from the server.
        """
        remote_name, branch_name = split_remote_branch_shorthand(remote_branch_name)

        # Delete .git/refs/{remote_name}/HEAD to work around a bug in libgit2
        # where git_revwalk__push_glob chokes on refs/remotes/{remote_name}/HEAD
        # if it points to a branch that doesn't exist anymore.
        self.delete_stale_remote_head_symbolic_ref(remote_name)

        remote = self.remotes[remote_name]
        #            src (remote)........... : dst (local ref to update).............
        refspec = f"+refs/heads/{branch_name}:refs/remotes/{remote_name}/{branch_name}"
        transfer = remote.fetch(refspecs=[refspec], callbacks=remote_callbacks, prune=FetchPrune.PRUNE)
        return transfer

    def get_commit_message(self, commit_id: Oid) -> str:
        commit = self.peel_commit(commit_id)
        return commit.message

    def create_commit_on_head(
            self,
            message: str,
            author: Signature | None = None,
            committer: Signature | None = None
    ) -> Oid:
        """
        Create a commit with the contents of the index tree.
        Use the commit at HEAD as the new commit's parent.
        If `author` or `committer` are not overridden, use the repository's default_signature.
        """

        # Prep ref to update
        if self.head_is_detached:
            ref_to_update = "HEAD"
        else:
            # Get the ref name pointed to by HEAD, but DON'T use repo.head! It won't work if HEAD is unborn.
            # Both git and libgit2 store a default branch name in .git/HEAD when they init a repo,
            # so we should always have a ref name, even though it might not point to anything.
            ref_to_update = self.lookup_reference("HEAD").target

        # Prep parent list
        if self.head_is_unborn:
            parents = []
        else:
            # Always take HEAD commit as 1st parent
            parents = [self.head_commit_id]

        # If a merge was in progress, add merge heads to parent list
        parents += self.listall_mergeheads()
        assert len(set(parents)) == len(parents), "duplicate heads!"

        # Get id of index tree
        index_tree_id = self.index.write_tree()

        # Take default signature now to prevent any timestamp diff between
        # author and committer. Note that there may not be a fallback signature
        # if the system's git config isn't set up.
        try:
            fallback_signature = self.default_signature
        except KeyError:
            fallback_signature = None
            assert author is not None, "fallback signature missing - author signature must be provided"
            assert committer is not None, "fallback signature missing - committer signature must be provided"

        # Create the commit
        new_commit_id = self.create_commit(
            ref_to_update,
            author or fallback_signature,
            committer or fallback_signature,
            message,
            index_tree_id,
            parents
        )

        # Clear repository state to conclude a merge/cherrypick operation
        self.state_cleanup()

        # Repository.create_commit flushes the staged changes from the in-memory index.
        # Write the index to disk so that other applications can pick up the updated staging area.
        self.index.write()

        assert not self.head_is_unborn, "HEAD is still unborn after we have committed!"

        return new_commit_id

    def amend_commit_on_head(
            self,
            message: str,
            author: Signature | None = None,
            committer: Signature | None = None
    ) -> Oid:
        """
        Amend the commit at HEAD with the contents of the index tree.
        If `author` is None, don't replace the original commit's author.
        If `committer` is None, use default_signature for the committer's signature.
        """
        index_tree_id = self.index.write_tree(self)
        new_commit_id = self.amend_commit(
            self.head_commit,
            'HEAD',
            message=message,
            author=author,
            committer=committer or self.default_signature,
            tree=index_tree_id
        )
        return new_commit_id

    def commit_id_from_refname(self, refname: str) -> Oid:
        reference = self.references[refname]
        commit: Commit = reference.peel(Commit)
        return commit.id

    def commit_id_from_tag_name(self, tagname: str) -> Oid:
        assert not tagname.startswith("refs/")
        return self.commit_id_from_refname(RefPrefix.TAGS + tagname)

    def map_refs_to_ids(self) -> dict[str, Oid]:
        """
        Return commit oids at the tip of all branches, tags, etc. in the repository.

        To ensure a consistent outcome across multiple walks of the same commit graph,
        the oids are sorted by ascending commit time.
        """

        tips: list[tuple[str, Commit]] = []

        try:
            directRefType = ReferenceType.DIRECT
        except AttributeError:  # pragma: no cover - pygit2 <= 1.14.0 compatibility
            directRefType = ReferenceType.OID

        for ref in self.listall_reference_objects():
            if (ref.type != directRefType  # Skip symbolic references
                    or ref.name == "refs/stash"):  # Stashes are dealt with separately
                continue

            try:
                commit: Commit = ref.peel(Commit)
                tips.append((ref.name, commit))
            except InvalidSpecError as e:
                # Some refs might not be committish, e.g. in linux's source repo
                _logger.info(f"{e} - Skipping ref '{ref.name}'")

        for i, stash in enumerate(self.listall_stashes()):
            try:
                commit = self.peel_commit(stash.commit_id)
                tips.append((f"stash@{{{i}}}", commit))
            except InvalidSpecError as e:
                _logger.info(f"{e} - Skipping stash '{stash.message}'")

        # Always add 'HEAD' if we have one.
        # Do so *just* before reinserting the tips in chronological order below.
        # This causes the checked-out branch to be sorted more favorably if
        # there is another tip that shares the exact same timestamp.
        # (This guarantees that the local branch appears on top e.g. when
        # pushing a branch to a remote, then amending the top commit with the
        # same author/committer signatures.)
        try:
            tips.append(("HEAD", self.head_commit))
        except (GitError, InvalidSpecError):
            pass  # Skip detached/unborn head

        # Reinsert all tips in chronological order
        # (In Python 3.7+, dict key order is stable)
        tips.sort(key=lambda item: item[1].commit_time)
        return dict((ref, commit.id) for ref, commit in tips)

    def listall_refs_pointing_at(self, commit_id: Oid):
        refs = []

        # Detached HEAD isn't in repo.references
        if self.head_is_detached and type(self.head.target) is Oid and self.head.target == commit_id:
            refs.append('HEAD')

        for ref in self.references.objects:
            ref_key = ref.name

            if type(ref.target) != Oid:
                # Symbolic reference
                _logger.debug(f"Skipping symbolic reference {ref_key} --> {ref.target}")
                continue

            if ref.target != commit_id:
                continue

            assert ref_key.startswith("refs/")

            if ref_key == "refs/stash":
                # Stashes must be dealt with separately
                continue

            refs.append(ref_key)

        for stash_index, stash in enumerate(self.listall_stashes()):
            if stash.commit_id == commit_id:
                refs.append(F"stash@{{{stash_index}}}")

        return refs

    def stage_files(self, patches: list[Patch]):
        index = self.index
        for patch in patches:
            path = patch.delta.new_file.path
            if patch.delta.new_file.mode == FileMode.TREE and path.endswith("/"):
                path = path.removesuffix("/")
            if patch.delta.status == DeltaStatus.DELETED:
                index.remove(path)
            else:
                index.add(path)
        index.write()

    def restore_files_from_head(self, paths: list[str], restore_all=False):
        """
        Reset the given files to their state at the HEAD commit.
        Any staged, unstaged, or untracked changes in those files will be lost.
        """
        assert bool(paths) ^ restore_all, "if you want to reset all files, pass empty path list and restore_all=True"
        assert not self.head_is_unborn

        self.checkout_tree(self.head_tree, paths=paths, strategy=_RESTORE_STRATEGY)

    def restore_files_from_index(self, paths: list[str], restore_all=False):
        """
        Discard unstaged changes in the given files.
        Staged changes will remain.
        """
        assert bool(paths) ^ restore_all, "if you want to reset all files, pass empty path list and restore_all=True"

        self.refresh_index()  # in case an external program modified the staging area
        self.checkout_index(paths=paths, strategy=_RESTORE_STRATEGY)

    def discard_mode_changes(self, paths: list[str]):
        """
        Discards mode changes in the given files.
        """

        self.refresh_index()  # in case an external program modified the staging area
        index = self.index

        # Reset files to their mode in the staged (index) tree
        for p in paths:
            try:
                mode = index[p].mode
            except KeyError:
                continue
            if mode in [FileMode.BLOB, FileMode.BLOB_EXECUTABLE]:
                _os.chmod(self.in_workdir(p), mode)

    def unstage_files(self, patches: list[Patch]):
        index = self.index

        head_tree: Tree | None
        if self.head_is_unborn:
            head_tree = None
        else:
            head_tree = self.head_tree

        for patch in patches:
            delta = patch.delta
            old_path = delta.old_file.path
            new_path = delta.new_file.path
            if delta.status == DeltaStatus.ADDED:
                assert (not head_tree) or (old_path not in head_tree)
                index.remove(old_path)
            elif delta.status == DeltaStatus.RENAMED:
                # TODO: Two-step removal to completely unstage a rename -- is this what we want?
                assert new_path in index
                index.remove(new_path)
            else:
                assert head_tree
                assert old_path in head_tree
                obj = head_tree[old_path]
                index.add(IndexEntry(old_path, obj.id, obj.filemode))
        index.write()

    def unstage_mode_changes(self, patches: list[Patch]):
        index = self.index

        for patch in patches:
            of = patch.delta.old_file
            nf = patch.delta.new_file
            if (of.mode != nf.mode
                    and patch.delta.status not in [DeltaStatus.ADDED, DeltaStatus.DELETED, DeltaStatus.UNTRACKED]
                    and of.mode in [FileMode.BLOB, FileMode.BLOB_EXECUTABLE]):
                index.add(IndexEntry(nf.path, nf.id, of.mode))

        index.write()

    def create_stash(self, message: str, paths: list[str]) -> Oid:
        """
        Creates a stash that backs up all changes to the given files.
        Does NOT remove the changes from the workdir (you can use resetFiles afterwards).
        """

        assert paths, "path list cannot be empty"

        try:
            signature = self.default_signature
        except (KeyError, ValueError):
            # Allow creating a stash if the identity isn't set
            signature = Signature(name="UNKNOWN", email="UNKNOWN")

        commit_id = self.stash(
            stasher=signature,
            message=message,
            keep_index=False,
            keep_all=True,
            include_untracked=False,
            include_ignored=False,
            paths=paths)

        return commit_id

    def find_stash_index(self, commit_id: Oid) -> int:
        """
        Libgit2 takes an index number to apply/pop/drop stashes. However, it's
        unsafe to cache such an index for the GUI. Instead, we cache the commit ID
        of the stash, and we only convert that to an index when we need to perform
        an operation on the stash. This way, we'll always manipulate the stash
        intended by the user, even if the indices change outside our control.
        """
        try:
            return next(i for i, stash in enumerate(self.listall_stashes())
                        if stash.commit_id == commit_id)
        except StopIteration:
            raise KeyError(f"Stash not found: {commit_id}")

    def stash_apply_id(self, commit_id: Oid):
        i = self.find_stash_index(commit_id)
        with StashApplyBreakdown() as callbacks:
            self.stash_apply(i, callbacks=callbacks)

    def stash_pop_id(self, commit_id: Oid):
        i = self.find_stash_index(commit_id)
        with StashApplyBreakdown() as callbacks:
            self.stash_pop(i, callbacks=callbacks)

    def stash_drop_id(self, commit_id: Oid):
        i = self.find_stash_index(commit_id)
        self.stash_drop(i)

    def applies_breakdown(self, patch_data: bytes | str, location: int = ApplyLocation.WORKDIR) -> Diff:
        diff = Diff.parse_diff(patch_data)
        error = MultiFileError()

        # Attempt to apply every patch in the diff separately, so we can report which file an error pertains to
        for patch in diff:
            patch_data = patch.data

            # Work around libgit2 bug: If a patch lacks the "index" line (as our partial patches do),
            # then libgit2 fails to recreate the "---" and "+++" lines. Then it can't parse its own output.
            patch_lines = patch_data.splitlines(True)
            if len(patch_lines) >= 2 and patch_lines[0].startswith(b"diff --git ") and patch_lines[1].startswith(b"@@"):
                header = patch_lines[0].strip().decode("utf-8")
                match = _re.match(DIFF_HEADER_PATTERN, header)
                if match:
                    patch_lines.insert(1, ("--- " + match[1] + "\n").encode("utf-8"))
                    patch_lines.insert(2, ("+++ " + match[2] + "\n").encode("utf-8"))
                    patch_data = b"".join(patch_lines)

            patch_diff = Diff.parse_diff(patch_data)  # can we extract a diff from the patch without re-parsing it?
            try:
                self.applies(patch_diff, location, raise_error=True)
            except (GitError, OSError) as exc:
                error.add_file_error(patch.delta.old_file.path, exc)

        if error:
            raise error
        else:
            return diff

    def apply(self,
              patch_data_or_diff: bytes | str | Diff,
              location: ApplyLocation = ApplyLocation.WORKDIR
              ) -> Diff:
        if type(patch_data_or_diff) in [bytes, str]:
            diff = Diff.parse_diff(patch_data_or_diff)
        elif type(patch_data_or_diff) is Diff:
            diff = patch_data_or_diff
        else:
            raise TypeError("patchDataOrDiff must be bytes, str, or Diff")

        super().apply(diff, location)
        return diff

    def get_submodule_workdir(self, submo_key: str) -> str:
        submo = self.submodules[submo_key]
        return self.in_workdir(submo.path)

    def listall_submodules(self):  # pragma: no cover
        """
        Don't use listall_submodules, it's slow and it omits critical
        information about submodule names.
        Note that if a submodule's name is different from its path,
        SubmoduleCollection[path].name will NOT return the correct name!
        """
        warnings.warn("Don't use this", DeprecationWarning)
        raise DeprecationWarning("Don't use listall_submodules")

    def listall_submodules_fast(self) -> list[str]:
        """
        Faster drop-in replacement for pygit2's Repository.listall_submodules (which can be very slow).
        Return a list of submodule workdir paths within the root repo's workdir.
        """
        return list(self.listall_submodules_dict().values())

    def listall_submodules_dict(self, absolute_paths=False) -> dict[str, str]:
        """
        Return a dict of submodule names to paths.
        You should use this instead of pygit2's Repository.listall_submodules,
        because the latter doesn't give you information about submodule names,
        which you need to
        """

        config_path = self.in_workdir(DOT_GITMODULES)
        if not _isfile(config_path):
            return {}

        config = GitConfig(config_path)
        submos = {}
        for entry in config:
            key: str = entry.name
            match = SUBMODULE_CONFIG_KEY_PATTERN.fullmatch(key)
            if match:
                name = match.group(1)
                path = entry.value
                if absolute_paths:
                    path = self.in_workdir(path)
                submos[name] = path

        return submos

    def get_submodule_name_from_path(self, submodule_path: str) -> str:
        d = self.listall_submodules_dict()
        try:
            return next(name for name, path in d.items() if path == submodule_path)
        except StopIteration:
            raise KeyError(f"submodule path not found: {submodule_path}")

    def listall_initialized_submodule_names(self) -> list[str]:
        config = self.config
        submo_names = []
        for entry in config:
            key: str = entry.name
            if key.startswith("submodule."):
                i = len("submodule.")
                j = key.rfind(".")
                name = key[i:j]
                submo_names.append(name)
        return submo_names

    def submodule_dotgit_present(self, submo_path: str) -> bool:
        path = self.in_workdir(submo_path)
        path = _joinpath(path, ".git")
        return _exists(path)

    def recurse_submodules(self) -> _typing.Generator[tuple[Submodule, str], None, None]:
        def gen_frontier(repo: Repo) -> _typing.Generator[tuple[Submodule, str], None, None]:
            for name, path in repo.listall_submodules_dict(absolute_paths=True).items():
                yield repo.submodules[name], path

        frontier: list[tuple[Submodule, str]] = list(gen_frontier(self))

        while frontier:
            submodule, path = frontier.pop(0)
            yield submodule, path

            # Extend frontier AFTER the yield statement so user code can
            # potentially add nested submodules here
            # TODO: pygit2 bug: Submodule.open is broken (that's why we recreate a Repo)
            with RepoContext(path, RepositoryOpenFlag.NO_SEARCH) as subrepo:
                frontier.extend(gen_frontier(subrepo))

    def fast_forward_branch(self, local_branch_name: str, target_branch_name: str = ""):
        """
        Fast-forward a local branch to another branch (local or remote).
        Return True if the local branch was up-to-date.
        Raise DivergentBranchesError if fast-forwarding is impossible.

        If target_branch_name is omitted, attempt to fast-forward to the
        branch's upstream (will not fetch it beforehand).
        """
        assert not local_branch_name.startswith("refs/")
        lb = self.branches.local[local_branch_name]

        if not target_branch_name:
            rb = lb.upstream
            if not rb:
                raise ValueError("Local branch does not track a remote branch")
        else:
            assert isinstance(target_branch_name, str)
            target_prefix, target_shorthand = RefPrefix.split(target_branch_name)
            if target_prefix == RefPrefix.REMOTES:
                rb = self.branches.remote[target_shorthand]
            elif target_prefix == RefPrefix.HEADS:
                rb = self.branches.local[target_shorthand]
            else:
                rb = self.branches[target_shorthand]

        merge_analysis, merge_pref = self.merge_analysis(rb.target, RefPrefix.HEADS + local_branch_name)
        _logger.debug(f"Merge analysis: {repr(merge_analysis)}. Merge preference: {repr(merge_pref)}.")

        if merge_analysis & MergeAnalysis.UP_TO_DATE:
            # Local branch is up-to-date with remote branch, nothing to do.
            return True

        elif merge_analysis == (MergeAnalysis.NORMAL | MergeAnalysis.FASTFORWARD):
            # Go ahead and fast-forward.

            # First, we need to check out the tree pointed to by the remote branch. This step is necessary,
            # otherwise the contents of the commits we're pulling will spill into the unstaged area.
            # Note: checkout_tree defaults to a safe checkout, so it'll raise GitError if any uncommitted changes
            # affect any of the files that are involved in the pull.
            with CheckoutBreakdown() as callbacks:
                self.checkout_tree(rb.peel(Tree), callbacks=callbacks)

            # Then make the local branch point to the same commit as the remote branch.
            lb.set_target(rb.target)

        elif merge_analysis == MergeAnalysis.NORMAL:
            # Can't FF. Divergent branches?
            raise DivergentBranchesError(lb, rb)

        else:
            # Unborn or something...
            raise NotImplementedError(f"Cannot fast-forward with {repr(merge_analysis)}.")

    def get_superproject(self) -> str:
        """
        If this repo is a submodule, returns the path to the superproject's working directory,
        otherwise returns None.
        Equivalent to `git rev-parse --show-superproject-working-tree`.
        """

        # Try to detect a "modern" submodule setup first
        # (where the submodule's git dir is absorbed in the superproject's .git/modules)
        gitpath = self.path  # e.g. "/home/user/superproj/.git/modules/src/extern/subproj/"
        git_modules_pos = gitpath.rfind("/.git/modules/")
        if git_modules_pos >= 0:
            outer_wd = gitpath[:git_modules_pos]  # e.g. "/home/user/superproj"
            with _suppress(KeyError):
                tentative_wd = self.config['core.worktree']
                if not _isabs(tentative_wd):
                    tentative_wd = gitpath + "/" + tentative_wd
                tentative_wd = _normpath(tentative_wd)
                actual_wd = _normpath(self.workdir)
                if actual_wd == tentative_wd:
                    return outer_wd

        # Try to detect "legacy" submodule that manages its own .git dir
        norm_wd = _normpath(self.workdir)
        outer_seed = _dirname(norm_wd)
        with _suppress(GitError), RepoContext(outer_seed) as outer_repo:
            assert outer_repo.workdir.endswith("/")
            likely_submo_key = norm_wd.removeprefix(outer_repo.workdir)
            if likely_submo_key in outer_repo.listall_submodules_fast():
                return _normpath(outer_repo.workdir)

        return ""

    def get_branch_from_refname(self, refname: str) -> tuple[Branch, bool]:
        prefix, shorthand = RefPrefix.split(refname)
        if prefix == RefPrefix.HEADS:
            return self.branches.local[shorthand], False
        elif prefix == RefPrefix.REMOTES:
            return self.branches.remote[shorthand], True
        raise ValueError("ref is not a local or remote branch")

    def repo_name(self):
        return _basename(_normpath(self.workdir))

    def get_local_identity(self) -> tuple[str, str]:
        """
        Return the name and email set in the repository's local config.
        If an identity isn't set specifically for this repo, this function returns blank strings.
        """

        config = self.config_snapshot
        local = {}
        for key in ["user.name", "user.email"]:
            with _suppress(KeyError):
                entry = config._get_entry(key)
                if GitConfigLevel.LOCAL <= entry.level: # <= GitConfigLevel.WORKTREE: -----requires pg2 1.15
                    local[key] = entry.value

        name = local.get("user.name", "")
        email = local.get("user.email", "")
        return name, email

    def has_local_identity(self):
        name, email = self.get_local_identity()
        return bool(name or email)

    def delete_tag(self, tagname: str):
        assert not tagname.startswith("refs/")
        refname = RefPrefix.TAGS + tagname
        assert refname in self.references
        self.references.delete(refname)

    def add_inner_repo_as_submodule(self, inner_w: str, remote_url: str, absorb_git_dir: bool = True, name: str = ""):
        outer_w = _Path(self.workdir)
        inner_w = _Path(outer_w, inner_w)  # normalize

        if not inner_w.is_dir():
            raise FileNotFoundError(f"Inner workdir not found: {inner_w}")

        if not inner_w.is_relative_to(outer_w):
            raise ValueError("Subrepo workdir must be relative to superrepo workdir")

        if not name:
            name = str(inner_w.relative_to(outer_w))

        with RepoContext(str(inner_w)) as inner_repo:
            inner_g = _Path(inner_repo.path)
            inner_head_id = inner_repo.head_commit.id

        if not inner_g.is_relative_to(outer_w):
            raise ValueError("Subrepo .git dir must be relative to superrepo workdir")

        gitmodules = GitConfig(self.in_workdir(DOT_GITMODULES))
        gitmodules[f"submodule.{name}.path"] = inner_w.relative_to(outer_w)
        if remote_url:
            gitmodules[f"submodule.{name}.url"] = remote_url
            self.config[f"submodule.{name}.url"] = remote_url

        if absorb_git_dir:
            inner_g2 = _Path(self.path, "modules", inner_w.relative_to(outer_w))
            if inner_g2.exists():
                raise FileExistsError(f"Directory already exists: {inner_g2}")
            inner_g2.parent.mkdir(parents=True, exist_ok=True)
            inner_g.rename(inner_g2)
            inner_g = inner_g2

            # TODO: Use Path.relative_to(..., walk_up=True) once we drop support for all versions older than Python 3.13
            submodule_config = GitConfig(str(inner_g / "config"))
            submodule_config["core.worktree"] = _relpath(inner_w, inner_g2)

            with open(inner_w / ".git", "wt") as submodule_dotgit_file:
                submodule_dotgit_file.write(f"gitdir: {_relpath(inner_g2, inner_w)}\n")

        # Poor man's workaround for git_submodule_add_to_index (not available in pygit2 yet)
        entry = IndexEntry(inner_w.relative_to(outer_w), inner_head_id, FileMode.COMMIT)
        self.index.add(entry)

        # While we're here also add .gitmodules
        self.index.add(DOT_GITMODULES)

    def remove_submodule(self, submodule_name: str):
        inner_w = self.listall_submodules_dict()[submodule_name]
        config_abspath = self.in_workdir(DOT_GITMODULES)

        # Delete "submodule.{name}.*" from local config (optional)
        GitConfigHelper.delete_section(_joinpath(self.path, "config"), "submodule", submodule_name)

        # Delete "submodule.{name}.*" from .gitmodules
        did_delete = GitConfigHelper.delete_section(config_abspath, "submodule", submodule_name)

        if GitConfigHelper.is_empty(config_abspath):
            # That was the only submodule, so remove .gitmodules
            _os.unlink(config_abspath)
            self.index.remove(DOT_GITMODULES)
        else:
            self.index.add(DOT_GITMODULES)

        if did_delete:
            _shutil.rmtree(self.in_workdir(inner_w))
            self.index.remove(inner_w)

        self.index.write()

    def restore_submodule_gitlink(self, inner_wd: str) -> bool:
        """
        If a submodule's worktree was deleted, recreate the ".git" file that
        connects the submodule's worktree to the repo within ".git/modules".

        Return True if the gitlink file needed to be restored.
        """
        assert not _isabs(inner_wd)

        sub_wd = self.in_workdir(inner_wd)
        sub_dotgit = _joinpath(sub_wd, ".git")
        sub_gitdir = _joinpath(self.path, "modules", inner_wd)

        def can_restore():
            if _exists(sub_dotgit):
                # The .git file already exists in the submo's worktree
                return False

            sub_configpath = _joinpath(sub_gitdir, "config")
            if not _isfile(sub_configpath):
                # Can't find corresponding bare repo in .git/modules
                return False

            # Double-check worktree path...
            try:
                wd2 = GitConfig(sub_configpath)["core.worktree"]
            except KeyError:
                return False

            # Make it an absolute path
            if not _isabs(wd2):
                wd2 = _joinpath(sub_gitdir, wd2)
                wd2 = _abspath(wd2)

            # The worktree that's configured for this submodule
            # has to match the path we're given.
            return sub_wd == wd2

        if can_restore():
            # Restore gitlink file
            _os.makedirs(_dirname(sub_dotgit), exist_ok=True)
            with open(sub_dotgit, "wt") as f:
                rel_gitdir = _relpath(sub_gitdir, sub_wd)
                f.write(f"gitdir: {rel_gitdir}\n")
            return True

    @staticmethod
    def _sanitize_config_key(key: str | tuple) -> str:
        if type(key) is tuple:
            key = ".".join(key)
        assert type(key) is str
        return key

    def get_config_value(self, key: str | tuple):
        key = self._sanitize_config_key(key)
        try:
            return self.config[key]
        except KeyError:
            return ""

    def set_config_value(self, key: str | tuple, value: str):
        key = self._sanitize_config_key(key)
        if value:
            self.config[key] = value
        else:
            with _suppress(KeyError):
                del self.config[key]

    def get_reset_merge_file_list(self):
        self.index.read()

        staged_diff = self.diff('HEAD', None, cached=True)  # staged - index to head
        unstaged_diff = self.diff(None, None)  # unstaged - index to workdir

        staged_paths = [p.delta.new_file.path for p in staged_diff]
        unstaged_paths = [p.delta.new_file.path for p in unstaged_diff if p.delta.status != DeltaStatus.CONFLICTED]

        if set(staged_paths).intersection(unstaged_paths):
            raise ValueError("entries not up-to-date")

        return staged_paths

    def reset_merge(self):
        """
        "git reset --merge" resets the index and updates the files in the working tree that are different between
        <commit> and HEAD, but keeps those which are different between the index and working tree (i.e. which have
        changes which have not been added). If a file that is different between <commit> and the index has unstaged
        changes, reset is aborted.

        In other words, --merge does something like a git read-tree -u -m <commit>, but carries forward unmerged
        index entries.
        """
        staged_paths = self.get_reset_merge_file_list()
        if staged_paths:
            self.restore_files_from_head(staged_paths)

    def wrap_conflict(self, path: str) -> DiffConflict:
        ancestor, ours, theirs = self.index.conflicts[path]
        return DiffConflict(ancestor, ours, theirs)


class RepoContext:
    def __init__(self, path: str | _Path, flags: RepositoryOpenFlag = 0, write_index = False):
        self.repo = Repo(path, flags)
        self.write_index = write_index

    def __enter__(self) -> Repo:
        return self.repo

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.write_index:
            self.repo.index.write()
        # repo.free() is necessary for correct test teardown on Windows
        self.repo.free()
        del self.repo
        self.repo = None


class ConflictSides(enum.IntEnum):
    # -------------------TOA (Theirs, Ours, Ancestor)
    MODIFIED_BY_BOTH = 0b111
    DELETED_BY_THEM  = 0b011
    DELETED_BY_US    = 0b101
    DELETED_BY_BOTH  = 0b001
    ADDED_BY_US      = 0b010
    ADDED_BY_THEM    = 0b100
    ADDED_BY_BOTH    = 0b110


@_dataclasses.dataclass(frozen=True)
class DiffConflict:
    ancestor: IndexEntry | None
    ours: IndexEntry | None
    theirs: IndexEntry | None

    @property
    def sides(self) -> ConflictSides:
        a = 0b001 * bool(self.ancestor)
        o = 0b010 * bool(self.ours)
        t = 0b100 * bool(self.theirs)
        return ConflictSides(t | o | a)
        # This ctor will raise ValueError if it's an invalid IntEnum

    @property
    def deleted_by_us(self):
        return self.sides == ConflictSides.DELETED_BY_US

    @property
    def deleted_by_them(self):
        return self.sides == ConflictSides.DELETED_BY_THEM

    @property
    def deleted_by_both(self):
        return self.sides == ConflictSides.DELETED_BY_BOTH

    @property
    def modified_by_both(self):
        return self.sides == ConflictSides.MODIFIED_BY_BOTH

    @property
    def added_by_them(self):
        return self.sides == ConflictSides.ADDED_BY_THEM

    @property
    def added_by_us(self):
        return self.sides == ConflictSides.ADDED_BY_US

    @property
    def added_by_both(self):
        return self.sides == ConflictSides.ADDED_BY_BOTH
