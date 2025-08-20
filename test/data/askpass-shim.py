#!/usr/bin/env python3

import os
import sys
from pathlib import Path

prompt = " ".join(sys.argv[1:])

print(f"[{Path(__file__).name}] {prompt}", file=sys.stderr)
print(os.environ["GFTEST_ASKPASS_SHIM_PASSWORD"])

dump = Path(os.environ["GFTEST_ASKPASS_SHIM_DUMPFILE"])
lines = dump.read_text().splitlines()
lines.append(prompt)
dump.write_text('\n'.join(lines))
