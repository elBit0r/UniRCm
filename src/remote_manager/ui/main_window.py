"""SSH profile manager and independent embedded terminal tabs."""
from time import monotonic

from PyQt6.sip import isdeleted

from PyQt6.QtCore import Qt, QEvent, QSize, QTimer, pyqtSignal, QPointF
from PyQt6.QtGui import QAction, QActionGroup, QColor, QKeySequence, QShortcut, QPainter
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QLineEdit, QMainWindow, QMessageBox, QSplitter, QSplitterHandle, QStyle, QStyleOptionToolButton, QStylePainter, QWidget, QVBoxLayout,
                            QMenu, QInputDialog, QTabWidget, QToolButton, QHBoxLayout, QSizePolicy, QTreeWidget, QTreeWidgetItem, QDialogButtonBox)

from remote_manager import APP_SHORT_NAME, APP_NAME, __version__
from remote_manager.terminal.public_key import public_key_from_private
from remote_manager.terminal.ssh import Terminal
from .dialogs import TerminalAppearanceDialog, GroupDefaultsDialog, LocalTerminalProfileDialog, ProfileDialog, VaultUnlockPanel
from .settings import SettingsDialog
from .visuals import brand_header, style_surface, contrast_workspace
from .language import set_language
from .credentials import CredentialManager
from .session_status import SessionStatusLabel
from .terminal_tabs import TerminalTabs
from .session_workspace import SessionWorkspace, sessions, active_session
from .icons import ssh_icon, connection_icon, group_icon, action_icon


class TreeGripButton(QToolButton):
    """Clickable three-dot grip, separate from the draggable splitter surface."""
    def paintEvent(self, event):
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.text = ''
        painter = QStylePainter(self)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ToolButton, option)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().buttonText())
        for offset in (-5, 0, 5):
            painter.drawEllipse(QPointF(self.rect().center()) + QPointF(0, offset), 1.5, 1.5)


