#!/usr/bin/env python3

import sys

scratch = sys.argv[1]

with open(scratch, "w") as file:
    file.write("\n".join(sys.argv[2:]))
