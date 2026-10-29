#! /bin/bash -i

# If the system doesn't provide libOpenGL.so.0, use our built-in fallback
# (referenced by libqadwaitadecorations.so)
if ! ldconfig -p 2>/dev/null | grep -Fq libOpenGL.so.0 ; then
    export LD_LIBRARY_PATH="${APPDIR}/gl_fallback${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

"{{ python-executable }}" -u "${APPDIR}/opt/python{{ python-version }}/bin/gitfourchette" "$@"

