#!/usr/bin/env python3

import os
import sys
from pathlib import Path

tag = f"[{Path(__file__).name}]"
prompt = " ".join(sys.argv[1:])

dump = Path(os.environ["GFTEST_ASKPASS_SHIM_DUMPFILE"])
lines = dump.read_text().splitlines()
lines.append(prompt)
dump.write_text('\n'.join(lines))

print(f"{tag} {prompt}", file=sys.stderr)

if os.environ.get("GFTEST_ASKPASS_SHIM_CANCEL", ""):
    print(f"{tag} passphrase input canceled from unit test", file=sys.stderr)
    sys.exit(1)

print(os.environ["GFTEST_ASKPASS_SHIM_PASSWORD"])