class TreeSplitterHandle(QSplitterHandle):
    def __init__(self, orientation, splitter):
        super().__init__(orientation, splitter)
        self.toggle = TreeGripButton(self)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.toggle.setText(self.tr('Connection tree'))
        self.toggle.setAccessibleName(self.tr('Connection tree'))
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setAutoRaise(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.toggle.setGeometry(0, max(0, (self.height() - 36) // 2), self.width(), 36)


class TreeSplitter(QSplitter):
    def createHandle(self):
        return TreeSplitterHandle(self.orientation(), self)


class ConnectionItem(QTreeWidgetItem):
    def __lt__(self, other):
        return self.data(0, Qt.ItemDataRole.UserRole + 1) < other.data(0, Qt.ItemDataRole.UserRole + 1)


class ConnectionTree(QTreeWidget):
    move_requested = pyqtSignal(object, object, object, bool)

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dropEvent(self, event):
        source = self.currentItem()
        if event.source() is not self or source is None:
            event.ignore()
            return
        data = source.data(0, Qt.ItemDataRole.UserRole)
        target = self.itemAt(event.position().toPoint())
        indicator = self.dropIndicatorPosition()
        anchor, after = None, False
        if target is None or indicator == QAbstractItemView.DropIndicatorPosition.OnViewport:
            folder_id = None
        else:
            target_data = target.data(0, Qt.ItemDataRole.UserRole)
            if indicator == QAbstractItemView.DropIndicatorPosition.OnItem and target_data.get('kind') == 'folder':
                folder_id = target_data['id']
            else:
                parent = target.parent()
                folder_id = parent.data(0, Qt.ItemDataRole.UserRole)['id'] if parent else None
                anchor = (target_data.get('kind', 'profile'), target_data['id'])
                after = indicator != QAbstractItemView.DropIndicatorPosition.AboveItem
        # Persist first; rebuilding the tree avoids unsaved in-memory moves.
        event.ignore()
        self.move_requested.emit(data, folder_id, anchor, after)



class MainWindow(QMainWindow):
    def __init__(self, vault, database_path):
        super().__init__()
        self.vault = vault
        self._tree_clipboard = None
        self.unlock_panel = None
        set_language(vault.language())
        self.database_path = database_path
        self.ssh_icon = ssh_icon(self.palette())
        self.resize(1100, 720)
        self.tree = ConnectionTree()
        self.tree.move_requested.connect(self.move_item)
        self.tree.setIconSize(QSize(20, 20))
        self.tree.setStyleSheet('QTreeWidget::item { padding-top: 5px; padding-bottom: 5px; }')
        self.tree.setUniformRowHeights(True)
        self.tree.setFrameShape(QTreeWidget.Shape.NoFrame)
        self.tree.setHeaderLabels([self.tr('Remote')])
        self.tree.setToolTip(self.tr('Drag above or below an item to reorder; drop onto a group to move inside it.'))
        self.tree.itemDoubleClicked.connect(lambda *_: self.connect_profile())
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_context_menu)
        self.session_status_label = SessionStatusLabel(self)
        self.statusBar().addPermanentWidget(self.session_status_label, 1)
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_session_status)
        self.status_timer.start(1000)
        self.tabs = TerminalTabs()
        self.tabs.currentChanged.connect(self.update_session_status)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.tab_context_menu)
        self.tabs.tabBar().session_dropped.connect(self.drop_session_on_tab)
        split = self.tree_splitter = TreeSplitter()
        self._tree_sizes = [280, 820]
        sidebar = self.sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 10, 8, 8)
        sidebar_layout.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr('Search name, host or username…'))
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumHeight(34)
        self.search.textChanged.connect(self.filter_tree)
        self._filter_expansion = None
        self._filter_selection = None
        self._filter_scroll = 0
        self.local_tree = QTreeWidget()
        self.local_tree.setRootIsDecorated(False)
        self.local_tree.setUniformRowHeights(True)
        self.local_tree.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.local_tree.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.local_tree.setMaximumHeight(150)
        self.local_tree.hide()
        self.local_tree.itemActivated.connect(
            lambda item, column: self.open_local_terminal(profile_id=item.data(0, Qt.ItemDataRole.UserRole)))
        self.local_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.local_tree.customContextMenuRequested.connect(self.local_tree_menu)
        sidebar_layout.addWidget(self.local_tree)
        sidebar_layout.addWidget(self.search)
        sidebar_layout.addWidget(self.tree)
        # Keep the splitter's first pane present when its contents are hidden,
        # so its handle and toggle remain available at the left edge.
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.addWidget(sidebar)
        split.addWidget(host)
        split.addWidget(self.tabs)
        self.tree_handle = split.handle(1)
        self.tree_handle.setToolTip(self.tr('Drag to resize; click the dots to show or hide the connections panel.'))
        self.tree_toggle = self.tree_handle.toggle
        self.tree_toggle.setToolTip(self.tr('Show or hide the connections panel.'))
        self.tree_toggle.clicked.connect(lambda: self.actions['Connection tree'].trigger())
        split.setStretchFactor(1, 1)
        split.setSizes([280, 820])
        split.setHandleWidth(14)
        split.setObjectName('connectionDivider')
        split.setStyleSheet('''
            QSplitter#connectionDivider::handle {
                background: palette(midlight);
                border-left: 1px solid palette(mid);
                border-right: 1px solid palette(mid);
            }
            QSplitter#connectionDivider::handle:hover { background: palette(highlight); }
        ''')
        contrast_workspace(self.sidebar, self.tabs, self.palette())
        self.setCentralWidget(split)
        toolbar = self.addToolBar(self.tr('Connections'))
        self.toolbar = toolbar
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setStyleSheet('QToolBar { spacing: 4px; padding: 4px; } QToolButton { padding: 5px 7px; }')
        self.actions = {}
        for title, callback in [('New connection', self.new_profile), ('New group', self.new_folder), ('Edit', self.edit_profile),
                                ('Duplicate', self.duplicate_profile),
                                ('Delete', self.delete_profile), ('Connect', self.connect_profile),
                                ('Open database', self.switch_database), ('Settings', self.database_settings), ('Credentials', self.manage_credentials), ('Lock', self.lock_vault),
                                ('New database', self.new_database), ('Exit', self.close),
                                ('New local terminal', self.open_local_terminal),
                                ('Disconnect', self.disconnect_current_session), ('Reconnect', self.reconnect_current_session),
                                ('Close tab', self.close_current_tab), ('Find connection', self.focus_search),
                                ('Help', self.show_help), ('About', self.show_about),
                                ('Cut', self.cut_tree_item), ('Copy', self.copy_tree_item), ('Paste', self.paste_tree_item)]:
            action = QAction(action_icon(self, title), title, self)
            action.setIconVisibleInMenu(True)
            action.setToolTip(self.tr('Manage shared encrypted credentials') if title == 'Credentials' else self.tr(title))
            action.setText(self.tr(title))
            action.triggered.connect(lambda checked=False, method=callback.__name__: getattr(self, method)())
            self.actions[title] = action
        self.actions['New local terminal'].setToolTip(self.tr('Open an interactive shell on this computer.'))
        for group in [('New connection', 'Open database'), ('Edit', 'Connect', 'Disconnect'), ('Lock',)]:
            if toolbar.actions():
                toolbar.addSeparator()
            for title in group:
                toolbar.addAction(self.actions[title])
        toolbar.addSeparator()
        for title, icon, mode in [('Split vertically', 'Side by side', 'side'),
                                  ('Split horizontally', 'Stacked', 'stack'),
                                  ('Grid 2 × 2', 'Grid 2 × 2', 'grid')]:
            action = QAction(action_icon(self, icon), self.tr(title), self)
            action.setToolTip(self.tr(title))
            action.triggered.connect(lambda checked=False, m=mode: self.apply_workspace_layout(m))
            self.actions[title] = action
            toolbar.addAction(action)
        self.tree.itemSelectionChanged.connect(self.update_actions)
        for sequence, callback in [('Return', self.connect_profile), ('Enter', self.connect_profile)]:
            shortcut = QShortcut(QKeySequence(sequence), self.tree)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(callback)
        self._restoring_tree = True
        self._pending_tree_scroll = None
        self.restore_scroll_timer = QTimer(self)
        self.restore_scroll_timer.setSingleShot(True)
        self.restore_scroll_timer.timeout.connect(self.restore_tree_scroll)
        self.tree_state_timer = QTimer(self)
        self.tree_state_timer.setSingleShot(True)
        self.tree_state_timer.timeout.connect(self.save_tree_state)
        self.tree.itemExpanded.connect(self.schedule_tree_state)
        self.tree.itemCollapsed.connect(self.schedule_tree_state)
        self.tree.itemSelectionChanged.connect(self.schedule_tree_state)
        self.tree.verticalScrollBar().valueChanged.connect(self.tree_scroll_changed)
        self.add_tree_actions()
        self.add_main_menus()
        self.add_tree_tools(sidebar_layout)
        self.refresh()
        self.restore_tree_state()
        self.update_session_status()
        self._locking = False
        self.last_activity = monotonic()
        self.inactivity_limit = self.vault.inactivity_minutes() * 60
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self.check_inactivity)
        self.idle_timer.start(1000)
        QApplication.instance().installEventFilter(self)
        QTimer.singleShot(0, self.connect_startup_profiles)

    def connect_startup_profiles(self):
        if self.vault is None or self._locking:
            return
        for profile in self.vault.profiles():
            if profile.get('connect_at_startup'):
                self.open_profile(profile)

    def add_main_menus(self):
        self.menuBar().setNativeMenuBar(False)
        self.menus = {}
        contents = {
            'File': [('New connection', 'New group', 'New database'), ('Open database',), ('Lock',), ('Exit',)],
            'Edit': [('Edit', 'Duplicate', 'Delete'), ('Credentials', 'Settings')],
            'Session': [('Connect', 'New local terminal'), ('Disconnect', 'Reconnect', 'Close tab')],
            'View': [('Find connection',), ('Expand all groups', 'Collapse all groups')],
            'Help': [('Help', 'About')],
        }
        for title, groups in contents.items():
            menu = self.menuBar().addMenu(self.tr(title))
            self.menus[title] = menu
            for index, group in enumerate(groups):
                if index:
                    menu.addSeparator()
                for name in group:
                    menu.addAction(self.actions[name])
        order = QMenu(self.tr('Order'), self.menus['Edit'])
        order.setIcon(action_icon(self, 'Sort alphabetically'))
        order.menuAction().setIconVisibleInMenu(True)
        self.menus['Edit'].insertMenu(self.actions['Duplicate'], order)
        for name in ('Move up', 'Move down', 'Sort alphabetically'):
            order.addAction(self.actions[name])
        self.menus['Edit'].insertActions(self.actions['Duplicate'], [self.actions[name] for name in ('Cut', 'Copy', 'Paste')])
        for name, key in [('Cut', 'Ctrl+X'), ('Copy', 'Ctrl+C'), ('Paste', 'Ctrl+V')]:
            action = self.actions[name]
            action.setShortcut(QKeySequence(key))
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            self.tree.addAction(action)
        self.menus['Session'].aboutToShow.connect(self.update_session_actions)
        workspace_menu = self.menus['Session'].addMenu(self.tr('Workspace'))
        def rebuild_workspace_menu():
            workspace_menu.clear()
            page = self.tabs.currentWidget()
            if page is not None:
                self.populate_workspace_menu(workspace_menu, page)
            else:
                for title in ('Split vertically', 'Split horizontally', 'Grid 2 × 2'):
                    workspace_menu.addAction(self.actions[title])
        workspace_menu.aboutToShow.connect(rebuild_workspace_menu)
        toggle = self.toolbar.toggleViewAction()
        toggle.setText(self.tr('Toolbar'))
        toggle.setIconVisibleInMenu(True)
        toggle.setIcon(action_icon(self, 'Toolbar'))
        toggle.setToolTip(self.tr('Show or hide the connection toolbar.'))
        self.menus['View'].addSeparator()
        self.menus['View'].addAction(toggle)
        self.actions['Toolbar'] = toggle
        tree_toggle = QAction(action_icon(self, 'Connection tree'), self.tr('Connection tree'), self)
        tree_toggle.setIconVisibleInMenu(True)
        tree_toggle.setCheckable(True)
        tree_toggle.setChecked(True)
        tree_toggle.setToolTip(self.tr('Show or hide the connections panel, including search and tree tools.'))
        tree_toggle.toggled.connect(self.set_tree_visible)
        self.menus['View'].addAction(tree_toggle)
        self.actions['Connection tree'] = tree_toggle
        local_toggle = QAction(action_icon(self, 'New local terminal'), self.tr('Local profiles'), self)
        local_toggle.setIconVisibleInMenu(True)
        local_toggle.setCheckable(True)
        local_toggle.setToolTip(self.tr('Show or hide the local terminal profiles in the connections panel.'))
        local_toggle.toggled.connect(self.local_tree.setVisible)
        self.menus['View'].addAction(local_toggle)
        self.actions['Local profiles'] = local_toggle
        status = QAction(action_icon(self, 'Status bar'), self.tr('Status bar'), self)
        status.setIconVisibleInMenu(True)
        status.setCheckable(True)
        status.setChecked(True)
        status.setToolTip(self.tr('Show or hide the current session status.'))
        status.toggled.connect(self.statusBar().setVisible)
        self.menus['View'].addAction(status)
        self.actions['Status bar'] = status
        # Keep ordinary control keys available to SSH/Telnet terminal programs.
        for title, key in [('New connection', 'Ctrl+N'), ('New group', 'Ctrl+Shift+N'),
                           ('Open database', 'Ctrl+O'), ('Find connection', 'Ctrl+F'), ('Help', 'F1')]:
            action = self.actions[title]
            action.setShortcut(QKeySequence(key))
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            self.tree.addAction(action)
            self.search.addAction(action)
        for title, key in [('Edit', 'F2'), ('Duplicate', 'Ctrl+D'), ('Delete', 'Del')]:
            action = self.actions[title]
            action.setShortcut(QKeySequence(key))
            action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            self.tree.addAction(action)
        self.actions['Exit'].setShortcut(QKeySequence('Ctrl+Shift+Q'))
        self.actions['Close tab'].setShortcut(QKeySequence('Ctrl+Shift+W'))
        self.actions['New database'].setToolTip(self.tr('Create and open a separate encrypted configuration database.'))
        self.actions['Disconnect'].setToolTip(self.tr('Disconnect the current session and keep its terminal tab.'))
        self.actions['Reconnect'].setToolTip(self.tr('Reconnect the stopped session using its current saved connection settings.'))
        self.actions['Close tab'].setToolTip(self.tr('Close the current tab and disconnect its session.'))
        self.actions['Exit'].setToolTip(self.tr('Exit UniRCm, disconnecting active sessions after confirmation.'))

    def add_tree_tools(self, layout):
        self.tree_tools = QWidget()
        bar = QHBoxLayout(self.tree_tools)
        bar.setContentsMargins(2, 2, 2, 2)
        bar.setSpacing(2)
        add = QToolButton()
        add.setText(self.tr('Add'))
        add.setIcon(action_icon(self, 'Add'))
        add.setToolTip(self.tr('Add a connection or a group here.'))
        add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(add)
        menu.addAction(self.actions['New connection'])
        menu.addAction(self.actions['New group'])
        add.setMenu(menu)
        self.tree_tool_buttons = {'Add': add}
        for title in ('Delete', 'Move up', 'Move down', 'Cut', 'Copy', 'Paste'):
            button = QToolButton()
            button.setDefaultAction(self.actions[title])
            self.tree_tool_buttons[title] = button
        for title, button in self.tree_tool_buttons.items():
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setIconSize(QSize(20, 20))
            button.setMinimumSize(30, 30)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setAccessibleName(self.tr(title))
            bar.addWidget(button, 1)
        self.actions['Cut'].setToolTip(self.tr('Cut the selected group or connection, then select a destination and paste.'))
        self.actions['Copy'].setToolTip(self.tr('Copy the selected connection.'))
        self.actions['Paste'].setToolTip(self.tr('Paste into the selected group, after the selected connection, or at root on empty space.'))
        layout.addWidget(self.tree_tools)
        cancel = QShortcut(QKeySequence('Escape'), self.tree)
        cancel.setContext(Qt.ShortcutContext.WidgetShortcut)
        cancel.activated.connect(self.cancel_tree_transfer)

    def cancel_tree_transfer(self):
        if self._tree_clipboard is not None:
            self._tree_clipboard = None
            self.refresh()

    def update_clipboard_actions(self):
        if 'Cut' not in self.actions:
            return
        selected = self.selected_item()
        self.actions['Cut'].setEnabled(selected is not None)
        self.actions['Copy'].setEnabled(self.selected() is not None)
        buffer = self._tree_clipboard
        valid = buffer is not None and not self.search.text().strip()
        if valid:
            key = (buffer['kind'], buffer['id'])
            valid = any(self.item_key(item) == key for item in self.tree_items())
            if valid and buffer['kind'] == 'folder':
                destination = self.tree.currentItem()
                if destination is not None and self.item_key(destination)[0] != 'folder':
                    destination = destination.parent()
                while destination is not None:
                    if self.item_key(destination) == key:
                        valid = False
                        break
                    destination = destination.parent()
        self.actions['Paste'].setEnabled(valid)

    def cut_tree_item(self):
        selected = self.selected_item()
        if selected is not None:
            self._tree_clipboard = dict(mode='cut', kind=selected.get('kind', 'profile'), id=selected['id'])
            self.refresh()

    def copy_tree_item(self):
        selected = self.selected()
        if selected is not None:
            self._tree_clipboard = dict(mode='copy', kind='profile', id=selected['id'])
            self.refresh()

    def paste_tree_item(self):
        self.update_clipboard_actions()
        if not self.actions['Paste'].isEnabled():
            return
        buffer = self._tree_clipboard
        selected = self.selected_item()
        folder_id = self.selected_folder_id()
        anchor = ('profile', selected['id']) if selected and selected.get('kind') != 'folder' else None
        try:
            if buffer['mode'] == 'cut':
                self.vault.move_tree_item(buffer['kind'], buffer['id'], folder_id, anchor, after=True)
                self._tree_clipboard = None
                self.refresh(selected_folder=buffer['id']) if buffer['kind'] == 'folder' else self.refresh(buffer['id'])
            else:
                new_id = self.vault.copy_profile(buffer['id'], folder_id, anchor, after=True)
                self.refresh(new_id)
        except ValueError as error:
            QMessageBox.warning(self, self.tr('Paste failed'), self.tr(str(error)))
        except Exception:
            QMessageBox.warning(self, self.tr('Paste failed'), self.tr('Unable to paste into the encrypted database.'))

    def new_database(self):
        self.switch_database(create=True)

    def set_tree_visible(self, visible):
        if visible:
            self.sidebar.show()
            self.tree_splitter.setSizes(self._tree_sizes)
            self.tree.setFocus()
        else:
            sizes = self.tree_splitter.sizes()
            if sizes[0] > 0:
                self._tree_sizes = sizes
            self.sidebar.hide()
            self.tree_splitter.setSizes([0, sum(sizes)])
            terminal = active_session(self.tabs.currentWidget())
            (terminal if terminal is not None else self.tabs).setFocus()

    def focus_search(self):
        self.actions['Connection tree'].setChecked(True)
        self.search.setFocus()
        self.search.selectAll()

    def show_help(self):
        from .help import HelpDialog
        HelpDialog(self).exec()

    def show_about(self):
        description = self.tr('SSH and Telnet connection manager with an embedded terminal and encrypted SQLCipher configuration.')
        QMessageBox.about(
            self, self.tr('About UniRCm'),
            f"<p><b>{APP_NAME} ({APP_SHORT_NAME})</b><br>"
            f"{self.tr('Version')}: {__version__}</p>"
            f"<p>{description}</p>"
            f"<p>{self.tr('License')}: GPL-3.0-or-later<br>"
            f"{self.tr('Email')}: <a href='mailto:victor@unirc.eu'>victor@unirc.eu</a><br>"
            f"{self.tr('Website')}: <a href='https://www.unirc.eu'>www.unirc.eu</a></p>",
        )

    def can_reconnect(self, terminal):
        return (terminal is not None and not terminal.is_running() and self.vault is not None
                and self.vault.profile_exists(terminal.profile_id))

    def update_session_actions(self):
        if self.vault is None or not hasattr(self, 'actions') or 'Close tab' not in self.actions:
            return
        page = self.tabs.currentWidget()
        terminal = active_session(page)
        self.actions['Disconnect'].setEnabled(terminal is not None and terminal.is_running())
        self.actions['Reconnect'].setEnabled(self.can_reconnect(terminal))
        self.actions['Close tab'].setEnabled(page is not None)

    def disconnect_current_session(self):
        terminal = active_session(self.tabs.currentWidget())
        if terminal is None or not terminal.is_running():
            return
        terminal.stop()
        self.set_session_title(terminal, f"{getattr(terminal, '_workspace_title', self.tr('Session'))} [{self.tr('disconnected')}]", self.tr('Session disconnected.'))
        self.update_session_status()

    def reconnect_current_session(self):
        terminal = active_session(self.tabs.currentWidget())
        if self.can_reconnect(terminal):
            self.reconnect_terminal(terminal)

    def close_current_tab(self):
        self.close_tab(self.tabs.currentIndex())

    def add_tree_actions(self):
        definitions = [
            ('Move up', lambda: self.shift_tree_item(-1), 'Move the selected item up within its group.'),
            ('Move down', lambda: self.shift_tree_item(1), 'Move the selected item down within its group.'),
            ('Sort alphabetically', self.sort_tree_level, 'Sort this level by name, with groups before connections.'),
            ('Expand all groups', self.tree.expandAll, 'Expand every group in the connection tree.'),
            ('Collapse all groups', self.collapse_all_groups, 'Collapse every group in the connection tree.')]
        for title, callback, tooltip in definitions:
            action = QAction(action_icon(self, title), self.tr(title), self)
            action.setIconVisibleInMenu(True)
            action.setToolTip(self.tr(tooltip))
            action.triggered.connect(callback)
            self.actions[title] = action
            self.tree.addAction(action)
        for title, key in [('Move up', 'Ctrl+Up'), ('Move down', 'Ctrl+Down')]:
            self.actions[title].setShortcut(QKeySequence(key))
            self.actions[title].setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.update_tree_actions()

    def update_tree_actions(self):
        if 'Move up' not in self.actions:
            return
        filtered = bool(self.search.text().strip())
        self.tree.setDragEnabled(not filtered)
        self.tree.setAcceptDrops(not filtered)
        item = self.tree.currentItem()
        parent = item.parent() or self.tree.invisibleRootItem() if item else None
        index = parent.indexOfChild(item) if parent else -1
        self.actions['Move up'].setEnabled(not filtered and index > 0)
        self.actions['Move down'].setEnabled(not filtered and index >= 0 and index < parent.childCount() - 1)
        for title in ('Sort alphabetically', 'Expand all groups', 'Collapse all groups'):
            self.actions[title].setEnabled(not filtered)
        data = self.selected_item()
        self.actions['Sort alphabetically'].setToolTip(self.tr('Sort the selected group contents by name, with groups before connections.') if data and data.get('kind') == 'folder' else self.tr('Sort this level by name, with groups before connections.'))

    def collapse_all_groups(self):
        current = self.tree.currentItem()
        if current is not None:
            while current.parent() is not None:
                current = current.parent()
            self.tree.setCurrentItem(current)
        self.tree.collapseAll()

    def shift_tree_item(self, direction):
        item = self.tree.currentItem()
        if item is None or self.search.text().strip():
            return
        parent = item.parent() or self.tree.invisibleRootItem()
        index = parent.indexOfChild(item)
        if not 0 <= index + direction < parent.childCount():
            return
        anchor = self.item_key(parent.child(index + direction))
        folder_id = parent.data(0, Qt.ItemDataRole.UserRole)['id'] if item.parent() else None
        self.move_item(self.selected_item(), folder_id, anchor, direction > 0)

    def sort_tree_level(self):
        if self.search.text().strip():
            return
        data = self.selected_item()
        parent_id = data['id'] if data and data.get('kind') == 'folder' else data.get('folder_id') if data else None
        try:
            self.vault.sort_tree_children(parent_id)
            self.refresh()
        except Exception:
            QMessageBox.warning(self, self.tr('Save failed'), self.tr('Unable to save tree ordering.'))

    def tree_scroll_changed(self, *_):
        if not self._restoring_tree:
            self._pending_tree_scroll = None
        self.schedule_tree_state()

    def schedule_tree_state(self, *_):
        if (not getattr(self, '_restoring_tree', True) and not getattr(self, '_locking', False)
                and self.vault is not None and not self.search.text().strip()):
            self.tree_state_timer.start(250)

    def save_tree_state(self):
        self.tree_state_timer.stop()
        if self.vault is None or self._restoring_tree:
            return
        expansion = self._filter_expansion if self._filter_expansion is not None else self.expanded_groups()
        selected = self._filter_selection if self._filter_expansion is not None else self.item_key(self.tree.currentItem())
        scroll = self._filter_scroll if self._filter_expansion is not None else self.tree.verticalScrollBar().value()
        if self._pending_tree_scroll is not None and self._pending_tree_scroll[0] is self.vault:
            scroll = self._pending_tree_scroll[1]
        try:
            self.vault.save_tree_view_state([key for key, expanded in expansion.items() if not expanded], selected, scroll)
        except Exception:
            self.statusBar().showMessage(self.tr('Unable to save tree view state.'))

    def restore_tree_state(self):
        self._restoring_tree = True
        state = self.vault.tree_view_state()
        collapsed = set(state.get('collapsed', []))
        selected = tuple(state['selected']) if state.get('selected') else None
        for item in self.tree_items():
            key = self.item_key(item)
            if key[0] == 'folder':
                item.setExpanded(key[1] not in collapsed)
            if key == selected:
                self.tree.setCurrentItem(item)
        self._pending_tree_scroll = (self.vault, state.get('scroll', 0))
        self._restoring_tree = False
        self.update_actions()
        if self.isVisible():
            self.restore_scroll_timer.start(0)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange) and hasattr(self, 'sidebar'):
            contrast_workspace(self.sidebar, self.tabs, self.palette())

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, '_pending_tree_scroll', None) is not None:
            self.restore_scroll_timer.start(0)

    def restore_tree_scroll(self):
        pending, self._pending_tree_scroll = self._pending_tree_scroll, None
        if pending is None or self.vault is not pending[0]:
            return
        if self.search.text().strip():
            self._filter_scroll = pending[1]
        else:
            self.tree.verticalScrollBar().setValue(pending[1])

    def switch_database(self, create=False):
        from .databases import DatabaseChooser
        chooser = DatabaseChooser(self.database_path, self, excluded_path=self.database_path)
        if create:
            chooser.create()
            result = chooser.exec() if chooser.unlock_panel is not None else chooser.result()
        else:
            result = chooser.exec()
        if result != QDialog.DialogCode.Accepted:
            chooser.deleteLater()
            return
        replacement, path = chooser.vault, chooser.path
        chooser.vault = None
        chooser.deleteLater()
        if not self.confirm_disconnect():
            replacement.close()
            return
        self.save_tree_state()
        self.dismiss_editors()
        while self.tabs.count():
            self.close_tab(0, confirm=False)
        try:
            self.vault.close()
        except Exception:
            replacement.close()
            QMessageBox.warning(self, self.tr('Database switch failed'), self.tr('Unable to close the current encrypted database.'))
            return
        self.vault, self.database_path = replacement, path
        self._tree_clipboard = None
        set_language(self.vault.language())
        self.tree.clear()
        self._filter_expansion = self._filter_selection = None
        self._filter_scroll = 0
        self.search.clear()
        self.update_window_title()
        self.inactivity_limit = self.vault.inactivity_minutes() * 60
        self.last_activity = monotonic()
        self.refresh()
        self.restore_tree_state()

    def database_settings(self):
        SettingsDialog(self.vault, self).exec()
        if self.vault is not None:
            set_language(self.vault.language())
            self.search.setPlaceholderText(self.tr('Search name, host or username…'))
            self.update_actions()
            self.update_session_status()
            self.inactivity_limit = self.vault.inactivity_minutes() * 60
            self.last_activity = monotonic()

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.MouseButtonDblClick
                and watched is getattr(self, 'tree_handle', None)
                and event.button() == Qt.MouseButton.LeftButton
                and not getattr(self, '_locking', True)):
            self.last_activity = monotonic()
            self.actions['Connection tree'].trigger()
            return True
        if not getattr(self, '_locking', True) and event.type() in (
                QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                QEvent.Type.MouseMove, QEvent.Type.Wheel, QEvent.Type.TouchBegin):
            self.last_activity = monotonic()
        return super().eventFilter(watched, event)

    def check_inactivity(self):
        if self.vault is None or self._locking or not self.inactivity_limit:
            return
        if monotonic() - self.last_activity < self.inactivity_limit:
            return
        self._locking = True
        self.dismiss_editors()
        QTimer.singleShot(0, lambda: self.lock_vault(automatic=True))

    def dismiss_editors(self):
        # Unwind active dialogs and discard hidden editors' credential snapshots.
        for dialog in self.findChildren(QDialog):
            for field in dialog.findChildren(QLineEdit):
                field.clear()
            if hasattr(dialog, 'profile'):
                dialog.profile.clear()
            dialog.reject()
            dialog.deleteLater()

    def manage_credentials(self):
        CredentialManager.open(self.vault, self)
        self.refresh()

    def update_window_title(self):
        name = self.database_path.name
        if len(name) > 40:
            name = name[:27] + '…' + name[-12:]
        # Qt appends the display name unless the title already ends with it.
        self.setWindowTitle(f'{name} — {APP_SHORT_NAME}')

    def update_session_status(self, *_):
        self.update_session_actions()
        self.update_window_title()
        terminal = active_session(self.tabs.currentWidget())
        self.session_status_label.show_session(getattr(terminal, 'session_status', None))

    def refresh(self, selected=None, selected_folder=None):
        if self.vault is None:
            return
        self.refresh_local_profiles()
        self.tree.setHeaderLabels([self.tr('Remote')])
        restoring = self._restoring_tree
        self._restoring_tree = True
        previous = self.item_key(self.tree.currentItem())
        positions = self.vault.tree_positions()
        expanded = self.expanded_groups()
        scroll = self.tree.verticalScrollBar().value()
        self.tree.clear()
        folders = self.vault.folders()
        items = {}
        for folder in folders:
            item = ConnectionItem([folder['name']])
            position = positions.get(('folder', folder['id']))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, (position is None, position or 0, 'folder', folder['name'].casefold(), folder['id']))
            item.setData(0, Qt.ItemDataRole.UserRole, dict(folder, kind='folder'))
            if self._tree_clipboard == dict(mode='cut', kind='folder', id=folder['id']):
                font = item.font(0)
                font.setItalic(True)
                item.setFont(0, font)
            appearance = folder.get('appearance', {})
            item.setIcon(0, group_icon(self, appearance.get('icon', 'folder')))
            if appearance.get('color'):
                item.setForeground(0, QColor(appearance['color']))
            items[folder['id']] = item
        for folder in folders:
            parent = items.get(folder['parent_id'])
            item = items[folder['id']]
            (parent.addChild if parent else self.tree.addTopLevelItem)(item)
        for profile in self.vault.profiles():
            item = ConnectionItem([profile['name']])
            position = positions.get(('profile', profile['id']))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, (position is None, position or 0, 'profile', profile['name'].casefold(), profile['id']))
            item.setData(0, Qt.ItemDataRole.UserRole, profile)
            if self._tree_clipboard == dict(mode='cut', kind='profile', id=profile['id']):
                font = item.font(0)
                font.setItalic(True)
                item.setFont(0, font)
            item.setIcon(0, connection_icon(profile.get('icon', 'terminal'), self.palette()))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            effective = self.vault.effective_profile(profile)
            item.setToolTip(0, f"{effective.get('protocol', 'ssh').upper()} — {effective['username']}@{effective['host']}:{effective['port']}")
            parent = items.get(profile['folder_id'])
            (parent.addChild if parent else self.tree.addTopLevelItem)(item)
            if selected == profile['id']:
                self.tree.setCurrentItem(item)
        self.tree.invisibleRootItem().sortChildren(0, Qt.SortOrder.AscendingOrder)
        for item in items.values():
            item.sortChildren(0, Qt.SortOrder.AscendingOrder)
        if selected_folder in items:
            self.tree.setCurrentItem(items[selected_folder])
        for folder_id, item in items.items():
            item.setExpanded(expanded.get(folder_id, True))
        explicit = selected is not None or selected_folder is not None
        if not explicit and previous:
            for item in self.tree_items():
                if self.item_key(item) == previous:
                    self.tree.setCurrentItem(item)
                    break
        if explicit and self.tree.currentItem():
            ancestor = self.tree.currentItem().parent()
            while ancestor:
                ancestor.setExpanded(True)
                ancestor = ancestor.parent()
        self.filter_tree()
        if explicit and self.tree.currentItem():
            self.tree.scrollToItem(self.tree.currentItem())
        else:
            self.tree.verticalScrollBar().setValue(scroll)
        self.update_actions()
        profiles = {profile['id']: profile for profile in self.vault.profiles()}
        for terminal in self.all_terminals():
            index = self.tabs.indexOf(terminal)
            profile = profiles.get(terminal.profile_id)
            if profile is None:
                continue
            effective = self.vault.effective_profile(profile)
            options = effective.get('terminal_options', {})
            if terminal.options != options:
                terminal.apply_options(options)
            color = QColor(effective.get('tab_color', ''))
            if not color.isValid():
                color = self.palette().windowText().color()
            self.tabs.set_terminal_color(terminal, color)
        self._restoring_tree = restoring
        self.schedule_tree_state()

    def selected_item(self):
        item = self.tree.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def tree_items(self):
        def walk(item):
            yield item
            for index in range(item.childCount()):
                yield from walk(item.child(index))
        for index in range(self.tree.topLevelItemCount()):
            yield from walk(self.tree.topLevelItem(index))

    @staticmethod
    def item_key(item):
        if item is None:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        return (data.get('kind', 'profile'), data['id'])

    def expanded_groups(self):
        return {item.data(0, Qt.ItemDataRole.UserRole)['id']: item.isExpanded()
                for item in self.tree_items() if item.data(0, Qt.ItemDataRole.UserRole).get('kind') == 'folder'}

    def filter_tree(self, *_):
        query = self.search.text().strip().casefold()
        if query and self._filter_expansion is None:
            self._filter_expansion = self.expanded_groups()
            self._filter_selection = self.item_key(self.tree.currentItem())
            self._filter_scroll = self.tree.verticalScrollBar().value()
        def visit(item, parent_match=False):
            data = item.data(0, Qt.ItemDataRole.UserRole)
            effective = self.vault.effective_profile(data) if data.get('kind') != 'folder' else data
            match = not query or any(query in str(effective.get(key, '')).casefold() for key in ('name', 'host', 'username'))
            visible = match or parent_match
            for index in range(item.childCount()):
                visible = visit(item.child(index), parent_match or match) or visible
            item.setHidden(not visible)
            if query and visible and item.childCount():
                item.setExpanded(True)
            return visible
        for index in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(index))
        if not query and self._filter_expansion is not None:
            for item in self.tree_items():
                key = self.item_key(item)
                if key[0] == 'folder':
                    item.setExpanded(self._filter_expansion.get(key[1], True))
            self._filter_expansion = None
            for item in self.tree_items():
                if self.item_key(item) == self._filter_selection:
                    self.tree.setCurrentItem(item)
                    break
            self.tree.verticalScrollBar().setValue(self._filter_scroll)
            self._filter_selection = None
        if self.tree.currentItem() and self.tree.currentItem().isHidden():
            self.tree.setCurrentItem(None)
        self.update_actions()
        self.schedule_tree_state()

    def update_actions(self):
        if self.vault is None or not hasattr(self, 'actions'):
            return
        data = self.selected_item()
        self.update_tree_actions()
        self.update_session_actions()
        self.update_clipboard_actions()
        for title in ('Edit', 'Delete'):
            self.actions[title].setEnabled(data is not None)
        for title in ('Connect', 'Duplicate'):
            self.actions[title].setEnabled(self.selected() is not None)
        self.actions['New group'].setText(self.tr('New subgroup') if self.selected_folder_id() is not None else self.tr('New group'))
        self.actions['Edit'].setText(self.tr('Group properties…') if data and data.get('kind') == 'folder' else self.tr('Edit'))
        self.actions['Edit'].setToolTip(self.tr('Edit selected group properties') if data and data.get('kind') == 'folder' else self.tr('Edit selected connection'))

    def tree_context_menu(self, position):
        item = self.tree.itemAt(position)
        self.tree.setCurrentItem(item)
        if item is None:
            self.tree.clearSelection()
        self.update_actions()
        menu = QMenu(self.tree)
        new = menu.addMenu(action_icon(self, 'New'), self.tr('New'))
        for title in ('New connection', 'New group'):
            new.addAction(self.actions[title])
        if item:
            if self.selected():
                menu.addAction(self.actions['Connect'])
                menu.addSeparator()
            menu.addAction(self.actions['Edit'])
            if self.selected():
                menu.addAction(self.actions['Duplicate'])
            menu.addSeparator()
            for title in ('Cut', 'Copy', 'Paste'):
                menu.addAction(self.actions[title])
            menu.addSeparator()
            menu.addAction(self.actions['Delete'])
        else:
            menu.addAction(self.actions['Paste'])
        order = menu.addMenu(action_icon(self, 'Sort alphabetically'), self.tr('Order'))
        for title in ('Move up', 'Move down', 'Sort alphabetically', 'Expand all groups', 'Collapse all groups'):
            order.addAction(self.actions[title])
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def duplicate_profile(self):
        profile = self.selected()
        if profile is None:
            return
        try:
            profile_id = self.vault.copy_profile(profile['id'], profile.get('folder_id'), ('profile', profile['id']), after=True)
            self.refresh(profile_id)
        except Exception:
            QMessageBox.warning(self, 'Duplicate failed', 'Unable to duplicate connection in the encrypted database.')

    def selected(self):
        data = self.selected_item()
        return data if data and data.get('kind') != 'folder' else None

    def selected_folder_id(self):
        data = self.selected_item()
        return data['id'] if data and data.get('kind') == 'folder' else (data.get('folder_id') if data else None)

    def new_folder(self):
        self.group_dialog(dict(name='', parent_id=self.selected_folder_id()))

    def group_dialog(self, data):
        def save(name, parent_id, defaults):
            return self.vault.save_folder(name, parent_id, data.get('id'), defaults=defaults, appearance=dialog.appearance())
        dialog = GroupDefaultsDialog(data, self, self.vault.folders(), save_callback=save)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh(selected_folder=dialog.folder_id)

    def save_folder(self, name, parent_id, folder_id=None):
        try:
            folder_id = self.vault.save_folder(name, parent_id, folder_id)
            self.refresh(selected_folder=folder_id)
        except ValueError as error:
            QMessageBox.warning(self, 'Invalid group', str(error))
        except Exception:
            QMessageBox.warning(self, 'Save failed', 'Unable to save group to the encrypted database.')

    def move_item(self, data, folder_id, anchor=None, after=False):
        try:
            kind = data.get('kind', 'profile')
            self.vault.move_tree_item(kind, data['id'], folder_id, anchor, after)
            self.refresh(selected_folder=data['id']) if kind == 'folder' else self.refresh(data['id'])
        except ValueError as error:
            QMessageBox.warning(self, self.tr('Move failed'), self.tr(str(error)))
        except Exception:
            QMessageBox.warning(self, self.tr('Move failed'), self.tr('Unable to move the connection.'))

    def edit_group_defaults(self):
        data = self.selected_item()
        if not data or data.get('kind') != 'folder':
            self.statusBar().showMessage('Select a group to edit SSH defaults.')
            return
        self.group_dialog(data)

    def new_profile(self):
        self.edit_dialog(None)

    def edit_profile(self):
        data = self.selected_item()
        if data and data.get('kind') == 'folder':
            self.group_dialog(data)
        elif data:
            self.edit_dialog(data)

    def edit_dialog(self, profile):
        dialog = ProfileDialog(profile, self, self.vault.folders(), self.selected_folder_id(), save_callback=self.vault.save)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh(dialog.profile['id'])

    def delete_profile(self):
        data = self.selected_item()
        if data and data.get('kind') == 'folder':
            if QMessageBox.question(self, 'Delete group', f"Delete {data['name']}? Connections and subgroups will move to its parent.") == QMessageBox.StandardButton.Yes:
                try:
                    self.vault.delete_folder(data['id'])
                    if self._tree_clipboard and (self._tree_clipboard['kind'], self._tree_clipboard['id']) == ('folder', data['id']):
                        self._tree_clipboard = None
                    self.refresh(selected_folder=data['parent_id'])
                except Exception:
                    QMessageBox.warning(self, 'Delete failed', 'Unable to delete group.')
            return
        profile = self.selected()
        if profile and QMessageBox.question(self, 'Delete connection', f"Delete {profile['name']}?") == QMessageBox.StandardButton.Yes:
            try:
                self.vault.delete(profile['id'])
                if self._tree_clipboard and (self._tree_clipboard['kind'], self._tree_clipboard['id']) == ('profile', profile['id']):
                    self._tree_clipboard = None
                self.refresh()
            except Exception:
                QMessageBox.warning(self, 'Delete failed', 'Unable to delete connection.')

    def connect_profile(self):
        profile = self.selected()
        if not profile:
            return
        self.open_profile(profile)

    def open_profile(self, profile):
        try:
            profile = self.vault.effective_profile(profile)
            if profile.get('protocol') == 'rdp':
                from remote_manager.protocols.rdp import RdpSession
                terminal = RdpSession(profile, self)
            elif profile.get('protocol') == 'vnc':
                from remote_manager.protocols.vnc import VncSession
                terminal = VncSession(profile, self)
            else:
                private_key = self.vault.ssh_private_key(profile) if profile.get('imported_key_name') else None
                terminal = Terminal(profile, self, private_key=private_key) if private_key is not None else Terminal(profile, self)
        except Exception as error:
            QMessageBox.warning(self, self.tr('Connection failed'), str(error))
            return
        return self.add_session_tab(terminal, profile)

    def refresh_local_profiles(self, selected=None):
        current = self.local_tree.currentItem()
        if selected is None and current is not None:
            selected = current.data(0, Qt.ItemDataRole.UserRole)
        self.local_tree.clear()
        self.local_tree.setHeaderLabels([self.tr('Local')])
        profiles = sorted(self.vault.local_terminal_profiles(), key=lambda profile: profile['name'].casefold())
        for profile in [dict(id=None, name=self.tr('Local terminal')), *profiles]:
            item = QTreeWidgetItem(self.local_tree, [profile['name']])
            item.setData(0, Qt.ItemDataRole.UserRole, profile['id'])
            item.setIcon(0, action_icon(self, 'New local terminal'))
            item.setToolTip(0, self.tr('Open this local terminal or drag it onto an empty workspace pane.'))
            if profile['id'] == selected:
                self.local_tree.setCurrentItem(item)

    def local_tree_menu(self, position):
        item = self.local_tree.itemAt(position)
        menu = QMenu(self.local_tree)
        add = menu.addAction(action_icon(self, 'New connection'), self.tr('Add local profile'),
                             lambda: self.edit_local_profile())
        add.setToolTip(self.tr('Save a local terminal with a working directory and startup commands.'))
        menu.setToolTipsVisible(True)
        if item is not None:
            profile_id = item.data(0, Qt.ItemDataRole.UserRole)
            menu.addSeparator()
            menu.addAction(action_icon(self, 'New local terminal'), self.tr('Open local terminal'),
                           lambda: self.open_local_terminal(profile_id=profile_id))
            if profile_id is not None:
                menu.addAction(action_icon(self, 'Edit'), self.tr('Edit local profile'),
                               lambda: self.edit_local_profile(profile_id))
                menu.addAction(action_icon(self, 'Delete'), self.tr('Delete local profile'),
                               lambda: self.delete_local_profile(profile_id))
        menu.exec(self.local_tree.viewport().mapToGlobal(position))

    def edit_local_profile(self, profile_id=None):
        vault = self.vault
        profile = next((p for p in vault.local_terminal_profiles() if p['id'] == profile_id), {})
        if profile_id is not None and not profile:
            return
        saved_id = None

        def save(name, directory, commands):
            nonlocal saved_id
            saved_id = vault.save_local_terminal_profile(name, directory, commands, profile_id)

        dialog = LocalTerminalProfileDialog(profile, save, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and self.vault is vault:
            self.refresh_local_profiles(saved_id)
        if not isdeleted(dialog):
            dialog.deleteLater()

    def delete_local_profile(self, profile_id):
        vault = self.vault
        if QMessageBox.question(self, self.tr('Delete local profile'), self.tr('Delete this local terminal profile?'),
                                defaultButton=QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes and self.vault is vault:
            vault.delete_local_terminal_profile(profile_id)
            self.refresh_local_profiles()

    def open_local_terminal(self, *, profile_id=None, workspace=None, slot=None):
        if self.vault is None:
            return
        if workspace is None:
            workspace = self.tabs.currentWidget()
        if isinstance(workspace, SessionWorkspace):
            vacant = [pane.slot for pane in workspace.empty_panes]
            if slot is not None and slot not in vacant:
                return
            if slot is None and vacant:
                slot = vacant[0]
        profile = dict(name=self.tr('Local terminal'), protocol='local')
        if profile_id is not None:
            saved = next((p for p in self.vault.local_terminal_profiles() if p['id'] == profile_id), None)
            if saved is None:
                return
            profile.update(name=saved['name'], directory=saved['directory'], commands=saved['commands'])
        try:
            terminal = Terminal(profile, self)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, self.tr('Unable to start local terminal'), str(error))
            return
        self.add_session_tab(terminal, profile)
        if slot is not None:
            self.move_to_workspace(terminal, workspace, workspace.mode, slot)
        return terminal

    def add_session_tab(self, terminal, profile):
        terminal.session_status.changed.connect(self.update_session_status)
        if hasattr(terminal, 'public_key_install_finished'):
            terminal.public_key_install_finished.connect(self.public_key_install_result)
        if hasattr(terminal, 'appearance_requested'):
            terminal.appearance_requested.connect(lambda term=terminal: self.terminal_appearance(term))
        terminal._workspace_title = profile['name']
        terminal._workspace_icon = connection_icon(profile.get('icon', 'terminal'), self.palette())
        index = self.tabs.addTab(terminal, terminal._workspace_icon, profile['name'])
        color = QColor(profile.get('tab_color', ''))
        if color.isValid():
            self.tabs.set_base_color(index, color)
        self.tabs.watch_terminal(terminal)
        protocol = terminal.session_status.protocol
        if protocol == 'LOCAL':
            terminal._workspace_tooltip = profile['name']
        else:
            warning = self.tr(' — Unencrypted connection') if protocol == 'TELNET' else ''
            terminal._workspace_tooltip = f"{protocol} — {profile['username']}@{profile['host']}:{profile['port']}{warning}"
        if protocol == 'RDP':
            terminal._workspace_tooltip += self.tr(' — Embedded desktop') if terminal.embedded else self.tr(' — External window')
        self.tabs.setTabToolTip(index, terminal._workspace_tooltip)
        terminal.exited.connect(lambda code, term=terminal, name=profile['name']: self.session_exited(term, name, code))
        self.tabs.setCurrentIndex(index)
        terminal.setFocus()
        self.update_session_status()
        return terminal

    def install_vault_public_key(self, terminal):
        vault = self.vault
        if vault is None or not terminal.can_install_public_key():
            return
        try:
            profiles = vault.profiles(terminal.profile_id) if terminal.profile_id is not None else []
            private_key = vault.ssh_private_key(profiles[0]) if profiles else None
            if private_key is None:
                self.statusBar().showMessage(self.tr('Import a private key into this SSH profile first.'), 7000)
                return
            public_key, fingerprint = public_key_from_private(private_key)
            del private_key
        except (ValueError, OSError):
            self.statusBar().showMessage(self.tr('Unable to derive the public key from the imported OpenSSH key.'), 7000)
            return

        title = self.tr('Install public key…')
        status = terminal.session_status
        host = f'{status.host} [{status.port}]'
        target = f'{status.username}@{host}' if status.username else host
        message = QMessageBox(self)
        message.setWindowTitle(title)
        message.setTextFormat(Qt.TextFormat.PlainText)
        message.setText(self.tr('Install this public key in ~/.ssh/authorized_keys for the active SSH account on %1?').replace('%1', target))
        message.setInformativeText(fingerprint)
        install = message.addButton(self.tr('Install public key'), QMessageBox.ButtonRole.AcceptRole)
        install.setIcon(action_icon(self, 'Install public key…'))
        install.setToolTip(self.tr('Authorize this public key for future SSH logins.'))
        cancel = message.addButton(self.tr('Cancel'), QMessageBox.ButtonRole.RejectRole)
        cancel.setIcon(action_icon(self, 'Cancel'))
        cancel.setToolTip(self.tr('Cancel'))
        message.setDefaultButton(cancel)
        message.exec()
        if message.clickedButton() is install and self.vault is vault and not isdeleted(terminal):
            if terminal.install_public_key(public_key):
                self.statusBar().showMessage(self.tr('Installing public key…'), 10000)

    def public_key_install_result(self, status):
        message = {
            'installed': 'Public key installed in ~/.ssh/authorized_keys.',
            'exists': 'This public key is already authorized on the server.',
            'failed': 'Public key installation could not be confirmed. Check the SSH session and remote authorized_keys.',
        }[status]
        self.statusBar().showMessage(self.tr(message), 10000)

    def terminal_appearance(self, terminal):
        def save_options(options):
            profile = next((p for p in self.vault.profiles() if p['id'] == terminal.profile_id), None)
            if profile is None:
                raise ValueError('Connection no longer exists.')
            profile['terminal_options'] = options
            profile['ssh_modes'] = dict(profile.get('ssh_modes', {}), terminal_options='override')
            self.vault.save(profile)
            self.refresh()

        callback = None if terminal.session_status.protocol == 'LOCAL' else save_options
        dialog = TerminalAppearanceDialog(terminal, callback, self)
        dialog.exec()
        terminal.setFocus()

    def session_exited(self, terminal, name, code):
        index = self.tabs.indexOf(terminal)
        if index >= 0:
            if terminal.session_status.protocol == 'TELNET':
                state = self.tr('disconnected') if code == 0 else self.tr('error')
                self.set_session_title(terminal, f'{name} [{state}]')
                self.set_session_title(terminal, terminal._workspace_title, self.tr('Telnet connection closed') if code == 0 else self.tr('Telnet connection error'))
            else:
                self.set_session_title(terminal, f'{name} [exit {code}]')
                self.set_session_title(terminal, terminal._workspace_title, f'{terminal.session_status.protocol} — process exited with code {code}')
            self.update_session_status()

    def all_terminals(self):
        return [term for i in range(self.tabs.count()) for term in sessions(self.tabs.widget(i))]

    def set_session_title(self, terminal, title, tooltip=None):
        terminal._workspace_title = title
        if tooltip is not None:
            terminal._workspace_tooltip = tooltip
        index = self.tabs.indexOf(terminal)
        page = self.tabs.widget(index)
        if isinstance(page, SessionWorkspace):
            page.panels[terminal][1].set_session_tooltip(getattr(terminal, '_workspace_tooltip', ''))
            page.activate(page.active)
        elif index >= 0:
            self.tabs.setTabText(index, title)
            self.tabs.setTabToolTip(index, getattr(terminal, '_workspace_tooltip', ''))

    def apply_workspace_layout(self, mode):
        self.ensure_workspace(self.tabs.currentWidget()).arrange(mode)

    def workspace_drop_profile(self, source):
        if source is not self.tree or len(self.tree.selectedItems()) != 1:
            return None
        data = self.tree.selectedItems()[0].data(0, Qt.ItemDataRole.UserRole)
        if data and data.get('kind') != 'folder':
            return next((p for p in self.vault.profiles() if p['id'] == data['id']), None)
        return None

    def fill_workspace_drop(self, workspace, source, slot):
        if source is self.local_tree and len(self.local_tree.selectedItems()) == 1:
            item = self.local_tree.selectedItems()[0]
            self.open_local_terminal(profile_id=item.data(0, Qt.ItemDataRole.UserRole), workspace=workspace, slot=slot)
            return
        profile = self.workspace_drop_profile(source)
        if profile is not None and slot not in workspace.positions.values():
            self.add_workspace_connection(workspace, workspace.mode, profile, slot)

    def drop_session_on_tab(self, terminal, target):
        self.move_to_workspace(terminal, target, getattr(target, 'mode', 'side'))

    def populate_empty_pane_menu(self, workspace, menu, slot):
        for terminal in self.all_terminals():
            if terminal not in workspace.terminals and terminal.is_running():
                menu.addAction(terminal._workspace_icon, terminal._workspace_title,
                               lambda checked=False, t=terminal: self.move_to_workspace(t, workspace, workspace.mode, slot))
        if not menu.actions():
            menu.addAction(self.tr('No other active sessions')).setEnabled(False)

    def ensure_workspace(self, page):
        if isinstance(page, SessionWorkspace):
            return page
        if page is None:
            index = self.tabs.count()
            title, icon = self.tr('Workspace'), action_icon(self, 'Grid 2 × 2')
        else:
            index = self.tabs.indexOf(page)
            title, icon = self.tabs.tabText(index), self.tabs.tabIcon(index)
            self.tabs.take_page(index)
        workspace = SessionWorkspace(keep_empty=page is None)
        workspace.accepts_drop = lambda source: (
            (source is self.local_tree and len(self.local_tree.selectedItems()) == 1)
            or self.workspace_drop_profile(source) is not None
        )
        workspace.accepts_session_drop = lambda terminal: self.tabs.can_move_session(terminal, workspace)
        workspace.empty_menu_requested.connect(lambda menu, slot: self.populate_empty_pane_menu(workspace, menu, slot))
        workspace.connection_dropped.connect(lambda source, slot: self.fill_workspace_drop(workspace, source, slot))
        workspace.session_dropped.connect(lambda terminal, slot: self.move_to_workspace(terminal, workspace, workspace.mode, slot))
        workspace.active_changed.connect(self.update_session_status)
        workspace.close_requested.connect(self.close_pane)
        workspace.detach_requested.connect(self.detach_terminal)
        self.tabs.insertTab(index, workspace, icon, title)
        self.tabs.setTabToolTip(index, '')
        if page is not None:
            workspace.add_terminal(page)
        self.tabs.setCurrentWidget(workspace)
        return workspace

    def move_to_workspace(self, terminal, target, mode, slot=None):
        if not self.tabs.can_move_session(terminal, target):
            return
        workspace = self.ensure_workspace(target)
        if slot is not None and slot in workspace.positions.values():
            return
        source = self.tabs.widget(self.tabs.indexOf(terminal))
        if isinstance(source, SessionWorkspace):
            source.take_terminal(terminal)
            if not source.terminals and not source.keep_empty:
                self.tabs.take_page(self.tabs.indexOf(source))
                source.deleteLater()
        else:
            self.tabs.take_page(self.tabs.indexOf(terminal))
        workspace.add_terminal(terminal, mode, slot)
        self.tabs.setCurrentWidget(workspace)
        terminal.setFocus()
        self.tabs._paint(terminal)

    def detach_terminal(self, terminal):
        workspace = self.tabs.widget(self.tabs.indexOf(terminal))
        if not isinstance(workspace, SessionWorkspace):
            return
        workspace.take_terminal(terminal)
        if not workspace.terminals and not workspace.keep_empty:
            self.tabs.take_page(self.tabs.indexOf(workspace))
            workspace.deleteLater()
        index = self.tabs.addTab(terminal, terminal._workspace_icon, terminal._workspace_title)
        self.tabs.setTabToolTip(index, terminal._workspace_tooltip)
        self.tabs.setCurrentIndex(index)
        terminal.setFocus()
        self.tabs._paint(terminal)

    def close_pane(self, terminal, confirm=True):
        page = self.tabs.widget(self.tabs.indexOf(terminal))
        if not isinstance(page, SessionWorkspace):
            self.close_tab(self.tabs.indexOf(terminal), confirm)
            return
        if confirm and terminal.is_running() and QMessageBox.question(
                self, self.tr('Close pane'), self.tr('Disconnect and close this pane?'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        page = self.tabs.widget(self.tabs.indexOf(terminal))
        if not isinstance(page, SessionWorkspace) or terminal not in page.terminals:
            return
        terminal.stop()
        self.tabs.unwatch_terminal(terminal)
        page.take_terminal(terminal)
        terminal.deleteLater()
        if not page.terminals and not page.keep_empty:
            self.tabs.take_page(self.tabs.indexOf(page))
            page.deleteLater()
        self.update_session_status()

    def add_workspace_connection(self, page, mode, profile, slot=None):
        if self.tabs.indexOf(page) < 0 or len(sessions(page)) >= 4:
            return
        terminal = self.open_profile(profile)
        if terminal is not None:
            self.move_to_workspace(terminal, page, mode, slot)

    def rename_workspace(self, page):
        index = self.tabs.indexOf(page)
        name, ok = QInputDialog.getText(self, self.tr('Rename tab'), self.tr('Name'), text=self.tabs.tabText(index))
        if ok and name.strip() and self.tabs.indexOf(page) >= 0:
            self.tabs.setTabText(self.tabs.indexOf(page), name.strip())
            self.update_window_title()

    def populate_workspace_menu(self, menu, page):
        def action(target, title, callback):
            result = target.addAction(action_icon(self, title), self.tr(title), callback)
            result.setIconVisibleInMenu(True)
            return result
        action(menu, 'Rename tab', lambda: self.rename_workspace(page))
        layout_menu = menu.addMenu(action_icon(self, 'Move'), self.tr('Layout'))
        layouts = QActionGroup(layout_menu)
        layouts.setExclusive(True)
        for title, mode in [('Side by side', 'side'), ('Stacked', 'stack'), ('Grid 2 × 2', 'grid')]:
            item = action(layout_menu, title, lambda checked=False, mode=mode: self.ensure_workspace(page).arrange(mode))
            item.setCheckable(True)
            item.setChecked(mode == getattr(page, 'mode', 'side'))
            layouts.addAction(item)
        add = menu.addMenu(self.tr('Add connection'))
        add.setEnabled(len(sessions(page)) < 4)
        for profile in self.vault.profiles():
            add.addAction(connection_icon(profile.get('icon', 'terminal'), self.palette()), profile['name'],
                          lambda checked=False, p=profile: self.add_workspace_connection(page, getattr(page, 'mode', 'side'), p))
        existing = menu.addMenu(self.tr('Move open session here'))
        candidates = [term for term in self.all_terminals() if term not in sessions(page)]
        existing.setEnabled(bool(candidates) and len(sessions(page)) < 4)
        for terminal in candidates:
            existing.addAction(terminal._workspace_icon, terminal._workspace_title,
                               lambda checked=False, t=terminal: self.move_to_workspace(t, page, getattr(page, 'mode', 'side')))
        if isinstance(page, SessionWorkspace):
            action(menu, 'Detach active pane', lambda: self.detach_terminal(page.active)).setEnabled(page.active is not None)
            action(menu, 'Close active pane', lambda: self.close_pane(page.active)).setEnabled(page.active is not None)

    def tab_context_menu(self, position):
        index = self.tabs.tabBar().tabAt(position)
        if index < 0:
            return
        page = self.tabs.widget(index)
        self.tabs.setCurrentIndex(index)
        terminal = active_session(page)
        menu = QMenu(self.tabs)
        menu.addAction(self.actions['Close tab'])
        reconnect = menu.addAction(action_icon(self, 'Reconnect'), self.tr('Reconnect'), lambda: self.reconnect_terminal(terminal))
        reconnect.setEnabled(self.can_reconnect(terminal))
        if hasattr(terminal, 'can_install_public_key') and terminal.session_status.protocol == 'SSH':
            title = 'Install public key…'
            install = menu.addAction(action_icon(self, title), self.tr(title),
                                     lambda: self.install_vault_public_key(terminal))
            install.setEnabled(terminal.can_install_public_key())
            install.setToolTip(self.tr('Authorize the public key from this profile’s vault on the connected server.'))
            menu.setToolTipsVisible(True)
        menu.addSeparator()
        self.populate_workspace_menu(menu, page)
        menu.exec(self.tabs.tabBar().mapToGlobal(position))

    def reconnect_terminal(self, terminal):
        if terminal.is_running():
            return
        profile = next((p for p in self.vault.profiles() if p['id'] == terminal.profile_id), None)
        if profile is None:
            return
        page = self.tabs.widget(self.tabs.indexOf(terminal))
        position = page.terminals.index(terminal) if isinstance(page, SessionWorkspace) else 0
        slot = page.positions[terminal] if isinstance(page, SessionWorkspace) else None
        replacement = self.open_profile(profile)
        if replacement is not None:
            if isinstance(page, SessionWorkspace):
                mode = page.mode
                self.close_pane(terminal, confirm=False)
                if self.tabs.indexOf(page) >= 0:
                    self.move_to_workspace(replacement, page, mode, slot)
                    page.terminals.remove(replacement)
                    page.terminals.insert(position, replacement)
                    page.arrange(mode)
                    replacement.setFocus()
            else:
                index = self.tabs.indexOf(terminal)
                self.close_tab(index, confirm=False)
                if index >= 0:
                    self.tabs.tabBar().moveTab(self.tabs.indexOf(replacement), index)

    def close_tab(self, index, confirm=True):
        terminal = self.tabs.widget(index)
        if terminal is None:
            return
        if confirm and any(term.is_running() for term in sessions(terminal)):
            answer = QMessageBox.question(
                self, self.tr('Close tab'),
                self.tr('Disconnect all active sessions in this tab and close it?'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        # A modal dialog can process tab changes: resolve the terminal again.
        index = self.tabs.indexOf(terminal)
        if index < 0:
            return
        for term in sessions(terminal):
            term.stop()
        self.tabs.removeTab(index)
        terminal.deleteLater()

    def confirm_disconnect(self):
        active = any(term.is_running() for i in range(self.tabs.count()) for term in sessions(self.tabs.widget(i)))
        return not active or QMessageBox.question(self, 'Disconnect sessions', 'Disconnect all active sessions?') == QMessageBox.StandardButton.Yes

    def lock_vault(self, automatic=False):
        if self.vault is None:
            return
        if not automatic and not self.confirm_disconnect():
            return
        self._locking = True
        self._tree_clipboard = None
        self.save_tree_state()
        self.dismiss_editors()
        while self.tabs.count():
            self.close_tab(0, confirm=False)
        self.search.clear()
        self._filter_expansion = None
        self._filter_selection = None
        self.tree.clear()
        self.local_tree.clear()
        self.vault.close()
        self.vault = None
        self._locked_workspace = self.takeCentralWidget()
        self._locked_workspace.setParent(self)
        self._locked_workspace.hide()
        self._locked_chrome = [(widget, widget.isVisible()) for widget in
                               (self.menuBar(), self.toolbar, self.statusBar())]
        for widget, _ in self._locked_chrome:
            widget.hide()
        # QActions retain shortcuts even when their menu is hidden.
        self._locked_actions = [(action, action.isEnabled()) for action in self.findChildren(QAction)]
        self._locked_shortcuts = [(shortcut, shortcut.isEnabled()) for shortcut in self.findChildren(QShortcut)]
        for action, _ in self._locked_actions + self._locked_shortcuts:
            action.setEnabled(False)
        page = QWidget()
        style_surface(page)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.addWidget(brand_header(page, self.tr('Database locked')))
        panel = self.unlock_panel = VaultUnlockPanel(self.database_path, page)
        cancel = panel.buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText(self.tr('Exit'))
        cancel.setProperty('unircmText', 'Exit')
        cancel.setIcon(action_icon(self, 'Exit'))
        cancel.setToolTip(self.tr('Close the application.'))
        panel.cancelled.connect(self.close)
        panel.unlocked.connect(self.finish_unlock)
        layout.addWidget(panel, 1)
        self.setCentralWidget(page)
        self.show()
        panel.password.setFocus()

    def finish_unlock(self, vault):
        self.vault = vault
        locked_page = self.takeCentralWidget()
        self.unlock_panel.clear()
        self.unlock_panel = None
        self.setCentralWidget(self._locked_workspace)
        self._locked_workspace.show()
        self._locked_workspace = None
        locked_page.deleteLater()
        for action, enabled in self._locked_actions + self._locked_shortcuts:
            if not isdeleted(action):
                action.setEnabled(enabled)
        for widget, visible in self._locked_chrome:
            widget.setVisible(visible)
        self._locked_actions = self._locked_shortcuts = self._locked_chrome = []
        set_language(self.vault.language())
        self.inactivity_limit = self.vault.inactivity_minutes() * 60
        self.last_activity = monotonic()
        self._locking = False
        self.refresh()
        self.restore_tree_state()
        self.update_session_status()
        self.search.setFocus()

    def closeEvent(self, event):
        if self.unlock_panel is not None:
            self.unlock_panel.clear()
        if not self.confirm_disconnect():
            event.ignore()
            return
        while self.tabs.count():
            self.close_tab(0, confirm=False)
        self._locking = True
        self._tree_clipboard = None
        self.save_tree_state()
        self.dismiss_editors()
        QApplication.instance().removeEventFilter(self)
        self.restore_scroll_timer.stop()
        self._pending_tree_scroll = None
        self.idle_timer.stop()
        if self.vault is not None:
            self.vault.close()
            self.vault = None
        event.accept()
