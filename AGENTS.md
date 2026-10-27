# AGENTS.md

GitFourchette is a Qt-based Git GUI written in Python (≥ 3.12). It uses **pygit2** (libgit2) for most repository access and shells out to vanilla `git` (via `QProcess`/`GitDriver`) for operations such as fetch, push, commit hooks, LFS, and signing.

## Setup

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e .[pyqt6,test]          # optional extras: pyside6, mfusepy, memory-indicator
./run.sh                              # launch the app from source
```

Qt binding selection: `QT_API=pyqt6|pyside6|pyqt5` at runtime, `PYTEST_QT_API` (or `./test.py --qt=...`) for tests. PyQt6 is the default; PyQt5 is deprecated but still tested in CI — don't break it.

## Validate changes

```sh
ruff check                            # lint (config in pyproject.toml)
mypy                                  # type-check gitfourchette/ (not test/)
./test.py                             # full suite: offscreen, parallel via pytest-xdist
./test.py test/test_tasks_stash.py    # extra args are forwarded to pytest
./test.py -1 -g -k testNewStash       # single-process with live logging, for debugging
```

Other `test.py` flags: `--qt=pyside6`, `--cov`, `--visual` (show windows), `--with-network`, `--with-fuse`.
CI (`.github/workflows/tests.yml`) runs ruff + mypy and the test matrix on Python 3.12–3.14 with PyQt5/PyQt6/PySide6, including pygit2 1.14.1 — avoid APIs newer than the minimum supported versions, or guard them with `pygit2_version_at_least(...)`.

## Repository layout

- `gitfourchette/` — application package
  - `qt.py` — Qt binding compatibility layer. **Always** import Qt via `from gitfourchette.qt import *`, never directly from PyQt6/PySide6.
  - `porcelain.py` — wrapper around pygit2 (`Repo`, `Oid`, `FileStatus`, …). Import via `from gitfourchette.porcelain import *`.
  - `gitdriver/` — vanilla `git` process driver and output parsers.
  - `tasks/` — `RepoTask` subclasses: every user-facing repo operation. Tasks are generator-based flows (`flow()` using `yield from self.flowEnterWorkerThread()`, `flowDialog()`, `flowCallGit()`, etc.) declaring `TaskPrereqs`/`TaskEffects`. Export new tasks in `tasks/__init__.py` and give them names/toolbar labels/tooltips in `tasks/taskbook.py`.
  - `forms/` — dialogs. `*.ui` files are Qt Designer sources; `ui_*.py` are **generated** — never edit by hand (regenerate with `./update_resources.py --ui`).
  - `toolbox/` — generic Qt/utility helpers (`from gitfourchette.toolbox import *`).
  - `graph/`, `graphview/`, `diffview/`, `codeview/`, `blameview/`, `sidebar/`, `filelists/`, `syntax/`, `mount/` — feature areas.
  - `localization.py` — gettext helpers `_()`, `_n()`, `_p()`, `_np()`.
  - `appconsts.py` — app constants, including `APP_VERSION`.
  - `assets/` — icons, styles, translations (`lang/*.po`, `*.mo`, `gitfourchette.pot`).
- `test/` — pytest + pytest-qt suite. `util.py` holds helpers (`unpackRepo`, `shell`, `findQDialog`, `triggerMenuAction`, `qlvGetRowData`, …); `conftest.py` provides `tempDir`, `mainWindow`, `taskThread` fixtures; `data/` holds test repos and shims.
- `pkg/` — packaging (AppImage, Flatpak, PyInstaller).
- `update_resources.py` — regenerates UI code, translation catalogs, and other assets.

## Conventions

- **camelCase** for functions, methods, and variables (matches Qt); PascalCase for classes.
- Every source file starts with the standard GPLv3 copyright header block — copy it from an existing file.
- Star imports from the project's facade modules (`qt`, `porcelain`, `toolbox`, `localization`) are idiomatic here.
- Wrap all user-visible strings in `_()` / `_n()` / `_p()` for translation. Don't edit `.po`/`.mo` files manually; translations come from Weblate.
- Use `logger = logging.getLogger(__name__)` for logging.
- Don't block the UI thread: run slow repo work inside a `RepoTask` worker-thread section.
- Platform-specific code paths use the `MACOS`, `WINDOWS`, `FLATPAK` flags from `qt.py`.
- Tests drive the real UI: create a repo with `unpackRepo(tempDir)`, open it with `mainWindow.openRepo(wd)`, interact via menus/keys/dialogs, then assert on widgets and repo state. Add tests for behavior changes alongside the relevant `test/test_*.py`.
- User-facing changes get an entry in `CHANGELOG.md` under the upcoming version.
