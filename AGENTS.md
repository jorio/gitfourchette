# AGENTS.md

GitFourchette is a Qt desktop Git client for Linux, written in Python 3.12+. It runs on PyQt6 (preferred), PySide6, or PyQt5 (deprecated) through a compatibility layer. It reads repositories with pygit2 and runs the `git` CLI for most operations that change a repository.

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[pyqt6,test,lint]   # Install app + test + lint dependencies
./run.py                            # Run the app from source
```

## Single-File Verification

Lint a single file:

```bash
ruff check path/to/file.py
```

Type-check a single file:

```bash
mypy path/to/file.py
```

Run a single test file or test function:

```bash
./test.py test/test_tasks_stash.py
./test.py -k testNewStash
```

## Essential Commands

```bash
./test.py                   # Run the full test suite (offscreen, parallel via pytest-xdist)
./test.py -1 -v -x          # Serial, verbose, stop on first failure
./test.py -g -1             # Live logging (best combined with -1)
./test.py --cov             # Coverage report (coverage_html_report/)
./test.py --qt=pyside6      # Use another Qt binding (pyqt6, pyside6, pyqt5)
./test.py --with-network    # Include tests that need network access
./test.py --with-fuse       # Include tests that need FUSE
ruff check                  # Lint (whole project)
mypy                        # Type check (whole project)
./update_resources.py --ui  # Regenerate forms/ui_*.py after editing .ui files
./update_resources.py --pot # Regenerate the localization template
```

Extra arguments to `./test.py` are passed to pytest. Tests run offscreen by default (`QT_QPA_PLATFORM=offscreen`). CI only requires the suite to pass reliably in offscreen mode.

CI runs mypy with `pyqt6<6.12`, because newer PyQt6 type stubs produce false mypy errors.

## Architecture

**Preconditions & invariants:**

- Always import Qt through `from gitfourchette.qt import *`. Never import `PyQt6`, `PySide6` or `PyQt5` directly; only `qt.py` does that.
- Wrap user-facing strings in the gettext helpers from `gitfourchette.localization` (`_()`, `_n()`, `_p()`, `_np()`).
- Run actions that change a repository as `RepoTask` subclasses (`gitfourchette/tasks/`). Each task's `flow()` generator uses `yield from self.flowCallGit(...)`, `flowDialog(...)`, `flowConfirm(...)`, `flowEnterWorkerThread()` / `flowEnterUiThread()`, and so on. Register new tasks in `tasks/taskbook.py`.
- Never edit `gitfourchette/forms/ui_*.py` by hand. Those files are generated from the `.ui` files.
- Never edit `gitfourchette/assets/lang/*.po` by hand. Translations are managed on Weblate.
- Use `gitfourchette.porcelain` as the main entry point to pygit2.

### Key Modules

```
gitfourchette/qt.py           - PyQt6/PySide6/PyQt5 compatibility layer
gitfourchette/application.py  - GFApplication (QApplication subclass, app bootstrap)
gitfourchette/mainwindow.py   - Main window, tabs, menus
gitfourchette/repowidget.py   - Per-repository tab widget
gitfourchette/repomodel.py    - Per-repository state
gitfourchette/porcelain.py    - Extension layer on top of pygit2 (snake_case)
gitfourchette/gitdriver/      - Wrapper around the git CLI and parsers for its output
gitfourchette/tasks/          - RepoTask subclasses (all user actions) + RepoTaskRunner
gitfourchette/forms/          - Dialogs; *.ui (Qt Designer) + generated ui_*.py
gitfourchette/graphview/      - Commit graph view; graph/ holds the graph model
gitfourchette/diffview/       - Diff view; codeview/ and syntax/ for text rendering
gitfourchette/sidebar/        - Branches/remotes/tags/stashes/submodules sidebar
gitfourchette/toolbox/        - Reusable Qt widgets and utilities
gitfourchette/settings.py     - User preferences (prefsfile.py, repoprefs.py)
gitfourchette/assets/         - Icons, stylesheets, translations
test/                         - pytest + pytest-qt suite; helpers in test/util.py
test/data/                    - Test repositories (unpacked with unpackRepo)
update_resources.py           - Generates UI forms, translations, packaging files
```

### Technology Stack

| Layer    | Technologies                                    |
| -------- | ----------------------------------------------- |
| Language | Python 3.12+                                    |
| UI       | Qt 6 via PyQt6 (preferred) or PySide6 6.9+      |
| Git      | pygit2 1.14.1+, git CLI                         |
| Testing  | pytest, pytest-qt, pytest-xdist, pytest-cov     |
| Linting  | ruff, mypy                                      |
| Build    | setuptools (pyproject.toml); Flatpak, AppImage  |

## Guidelines

1. Read [CONTRIBUTING.md](CONTRIBUTING.md) before making changes.
2. Run `ruff check` and `mypy` before each commit.
3. Use camelCase for functions, methods, and variables, following PyQt/PySide naming. The one exception is `porcelain.py`, which uses snake_case because it extends pygit2.
4. Write tests for your changes unless the change is purely cosmetic. Tests use the `tempDir` and `mainWindow` fixtures, plus helpers from `test/util.py` (`unpackRepo`, `shell`, `triggerMenuAction`, `acceptQMessageBox`, `waitForQDialog`, …). To pause the UI and inspect it while writing a test, use `pause()` / `pauseDialog()` together with `--visual`.
5. Target PyQt6 first. Try to keep PySide6 working. PyQt5 is deprecated, so it's acceptable to turn a feature off under Qt 5.
6. After editing a `.ui` file, run `./update_resources.py --ui`.
7. Start new source files with the GPL v3 copyright header used by existing files.
8. Commit messages follow the pattern `Area: Short description` (e.g. `Sidebar: Hide "Submodules" section in repos that don't use them`).
9. Mention AI assistance in commits.

## Pull requests

- Never make a PR unless the developer explicitly asks you to do so.
- Keep PRs small and incremental so they're easy to review. Avoid large PRs with sweeping changes in a single commit.
- One concern per PR. If the description says "also", split it.
- Use the template in `.github/PULL_REQUEST_TEMPLATE.md` and complete its checklist.
- UI changes need before/after screenshots.
- Disclose AI-assisted work: add a `Co-authored-by:` trailer or a short note in the PR description. Say so if the change was made only by AI without human review.
- Stand behind the change: the PR must be reviewable, explainable, and able to respond to review feedback.
- See [LLM_POLICY.md](LLM_POLICY.md) for the full AI (LLM) development policy.

## Pattern References

- **Contributing, code style & testing tips**: [CONTRIBUTING.md](CONTRIBUTING.md)
- **AI (LLM) development policy**: [LLM_POLICY.md](LLM_POLICY.md)
- **Task framework**: `gitfourchette/tasks/repotask.py`; existing tasks in `gitfourchette/tasks/`
- **Test helpers**: `test/util.py`, `test/conftest.py`, `test/reposcenario.py`
- **Localization**: <https://gitfourchette.org/localization>
- **User's guide**: <https://gitfourchette.org/guide>
- **Changelog**: [CHANGELOG.md](CHANGELOG.md)
