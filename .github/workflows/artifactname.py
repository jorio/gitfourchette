#! /usr/bin/env python3
import platform
from gitfourchette.appconsts import *
system = platform.system()
if system == "Darwin":
    system = "macOS"
print(f"ARTIFACT_NAME={APP_DISPLAY_NAME}-{APP_VERSION}-{system}")
