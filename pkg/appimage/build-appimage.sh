#!/usr/bin/env bash

set -e
set -x

export PYVER=${PYVER:-"3.14"}
export QT_API=${QT_API:-PyQt6}
export QT_API_LOWERCASE=${QT_API,,}

HERE="$(dirname "$(readlink -f -- "$0")" )"
ROOT="$(readlink -f -- "$HERE/../..")"

ARCH="$(uname -m)"

cd "$ROOT"
APPVER="$(python3 -c 'from gitfourchette.appconsts import APP_VERSION; print(APP_VERSION)')"
echo "App version: $APPVER"

mkdir -p "$ROOT/build"
cd "$ROOT/build"

# Freeze Qt api
"$ROOT/update_resources.py" --freeze $QT_API

# Write requirements file so python_appimage knows what to include.
# The path to gitfourchette's root dir must be absolute.
echo -e "$PINNED_REQUIREMENTS\n$ROOT[$QT_API,pygments,mfusepy]" > "$HERE/requirements.txt"

# Use python_appimage to create AppImage contents directory
python3 -m python_appimage --verbose build app --python-version $PYVER --no-packaging "$HERE"

pushd GitFourchette-$ARCH
    # Copy extra Qt libs
    if [ ! -z "$QT_EXTRASTUFF" ]; then
        echo "Copying extra Qt stuff from $QT_EXTRASTUFF"
        QT_LIBS_DIR="opt/python$PYVER/lib/python$PYVER/site-packages/$QT_API/Qt6"
        cp -rv "$QT_EXTRASTUFF"/* "$QT_LIBS_DIR"/
        # Prevent Qt's built-in libadwaita.so from taking precedence over our libqadwaitadecorations.so
        rm -v "$QT_LIBS_DIR/plugins/wayland-decoration-client/libadwaita.so"
    fi

    # Copy fallback OpenGL libs
    if [ ! -z "$GL_FALLBACK" ]; then
        echo "Copying extra stuff from $GL_FALLBACK"
        cp -rv "$GL_FALLBACK" gl_fallback
    fi

    # Remove junk that we don't need
    junklist=$(cat "$HERE/junklist.txt")
    rm -rfv $junklist
popd

# Package the AppImage ourselves
wget -N https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage
chmod +x appimagetool-$ARCH.AppImage
./appimagetool-$ARCH.AppImage --no-appstream GitFourchette-$ARCH
chmod +x GitFourchette-$ARCH.AppImage
mv -v GitFourchette{,-$APPVER}-$ARCH.AppImage
