#!/usr/bin/env zsh

# Wrapper for merge/diff tools on macOS

set -e
set +x

app="$1"
shift

if [[ "$app" == *.app ]]; then
  open -WFn "$app" --args "$@"
elif [[ "$app" == "opendiff" ]]; then
  # Prevent opendiff (launcher shim for FileMerge) from exiting immediately.
  "$app" "$@" | cat
else
  "$app" "$@"
fi
