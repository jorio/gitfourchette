#!/usr/bin/env bash

# Run GitFourchette from source within its Flatpak environment.
# Requires installing org.gitfourchette.gitfourchette (any version will do).

set -eu

here="$(dirname "$(realpath "$0")")"
source_root="$here/../.."

flatpak run \
  --env=PYTHONPYCACHEPREFIX=/tmp/__DONT_POLLUTE_HOST_PYCACHE__ \
  --cwd="$source_root" \
  --command=python org.gitfourchette.gitfourchette \
  -m gitfourchette "$@"
