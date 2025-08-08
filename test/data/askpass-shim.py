#!/usr/bin/env python3

import os
import sys

print("askpass args:", sys.argv[1:], file=sys.stderr)
print(os.environ["GFTEST_ASKPASS_SHIM_PASSWORD"])
