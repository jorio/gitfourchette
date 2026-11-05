# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations as _annotations

import configparser as _configparser
import enum as _enum
import hashlib
import logging as _logging
import os as _os
import re as _re
import typing as _typing
import warnings as _warnings
from contextlib import suppress as _suppress
from pathlib import Path as _Path

from pygit2 import settings as _pygit2settings

from pygit2 import (
    Blob,
    Branch,
    Commit,
    Config as GitConfig,
    Diff,
    GitError,
    IndexEntry,
    InvalidSpecError,
    Object as GitObject,
    Oid,
    Remote,
    Repository as _VanillaRepository,
    Signature,
    Stash,
    Submodule,
    Tree,
    Walker,

    __version__ as PYGIT2_VERSION,
    LIBGIT2_VERSION,
)

from pygit2.enums import (
    ApplyLocation,
    BranchType,
    ConfigLevel as GitConfigLevel,
    DeltaStatus,
    DiffOption,
    FileStatus,
    FileMode,
    MergeAnalysis,
    MergePreference,
    ObjectType,
    RepositoryOpenFlag,
    RepositoryState,
    ReferenceType,
    ResetMode,
    SortMode,
)

from gitfourchette.versiontuple import versiontuple


_logger = _logging.getLogger(__name__)

NULL_OID = Oid(raw=b'')
"""
A hash consisting of all zeros.
Used in some places to denote the absence of an object.
"""

EMPTYTREE_OID = Oid(hex="4b825dc642cb6eb9a060e54bf8d69288fbee4904")
"""
SHA-1 hash of the empty tree (sha1(b"tree \0")).
"""

DOT_GITMODULES = ".gitmodules"

CORE_STASH_MESSAGE_PATTERN = _re.compile(r"^On (?:[^\s:]+|\(no branch\)): (.+)")
WINDOWS_RESERVED_FILENAMES_PATTERN = _re.compile(r"(.*/)?(AUX|COM[1-9]|CON|LPT[1-9]|NUL|PRN)($|\.|/)", _re.IGNORECASE)


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
    class Rule(_enum.IntEnum):
        CANNOT_BE_EMPTY = 0
        ILLEGAL_NAME = 1
        ILLEGAL_PREFIX = 2
        ILLEGAL_SUFFIX = 3
        CONTAINS_ILLEGAL_CHAR = 4
        CONTAINS_ILLEGAL_SEQ = 5
        NOT_WINDOWS_FRIENDLY = 6
        NAME_TAKEN_BY_REF = 7
        NAME_TAKEN_BY_FOLDER = 8
        NOT_A_FOLDER = 9

    def __init__(self, rule: Rule):
        super().__init__(f"Name validation failed ({rule})")
        self.rule = rule


class MultiFileError(Exception):
    file_exceptions: dict[str, Exception | None]

    def __init__(self, message: str = ""):
        self.file_exceptions = {}
        self.message = message
        self.file_successes = 0

    def add_file_error(self, path: str, exc: Exception | None):
        self.file_exceptions[path] = exc

    def add_file_success(self):
        self.file_successes += 1

    def __bool__(self):
        return bool(self.file_exceptions)


class _UnchangedConfigFile(Exception):
    pass


def fast_blob_sha1(data: bytes) -> Oid:
    """
    Drop-in replacement for pygit2.hash(). Can be much faster depending on how
    libgit2 was built (in practice this implementation is never slower).
    """
    hasher = hashlib.sha1(f"blob {len(data)}\0".encode("ascii"))
    hasher.update(data)
    sha1 = hasher.digest()
    return Oid(raw=sha1)


def pygit2_min_version(required_version: str, warning: str = "") -> bool:
    req = versiontuple(required_version)
    cur = versiontuple(PYGIT2_VERSION)

    if cur >= req:
        return True

    if warning:
        _warnings.warn(f"{warning} requires pygit2 v{required_version} "
                       f"or later (you have v{PYGIT2_VERSION}).")

    return False


