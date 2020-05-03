import git
from PySide2.QtCore import *
from PySide2.QtGui import *
from PySide2.QtWidgets import *
import globals
import os
import traceback
from RepoState import RepoState
from RepoWidget import RepoWidget
from util import compactPath


class MainWindow(QMainWindow):
    repoWidget: RepoWidget
    tabs: QTabWidget

    def __init__(self):
        super().__init__()

        self.setWindowTitle(globals.PROGRAM_NAME)
        self.setWindowIcon(QIcon("icons/gf.png"))
        self.resize(globals.appSettings.value("MainWindow/size", QSize(800, 600)))
        self.move(globals.appSettings.value("MainWindow/position", QPoint(50, 50)))

        self.tabs = QTabWidget()
        #self.tabs.setTabBarAutoHide(True)
        self.tabs.setMovable(True)

        self.repoWidget = None

        self.setCentralWidget(self.tabs)

        self.makeMenu()

    def makeMenu(self):
        menubar = QMenuBar()

        fileMenu = menubar.addMenu("&File")
        self.createFileMenu(fileMenu)

        repoMenu = menubar.addMenu("&Repo")
        repoMenu.addAction("Push", lambda: self.repoWidget.push())
        repoMenu.addAction("Rename...", lambda: self.repoWidget.renameRepo())

        helpMenu = menubar.addMenu("&Help")
        helpMenu.addAction(F"About {globals.PROGRAM_NAME}", self.about)
        helpMenu.addAction("About Qt", lambda: QMessageBox.aboutQt(self))
        helpMenu.addSeparator()
        helpMenu.addAction("Memory", self.memInfo)

        self.setMenuBar(menubar)

    def about(self):
        import sys, PySide2
        about_text = F"""\
        <h2>{globals.PROGRAM_NAME} {globals.VERSION}</h2>
        <p><small>
        {git.Git().version()}<br>
        Python {sys.version}<br>
        GitPython {git.__version__}<br>
        Qt {PySide2.QtCore.__version__}<br>
        PySide2 {PySide2.__version__}
        </small></p>
        <p>
        This is my git frontend.<br>There are many like it but this one is mine.
        </p>
        """
        QMessageBox.about(self, F"About {globals.PROGRAM_NAME}", about_text)

    def memInfo(self):
        import psutil, gc
        gc.collect()
        QMessageBox.information(self, F"Memory usage", F"{psutil.Process(os.getpid()).memory_info().rss:,}")

    def createFileMenu(self, m: QMenu):
        m.clear()

        m.addAction("&Open", self.open, QKeySequence.Open)

        recentMenu = m.addMenu("Open &Recent")
        for historic in globals.getRepoHistory():
            recentMenu.addAction(
                F"{globals.getRepoNickname(historic)} [{compactPath(historic)}]",
                lambda h=historic: self.setRepo(h))

        m.addSeparator()

        m.addAction("&Quit", self.close, QKeySequence.Quit)

    def setRepo(self, gitRepoDirPath):
            #with self.unready():
            shortname = globals.getRepoNickname(gitRepoDirPath)
            progress = QProgressDialog("Opening repository...", "Abort", 0, 0, self)
            progress.setWindowModality(Qt.WindowModal)
            progress.setWindowTitle(shortname)
            progress.setWindowFlags(Qt.Dialog | Qt.Popup)
            progress.setMinimumWidth(2 * progress.fontMetrics().width("000,000,000 commits loaded."))
            QCoreApplication.processEvents()
            progress.show()
            QCoreApplication.processEvents()
            #import time; time.sleep(3)

            newRW = RepoWidget(self)
            try:
                newRW.state = RepoState(gitRepoDirPath)
                globals.addRepoToHistory(gitRepoDirPath)
                newRW.graphView.fill(progress)
                self.tabs.addTab(newRW, shortname)
                self.repoWidget = newRW
                self.setWindowTitle(F"{shortname} [{self.repoWidget.state.repo.active_branch}] — {globals.PROGRAM_NAME}")
            except BaseException as e:
                newRW.destroy()
                progress.close()
                traceback.print_exc()
                if isinstance(e, git.exc.InvalidGitRepositoryError):
                    QMessageBox.warning(self, "Invalid repository", F"Couldn't open \"{gitRepoDirPath}\" because it is not a git repository.")
                else:
                    QMessageBox.critical(self, "Error", F"Couldn't open \"{gitRepoDirPath}\" because an exception was thrown.\n{e.__class__.__name__}: {e}.\nCheck stderr for details.")
                return
            finally:
                progress.close()

    def open(self):
        path = QFileDialog.getExistingDirectory(self, "Open repository", globals.appSettings.value(globals.SK_LAST_OPEN, "", type=str))
        if path:
            globals.appSettings.setValue(globals.SK_LAST_OPEN, path)
            self.setRepo(path)

    def closeEvent(self, e):
        # Write window size and position to config file
        globals.appSettings.setValue("MainWindow/size", self.size())
        globals.appSettings.setValue("MainWindow/position", self.pos())
        self.repoWidget.saveSplitterStates()
        e.accept()
