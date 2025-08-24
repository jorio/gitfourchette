#!/usr/bin/env bash
set -e
exec /usr/bin/ssh \
  -F none \
  -o IdentityFile=none \
  -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  "$@"