def id7(obj: str | Oid | GitObject, n=7):
    """
    Shorten oid or Object oid
    """
    if isinstance(obj, str):
        sid = obj
    elif isinstance(obj, Oid):
        sid = str(obj)
    else:
        sid = str(obj.id)
    return sid[:n]


def commit_diff_pair(commit: Commit) -> tuple[Oid | None, Oid]:
    try:
        # Compare to first parent
        a = commit.parent_ids[0]
    except IndexError:
        # Root commit, compare to empty tree
        a = None

    return a, commit.id


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
        remote_name, branch_name = remote_branch_name.split("/", 1)
        return remote_name, branch_name
    except ValueError:
        # `git svn clone` creates .git/refs/remotes/git-svn, which trips up pygit2
        return remote_branch_name, ""


def validate_refname(name: str, reserved_names: list[str], allow_dash_prefix: bool = False):
    """
    Checks the validity of a ref name according to `man git-check-ref-format`.
    Raises NameValidationError if the name is incorrect.
    """

    # Can't be empty
    if not name:
        raise NameValidationError(NameValidationError.Rule.CANNOT_BE_EMPTY)

    # Rule 9: can't be single character '@'
    if name == '@':
        raise NameValidationError(NameValidationError.Rule.ILLEGAL_NAME)

    # Rule 4: forbid space, tilde, caret, colon
    # Rule 5: forbid question mark, asterisk, open bracket
    # Rule 10: forbid backslash
    if any(c in " ~^:[?*\\" for c in name):
        raise NameValidationError(NameValidationError.Rule.CONTAINS_ILLEGAL_CHAR)

    # Rule 1: slash-separated components can't start with dot or end with .lock
    # Rule 3: forbid consecutive dots
    # Rule 6: forbid consecutive slashes
    # Rule 8: forbid '@{'
    if any(seq in name for seq in ["/.", ".lock/", "..", "//", "@{"]):
        raise NameValidationError(NameValidationError.Rule.CONTAINS_ILLEGAL_SEQ)

    # Rule 1: can't start with dot
    # Rule 6: can't start with slash
    if name.startswith((".", "/")):
        raise NameValidationError(NameValidationError.Rule.ILLEGAL_PREFIX)

    # Also: branches and tags can't start with dash
    if not allow_dash_prefix and name.startswith("-"):
        raise NameValidationError(NameValidationError.Rule.ILLEGAL_PREFIX)

    # Rule 1: can't end with .lock
    # Rule 6: can't end with slash
    # Rule 7: can't end with dot
    if name.endswith((".lock", "/", ".")):
        raise NameValidationError(NameValidationError.Rule.ILLEGAL_SUFFIX)

    # Prevent filenames that are reserved on Windows
    if WINDOWS_RESERVED_FILENAMES_PATTERN.match(name):
        raise NameValidationError(NameValidationError.Rule.NOT_WINDOWS_FRIENDLY)

    # Don't clash with existing refs
    if name.lower() in (n.lower() for n in reserved_names):
        raise NameValidationError(NameValidationError.Rule.NAME_TAKEN_BY_REF)

    # Don't clash with ref folders. If you attempt to rename a branch to the
    # name of an existing folder, libgit2 first deletes the branch, then errors
    # out with "cannot lock ref 'refs/heads/folder', there are refs beneath
    # that folder". So, let's avoid losing the branch.
    folder = name.lower() + "/"
    if any(n.lower().startswith(folder) for n in reserved_names):
        raise NameValidationError(NameValidationError.Rule.NAME_TAKEN_BY_FOLDER)

    # Prevent creating a folder with the same name as an existing ref
    if "/" in name and any(name.lower().startswith(n.lower() + "/") for n in reserved_names):
        raise NameValidationError(NameValidationError.Rule.NOT_A_FOLDER)


