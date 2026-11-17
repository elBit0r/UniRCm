"""Small, palette-aware building blocks for application chrome."""
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap, QPalette
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget, QTreeWidget, QLineEdit, QToolButton


def contrast_workspace(sidebar, workspace, palette):
    """Separate navigation from the session surface without styling terminals."""
    window = palette.color(QPalette.ColorRole.Window)
    light = window.lightness() > 128
    navigation = QPalette(palette)
    navigation.setColor(QPalette.ColorRole.Window,
                        palette.color(QPalette.ColorRole.Base) if light else window.lighter(118))
    sessions = QPalette(palette)
    sessions.setColor(QPalette.ColorRole.Window, window.darker(112 if light else 125))
    for widget, colors in ((sidebar, navigation), (workspace, sessions)):
        widget.setPalette(colors)
        widget.setAutoFillBackground(True)
    # Refresh controls with local stylesheets as well as their parent surface.
    for kind in (QTreeWidget, QLineEdit, QToolButton):
        for control in sidebar.findChildren(kind):
            control.setPalette(navigation)
            if isinstance(control, QTreeWidget):
                control.header().setPalette(navigation)


def title_label(text, parent=None, size=18):
    label = QLabel(text, parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    font = label.font()
    font.setPointSize(size)
    font.setWeight(QFont.Weight.DemiBold)
    label.setFont(font)
    label.setWordWrap(True)
    return label


def brand_header(parent, subtitle):
    header = QWidget(parent)
    row = QHBoxLayout(header)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(16)
    logo = QLabel()
    logo.setPixmap(QPixmap(str(Path(__file__).parent / 'assets/unircm.png')).scaled(
        64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    row.addWidget(logo)
    text = QVBoxLayout()
    text.setSpacing(4)
    text.addWidget(title_label('UniRCm', size=22))
    label = QLabel(subtitle)
    label.setWordWrap(True)
    text.addWidget(label)
    row.addLayout(text, 1)
    return header


def style_surface(widget):
    # Scope all selectors to chrome; terminal rendering and native dialogs stay native.
    widget.setObjectName('databaseSurface')
    widget.setStyleSheet('''
        QWidget#databaseSurface { background: palette(window); }
        QWidget#databaseSurface QLineEdit { padding: 7px; }
        QWidget#databaseSurface QPushButton { padding: 7px 12px; }
        QWidget#databaseSurface QPushButton[primary="true"] {
            background: palette(highlight); color: palette(highlighted-text);
            border: 1px solid palette(highlight); border-radius: 5px;
            font-weight: 600;
        }
        QWidget#databaseSurface QPushButton[primary="true"]:disabled {
            background: palette(button); color: palette(mid); border-color: palette(mid);
        }
        QWidget#databaseSurface QPushButton[primary="true"]:hover {
            border: 1px solid palette(text);
        }
        QWidget#databaseSurface QPushButton[primary="true"]:focus {
            border: 2px solid palette(text);
        }
        QWidget#databaseSurface QTreeWidget {
            background: palette(base); border: 1px solid palette(mid);
            border-radius: 6px;
        }
        QWidget#databaseSurface QTreeWidget::item { padding: 9px 6px; }
    ''')
