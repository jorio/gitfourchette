#!/usr/bin/env python3

from pathlib import Path
import os
import stat
import sys

def atomicWrite(pathStr, text):
    path = Path(pathStr)
    temp = Path(pathStr + ".temp")
    if path.exists() and not (path.lstat().st_mode & stat.S_IWUSR):
        raise PermissionError("no write perms")
    assert not temp.exists()
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)

atomicWrite(sys.argv[1], "\n".join(sys.argv[2:]))
