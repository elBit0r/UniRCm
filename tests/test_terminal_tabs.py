import pyte
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget
from remote_manager.session import SessionStatus
from remote_manager.terminal.screen import TerminalScreen
from remote_manager.ui.terminal_tabs import TerminalTabs


def test_activity_bell_and_tab_lifecycle(qtbot):
    tabs = TerminalTabs()
    qtbot.addWidget(tabs)
    terminals = [QWidget(), QWidget()]
    for term in terminals:
        term.session_status = SessionStatus('ssh', 'host', 22, parent=term)
        tabs.addTab(term, 'Session')
        tabs.set_base_color(tabs.indexOf(term), QColor('purple'))
        tabs.watch_terminal(term)
    first, second = terminals
    tabs.setCurrentWidget(second)
    first.session_status.activity.emit('tx')
    assert tabs.tabBar().tabTextColor(0) == QColor('purple')
    first.session_status.activity.emit('rx')
    assert tabs.tabBar().tabTextColor(0) == QColor('#3498db')
    stream = pyte.ByteStream(TerminalScreen(80, 24, bell=first.session_status.bell.emit))
    stream.feed(b'\x07')
    assert tabs.tabBar().tabTextColor(0) == QColor('#e67e22')
    tabs._tick(first)
    assert tabs.tabBar().tabTextColor(0) == QColor('purple')
    tabs.tabBar().moveTab(0, 1)
    tabs._tick(first)
    assert tabs.tabBar().tabTextColor(1) == QColor('#e67e22')
    tabs.setCurrentWidget(first)
    assert tabs.tabBar().tabTextColor(1) == QColor('purple')
    first.session_status.activity.emit('rx')
    tabs._tick(first)
    tabs._tick(first)
    assert tabs.tabBar().tabTextColor(1) == QColor('purple')
    stream.feed(b'\x07')
    tabs.removeTab(1)
    first.session_status.activity.emit('rx')
    assert first not in tabs._notifications
