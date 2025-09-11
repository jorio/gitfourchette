#!/usr/bin/env bash

# Run unit tests from source within GitFourchette's Flatpak environment.
# Requires installing org.gitfourchette.gitfourchette (any version will do).

set -eu

here="$(dirname "$(realpath "$0")")"

# Passing paths between the host and the sandbox is error-prone
# if the test suite creates repositories in the flatpak's tmpfs.
# So, make a shared directory.
export GITFOURCHETTE_TEMPDIR="${GITFOURCHETTE_TEMPDIR:-$HOME/.cache/gitfourchette_test_as_flatpak.DELETE_ME}"
mkdir -p "$GITFOURCHETTE_TEMPDIR"

flatpak run --command="$here/test_in_flatpak.sh" org.gitfourchette.gitfourchette "$@"
