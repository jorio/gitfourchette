# -----------------------------------------------------------------------------
# Copyright (C) 2024 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

import dataclasses
import urllib.parse

from gitfourchette.toolbox import *


HTTPS_PORT = 443


@dataclasses.dataclass
class WebHost:
    name: str
    branchPrefix: str
    port: int = HTTPS_PORT

    @staticmethod
    def makeLink(remoteUrl: str, branch: str = ""):
        host, path = splitRemoteUrl(remoteUrl)

        if not host:
            return "", ""

        path = path.removesuffix(".git")

        try:
            hostInfo = WEB_HOSTS[host]
            hostName = hostInfo.name
        except KeyError:
            hostInfo = WEB_HOSTS["github.com"]  # fall back to GitHub's scheme
            hostName = host

        port = "" if hostInfo.port == HTTPS_PORT else f":{hostInfo.port}"
        suffix = ""

        if branch:
            suffix = hostInfo.branchPrefix + urllib.parse.quote(branch, safe='/')

        return f"https://{host}{port}/{path}{suffix}", hostName


WEB_HOSTS = {
    "github.com": WebHost("GitHub", "/tree/"),
    "gitlab.com": WebHost("GitLab", "/-/tree/"),
    "git.sr.ht": WebHost("Sourcehut", "/tree/"),
    "codeberg.org": WebHost("Codeberg", "/src/branch/"),
    "git.launchpad.net": WebHost("Launchpad", "/log?h="),
    "bitbucket.org": WebHost("Bitbucket", "/src/"),
}
