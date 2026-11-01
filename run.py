#!/usr/bin/env python3

import runpy
import sys
from pathlib import Path

here = Path(__file__).parent.resolve()
sys.path.insert(0, str(here))
runpy.run_module("gitfourchette", run_name="__main__")
