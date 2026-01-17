# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

def main():
    import argparse
    import ctypes
    import sys

    parser = argparse.ArgumentParser(description="Send CTRL_C_EVENT or CTRL_BREAK_EVENT to win32 console process (roughly equivalent to SIGTERM)")
    parser.add_argument("pid", type=int, help="Process ID to terminate")
    parser.add_argument("-e", "--event", type=int, choices=[0, 1], default=0, help="0=CTRL_C_EVENT, 1=CTRL_BREAK_EVENT")
    args = parser.parse_args()

    def check(rc, exitCode):
        if rc == 0:
            sys.exit(exitCode)

    kernel = ctypes.windll.kernel32

    result = kernel.FreeConsole()
    check(result, 1)

    result = kernel.AttachConsole(args.pid)
    check(result, 2)

    result = kernel.SetConsoleCtrlHandler(None, 1)
    check(result, 3)

    result = kernel.GenerateConsoleCtrlEvent(args.event, 0)
    check(result, 4)


if __name__ == '__main__':
    main()
