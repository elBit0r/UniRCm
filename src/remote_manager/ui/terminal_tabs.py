"""Terminal tab activity and parsed BEL notifications."""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QTabBar, QTabWidget
from .session_workspace import SessionDragData, active_session, sessions


class SessionTabBar(QTabBar):
    session_dropped = pyqtSignal(object, object)

    def __init__(self, tabs):
        super().__init__(tabs)
        self.tabs = tabs
        self._session_press = None
        self.setAcceptDrops(True)

    def mousePressEvent(self, event):
        index = self.tabAt(event.position().toPoint())
        if (index >= 0 and event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() == Qt.KeyboardModifier.ShiftModifier):
            self._session_press = (event.position(), active_session(self.tabs.widget(index)))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._session_press is None:
            super().mouseMoveEvent(event)
            return
        origin, terminal = self._session_press
        if (terminal is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position() - origin).manhattanLength() >= QApplication.startDragDistance()):
            self._session_press = None
            if self.tabs.indexOf(terminal) >= 0:
                SessionDragData.start(self, terminal)

    def mouseReleaseEvent(self, event):
        self._session_press = None
        super().mouseReleaseEvent(event)

    def _drop_target(self, event):
        data = event.mimeData()
        target = self.tabs.widget(self.tabAt(event.position().toPoint()))
        if isinstance(data, SessionDragData) and self.tabs.can_move_session(data.terminal, target):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return target
        event.ignore()
        return None

    def dragMoveEvent(self, event):
        self._drop_target(event)

    def dragEnterEvent(self, event):
        data = event.mimeData()
        # Enter over any tab so Qt keeps sending move events across the bar.
        if isinstance(data, SessionDragData) and self.tabs.indexOf(data.terminal) >= 0:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        target = self._drop_target(event)
        if target is not None:
            self.session_dropped.emit(event.mimeData().terminal, target)


class TerminalTabs(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabBar(SessionTabBar(self))
        self._notifications = {}
        self.currentChanged.connect(self._acknowledge)

    def setTabToolTip(self, index, tooltip):
        hint = self.tr('Hold Shift and drag to move the active session to another workspace.')
        super().setTabToolTip(index, '\n'.join(filter(None, (tooltip, hint))))

    def can_move_session(self, terminal, target):
        return (terminal is not None and target is not None and self.indexOf(terminal) >= 0
                and super().indexOf(target) >= 0 and terminal not in sessions(target)
                and len(sessions(target)) < 4)

    def indexOf(self, widget):
        index = super().indexOf(widget)
        if index < 0:
            for i in range(self.count()):
                if widget in sessions(self.widget(i)):
                    return i
        return index

    def take_page(self, index):
        """Remove a page for reparenting while keeping its live notifications."""
        page = self.widget(index)
        super().removeTab(index)
        page.setParent(None)
        return page

    def watch_terminal(self, terminal):
        timer = QTimer(self)
        timer.setInterval(500)
        state = dict(base=self.tabBar().tabTextColor(self.indexOf(terminal)),
                     activity=False, bell=False, phase=True, ticks=0, timer=timer)
        self._notifications[terminal] = state
        timer.timeout.connect(lambda: self._tick(terminal))
        terminal.session_status.activity.connect(lambda direction: self._activity(terminal, direction))
        terminal.session_status.bell.connect(lambda: self._bell(terminal))

    def set_base_color(self, index, color):
        terminal = self.widget(index)
        if terminal in self._notifications:
            self._notifications[terminal]['base'] = color
            self._paint(terminal)
        else:
            self.tabBar().setTabTextColor(index, color)

    def set_terminal_color(self, terminal, color):
        if terminal in self._notifications:
            self._notifications[terminal]['base'] = color
            self._paint(terminal)

    def _paint(self, terminal):
        index = self.indexOf(terminal)
        if index < 0:
            return
        states = [self._notifications[t] for t in sessions(self.widget(index)) if t in self._notifications]
        if not states:
            return
        color = states[0]['base']
        bells = [state for state in states if state['bell']]
        if any(state['phase'] for state in bells):
            color = QColor('#e67e22')
        elif not bells and any(state['activity'] for state in states):
            color = QColor('#3498db')
        self.tabBar().setTabTextColor(index, color)

    def _activity(self, terminal, direction):
        if direction != 'rx' or terminal not in self._notifications:
            return
        state = self._notifications[terminal]
        state['activity'] = True
        if not state['bell']:
            state['ticks'] = 2
            state['timer'].start()
        self._paint(terminal)

    def _bell(self, terminal):
        if terminal not in self._notifications:
            return
        state = self._notifications[terminal]
        state.update(bell=True, phase=True, ticks=6)
        state['timer'].start()
        self._paint(terminal)

    def _tick(self, terminal):
        state = self._notifications[terminal]
        state['phase'] = not state['phase']
        state['ticks'] -= 1
        if self.indexOf(terminal) == self.currentIndex() and state['ticks'] <= 0:
            self._acknowledge(self.currentIndex())
        else:
            if not state['bell']:
                state['timer'].stop()
            self._paint(terminal)

    def _acknowledge(self, index):
        for terminal in sessions(self.widget(index)):
            if terminal in self._notifications:
                state = self._notifications[terminal]
                state.update(activity=False, bell=False)
                state['timer'].stop()
                self._paint(terminal)

    def unwatch_terminal(self, terminal):
        state = self._notifications.pop(terminal, None)
        if state:
            state['timer'].stop()
            state['timer'].deleteLater()

    def removeTab(self, index):
        for terminal in sessions(self.widget(index)):
            self.unwatch_terminal(terminal)
        super().removeTab(index)
