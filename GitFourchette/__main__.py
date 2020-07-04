from PySide2.QtWidgets import QApplication
import sys
import signal
from util import excMessageBox


def excepthook(exctype, value, tb):
    sys._excepthook(exctype, value, tb)
    # todo: this is not thread safe!
    excMessageBox(value)


if __name__ == "__main__":
    # allow interrupting with Control-C
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # inject our own exception hook to show an error dialog in case of unhandled exceptions
    sys._excepthook = sys.excepthook
    sys.excepthook = excepthook

    # initialize Qt before importing app modules so fonts are loaded correctly
    app = QApplication(sys.argv)
    with open("icons/style.qss", "r") as f:
        app.setStyleSheet(f.read())

    import MainWindow
    window = MainWindow.MainWindow()
    window.show()

    try:
        window.tryLoadSession()
    except BaseException as e:
        excMessageBox(e, "Resume Session", "Failed to resume previous session.")

    app.exec_()