def validate_signature_item(s: str):
    """
    Checks the validity of the name or email in a signature according to `libgit2/signature.c`.
    Raises NameValidationError if the item is incorrect.
    """

    # Angle bracket characters are not allowed
    if "<" in s or ">" in s:
        raise NameValidationError(NameValidationError.Rule.CONTAINS_ILLEGAL_CHAR)

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
        raise NameValidationError(NameValidationError.Rule.CANNOT_BE_EMPTY)


def signatures_equalish(a: Signature, b: Signature) -> bool:
    """
    Sometimes two signature objects differ only by the encoding field.
    """

    if a == b:
        return True

    if not isinstance(a, Signature) or not isinstance(b, Signature):
        return False  # type: ignore[unreachable]

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


def strip_stash_message(stash_message: str) -> str:
    m = CORE_STASH_MESSAGE_PATTERN.match(stash_message)
    if m:
        return m.group(1)
    # Remove linebreaks in WIP-type messages
    return stash_message.split('\n', maxsplit=1)[0]


class GitConfigHelper:
    # Rough equivalent of git_config_open_default (not available in pygit2 yet)
    default_config_getters: _typing.ClassVar = [
        (GitConfigLevel.GLOBAL, GitConfig.get_global_config),   # ~/.gitconfig
        (GitConfigLevel.XDG,    GitConfig.get_xdg_config),      # ~/.config/git/config
        (GitConfigLevel.SYSTEM, GitConfig.get_system_config),   # /etc/gitconfig
        # Note: libgit2's git_config_open_default also adds GitConfigLevel.PROGRAMDATA for Windows,
        # but pygit2 doesn't expose git_config_find_programdata.
    ]
    assert (sorted([gcl for gcl, _ in default_config_getters], reverse=True)
            == [gcl for gcl, _ in default_config_getters]
            ), "default_config_getters should be sorted by decreasing globality"

    class SectionPatterns:
        SUBMODULE = _re.compile(r'^submodule "(.+)"$')
        REMOTE = _re.compile(r'^remote "(.+)"$')
        BRANCH = _re.compile(r'^branch "(.+)"$')

    @staticmethod
    def sanitize_key(key: str | tuple[str, ...]) -> str:
        if type(key) is tuple:
            return ".".join(key)
        assert type(key) is str
        return key

    @staticmethod
    def path_for_level(level: GitConfigLevel, missing_dir_ok=False):
        if not (GitConfigLevel.PROGRAMDATA <= level <= GitConfigLevel.GLOBAL):
            raise NotImplementedError(f"unsupported level {level}")

        # Several paths may be concatenated with GIT_PATH_LIST_SEPARATOR,
        # which git2/common.h defines as ":" (or ";" on Windows).
        # pygit2 doesn't expose this, but it appears to match os.pathsep.
        search_paths_orig = _pygit2settings.search_path[level].split(_os.pathsep)
        search_paths = [_Path(p) for p in search_paths_orig if p]  # filter out any empty paths

        if not search_paths:
            raise KeyError(f"no search path is set up for git config level {level}")

        try:
            path = next(p for p in search_paths if p.is_dir())
        except StopIteration as exc:
            if not missing_dir_ok:
                raise FileNotFoundError(f"no parent dir exists for git config level {level}") from exc
            path = search_paths[0]

        # Select appropriate filename (see libgit2/config.h: GIT_CONFIG_FILENAME_SYSTEM, etc.)
        if level == GitConfigLevel.SYSTEM:
            filename = "gitconfig"
        elif level == GitConfigLevel.GLOBAL:
            filename = ".gitconfig"
        else:
            filename = "config"

        return str(path / filename)

    @staticmethod
    def ensure_file(level: GitConfigLevel = GitConfigLevel.GLOBAL) -> GitConfig:
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
            path = GitConfigHelper.path_for_level(level, missing_dir_ok=True)
            _Path(path).parent.mkdir(parents=True, exist_ok=True)
            return GitConfig(path)

    @classmethod
    def get_default_value(cls, key: str | tuple) -> str:
        key = cls.sanitize_key(key)
        for _dummy, getter in cls.default_config_getters:
            with _suppress(OSError, KeyError):
                config = getter()
                return config[key]
        return ""

    @staticmethod
    def unescape(s: str):
        return s.encode('raw_unicode_escape').decode('unicode_escape')

    @staticmethod
    def walk_sections(config: _configparser.ConfigParser, section_pattern: _re.Pattern):
        for section_name in config.sections():
            match = section_pattern.fullmatch(section_name)
            if not match:
                continue

            section = config[section_name]
            name = GitConfigHelper.unescape(match.group(1))
            yield name, section


