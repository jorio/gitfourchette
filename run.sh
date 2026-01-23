#!/usr/bin/env bash

set -e

PYTHON=${PYTHON:-python3}
export PYTHONPATH="$(dirname "$(readlink -f -- "$0")" )"

$PYTHON -m gitfourchette "$@"
