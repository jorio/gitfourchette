#!/usr/bin/env bash

# Run GitFourchette test suite from source within its Flatpak environment.
# Requires installing org.gitfourchette.gitfourchette (any version will do).

set -e

if [ -z "$FLATPAK_ID" ]; then
    echo "INFO: We're not in a Flatpak. Restarting $0 as a Flatpak."
    exec flatpak run --command="$0" org.gitfourchette.gitfourchette "$@"
fi

echo "INFO: Running as Flatpak $FLATPAK_ID."

here="$(dirname "$(realpath "$0")")"
cd "$here/../.."

# Don't let Flatpak pick up host's PYTHONCACHEPREFIX
export PYTHONPYCACHEPREFIX=/tmp/__DONT_POLLUTE_HOST_PYCACHE__  # inside Flatpak tmpfs

# Passing paths between the host and the sandbox is error-prone
# if the test suite creates repositories in the flatpak's tmpfs.
# So, make a shared directory.
export GITFOURCHETTE_TEMPDIR="${GITFOURCHETTE_TEMPDIR:-$HOME/.cache/gitfourchette__TEST_AS_FLATPAK_TEMP__}"
mkdir -p "$GITFOURCHETTE_TEMPDIR"

VENVDIR="$GITFOURCHETTE_TEMPDIR/venv"

if [ -d "$VENVDIR" ]; then
    echo "INFO: Test virtual environment already exists. Dependencies will not be reinstalled."
    echo "INFO: To start with a clean environment, delete this directory:"
    echo "INFO:     $GITFOURCHETTE_TEMPDIR"
    echo ""
    source "$VENVDIR/bin/activate"
else
    echo "INFO: Will now set up the test environment."
    echo "INFO: When you're done, you may want to delete:"
    echo "INFO:     $GITFOURCHETTE_TEMPDIR"

    python -m venv "$VENVDIR" --system-site-packages
    source "$VENVDIR/bin/activate"

    # --ignore-installed: Override the Flatpak's possibly partial installs of the test dependencies
    # (e.g. we might have stripped things from pygments, which is a dependency of pytest)
    pip --cache-dir="$GITFOURCHETTE_TEMPDIR/pip-cache" --disable-pip-version-check install --ignore-installed pytest pytest-xdist pytest-qt
fi

pip list

./test.py "$@"

echo "INFO: You may now delete $GITFOURCHETTE_TEMPDIR"
echo "INFO: or you can let it be to reuse in future Flatpak test runs."
