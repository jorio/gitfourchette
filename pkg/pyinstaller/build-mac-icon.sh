#!/usr/bin/env bash

set -e

/Applications/Xcode.app/Contents/Developer/usr/bin/actool \
	gitfourchette.icon \
	--app-icon gitfourchette \
	--compile . \
	--output-partial-info-plist /dev/null \
	--platform macosx \
	--target-device mac \
	--enable-icon-stack-fallback-generation=disabled \
	--standalone-icon-behavior none \
	--lightweight-asset-runtime-mode enabled \
	--minimum-deployment-target 26.0
