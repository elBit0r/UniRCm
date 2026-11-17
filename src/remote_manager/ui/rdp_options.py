"""RDP connection and display controls."""
from PyQt6.QtWidgets import QWidget, QFormLayout, QComboBox, QSpinBox, QCheckBox
from remote_manager.rdp_options import effective_options
from .icons import action_icon


class RdpOptions(QWidget):
    def __init__(self, options, parent=None):
        super().__init__(parent)
        values = effective_options(options)
        form = QFormLayout(self)
        self.controls = {}
        combos = {
            'connection_speed': ('Connection speed', [('Automatic', 7), ('Modem (56 Kbps)', 1),
                ('Low-speed broadband', 2), ('Satellite', 3), ('High-speed broadband', 4), ('WAN', 5), ('LAN', 6)]),
            'color_depth': ('Color depth', [('15 bit (32,768 colors)', 15), ('16 bit (65,536 colors)', 16),
                ('24 bit (16.7 million colors)', 24), ('32 bit', 32)]),
            'resolution': ('Resolution', [('Automatic — follow window size', 'automatic'), ('Fixed', 'fixed')]),
            'display': ('Open desktop in', [('Workspace', 'workspace'), ('Detached window', 'detached')]),
        }
        for key, (label, choices) in combos.items():
            field = QComboBox()
            for title, value in choices:
                field.addItem(self.tr(title), value)
            field.setCurrentIndex(field.findData(values[key]))
            self.controls[key] = field
            form.addRow(self.tr(label), field)
        for key, label in [('width', 'Width'), ('height', 'Height'), ('timeout', 'Connection timeout')]:
            field = QSpinBox()
            field.setRange(1, 600) if key == 'timeout' else field.setRange(320, 8192)
            field.setSuffix(self.tr(' s') if key == 'timeout' else self.tr(' px'))
            field.setValue(values[key])
            self.controls[key] = field
            form.insertRow(3 if key == 'width' else 4 if key == 'height' else form.rowCount(), self.tr(label), field)
        for key, label in [('compression', 'Compress session data'), ('wallpaper', 'Show desktop wallpaper'),
                           ('font_smoothing', 'Smooth fonts'), ('themes', 'Use Windows themes'),
                           ('full_window_drag', 'Show window contents while dragging'),
                           ('menu_animations', 'Animate menus'), ('admin_session', 'Administrative session'),
                           ('smooth_scaling', 'Smooth local desktop scaling'),
                           ('clipboard', 'Share text clipboard')]:
            field = QCheckBox(self.tr(label))
            field.setIcon(action_icon(self, 'Settings'))
            field.setChecked(values[key])
            self.controls[key] = field
            form.addRow(field)
        self.controls['clipboard'].setToolTip(self.tr('Share text only while this desktop has focus. Other clipboard formats and file transfers are disabled.'))
        self.controls['resolution'].setToolTip(self.tr('Automatic requests the window size at connection and on resize. Servers without Display Control keep their negotiated resolution and are scaled locally.'))
        self.controls['connection_speed'].setToolTip(self.tr('Advertise the connection type to the server. Appearance switches below explicitly control visual effects.'))
        self.controls['display'].setToolTip(self.tr('Detached windows remain managed by this application and disconnect when the database is locked or the session is closed.'))
        self.controls['admin_session'].setToolTip(self.tr('Request an administrative server session. Requires appropriate server permissions.'))
        self.controls['color_depth'].setToolTip(self.tr('Requested remote color depth; the server may negotiate another supported depth.'))
        self.controls['resolution'].currentIndexChanged.connect(self.update_resolution)
        self.update_resolution()

    def update_resolution(self):
        fixed = self.controls['resolution'].currentData() == 'fixed'
        for key in ('width', 'height'):
            self.controls[key].setEnabled(fixed)

    def options(self):
        return {key: field.currentData() if isinstance(field, QComboBox) else
                field.isChecked() if isinstance(field, QCheckBox) else field.value()
                for key, field in self.controls.items()}
