"""Resizable groups of live terminal widgets; moving never restarts a session."""
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QMimeData
from PyQt6.QtGui import QDrag, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QSplitter, QMenu
from .icons import action_icon


def sessions(widget):
    return list(widget.terminals) if isinstance(widget, SessionWorkspace) else ([widget] if widget else [])


def active_session(widget):
    return widget.active if isinstance(widget, SessionWorkspace) else widget


class SessionDragData(QMimeData):
    def __init__(self, terminal):
        super().__init__()
        self.terminal = terminal
        self.setData('application/x-unircm-session', b'')

    @staticmethod
    def start(source, terminal):
        drag = QDrag(source)
        drag.setMimeData(SessionDragData(terminal))
        drag.exec(Qt.DropAction.MoveAction)


class SessionTitle(QLabel):
    def __init__(self, terminal):
        super().__init__()
        self.terminal = terminal
        self.press_position = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def set_session_tooltip(self, tooltip):
        self.setToolTip('\n'.join(filter(None, (tooltip, self.tr('Drag this session to another workspace tab.')))))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_position = event.position()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self.press_position is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position() - self.press_position).manhattanLength() >= QApplication.startDragDistance()):
            self.press_position = None
            # Keep the drag source alive even when moving out of the last pane.
            SessionDragData.start(self.window(), self.terminal)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_position = None
        super().mouseReleaseEvent(event)


class EmptyPane(QWidget):
    def __init__(self, workspace, slot):
        super().__init__()
        self.workspace = workspace
        self.slot = slot
        self.setAcceptDrops(True)
        box = QVBoxLayout(self)
        label = QLabel(self.tr('Drop a connection or an open session here.'))
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        box.addWidget(label)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        self.workspace.empty_menu_requested.emit(menu, self.slot)
        menu.exec(event.globalPos())

    def _accept_drop(self, event):
        data = event.mimeData()
        if self.slot in self.workspace.positions.values():
            event.ignore()
        elif isinstance(data, SessionDragData) and self.workspace.accepts_session_drop(data.terminal):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        elif self.workspace.accepts_drop(event.source()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    dragEnterEvent = _accept_drop
    dragMoveEvent = _accept_drop

    def dropEvent(self, event):
        self._accept_drop(event)
        if event.dropAction() == Qt.DropAction.MoveAction and event.isAccepted():
            self.workspace.session_dropped.emit(event.mimeData().terminal, self.slot)
        elif event.isAccepted():
            self.workspace.connection_dropped.emit(event.source(), self.slot)


class SessionPane(QWidget):
    """Paint a focus border without changing terminal palettes or geometry."""
    def __init__(self):
        super().__init__()
        self.active = False

    def set_active(self, active):
        if self.active != active:
            self.active = active
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        color = self.palette().highlight().color() if self.active else self.palette().mid().color()
        painter.setPen(QPen(color, 3 if self.active else 1))
        painter.drawRect(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5))


