# Contributing

Welcome!

I maintain this project in my spare time and I want to have a good understanding of every change that goes into it.

As such, I ask you to **please keep your PRs small and incremental to make them easy to review.** Please avoid large PRs that introduce sweeping changes in a single commit.

Thank you for your understanding.

## Localization

If you want to contribute translations, please take a look at https://gitfourchette.org/localization

## Linting & code style

Please run `mypy`, `ruff check` and `python check_imports.py` before each commit.

Please use camelCase. Most of the codebase follows PyQt6/PySide6 naming conventions and so uses camelCase.

Only `porcelain.py` uses snake_case because it is an extension to pygit2.

## Testing

**Please write tests that cover your changes** (unless your change is cosmetic and can only be appreciated subjectively).

Run `./test.py` locally to run the test suite. (More info about this script in "Tips for testing" below.)

You can also run GitHub Actions job `tests.yml` to verify that the tests pass in a variety of environments.

When the test job has finished running, you can download a coverage report from the GitHub Actions run (a file named `coverage_...zip`). Please take a look at it to ensure that your new code paths are being reasonably covered by the test suite.

### Tips for testing

The `test.py` script is a handy wrapper around `pytest`. Useful arguments to `test.py`:
- `-k <pattern>`: Only run test functions matching this pattern.
- `-1`: Don't run the tests in parallel.
- `-v`: Show which tests are being run.
- `-x`: Stop after the first failing test.
- `-g`: Live logging.
- `--qt=<value>`: Enforce a specific Qt binding (`pyqt6`, `pyside6` or `pyqt5`).
- `--with-net`: Enable tests that hit the network.
- `--with-fuse`: Enable tests that need FUSE.
- `--cov`: Generate HTML coverage report.
- `--visual`: Run tests visually instead of offscreen. Note that Wayland imposes restrictions on mouse control, so move your mouse cursor to the center of your display before starting the tests.

Useful environment variables if you're not using `test.py` (typically, to run tests from your IDE):
- `QT_QPA_PLATFORM`: Can be `offscreen`, `wayland`, `xcb` (X11), among others.
- `QT_API`: Can be `pyqt6`, `pyside6` or `pyqt5`.

While you're drafting a test, you may want to **pause the UI so you can inspect its state**. To do this, you can use `pause()` and `pauseDialog()`.

Some tests might reliably pass in offscreen mode only, due to restrictions imposed by Wayland on cursor/window control. That's okay. I only require that the test suite reliably passes in offscreen mode.

Some tests might fail in PyQt5. Try to work around it if you can. Don't sweat it too much; it's okay to disable your feature in Qt 5. The first-class target remains PyQt6 and I plan to remove Qt 5 support eventually.

## Qt Designer forms (`.ui` files)

After editing a `.ui` file with Qt Designer, you must regenerate the corresponding `ui_*.py` file with `./update_resources.py --ui`. Do not edit the generated file as it will be overwritten next time I recompile it.
