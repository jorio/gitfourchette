#!/usr/bin/env bash

set -e

if [ -z ${FLATPAK_ID} ]; then
    echo "!!! This script must run inside GitFourchette's Flatpak."
    echo "!!! flatpak run --command=$0 org.gitfourchette.gitfourchette"
    exit 1
fi

here="$(dirname "$(realpath "$0")")"
cd "$here/../.."

export PYTHONPYCACHEPREFIX=/tmp/__DONT_POLLUTE_HOST_PYCACHE__

VENVDIR="$XDG_CACHE_HOME/__TEST_IN_FLATPAK_VENV__"

if [ -d "$VENVDIR" ]; then
    echo "INFO: Test virtual environment already exists. Dependencies will not be reinstalled."
    echo "INFO: To start with a clean environment, delete this directory:"
    echo "INFO:     $VENVDIR"
    echo ""
    source "$VENVDIR/bin/activate"
else
    python -m venv "$VENVDIR"
    source "$VENVDIR/bin/activate"
    python -m ensurepip
    python -m pip --disable-pip-version-check install --upgrade --force-reinstall '.[test,pygments]'
fi

./test.py "$@"
