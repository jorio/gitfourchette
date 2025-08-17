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

python -m ensurepip
python -m pip --disable-pip-version-check install --upgrade --force-reinstall '.[test,pygments]'
./test.py "$@"
