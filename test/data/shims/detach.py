#!/usr/bin/env python3

import sys
import subprocess

p = subprocess.Popen(sys.argv[1:], start_new_session=True)
