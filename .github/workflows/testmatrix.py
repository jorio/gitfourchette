#!/usr/bin/env python3

import datetime
import dataclasses
import json
import os
import subprocess

FLATPAK_APPID = "org.gitfourchette.gitfourchette"
FLATPAK_DEFAULT_FLATPAKREF = f"https://dl.flathub.org/repo/appstream/{FLATPAK_APPID}.flatpakref"
FLATPAK_FLATHUB_REPO = f"https://github.com/flathub/{FLATPAK_APPID}"

@dataclasses.dataclass
class Config:
    name: str
    os: str
    py: str
    qt: str
    downgradeGit: bool = False
    fuse: bool = True
    coverage: bool = False
    prePip: str = ""

    def isLinux(self):
        return self.os.startswith("ubuntu")

    def compile(self):
        pip = []
        if self.prePip:
            pip.append(self.prePip)
        pipDeps = [self.qt, "test"]
        if self.fuse:
            pipDeps.append("mfusepy")
        pip.append(f"pip -q install -e .[{','.join(pipDeps)}]")
        pip.append("pip list --local")

        test = f"python3 test.py -v --color=yes --report-chars=fswE --qt={self.qt} --with-network"
        if self.fuse:
            test += " --with-fuse"
        if self.coverage:
            test += " --cov"
        if not self.isLinux():  # fail quickly on expensive runners
            test += " -x"

        apt = []
        if self.isLinux():
            aptPackages = ["libqt5gui5" if self.qt == "pyqt5" else "libqt6gui6"]
            if self.downgradeGit:
                apt.append("sudo apt -q remove git git-man")
                aptPackages.append("git")
            apt.append("sudo apt -q update")
            apt.append("sudo apt -q install " + " ".join(aptPackages))
        else:
            assert not self.downgradeGit, "you can only downgrade Git on Ubuntu runners"

        return {
            "name": self.name,
            "os": self.os,
            "qt": self.qt,
            "py": self.py,
            "pip-command": " && ".join(pip),
            "test-command": test,
            "coverage": self.coverage,
            "apt-command": " && ".join(apt),
        }

configs = [
    Config("linux-312-pyqt5-old", "ubuntu-22.04",   "3.12", "pyqt5", fuse=False, downgradeGit=True, prePip="pip install pygit2==1.14.1 pygments==2.12"),
    Config("linux-312-pyqt6-old", "ubuntu-24.04",   "3.12", "pyqt6", downgradeGit=True, prePip='pip install "pyqt6<6.6" "pyqt6-qt6<6.6" "pyqt6-sip<13.7" pytest-qt==4.3.1'),
    Config("linux-313-pyqt6",     "ubuntu-26.04",   "3.13", "pyqt6", downgradeGit=True),
    Config("linux-314-pyqt6",     "ubuntu-26.04",   "3.14", "pyqt6"),
    Config("linux-315-pyqt6-cov", "ubuntu-26.04",   "3.15", "pyqt6", coverage=True),
    Config("linux-315-pyside6",   "ubuntu-26.04",   "3.15", "pyside6"),
    Config("macos-315-pyqt6",     "macos-26",       "3.15", "pyqt6", fuse=False),
    Config("win32-315-pyqt6",     "windows-latest", "3.15", "pyqt6", fuse=False),
]

configMap = {c.name: c for c in configs}

if os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch") != "workflow_dispatch":
    # Keep everything for pull_request, push, etc.
    flatpakref = FLATPAK_DEFAULT_FLATPAKREF
else:
    inputs = json.loads(os.environ["WORKFLOW_INPUTS"])

    wantFlatpak = inputs.pop("flatpak", False)
    flatpakref = "" if not wantFlatpak else inputs.pop("flatpakref", FLATPAK_DEFAULT_FLATPAKREF).strip()

    configs = [configMap[name] for name, enabled in inputs.items() if enabled]

configs = [c.compile() for c in configs]

if not configs and not flatpakref:
    raise ValueError("No configs selected in WORKFLOW_INPUTS!")

# Work out cache key for Flatpak test environment.
# If using current public release, use current commit on Flathub.
# Otherwise, use URL to custom flatpakref.
flatpakCacheKey = flatpakref.removeprefix("https://")
if flatpakref == FLATPAK_DEFAULT_FLATPAKREF:
    flathubCommit = subprocess.check_output(["git", "ls-remote", FLATPAK_FLATHUB_REPO, "master"], text=True)[:7]
    flatpakCacheKey = f"Flathub {flathubCommit}"

# Rotate Flatpak cache monthly to keep it from getting stale
currentMonth = datetime.datetime.now().strftime("%B")
flatpakCacheKey = f"Flatpak test environment - {currentMonth} - {flatpakCacheKey}"

print(f"flatpakref={flatpakref}")
print(f"flatpakCacheKey={flatpakCacheKey}")
if configs:
    print(f"matrix={json.dumps({'include': configs})}")
else:
    print("matrix=")
