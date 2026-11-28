#!/usr/bin/env python3

"""
Pretend to be the OpenSSH client that ships with Windows.
"""

import sys

if "-V" in sys.argv[1:]:
    print("OpenSSH_for_Windows_9.5p2, LibreSSL 3.8.2", file=sys.stderr)
