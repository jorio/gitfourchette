#!/usr/bin/env python3

import signal
import sys
import time
import subprocess

# Disallow SIGINT and SIGTERM while sleeping
signal.signal(signal.SIGINT, signal.SIG_IGN)
signal.signal(signal.SIGTERM, signal.SIG_IGN)

secs = 5.0
n = int(100 * secs)
interval = secs / n
for i in range(n + 1):
    print(f"Delaying {sys.argv[1]} for {secs - i * secs / n:.1f} seconds... {100*i//n}% ({i}/{n})", end="\r", file=sys.stderr)
    time.sleep(secs / n)
print("", end="\r\n", file=sys.stderr)

# Restore SIGINT and SIGTERM after sleeping
signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGTERM, signal.SIG_DFL)

completed = subprocess.run(sys.argv[1:])
sys.exit(completed.returncode)
