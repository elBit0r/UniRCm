from types import SimpleNamespace

from PyQt6.QtWidgets import QMessageBox, QTabWidget, QWidget
from remote_manager.ui.main_window import MainWindow


class Session(QWidget):
    def __init__(self, running=True):
        super().__init__()
        self.running = running
        self.stopped = False

    def is_running(self):
        return self.running

    def stop(self):
        self.stopped = True


def test_close_active_tab_requires_yes(qtbot, monkeypatch):
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    terminal = Session()
    tabs.addTab(terminal, 'SSH')
    window = SimpleNamespace(tabs=tabs, tr=lambda text: text)
    answers = [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]

    def question(*args):
        assert args[-1] == QMessageBox.StandardButton.No
        return answers.pop(0)

    monkeypatch.setattr(QMessageBox, 'question', question)
    MainWindow.close_tab(window, 0)
    assert tabs.count() == 1 and not terminal.stopped
    MainWindow.close_tab(window, 0)
    assert tabs.count() == 0 and terminal.stopped


def test_finished_and_preconfirmed_tabs_close_without_prompt(qtbot, monkeypatch):
    tabs = QTabWidget()
    qtbot.addWidget(tabs)
    window = SimpleNamespace(tabs=tabs, tr=lambda text: text)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: (_ for _ in ()).throw(AssertionError('Unexpected prompt')))
    for running in (False, True):
        terminal = Session(running)
        tabs.addTab(terminal, 'SSH')
        MainWindow.close_tab(window, 0, confirm=not running)
        assert terminal.stopped and tabs.count() == 0
    MainWindow.close_tab(window, -1)