class SessionWorkspace(QWidget):
    empty_menu_requested = pyqtSignal(object, int)
    connection_dropped = pyqtSignal(object, int)
    session_dropped = pyqtSignal(object, int)
    active_changed = pyqtSignal()
    close_requested = pyqtSignal(object)
    detach_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.terminals = []
        self.panels = {}
        self.positions = {}
        self.empty_panes = []
        self.accepts_drop = lambda source: False
        self.accepts_session_drop = lambda terminal: False
        self.active = None
        self.mode = 'side'
        self.maximized = None
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(0, 0, 0, 0)
        self.root = None
        self._layout_sizes = {}
        self._layout_key = None
        QApplication.instance().focusChanged.connect(self._focus_changed)

    def _focus_changed(self, old, new):
        for terminal, (panel, label) in self.panels.items():
            if new is panel or (new is not None and panel.isAncestorOf(new)):
                self.activate(terminal)
                break

    def activate(self, terminal):
        self.active = terminal
        for term, (panel, label) in self.panels.items():
            panel.set_active(term is terminal)
            font = label.font()
            font.setBold(term is terminal)
            label.setFont(font)
            label.setText(('▶ ' if term is terminal else '') + getattr(term, '_workspace_title', self.tr('Session')))
        self.active_changed.emit()

    def add_terminal(self, terminal, mode=None, slot=None):
        if len(self.terminals) >= 4:
            raise ValueError('A workspace can contain at most four sessions.')
        if slot is None:
            slot = next(i for i in range(4) if i not in self.positions.values())
        if slot not in range(4) or slot in self.positions.values():
            raise ValueError('Workspace pane is occupied or invalid.')
        if hasattr(terminal, 'attach_desktop'):
            terminal.attach_desktop()
        self.positions[terminal] = slot
        panel = SessionPane()
        box = QVBoxLayout(panel)
        box.setContentsMargins(4, 4, 4, 4)
        header = QHBoxLayout()
        label = SessionTitle(terminal)
        label.set_session_tooltip(getattr(terminal, '_workspace_tooltip', ''))
        header.addWidget(label, 1)
        for title, callback, tip in (
            ('Maximize', lambda: self.toggle_maximize(terminal), 'Enlarge this pane or restore the layout.'),
            ('Detach', lambda: self.detach_requested.emit(terminal), 'Move this session into its own tab without reconnecting.'),
            ('Close', lambda: self.close_requested.emit(terminal), 'Disconnect and close only this pane.'),
        ):
            button = QToolButton()
            button.setAccessibleName(self.tr(title))
            button.setIcon(action_icon(self, title))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setToolTip(self.tr(tip))
            button.clicked.connect(callback)
            header.addWidget(button)
        box.addLayout(header)
        box.addWidget(terminal, 1)
        terminal.show()
        self.terminals.append(terminal)
        self.panels[terminal] = (panel, label)
        self.arrange(self.mode if mode is None else mode)
        self.activate(terminal)

    def take_terminal(self, terminal):
        panel, _ = self.panels.pop(terminal)
        self.terminals.remove(terminal)
        self.positions.pop(terminal)
        terminal.setParent(None)
        panel.setParent(None)
        panel.deleteLater()
        if self.active is terminal:
            self.active = self.terminals[0] if self.terminals else None
        self.arrange(self.mode)
        self.activate(self.active)
        return terminal

    def arrange(self, mode):
        if mode not in ('side', 'stack', 'grid'):
            raise ValueError('Unknown workspace layout.')
        count = 4 if mode == 'grid' else max(2, max(self.positions.values(), default=0) + 1)
        key = (mode, count)
        focused = QApplication.focusWidget()
        restore_focus = focused is not None and self.isAncestorOf(focused)
        if self.maximized is not None:
            self.toggle_maximize(self.maximized)
        if self.root is not None:
            self._remember_sizes()
            if key == self._layout_key:
                # Reusing the selected layout must not resize live terminals.
                occupied = {slot: term for term, slot in self.positions.items()}
                current = {pane.slot for pane in self.empty_panes}
                if current == set(range(count)) - set(occupied):
                    return
        self.mode = mode
        self.maximized = None
        self.setUpdatesEnabled(False)
        for panel, _ in self.panels.values():
            # Keep panes owned by the workspace while replacing their splitters.
            panel.setParent(self)
        if self.root is not None:
            self.root.hide()
            self.layout_box.removeWidget(self.root)
            self.root.deleteLater()
        self.root = QSplitter(Qt.Orientation.Vertical if mode in ('stack', 'grid') else Qt.Orientation.Horizontal)
        self.root.setChildrenCollapsible(False)
        self.layout_box.addWidget(self.root)
        self.empty_panes = []
        panes = []
        occupied = {slot: term for term, slot in self.positions.items()}
        for slot in range(count):
            if slot in occupied:
                panes.append(self.panels[occupied[slot]][0])
            else:
                empty = EmptyPane(self, slot)
                self.empty_panes.append(empty)
                panes.append(empty)
        if mode == 'grid':
            for start in range(0, count, 2):
                row = QSplitter(Qt.Orientation.Horizontal)
                row.setChildrenCollapsible(False)
                self.root.addWidget(row)
                for pane in panes[start:start + 2]:
                    row.addWidget(pane)
                row.setSizes([1, 1])
        else:
            for pane in panes:
                self.root.addWidget(pane)
        self.root.show()
        self.layout_box.activate()
        self.root.setSizes([1000] * self.root.count())
        self._layout_key = key
        self._restore_sizes()
        for panel, _ in self.panels.values():
            panel.show()
        self.setUpdatesEnabled(True)
        if restore_focus and self.active is not None:
            self.active.setFocus()

    def _remember_sizes(self):
        if self.root is None or self.maximized is not None:
            return
        rows = [self.root.widget(i).sizes() for i in range(self.root.count())] if self.mode == 'grid' else []
        self._layout_sizes[self._layout_key] = (self.root.sizes(), rows)

    def _restore_sizes(self):
        saved = self._layout_sizes.get(self._layout_key)
        if saved is None:
            return
        sizes, rows = saved
        self.root.setSizes(sizes)
        for i, widths in enumerate(rows):
            self.root.widget(i).setSizes(widths)

    def toggle_maximize(self, terminal):
        if self.maximized is None:
            self._remember_sizes()
        self.maximized = None if self.maximized is terminal else terminal
        for term, (panel, _) in self.panels.items():
            panel.setVisible(self.maximized is None or term is terminal)
        for empty in self.empty_panes:
            empty.setVisible(self.maximized is None)
        # Hide empty rows too, so a maximized pane occupies the whole workspace.
        if self.mode == 'grid':
            for i in range(self.root.count()):
                row = self.root.widget(i)
                row.setVisible(self.maximized is None or row.isAncestorOf(terminal))
        if self.maximized is None:
            self._restore_sizes()
        self.activate(terminal)
        terminal.setFocus()
