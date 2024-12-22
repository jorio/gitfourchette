# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from __future__ import annotations

from typing import TYPE_CHECKING

from gitfourchette.localization import *
from gitfourchette.porcelain import *

if TYPE_CHECKING:
    from gitfourchette.toolbox import PatchPurpose
    from gitfourchette.sidebar.sidebarmodel import SidebarItem


class TrTables:
    _exceptionNames             : dict[str, str] = {}
    _nameValidationCodes        : dict[int, str] = {}
    _sidebarItems               : dict[SidebarItem, str] = {}
    _prefKeys                   : dict[str, str] = {}
    _diffStatusChars            : dict[str, str] = {}
    _fileModes                  : dict[FileMode, str] = {}
    _shortFileModes             : dict[FileMode, str] = {}
    _repositoryStates           : dict[RepositoryState, str] = {}
    _patchPurposes              : dict[PatchPurpose, str] = {}
    _patchPurposesPastTense     : dict[PatchPurpose, str] = {}
    _conflictSides              : dict[ConflictSides, str] = {}

    @classmethod
    def init(cls):
        if not cls._exceptionNames:
            cls.retranslate()

    @classmethod
    def retranslate(cls):
        cls._exceptionNames = cls._init_exceptionNames()
        cls._nameValidationCodes = cls._init_nameValidationCodes()
        cls._sidebarItems = cls._init_sidebarItems()
        cls._prefKeys = cls._init_prefKeys()
        cls._diffStatusChars = cls._init_diffStatusChars()
        cls._fileModes = cls._init_fileModes()
        cls._shortFileModes = cls._init_shortFileModes()
        cls._repositoryStates = cls._init_repositoryStates()
        cls._patchPurposes = cls._init_patchPurposes()
        cls._patchPurposesPastTense = cls._init_patchPurposesPastTense()
        cls._conflictSides = cls._init_conflictSides()

    @classmethod
    def exceptionName(cls, exc: BaseException):
        name = type(exc).__name__
        return cls._exceptionNames.get(name, name)

    @classmethod
    def refNameValidation(cls, code: int):
        try:
            return cls._nameValidationCodes[code]
        except KeyError:
            return _("Name validation error {0}", code)

    @classmethod
    def sidebarItem(cls, item: SidebarItem):
        try:
            return cls._sidebarItems[item]
        except KeyError:
            return "?"+str(item)

    @classmethod
    def prefKey(cls, key: str):
        return cls._prefKeys.get(key, key)

    @classmethod
    def prefKeyNoDefault(cls, key: str):
        return cls._prefKeys.get(key, "")

    @classmethod
    def diffStatusChar(cls, c: str):
        return cls._diffStatusChars.get(c, c)

    @classmethod
    def fileMode(cls, m: FileMode):
        try:
            return cls._fileModes[m]
        except KeyError:
            return f"{m:o}"

    @classmethod
    def shortFileModes(cls, m: FileMode):
        try:
            return cls._shortFileModes[m]
        except KeyError:
            return f"{m:o}"

    @classmethod
    def repositoryState(cls, s: RepositoryState):
        try:
            return cls._repositoryStates[s]
        except KeyError:
            return f"#{s}"

    @classmethod
    def patchPurpose(cls, purpose: PatchPurpose):
        return cls._patchPurposes.get(purpose, "???")

    @classmethod
    def patchPurposePastTense(cls, purpose: PatchPurpose):
        return cls._patchPurposesPastTense.get(purpose, "???")

    @classmethod
    def conflictSides(cls, key: ConflictSides):
        return cls._conflictSides.get(key, f"?{key}")

    @staticmethod
    def _init_exceptionNames():
        return {
            "ConnectionRefusedError": _("Connection refused"),
            "FileNotFoundError": _("File not found"),
            "PermissionError": _("Permission denied"),
            "GitError": _("Git error"),
            "NotImplementedError": _("Unsupported feature"),
        }

    @staticmethod
    def _init_nameValidationCodes():
        from gitfourchette.porcelain import NameValidationError as E
        return {
            E.ILLEGAL_NAME: _("Illegal name."),
            E.ILLEGAL_SUFFIX: _("Illegal suffix."),
            E.ILLEGAL_PREFIX: _("Illegal prefix."),
            E.CONTAINS_ILLEGAL_SEQ: _("Contains illegal character sequence."),
            E.CONTAINS_ILLEGAL_CHAR: _("Contains illegal character."),
            E.CANNOT_BE_EMPTY: _("Cannot be empty."),
            E.NOT_WINDOWS_FRIENDLY: _("This name is discouraged for compatibility with Windows."),
            E.NAME_TAKEN_BY_REF: _("This name is already taken."),
            E.NAME_TAKEN_BY_FOLDER: _("This name is already taken by a folder."),
        }

    @staticmethod
    def _init_sidebarItems():
        from gitfourchette.sidebar.sidebarmodel import SidebarItem as E
        from gitfourchette.toolbox import toLengthVariants
        return {
            E.UncommittedChanges: toLengthVariants(_p("SidebarModel", "Uncommitted Changes|Changes")),
            E.LocalBranchesHeader: toLengthVariants(_p("SidebarModel", "Local Branches|Branches")),
            E.StashesHeader: _p("SidebarModel", "Stashes"),
            E.RemotesHeader: _p("SidebarModel", "Remotes"),
            E.TagsHeader: _p("SidebarModel", "Tags"),
            E.SubmodulesHeader: _p("SidebarModel", "Submodules"),
            E.LocalBranch: _p("SidebarModel", "Local branch"),
            E.DetachedHead: _p("SidebarModel", "Detached HEAD"),
            E.UnbornHead: _p("SidebarModel", "Unborn HEAD"),
            E.RemoteBranch: _p("SidebarModel", "Remote branch"),
            E.Stash: _p("SidebarModel", "Stash"),
            E.Remote: _p("SidebarModel", "Remote"),
            E.Tag: _p("SidebarModel", "Tag"),
            E.Submodule: _p("SidebarModel", "Submodules"),
            E.Spacer: "---",
        }

    @staticmethod
    def _init_diffStatusChars():
        # see git_diff_status_char (diff_print.c)
        return {
            "A": _p("FileStatus", "added"),
            "Z": _p("FileStatus", "added"),
            "C": _p("FileStatus", "copied"),
            "D": _p("FileStatus", "deleted"),
            "I": _p("FileStatus", "ignored"),
            "M": _p("FileStatus", "modified"),
            "R": _p("FileStatus", "renamed"),
            "T": _p("FileStatus", "file type changed"),
            "U": _p("FileStatus", "merge conflict"),  # "updated but unmerged"
            "X": _p("FileStatus", "unreadable"),
            "?": _p("FileStatus", "untracked"),
        }

    @staticmethod
    def _init_fileModes():
        return {
            0                       : _p("FileMode", "deleted"),
            FileMode.BLOB           : _p("FileMode", "regular file"),
            FileMode.BLOB_EXECUTABLE: _p("FileMode", "executable file"),
            FileMode.LINK           : _p("FileMode", "symbolic link"),
            FileMode.TREE           : _p("FileMode", "subtree"),
            FileMode.COMMIT         : _p("FileMode", "subtree commit"),
        }

    @staticmethod
    def _init_shortFileModes():
        # Intentionally untranslated.
        return {
            0: "",
            FileMode.BLOB: "",
            FileMode.BLOB_EXECUTABLE: "+x",
            FileMode.LINK: "link",
            FileMode.TREE: "tree",
            FileMode.COMMIT: "tree",
        }

    @staticmethod
    def _init_repositoryStates():
        return {
            RepositoryState.NONE                : _p("RepositoryState", "None"),
            RepositoryState.MERGE               : _p("RepositoryState", "Merging"),
            RepositoryState.REVERT              : _p("RepositoryState", "Reverting"),
            RepositoryState.REVERT_SEQUENCE     : _p("RepositoryState", "Reverting (sequence)"),
            RepositoryState.CHERRYPICK          : _p("RepositoryState", "Cherry-picking"),
            RepositoryState.CHERRYPICK_SEQUENCE : _p("RepositoryState", "Cherry-picking (sequence)"),
            RepositoryState.BISECT              : _p("RepositoryState", "Bisecting"),
            RepositoryState.REBASE              : _p("RepositoryState", "Rebasing"),
            RepositoryState.REBASE_INTERACTIVE  : _p("RepositoryState", "Rebasing (interactive)"),
            RepositoryState.REBASE_MERGE        : _p("RepositoryState", "Rebasing (merging)"),
            RepositoryState.APPLY_MAILBOX       : "Apply Mailbox",  # intentionally untranslated
            RepositoryState.APPLY_MAILBOX_OR_REBASE: "Apply Mailbox or Rebase",  # intentionally untranslated
        }

    @staticmethod
    def _init_patchPurposes():
        from gitfourchette.toolbox.gitutils import PatchPurpose as pp
        return {
            pp.STAGE                : _p("PatchPurpose", "Stage"),
            pp.UNSTAGE              : _p("PatchPurpose", "Unstage"),
            pp.DISCARD              : _p("PatchPurpose", "Discard"),
            pp.LINES | pp.STAGE     : _p("PatchPurpose", "Stage lines"),
            pp.LINES | pp.UNSTAGE   : _p("PatchPurpose", "Unstage lines"),
            pp.LINES | pp.DISCARD   : _p("PatchPurpose", "Discard lines"),
            pp.HUNK | pp.STAGE      : _p("PatchPurpose", "Stage hunk"),
            pp.HUNK | pp.UNSTAGE    : _p("PatchPurpose", "Unstage hunk"),
            pp.HUNK | pp.DISCARD    : _p("PatchPurpose", "Discard hunk"),
            pp.FILE | pp.STAGE      : _p("PatchPurpose", "Stage file"),
            pp.FILE | pp.UNSTAGE    : _p("PatchPurpose", "Unstage file"),
            pp.FILE | pp.DISCARD    : _p("PatchPurpose", "Discard file"),
        }

    @staticmethod
    def _init_patchPurposesPastTense():
        from gitfourchette.toolbox.gitutils import PatchPurpose as pp
        return {
            pp.STAGE                : _p("PatchPurpose", "Staged."),
            pp.UNSTAGE              : _p("PatchPurpose", "Unstaged."),
            pp.DISCARD              : _p("PatchPurpose", "Discarded."),
            pp.LINES | pp.STAGE     : _p("PatchPurpose", "Lines staged."),
            pp.LINES | pp.UNSTAGE   : _p("PatchPurpose", "Lines unstaged."),
            pp.LINES | pp.DISCARD   : _p("PatchPurpose", "Lines discarded."),
            pp.HUNK | pp.STAGE      : _p("PatchPurpose", "Hunk staged."),
            pp.HUNK | pp.UNSTAGE    : _p("PatchPurpose", "Hunk unstaged."),
            pp.HUNK | pp.DISCARD    : _p("PatchPurpose", "Hunk discarded."),
            pp.FILE | pp.STAGE      : _p("PatchPurpose", "File staged."),
            pp.FILE | pp.UNSTAGE    : _p("PatchPurpose", "File unstaged."),
            pp.FILE | pp.DISCARD    : _p("PatchPurpose", "File discarded."),
        }

    @staticmethod
    def _init_prefKeys():
        from gitfourchette.toolbox.textutils import paragraphs
        return {
            "general": _p("Prefs", "General"),
            "diff": _p("Prefs", "Code"),
            "imageDiff": _p("Prefs", "Images"),
            "tabs": _p("Prefs", "Tabs"),
            "graph": _p("Prefs", "Commit History"),
            "trash": _p("Prefs", "Trash"),
            "external": _p("Prefs", "External Tools"),
            "advanced": _p("Prefs", "Advanced"),

            "language": _("Language"),
            "qtStyle": _("Theme"),
            "shortHashChars": _("Shorten hashes to # characters"),
            "shortTimeFormat": _("Date/time format"),
            "pathDisplayStyle": _("Path display style"),
            "authorDisplayStyle": _("Author display style"),
            "maxRecentRepos": _("Remember up to # recent repositories"),
            "showStatusBar": _("Show status bar"),
            "showToolBar": _("Show toolbar"),
            "showMenuBar": _("Show menu bar"),
            "showMenuBar_help": _("When the menu bar is hidden, press the Alt key to show it again."),
            "resetDontShowAgain": _("Restore all “don’t show this again” messages"),
            "middleClickToStage": _("Middle-click a file name to stage/unstage the file"),

            "font": _("Font"),
            "tabSpaces": _("One tab is # spaces"),
            "contextLines": _("Show up to # context lines"),
            "contextLines_help": _("Amount of unmodified lines to show around red or green lines in a diff."),
            "largeFileThresholdKB": _("Load diffs up to # KB"),
            "imageFileThresholdKB": _("Load images up to # KB"),
            "syntaxHighlighting": _("Syntax highlighting"),
            "wordWrap": _("Word wrap"),
            "showStrayCRs": _("Display alien line endings (CRLF)"),
            "colorblind": _("Colorblind-friendly “add/remove” colors"),
            "colorblind_help": _("Display added/removed lines in blue/yellow instead of green/red."),
            "renderSvg": _("Treat SVG files as"),

            "tabCloseButton": _("Show tab close button"),
            "expandingTabs": _("Expand tabs to available width"),
            "autoHideTabs": _("Auto-hide tabs if only one repo is open"),
            "doubleClickTabOpensFolder": _("Double-click a tab to open repo folder"),

            "chronologicalOrder": _("Sort commits"),
            "chronologicalOrder_true": _("Chronologically"),
            "chronologicalOrder_false": _("Topologically"),
            "chronologicalOrder_help": paragraphs(
                _("<b>Chronological mode</b> lets you stay on top of the latest activity in the repository. "
                  "The most recent commits always show up at the top of the graph. "
                  "However, the graph can get messy when multiple branches receive commits in the same timeframe."),
                _("<b>Topological mode</b> makes the graph easier to read. It attempts to present sequences of "
                  "commits within a branch in a linear fashion. Since this is not a strictly chronological "
                  "mode, you may have to do more scrolling to see the latest changes in various branches."),
            ),
            "graphRowHeight": _("Row spacing"),
            "flattenLanes": _("Squeeze branch lanes in graph"),
            "authorDiffAsterisk": _("Mark author/committer signature differences"),
            "authorDiffAsterisk_help": paragraphs(
                _("The commit history displays information about a commit’s <b>author</b>—"
                  "their name and the date at which they made the commit. But in some cases, a commit "
                  "might have been revised by someone else than the original author—"
                  "this person is called the <b>committer</b>."),
                _("If you tick this option, an asterisk (*) will appear after the author’s name "
                  "and/or date if they differ from the committer’s for any given commit."),
                _("Note that you can always hover over the author’s name or date to obtain "
                  "detailed information about the author and the committer."),
            ),
            "maxCommits": _("Load up to # commits in the history"),
            "maxCommits_help": _("Set to 0 to always load the full commit history."),
            "alternatingRowColors": _("Draw rows using alternating background colors"),

            "maxTrashFiles": _("The trash keeps up to # discarded patches"),
            "maxTrashFileKB": _("Patches bigger than # KB won’t be salvaged"),
            "trash_HEADER": _(
                "When you discard changes from the working directory, {app} keeps a temporary copy in a hidden "
                "“trash” folder. This gives you a last resort to rescue changes that you have discarded by mistake. "
                "You can look around this trash folder via <i>“Help &rarr; Open Trash”</i>."),

            "verbosity": _("Logging verbosity"),
            "autoRefresh": _("Auto-refresh when app regains focus"),
            "animations": _("Animation effects"),
            "smoothScroll": _("Smooth scrolling (where applicable)"),
            "forceQtApi": _("Preferred Qt binding"),
            "forceQtApi_help": paragraphs(
                _("After restarting, {app} will use this Qt binding if available."),
                _("You can also pass the name of a Qt binding via the “QT_API” environment variable."),
            ),

            "externalEditor": _("Text editor"),
            "externalDiff": _("Diff tool"),
            "externalDiff_help": "<p style='white-space: pre'>" + _(
                "Argument placeholders:"
                "\n<code>$L</code> - Old/Left"
                "\n<code>$R</code> - New/Right"
            ),
            "externalMerge": _("Merge tool"),
            "externalMerge_help": "<p style='white-space: pre'>" + _(
                "Argument placeholders:"
                "\n<code>$B</code> - Ancestor / Base / Center"
                "\n<code>$L</code> - Ours / Local / Left"
                "\n<code>$R</code> - Theirs / Remote / Right"
                "\n<code>$M</code> - Merged / Output / Result"
            ),

            "FULL_PATHS": _("Full paths"),
            "ABBREVIATE_DIRECTORIES": _("Abbreviate directories"),
            "SHOW_FILENAME_ONLY": _("Show filename only"),

            "FULL_NAME": _("Full name"),
            "FIRST_NAME": _("First name"),
            "LAST_NAME": _("Last name"),
            "INITIALS": _("Initials"),
            "FULL_EMAIL": _("Full email"),
            "ABBREVIATED_EMAIL": _("Abbreviated email"),

            "CRAMPED": _p("row spacing", "Cramped"),
            "TIGHT": _p("row spacing", "Tight"),
            "RELAXED": _p("row spacing", "Relaxed"),
            "ROOMY": _p("row spacing", "Roomy"),
            "SPACIOUS": _p("row spacing", "Spacious"),

            "QTAPI_AUTOMATIC": _p("Qt binding", "Automatic (recommended)"),
            "QTAPI_PYSIDE6": "PySide6",
            "QTAPI_PYQT6": "PyQt6",
            "QTAPI_PYQT5": "PyQt5",
        }

    @staticmethod
    def _init_conflictSides():
        return {
            ConflictSides.MODIFIED_BY_BOTH: _p("ConflictSides", "modified by both sides"),
            ConflictSides.DELETED_BY_US: _p("ConflictSides", "deleted by us"),
            ConflictSides.DELETED_BY_THEM: _p("ConflictSides", "deleted by them"),
            ConflictSides.DELETED_BY_BOTH: _p("ConflictSides", "deleted by both sides"),
            ConflictSides.ADDED_BY_US: _p("ConflictSides", "added by us"),
            ConflictSides.ADDED_BY_THEM: _p("ConflictSides", "added by them"),
            ConflictSides.ADDED_BY_BOTH: _p("ConflictSides", "added by both sides"),
        }
