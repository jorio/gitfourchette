from gitfourchette.qt import translate


class TrTables:
    _exceptionNames = {}
    _nameValidationCodes = {}
    _sidebarItems = {}
    _prefKeys = {}
    _diffStatusChars = {}
    _fileModes = {}

    @classmethod
    def retranslateAll(cls):
        cls._exceptionNames = cls._init_exceptionNames()
        cls._nameValidationCodes = cls._init_nameValidationCodes()
        cls._sidebarItems = cls._init_sidebarItems()
        cls._prefKeys = cls._init_prefKeys()
        cls._diffStatusChars = cls._init_diffStatusChars()
        cls._fileModes = cls._init_fileModes()

    @classmethod
    def exceptionName(cls, exc: BaseException):
        name = type(exc).__name__
        return cls._exceptionNames.get(name, name)

    @classmethod
    def refNameValidation(cls, code: int):
        try:
            return cls._nameValidationCodes[code]
        except KeyError:
            return translate("NameValidationError", "Name validation error {0}").format(code)

    @classmethod
    def sidebarItem(cls, item: int):
        try:
            return cls._sidebarItems[item]
        except KeyError:
            return "?"+str(item)

    @classmethod
    def prefKey(cls, key: str):
        return cls._prefKeys.get(key, key)

    @classmethod
    def diffStatusChar(cls, c: str):
        return cls._diffStatusChars.get(c, c)

    @classmethod
    def fileMode(cls, m: int):
        try:
            return cls._fileModes[m]
        except KeyError:
            return f"{m:o}"

    @staticmethod
    def _init_exceptionNames():
        return {
            "ConnectionRefusedError": translate("Exception", "Connection refused"),
            "FileNotFoundError": translate("Exception", "File not found"),
        }

    @staticmethod
    def _init_nameValidationCodes():
        from gitfourchette.porcelain import NameValidationError as E
        return {
            E.ILLEGAL_NAME: translate("NameValidationError", "Illegal name."),
            E.ILLEGAL_SUFFIX: translate("NameValidationError", "Illegal suffix."),
            E.ILLEGAL_PREFIX: translate("NameValidationError", "Illegal prefix."),
            E.CONTAINS_ILLEGAL_SEQ: translate("NameValidationError", "Contains illegal character sequence."),
            E.CONTAINS_ILLEGAL_CHAR: translate("NameValidationError", "Contains illegal character."),
            E.CANNOT_BE_EMPTY: translate("NameValidationError", "Cannot be empty."),
            E.NOT_WINDOWS_FRIENDLY: translate("NameValidationError", "This name is discouraged for compatibility with Windows."),
            E.NAME_TAKEN: translate("NameValidationError", "This name is already taken."),
        }

    @staticmethod
    def _init_sidebarItems():
        from gitfourchette.sidebar.sidebarmodel import EItem as E
        return {
            E.UncommittedChanges: translate("SidebarModel", "Changes"),
            E.LocalBranchesHeader: translate("SidebarModel", "Branches"),
            E.StashesHeader: translate("SidebarModel", "Stashes"),
            E.RemotesHeader: translate("SidebarModel", "Remotes"),
            E.TagsHeader: translate("SidebarModel", "Tags"),
            E.SubmodulesHeader: translate("SidebarModel", "Submodules"),
            E.LocalBranch: translate("SidebarModel", "Local branch"),
            E.DetachedHead: translate("SidebarModel", "Detached HEAD"),
            E.UnbornHead: translate("SidebarModel", "Unborn HEAD"),
            E.RemoteBranch: translate("SidebarModel", "Remote branch"),
            E.Stash: translate("SidebarModel", "Stash"),
            E.Remote: translate("SidebarModel", "Remote"),
            E.Tag: translate("SidebarModel", "Tag"),
            E.Submodule: translate("SidebarModel", "Submodules"),
            E.Spacer: "---",
        }

    @staticmethod
    def _init_diffStatusChars():
        # see git_diff_status_char (diff_print.c)
        return {
            "A": translate("git", "added"),
            "C": translate("git", "copied"),
            "D": translate("git", "deleted"),
            "I": translate("git", "ignored"),
            "M": translate("git", "modified"),
            "R": translate("git", "renamed"),
            "T": translate("git", "file type changed"),
            "U": translate("git", "merge conflict"),  # "updated but unmerged"
            "X": translate("git", "unreadable"),
            "?": translate("git", "untracked"),
        }

    @staticmethod
    def _init_fileModes():
        import pygit2
        return {
            0: translate("git", "deleted", "unreadable/deleted file mode 0o000000"),
            pygit2.GIT_FILEMODE_BLOB: translate("git", "normal", "default file mode 0o100644"),
            pygit2.GIT_FILEMODE_BLOB_EXECUTABLE: translate("git", "executable", "executable file mode 0o100755"),
            pygit2.GIT_FILEMODE_LINK: translate("git", "link", "as in 'symlink' - file mode 0o120000"),
            pygit2.GIT_FILEMODE_TREE: translate("git", "tree", "as in 'directory tree' - file mode 0o40000"),
            pygit2.GIT_FILEMODE_COMMIT: translate("git", "commit", "'commit' file mode 0o160000"),
        }

    @staticmethod
    def _init_prefKeys():
        return {
            "general": translate("Prefs", "General"),
            "diff": translate("Prefs", "Diff"),
            "tabs": translate("Prefs", "Tabs"),
            "graph": translate("Prefs", "Commit History"),
            "trash": translate("Prefs", "Trash"),
            "external": translate("Prefs", "External Tools"),
            "debug": translate("Prefs", "Experimental"),

            "language": translate("Prefs", "Language"),
            "qtStyle": translate("Prefs", "Theme"),
            "shortHashChars": translate("Prefs", "Shorten hashes to # characters"),
            "shortTimeFormat": translate("Prefs", "Date/time format"),
            "pathDisplayStyle": translate("Prefs", "Path display style"),
            "authorDisplayStyle": translate("Prefs", "Author display style"),
            "maxRecentRepos": translate("Prefs", "Remember up to # recent repositories"),
            "showStatusBar": translate("Prefs", "Show status bar"),
            "autoHideMenuBar": translate("Prefs", "Toggle menu bar visibility with Alt key"),

            "diff_font": translate("Prefs", "Font"),
            "diff_tabSpaces": translate("Prefs", "One tab is # spaces"),
            "diff_largeFileThresholdKB": translate("Prefs", "Load diffs up to # KB"),
            "diff_imageFileThresholdKB": translate("Prefs", "Load images up to # KB"),
            "diff_wordWrap": translate("Prefs", "Word wrap"),
            "diff_showStrayCRs": translate("Prefs", "Highlight stray “CR” characters"),
            "diff_colorblindFriendlyColors": translate("Prefs", "Colorblind-friendly color scheme"),

            "tabs_closeButton": translate("Prefs", "Show tab close button"),
            "tabs_expanding": translate("Prefs", "Tab bar takes all available width"),
            "tabs_autoHide": translate("Prefs", "Auto-hide tab bar if there’s just 1 tab"),
            "tabs_doubleClickOpensFolder": translate("Prefs", "Double-click a tab to open repo folder"),

            "graph_chronologicalOrder": translate("Prefs", "Commit order"),
            "graph_flattenLanes": translate("Prefs", "Flatten lanes"),
            "graph_rowHeight": translate("Prefs", "Row spacing"),

            "trash_maxFiles": translate("Prefs", "The trash keeps up to # discarded patches"),
            "trash_maxFileSizeKB": translate("Prefs", "Patches bigger than # KB won’t be salvaged"),
            "trash_HEADER": translate(
                "Prefs",
                "When you discard changes from the working directory, {app} keeps a temporary copy in a hidden "
                "“trash” folder. This gives you a last resort to rescue changes that you have discarded by mistake. "
                "You can look around this trash folder via <i>“Repo &rarr; Rescue Discarded Changes”</i>."),

            "debug_showMemoryIndicator": translate("Prefs", "Show memory indicator in status bar"),
            "debug_showPID": translate("Prefs", "Show technical info in title bar"),
            "debug_verbosity": translate("Prefs", "Logging verbosity"),
            "debug_hideStashJunkParents": translate("Prefs", "Hide synthetic parents of stash commits"),
            "debug_fixU2029InClipboard": translate("Prefs", "Fix U+2029 in text copied from diff editor"),
            "debug_autoRefresh": translate("Prefs", "Auto-refresh when app regains focus"),

            "external_editor": translate("Prefs", "Text editor"),
            "external_diff": translate("Prefs", "Diff tool"),
            "external_merge": translate("Prefs", "Merge tool"),

            "FULL_PATHS": translate("PathDisplayStyle", "Full paths"),
            "ABBREVIATE_DIRECTORIES": translate("PathDisplayStyle", "Abbreviate directories"),
            "SHOW_FILENAME_ONLY": translate("PathDisplayStyle", "Show filename only"),

            "FULL_NAME": translate("Prefs", "Full name"),
            "FIRST_NAME": translate("Prefs", "First name"),
            "LAST_NAME": translate("Prefs", "Last name"),
            "INITIALS": translate("Prefs", "Initials"),
            "FULL_EMAIL": translate("Prefs", "Full email"),
            "ABBREVIATED_EMAIL": translate("Prefs", "Abbreviated email"),

            "CRAMPED": translate("Prefs", "Cramped"),
            "TIGHT": translate("Prefs", "Tight"),
            "RELAXED": translate("Prefs", "Relaxed"),
            "ROOMY": translate("Prefs", "Roomy"),
            "SPACIOUS": translate("Prefs", "Spacious"),
        }