class Repo(_VanillaRepository):
    """
    Drop-in replacement for pygit2.Repository with convenient front-ends to common git operations.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cached_config_stats = {}
        self._cached_config_stats_for_key = {}
        self._cached_config_parsers = {}
        self._cached_remote_list = []
        self._cached_upstream_table = {}
        self._cached_submodule_table = {}
        self._cached_commondir = ""

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

    def peel_commit(self, commit_id: Oid | str) -> Commit:
        return self[commit_id].peel(Commit)

    def peel_blob(self, blob_id: Oid | str) -> Blob:
        return self[blob_id].peel(Blob)

    def peel_tree(self, tree_id: Oid | str) -> Tree:
        return self[tree_id].peel(Tree)

    def in_workdir(self, path: str) -> str:
        """Return an absolutized version of `path` within this repo's workdir."""
        assert not _Path(path).is_absolute()
        p = _Path(self.workdir, path)
        if not p.is_relative_to(self.workdir):
            raise ValueError("Won't create absolute path outside workdir")
        return str(p)

    def is_in_workdir(self, path: str, include_gitdir: bool = False) -> bool:
        p = _Path(path)
        return (p.is_relative_to(self.workdir)
                and (include_gitdir or not p.is_relative_to(self.path)))

    @property
    def commondir(self) -> str:
        """
        Return the absolute path to this worktree's $GIT_COMMON_DIR.
        If this Repo isn't a worktree, the return value resolves to the same
        path as `Repo.path`.
        """
        if not self._cached_commondir:
            path = self.path
            commondir = _Path(path, "commondir")
            if commondir.exists():
                path = commondir.read_text().rstrip()
                path_obj = commondir.parent / path
                path_obj = path_obj.resolve(strict=True)
                path = str(path_obj)
                # For compatibility with Repository.path, tack a '/' to the end
                assert not path.endswith(_os.sep)
                path += _os.sep
            self._cached_commondir = path
        return self._cached_commondir

    def in_gitdir(self, path: str, common: bool = True) -> str:
        """
        Return an absolutized version of `path` within this repo's .git directory.

        If `common` is False, return `path` inside the worktree's private $GIT_DIR.
        Otherwise, return `path` inside $GIT_COMMON_DIR, i.e. the ".git" directory
        common to all worktrees. (See manpages for gitrepository-layout git-worktree)

        The `common` argument has no effect if this repo isn't a worktree.
        """
        assert not _Path(path).is_absolute()

        parent = self.commondir if common else self.path
        parent_resolved = _Path(parent).resolve()
        p = _Path(parent, path).resolve()

        if not p.is_relative_to(parent_resolved):
            raise ValueError("Won't resolve absolute path outside gitdir")

        return str(p)

    def refresh_index(self, force: bool = False):
        """
        Reload the index. Call this before manipulating the staging area
        to ensure any external modifications are taken into account.

        This is a fairly cheap operation if the index hasn't changed on disk,
        unless you pass force=True.
        """
        self.index.read(force)

    @property
    def any_conflicts(self) -> bool:
        """True if there are any conflicts in the index."""
        return bool(self.index.conflicts)

    @property
    def any_staged_changes(self) -> bool:
        """True if there are any staged changes in the index."""

        flags = DiffOption.INCLUDE_TYPECHANGE

        if self.head_is_unborn:  # can't compare against HEAD (empty repo or branch pointing nowhere)
            index_tree_id = self.index.write_tree()
            tree = self.peel_tree(index_tree_id)
            diff = tree.diff_to_tree(swap=True, flags=flags, context_lines=0)
        else:
            # compare HEAD to index
            diff = self.diff('HEAD', None, cached=True, flags=flags, context_lines=0)

        return 0 != len(diff)
        # ---This also works, but it's slower.
        # status = repo.status(untracked_files="no")
        # return any(0 != (flag & FileStatus.INDEX_MASK) for flag in status.values())

    def listall_remote_branches(self, value_style: _typing.Literal["strip", "shorthand", "refname"] = "strip") -> dict[str, list[str]]:
        names: dict[str, list[str]] = {}

        # Create empty lists for all remotes (including branchless remotes)
        for remote in self.remotes:
            names[remote.name] = []

        for ref in self.references.iterator():
            prefix, shorthand = RefPrefix.split(ref.name)

            if prefix != RefPrefix.REMOTES:
                continue

            if ref.name.endswith("/HEAD"):
                # Skip refs/remotes/*/HEAD (the remote's default branch).
                # The ref file (.git/refs/remotes/*/HEAD) is created ONCE when first cloning the repository,
                # and it's never updated again automatically, even if the default branch has changed on the remote.
                # It's a symbolic branch, so looking up a stale version of the remote's HEAD may raise KeyError.
                # It's just not worth the trouble.
                # See: https://stackoverflow.com/questions/8839958
                continue

            # Skip symbolic refs (e.g., repo tool's refs/remotes/m/master -> origin/master).
            # We only show direct refs in real remotes; resolving would duplicate the target
            # (e.g. origin/master would appear twice in the upstream context menu).
            if ref.type == ReferenceType.SYMBOLIC:
                continue

            remote_name, branch_name = split_remote_branch_shorthand(shorthand)
            # Skip references without a branch name (e.g., refs/remotes/git-svn from git svn clone)
            if not branch_name:
                continue
            # Skip references that don't match any known remote (e.g., stale refs from deleted remotes)
            if remote_name not in names:
                continue
            if value_style == "strip":
                value = branch_name
            elif value_style == "shorthand":
                value = shorthand
            elif value_style == "refname":
                value = ref.name
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

    def get_remote_skipfetchall(self, remote_name: str) -> bool:
        key = GitConfigHelper.sanitize_key(("remote", remote_name, "skipFetchAll"))
        try:
            return self.config.get_bool(key)
        except KeyError:
            return False

    def set_remote_skipfetchall(self, remote_name: str, value: bool):
        key = GitConfigHelper.sanitize_key(("remote", remote_name, "skipFetchAll"))

        # Set skipFetchAll only if it's True, otherwise delete it
        if value:
            self.config[key] = value
        else:
            with _suppress(KeyError):
                del self.config[key]

    def get_commit_message(self, commit_id: Oid) -> str:
        commit = self.peel_commit(commit_id)
        return commit.message

    def commit_id_from_refname(self, refname: str) -> Oid:
        reference = self.references[refname]
        commit: Commit = reference.peel(Commit)
        return commit.id

    def commit_id_from_tag_name(self, tagname: str) -> Oid:
        assert not tagname.startswith("refs/")
        return self.commit_id_from_refname(RefPrefix.TAGS + tagname)

    def map_refs_to_ids(self, include_stashes=False) -> dict[str, Oid]:
        """
        Return commit oids at the tip of all branches, tags, etc. in the repository.

        To ensure a consistent outcome across multiple walks of the same commit graph,
        the oids are sorted by ascending commit time.
        """

        tips: list[tuple[str, Commit]] = []

        supported_prefixes = (RefPrefix.HEADS, RefPrefix.REMOTES, RefPrefix.TAGS)

        for ref in self.listall_reference_objects():
            name: str = ref.name

            # Any text file containing a hash will be picked up by libgit2 if it is in refs/.
            # Exclude those if they don't match any of our supported ref prefixes.
            # Note that this also excludes refs/stash - we deal with stashes separately.
            if not name.startswith(supported_prefixes):
                continue

            # Skip symbolic references
            if ref.type != ReferenceType.DIRECT:
                continue

            # Skip non-commit references
            obj = ref.peel()
            if obj.type != ObjectType.COMMIT:
                continue

            assert isinstance(obj, Commit)
            tips.append((name, obj))

        if include_stashes:
            for i, stash in enumerate(self.listall_stashes()):
                try:
                    commit = self.peel_commit(stash.commit_id)
                    tips.append((f"stash@{{{i}}}", commit))
                except InvalidSpecError as e:
                    _logger.info(f"{e} - Skipping stash '{stash.message}'")

        # Always add 'HEAD' if we have one.
        # Do so *just* before reinserting the tips in chronological order below.
        # This will sort the checked-out branch at the *end* of the list
        # if there is another tip that shares the exact same timestamp.
        # (Refs pushed into Walker are Last-In First-Out, so the local branch will
        # come out on top e.g. when pushing a branch to a remote, then amending
        # the top commit with the same author/committer signatures.)
        try:
            tips.append(("HEAD", self.head_commit))
        except (GitError, InvalidSpecError):
            pass  # Skip detached/unborn head

        # Reinsert all tips in chronological order
        # (In Python 3.7+, dict key order is stable)
        tips.sort(key=lambda item: item[1].commit_time)
        return {ref: commit.id for ref, commit in tips}

    def listall_refs_pointing_at(self, commit_id: Oid, include_stashes=False):
        refs = []

        # Detached HEAD isn't in repo.references
        if self.head_is_detached and type(self.head.target) is Oid and self.head.target == commit_id:
            refs.append('HEAD')

        for ref in self.references.objects:
            ref_key = ref.name

            if type(ref.target) is not Oid:
                # Symbolic reference
                _logger.debug(f"Skipping symbolic reference {ref_key} --> {ref.target}")
                continue

            if ref.target != commit_id:
                continue

            assert ref_key.startswith("refs/")

            if ref_key == "refs/stash":
                # This is just the topmost stash.
                # Exhaustive stash info must be obtained separately.
                continue

            refs.append(ref_key)

        if include_stashes:
            for stash_index, stash in enumerate(self.listall_stashes()):
                if stash.commit_id == commit_id:
                    refs.append(f"stash@{{{stash_index}}}")

        return refs

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

    def create_stash(self, message: str, paths: list[str]) -> Oid:
        """
        Creates a stash that backs up all changes to the given files.
        Does NOT remove the changes from the workdir!
        (You can call 'git clean'/'git restore' manually afterwards).
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
        except StopIteration as exc:
            raise KeyError(f"Stash not found: {commit_id}") from exc

    # Override pygit2.Repository.apply()
    def apply(self,
              patch_data_or_diff: bytes | str | Diff,
              location: ApplyLocation = ApplyLocation.WORKDIR
              ):
        if isinstance(patch_data_or_diff, bytes | str):
            diff = Diff.parse_diff(patch_data_or_diff)
        elif isinstance(patch_data_or_diff, Diff):
            diff = patch_data_or_diff
        else:
            raise TypeError("patch_data_or_diff must be bytes, str, or Diff")

        super().apply(diff, location)

    def get_submodule_workdir(self, submo_key: str) -> str:
        submo = self.submodules[submo_key]
        return self.in_workdir(submo.path)

    def submodule_dotgit_present(self, submo_path: str) -> bool:
        path = self.in_workdir(submo_path)
        return _Path(path, ".git").exists()

    def repo_name(self) -> str:
        return _Path(self.workdir).resolve().name

    def get_config_value(self, key: str | tuple):
        key = GitConfigHelper.sanitize_key(key)
        try:
            return self.config[key]
        except KeyError:
            return ""

    def set_config_value(self, key: str | tuple, value: str):
        key = GitConfigHelper.sanitize_key(key)
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

        intersection = set(staged_paths).intersection(unstaged_paths)

        if intersection:
            error = MultiFileError()
            for path in intersection:
                error.add_file_error(path, None)
            raise error

        return staged_paths

    @property
    def message_without_conflict_comments(self) -> str:
        message = self.message
        clean_message = ""
        for line in message.splitlines(keepends=True):
            if not line.startswith('#'):
                clean_message += line
        return clean_message.strip()

    # -------------------------------------------------------------------------
    # Config parsers ("listall" APIs)

    def listall_remotes_fast(self):
        """
        Faster alternative to `list(repo.remotes.names())`.
        """
        config_path = self.in_gitdir("config", common=True)
        try:
            # strict=False to bypass DuplicateSectionError
            config = self._get_cached_config("listall_remotes_fast", config_path, strict=False)
        except OSError:
            self._cached_remote_list = []
        except _UnchangedConfigFile:
            pass
        else:
            self._cached_remote_list = Repo._listall_remotes_from_config(config)

        return self._cached_remote_list

    def listall_upstreams_fast(self) -> dict[str, str]:
        """
        Much faster alternative to looking up `Branch.upstream_name` in every branch.
        """
        config_path = self.in_gitdir("config", common=True)
        try:
            # strict=False to bypass DuplicateSectionError
            config = self._get_cached_config("listall_upstreams", config_path, strict=False)
        except OSError:
            self._cached_upstream_table = {}
        except _UnchangedConfigFile:
            pass
        else:
            self._cached_upstream_table = Repo._listall_upstreams_from_config(config)

        return self._cached_upstream_table

    def listall_submodules(self):  # pragma: no cover
        """
        Don't use listall_submodules, it's slow and it omits critical
        information about submodule names.
        Note that if a submodule's name is different from its path,
        SubmoduleCollection[path].name will NOT return the correct name!
        """
        _warnings.warn("Don't use this", DeprecationWarning)
        raise DeprecationWarning("Don't use listall_submodules")

    def listall_submodules_fast(self) -> list[str]:
        """
        Faster drop-in replacement for pygit2's Repository.listall_submodules (which can be very slow).
        Return a list of submodule workdir paths within the root repo's workdir.
        """
        return list(self.listall_submodules_dict().values())

    def listall_submodules_dict(self, config_text="") -> dict[str, str]:
        """
        Return a dict of submodule names to paths.
        Information is sourced from .gitmodules (or config_text if given).

        You should use this instead of pygit2's Repository.listall_submodules,
        because the latter doesn't give you information about submodule names.
        It is also faster.
        """
        # We use ConfigParser instead of pygit2.Config so that we can load the
        # config from a blob in memory.

        if config_text:
            config = _configparser.ConfigParser()
            config.read_string(config_text)
            return Repo._listall_submodules_from_config(config)

        config_path = self.in_workdir(DOT_GITMODULES)
        try:
            config = self._get_cached_config("listall_submodules_dict", config_path, strict=True)
        except OSError:
            self._cached_submodule_table = {}
        except _UnchangedConfigFile:
            pass
        else:
            self._cached_submodule_table = Repo._listall_submodules_from_config(config)
        return self._cached_submodule_table

    def listall_submodules_dict_at_head(self) -> dict[str, str]:
        try:
            gitmodules_blob: Blob = self.head_tree[".gitmodules"].peel(Blob)
        except (KeyError,  # .gitmodules doesn't exist
                ValueError):  # .gitmodules not Blob (probably Tree)
            return {}
        old_gitmodules = gitmodules_blob.data.decode("utf-8")
        return self.listall_submodules_dict(config_text=old_gitmodules)

    def _get_cached_config(self, cache_key: str, path: str, strict: bool) -> _configparser.ConfigParser:
        new_stat = _os.stat(path)

        with _suppress(KeyError):
            key_stat = self._cached_config_stats_for_key[cache_key]
            if key_stat == new_stat:
                raise _UnchangedConfigFile()

        self._cached_config_stats_for_key[cache_key] = new_stat

        with _suppress(KeyError):
            known_stat = self._cached_config_stats[path]
            if new_stat == known_stat:
                return self._cached_config_parsers[path]

        config = _configparser.ConfigParser(strict=strict)
        config.read(path)
        self._cached_config_stats[path] = new_stat
        self._cached_config_parsers[path] = config
        return config

    @staticmethod
    def _listall_remotes_from_config(config: _configparser.ConfigParser):
        remotes = []

        for remote_name, section in GitConfigHelper.walk_sections(config, GitConfigHelper.SectionPatterns.REMOTE):
            if not section.items():  # Skip empty sections
                continue
            remotes.append(remote_name)

        return remotes

    @staticmethod
    def _listall_upstreams_from_config(config: _configparser.ConfigParser):
        upstreams = {}

        for branch_name, section in GitConfigHelper.walk_sections(config, GitConfigHelper.SectionPatterns.BRANCH):
            try:
                remote_name = section["remote"]
                remote_ref = section["merge"]
            except KeyError:
                continue

            remote_ref_prefix, remote_branch = RefPrefix.split(remote_ref)
            if remote_ref_prefix != RefPrefix.HEADS:
                _logger.warning(f"unexpected prefix in config value {section}.merge: '{remote_branch}'")
                continue

            remote_branch = GitConfigHelper.unescape(remote_branch)
            remote_name = GitConfigHelper.unescape(remote_name)

            upstreams[branch_name] = f"{remote_name}/{remote_branch}"

        return upstreams

    @staticmethod
    def _listall_submodules_from_config(config: _configparser.ConfigParser):
        submodules = {}

        for submodule_name, section in GitConfigHelper.walk_sections(config, GitConfigHelper.SectionPatterns.SUBMODULE):
            try:
                path = section["path"]
            except KeyError:
                continue

            path = GitConfigHelper.unescape(path)
            submodules[submodule_name] = path

        return submodules

    def apply_filters_to_workdir(self, path: str) -> bytes:
        # See if this file is subject to any filters
        try:
            filters = self.load_filter_list(path)
        except AttributeError:  # pragma: no cover (old pygit2 compatibility)
            # TODO: Remove this once we can stop supporting pygit2 <= 1.19.1.
            #       This applies filters, but it also writes the resulting blob
            #       to the ODB on disk, which isn't optimal for transient contents
            #       that may change frequently (unstaged files).
            oid = self.create_blob_fromworkdir(path)
            blob = self.peel_blob(oid)
            return blob.data

        if filters is None:
            # No filters, read file from disk
            return _Path(self.in_workdir(path)).read_bytes()
        else:
            # Apply filters in a buffer
            return filters.apply_to_file(self, path)


class RepoContext:
    def __init__(self, repo_or_path: Repo | str | _Path, flags=RepositoryOpenFlag.DEFAULT, write_index=False):
        assert isinstance(repo_or_path, Repo | str | _Path)
        if isinstance(repo_or_path, Repo):
            self.repo = repo_or_path
            assert flags == 0, "flags are ignored if passing in a Repo"
        else:
            path = repo_or_path
            self.repo = Repo(path, flags)
        self.write_index = write_index

    def __enter__(self) -> Repo:
        return self.repo

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.write_index:
            self.repo.index.write()
        # repo.free() is necessary for correct test teardown on Windows
        self.repo.free()
        self.repo = None


# Bypass pygit2 1.21's artificial restriction on RepositoryConfig.add_file
if pygit2_min_version("1.21"):
    from pygit2 import RepositoryConfig as _RepositoryConfig
    _RepositoryConfig.add_file = GitConfig.add_file  # type: ignore[method-assign]
