#!/usr/bin/env python3

import sys

scratch = sys.argv[1]
M, L, R, B = sys.argv[2:6]

with open(scratch, "w") as file:
    file.write("\n".join(sys.argv[2:]))

with open(M, "w") as file:
    file.write("merge complete!")
