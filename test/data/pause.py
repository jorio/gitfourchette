#!/usr/bin/env python3

import os
import sys
import time

print(f"PID {os.getpid()} - parent {os.getppid()}")

with open(sys.argv[1], "w") as file:
    file.write("about to sleep\n")
    file.flush()
    time.sleep(2)
    file.write("finished sleeping\n")
