#!/bin/zsh

set -e

PYTHON=${PYTHON:-python3}

here="$(dirname "$(realpath "$0")")"
cd "$here/../.."

$PYTHON -m PyInstaller pkg/pyinstaller/gitfourchette-macos.spec --noconfirm

APP=dist/GitFourchette.app

# If macOS sees this file, AND the system's preferred language matches the language of
# "Edit" and "Help" menu titles, we'll automagically get stuff like a search field
# in the Help menu, or dictation stuff in the Edit menu.
# If this file is absent, the magic menu entries are only added if the menu names
# are in English.
touch $APP/Contents/Resources/empty.lproj

# Remove PySide6 bloat
# for component in QtNetwork QtOpenGL QtQml QtQmlModels QtQuick QtVirtualKeyboard
# do
#     echo "Removing $component"
#     rm -fv $APP/Contents/Resources/$component
#     rm -fv $APP/Contents/Frameworks/$component
#     rm -rfv $APP/Contents/Frameworks/PySide6/Qt/lib/$component.framework
# done

# Remove stock Qt localizations for unsupported languages to save a few megs
keeplang="qt.*_(en|fr)\.qm"
for i in "$APP/Contents/Resources/PyQt6/Qt6/translations/"*.qm
do
    if [[ "$(basename "$i")" =~ $keeplang ]]
        then echo "Keep: $i"
        else echo -n "Delete: " && rm -v "$i"
    fi
done

rm -v "$APP/Contents/Resources/assets/lang/"*.po*
rm -v "$APP/Contents/Resources/assets/lang/README.md"

# Remove framework bloat
# Note: QtDBus.framework is included but somehow the app won't start without it.
rm -v "$APP/Contents/Frameworks/QtNetwork"
rm -v "$APP/Contents/Frameworks/QtPdf"
rm -v "$APP/Contents/Resources/QtNetwork"
rm -v "$APP/Contents/Resources/QtPdf"
rm -rv "$APP/Contents/Frameworks/PyQt6/Qt6/lib/QtPdf.framework"
rm -rv "$APP/Contents/Frameworks/PyQt6/Qt6/lib/QtNetwork.framework"
rm -rv "$APP/Contents/Frameworks/PyQt6/Qt6/plugins/imageformats/libqpdf.dylib"
