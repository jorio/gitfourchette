#!/usr/bin/env python3

"""
Stand in for ssh: append the arguments to the file named by $SSH_SHIM_LOG,
then fail like ssh does when it can't connect.
"""

import os
import sys

with open(os.environ["SSH_SHIM_LOG"], "a", encoding="utf-8") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")

sys.exit(255)
