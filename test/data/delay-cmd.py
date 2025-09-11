#!/usr/bin/env python3

import argparse
import signal
import sys
import time
import subprocess

parser = argparse.ArgumentParser(description="Delay a command. Print git-like progress to stderr.")
parser.add_argument("-d", "--delay", type=float, default=5.0, metavar="SECONDS",
                    help="delay in seconds (float) before launching the command")
parser.add_argument("-b", "--block", action="store_true",
                    help="ignore SIGINT and SIGTERM while delaying")
parser.add_argument("command", nargs="+")
args = parser.parse_args()

# Disallow SIGINT and SIGTERM while sleeping
if args.block:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

secs = args.delay
n = int(100 * secs)
interval = secs / n

for i in range(n + 1):
    print(f"Delaying {args.command[0]} for {secs - i * secs / n:.1f} seconds... "
          f"{100*i//n}% ({i}/{n})",
          end="\r", file=sys.stderr)
    time.sleep(secs / n)

print("", end="\r\n", file=sys.stderr)

# Restore SIGINT and SIGTERM after sleeping
if args.block:
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)

completed = subprocess.run(args.command)
sys.exit(completed.returncode)
