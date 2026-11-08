#!/usr/bin/env python3

import sys

print("*** EDITOR SHIM STARTED!", file=sys.stderr)

scratch = sys.argv[1]

with open(scratch, "w") as file:
    file.write("\n".join(sys.argv[2:]))

print("*** EDITOR SHIM FINISHED, WROTE TO:", scratch, file=sys.stderr)
