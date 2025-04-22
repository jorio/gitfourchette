#!/usr/bin/env sh

# Prevent opendiff (launcher shim for FileMerge) from exiting immediately.
/usr/bin/opendiff "$@" | cat
