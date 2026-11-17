"""Advanced SSH editor with validated additional OpenSSH options."""
from PyQt6.QtWidgets import QWidget, QFormLayout, QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTableWidget, QHeaderView, QCheckBox, QPushButton, QHBoxLayout, QLabel
from .icons import action_icon
from .forms import section
from remote_manager.ssh_options import ADVANCED_DEFAULTS


class AdvancedSSHOptions(QWidget):
    def __init__(self, options=None, parent=None):
        super().__init__(parent)
        values = {**ADVANCED_DEFAULTS, **(options or {})}
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        self.fields = {}
        labels = dict(proxy_jump='Jump host', alive_interval='Keepalive interval (seconds)',
                      alive_count='Unanswered keepalives', identities_only='Use configured identities only',
                      address_family='IP version', compression='Compression', extra_options='Additional SSH options')
        tips = dict(proxy_jump='Optional [user@]host[:port]; separate multiple jump hosts with commas. Blank uses OpenSSH configuration.',
                    alive_interval='Send a keepalive after this many seconds without server data. Zero disables keepalives.',
                    alive_count='Disconnect after this many unanswered keepalives.',
                    identities_only='Restrict authentication to configured identities instead of trying every agent key.',
                    address_family='Choose automatic addressing, IPv4 or IPv6.',
                    compression='Compression can help on slow links; it is usually unnecessary on fast networks.',
                    extra_options='Use -o Name=value, separated by spaces or newlines. Examples:\n-o HostKeyAlgorithms=+ssh-rsa\n-o KexAlgorithms=+diffie-hellman-group14-sha1\n-o PubkeyAcceptedAlgorithms=+ssh-rsa\nEnable legacy algorithms only when required by this server. The + adds to modern defaults.\nSupported: KexAlgorithms, HostKeyAlgorithms, PubkeyAcceptedAlgorithms, Ciphers, MACs, RekeyLimit, IPQoS, TCPKeepAlive, NumberOfPasswordPrompts, FingerprintHash.\nPasswords, commands, configuration files and session-management overrides are not accepted.')
        headings = {'proxy_jump': 'Routing', 'alive_interval': 'Connection health',
                    'identities_only': 'Authentication and transport', 'extra_options': 'OpenSSH options'}
        for key, label in labels.items():
            if key in headings:
                section(form, headings[key])
            if key == 'extra_options':
                field = QPlainTextEdit(values[key])
                field.setMaximumHeight(100)
                field.setPlaceholderText('-o HostKeyAlgorithms=+ssh-rsa')
            elif key == 'proxy_jump':
                field = QLineEdit(values[key])
                field.setPlaceholderText('user@bastion:22')
            elif key in ('alive_interval', 'alive_count'):
                field = QSpinBox()
                field.setRange(0 if key == 'alive_interval' else 1, 3600 if key == 'alive_interval' else 100)
                field.setValue(values[key])
            else:
                field = QComboBox()
                choices = [('OpenSSH configuration', 'config')]
                choices += [('Automatic', 'any'), ('IPv4', 'inet'), ('IPv6', 'inet6')] if key == 'address_family' else [('Yes', 'yes'), ('No', 'no')]
                for title, value in choices:
                    field.addItem(self.tr(title), value)
                field.setCurrentIndex(field.findData(values[key]))
            field.setToolTip(self.tr(tips[key]))
            self.fields[key] = field
            form.addRow(self.tr(label), field)

        self.forwards = ForwardingEditor(values['forwards'], self)
        section(form, 'Port forwarding')
        form.addRow(self.forwards)

    def options(self):
        options = {key: field.toPlainText().strip() if isinstance(field, QPlainTextEdit) else field.text().strip() if isinstance(field, QLineEdit) else field.value() if isinstance(field, QSpinBox) else field.currentData()
                for key, field in self.fields.items()}
        rules = self.forwards.rules()
        if rules:
            options['forwards'] = rules
        return options


class ForwardingEditor(QWidget):
    """Editable tunnel list shared by profiles and group defaults."""
    def __init__(self, rules, parent=None):
        super().__init__(parent)
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel(self.tr('Edit cells directly. Local: client → server; Remote: server → client; Dynamic: SOCKS proxy.'))
        note.setWordWrap(True)
        layout.addRow(note)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([self.tr(t) for t in ('Enabled', 'Type', 'Listen address', 'Listen port', 'Destination host', 'Destination port')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(160)
        self.table.setToolTip(self.tr('Local and Dynamic listen on your computer; Remote listens on the SSH server. Use localhost to restrict access. A public Remote listener also requires server GatewayPorts permission.'))
        layout.addRow(self.table)
        buttons = QHBoxLayout()
        for title, icon, callback, tip in (
                ('Add', 'Add', self.add_rule, 'Add an SSH forwarding rule.'),
                ('Delete', 'Delete', self.remove_rule, 'Delete the selected forwarding rule.')):
            button = QPushButton(action_icon(self, icon), self.tr(title))
            button.setToolTip(self.tr(tip))
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addRow(buttons)
        for rule in rules:
            self.add_rule(rule)

    def add_rule(self, rule=None):
        if not isinstance(rule, dict):
            rule = dict(enabled=True, type='L', bind='localhost', port=8080, host='localhost', target_port=80)
        row = self.table.rowCount()
        self.table.insertRow(row)
        enabled = QCheckBox()
        enabled.setChecked(rule['enabled'])
        kind = QComboBox()
        for title, value in (('Local', 'L'), ('Remote', 'R'), ('Dynamic (SOCKS)', 'D')):
            kind.addItem(self.tr(title), value)
        kind.setCurrentIndex(kind.findData(rule['type']))
        bind = QLineEdit(rule['bind'])
        bind.setToolTip(self.tr('localhost restricts access. Use an explicit interface address or * to allow other machines.'))
        port = QSpinBox()
        port.setRange(1, 65535)
        port.setValue(rule['port'])
        host = QLineEdit(rule['host'])
        target = QSpinBox()
        target.setRange(1, 65535)
        target.setValue(rule['target_port'] or 80)
        for column, field in enumerate((enabled, kind, bind, port, host, target)):
            self.table.setCellWidget(row, column, field)
        def update_destination():
            active = kind.currentData() != 'D'
            host.setEnabled(active)
            target.setEnabled(active)
        kind.currentIndexChanged.connect(update_destination)
        update_destination()
        self.table.setCurrentCell(row, 1)

    def remove_rule(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def rules(self):
        result = []
        for row in range(self.table.rowCount()):
            enabled, kind, bind, port, host, target = [self.table.cellWidget(row, column) for column in range(6)]
            dynamic = kind.currentData() == 'D'
            result.append(dict(enabled=enabled.isChecked(), type=kind.currentData(), bind=bind.text().strip(),
                               port=port.value(), host='' if dynamic else host.text().strip(),
                               target_port=0 if dynamic else target.value()))
        return result
