"""Desktop terminal icon with a theme-independent, scalable fallback."""
from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QIcon, QPainter, QPen, QPixmap, QColor
from PyQt6.QtWidgets import QStyle


def action_icon(widget, action):
    """Standard desktop action icons with Qt fallbacks when no theme is set."""
    theme, fallback = {
        'Connection tree': ('view-list-tree', 'SP_DirIcon'),
        'Maximize': ('view-fullscreen', 'SP_TitleBarMaxButton'),
        'Detach': ('window-new', 'SP_TitleBarNormalButton'),
        'Close': ('window-close', 'SP_DialogCloseButton'),
        'Rename tab': ('document-edit', 'SP_FileDialogDetailedView'),
        'Side by side': ('view-split-left-right', 'SP_FileDialogContentsView'),
        'Stacked': ('view-split-top-bottom', 'SP_FileDialogListView'),
        'Grid 2 × 2': ('view-grid', 'SP_FileDialogListView'),
        'Apply layout': ('view-grid', 'SP_FileDialogListView'),
        'Detach active pane': ('window-new', 'SP_TitleBarNormalButton'),
        'Close active pane': ('window-close', 'SP_DialogCloseButton'),
        'Upload file': ('document-send', 'SP_ArrowUp'),
        'Install public key…': ('dialog-password', 'SP_DialogApplyButton'),
        'Download file': ('document-save', 'SP_ArrowDown'),
        'Open directory': ('folder-open', 'SP_DirOpenIcon'),
        'Back': ('go-previous', 'SP_ArrowBack'),
        'Forward': ('go-next', 'SP_ArrowForward'),
        'Remote home': ('user-home', 'SP_DirHomeIcon'),
        'Filesystem root': ('drive-harddisk', 'SP_DriveHDIcon'),
        'Remote folder': ('folder', 'SP_DirIcon'),
        'Remote file': ('text-x-generic', 'SP_FileIcon'),
        'Refresh': ('view-refresh', 'SP_BrowserReload'),
        'Add': ('list-add', 'SP_FileDialogNewFolder'),
        'Cut': ('edit-cut', 'SP_DialogDiscardButton'),
        'New': ('document-new', 'SP_FileIcon'),
        'New connection': ('document-new', 'SP_FileIcon'),
        'New local terminal': ('utilities-terminal', 'SP_ComputerIcon'),
        'New group': ('folder-new', 'SP_FileDialogNewFolder'),
        'Edit': ('document-edit', 'SP_FileDialogDetailedView'),
        'Group defaults': ('preferences-system', 'SP_FileDialogDetailedView'),
        'Move up': ('go-up', 'SP_ArrowUp'),
        'Move down': ('go-down', 'SP_ArrowDown'),
        'Sort alphabetically': ('view-sort-ascending', 'SP_FileDialogDetailedView'),
        'Expand all groups': ('folder-open', 'SP_DirOpenIcon'),
        'Collapse all groups': ('folder', 'SP_DirClosedIcon'),
        'Move': ('go-jump', 'SP_ArrowRight'),
        'Delete': ('edit-delete', 'SP_TrashIcon'),
        'Duplicate': ('edit-copy', 'SP_FileDialogListView'),
        'New database': ('document-new', 'SP_FileIcon'),
        'Exit': ('application-exit', 'SP_DialogCloseButton'),
        'Disconnect': ('network-disconnect', 'SP_MediaStop'),
        'View only': ('view-visible', 'SP_FileDialogContentsView'),
        'Reconnect': ('view-refresh', 'SP_BrowserReload'),
        'Close tab': ('tab-close', 'SP_DialogCloseButton'),
        'Find connection': ('edit-find', 'SP_FileDialogContentsView'),
        'Help': ('help-contents', 'SP_DialogHelpButton'),
        'About': ('help-about', 'SP_MessageBoxInformation'),
        'Toolbar': ('view-list-icons', 'SP_FileDialogDetailedView'),
        'Status bar': ('dialog-information', 'SP_MessageBoxInformation'),
        'Connect': ('network-connect', 'SP_DialogOkButton'),
        'Open database': ('document-open', 'SP_DialogOpenButton'),
        'Settings': ('preferences-system', 'SP_FileDialogDetailedView'),
        'Credentials': ('dialog-password', 'SP_FileDialogDetailedView'),
        'Lock': ('system-lock-screen', 'SP_DialogCloseButton'),
        'Copy': ('edit-copy', 'SP_FileDialogListView'),
        'Paste': ('edit-paste', 'SP_DialogOpenButton'),
        'Unlock selected': ('document-open', 'SP_DialogOpenButton'),
        'Open file…': ('document-open', 'SP_DialogOpenButton'),
        'New database…': ('document-new', 'SP_FileIcon'),
        'Remove from list': ('list-remove', 'SP_DialogDiscardButton'),
        'Cancel': ('dialog-cancel', 'SP_DialogCancelButton'),
    }[action]
    if action in ('Side by side', 'Stacked'):
        return layout_icon(widget, action)
    if action == 'Grid 2 × 2':
        fallback_icon = layout_icon(widget, action)
    else:
        fallback_icon = tree_action_icon(widget, action) if action in ('Add', 'Cut', 'Copy', 'Paste') else widget.style().standardIcon(getattr(QStyle.StandardPixmap, fallback))
    return QIcon.fromTheme(theme, fallback_icon)


def layout_icon(widget, action):
    icon = QIcon()
    for size in (16, 20, 24, 32, 48):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 24, size / 24)
        painter.setPen(QPen(widget.palette().windowText().color(), 1.6))
        if action in ('Side by side', 'Stacked'):
            # The same geometry rotated keeps both orientations equally legible.
            if action == 'Stacked':
                painter.translate(24, 0)
                painter.rotate(90)
            fill = QColor(widget.palette().highlight().color())
            fill.setAlpha(30)
            painter.setBrush(fill)
            for x in (2, 14):
                painter.drawRoundedRect(QRectF(x, 3, 8, 18), 1.2, 1.2)
            painter.setPen(QPen(widget.palette().highlight().color(), 1.8,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(12, 8, 12, 16)
        else:
            painter.drawRoundedRect(QRectF(3, 3, 18, 18), 1, 1)
            painter.drawLine(12, 3, 12, 21)
            painter.drawLine(3, 12, 21, 12)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def tree_action_icon(widget, action):
    icon = QIcon()
    for size in (16, 20, 24, 32, 48):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 24, size / 24)
        painter.setPen(QPen(widget.palette().windowText().color(), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(widget.palette().base())
        if action == 'Add':
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor('#3eaa32'))
            painter.drawEllipse(QRectF(2, 2, 20, 20))
            painter.setPen(QPen(Qt.GlobalColor.white, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(7, 12, 17, 12)
            painter.drawLine(12, 7, 12, 17)
        elif action == 'Cut':
            painter.drawEllipse(QRectF(3, 15, 6, 6))
            painter.drawEllipse(QRectF(12, 15, 6, 6))
            painter.drawLine(7, 15, 17, 3)
            painter.drawLine(14, 15, 4, 3)
        elif action == 'Copy':
            painter.drawRoundedRect(QRectF(8, 3, 12, 15), 1, 1)
            painter.drawRoundedRect(QRectF(4, 7, 12, 15), 1, 1)
            for y in (11, 14, 17):
                painter.drawLine(7, y, 13, y)
        else:
            painter.drawRoundedRect(QRectF(5, 5, 15, 17), 1.5, 1.5)
            painter.drawRoundedRect(QRectF(9, 2, 7, 5), 1, 1)
            for y in (11, 14, 17):
                painter.drawLine(9, y, 16, y)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def ssh_icon(palette):
    fallback = QIcon()
    for size in (16, 24, 32, 48, 64, 128):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 24, size / 24)
        painter.setPen(QPen(palette.windowText().color(), 1.8))
        painter.setBrush(palette.window())
        painter.drawRoundedRect(QRectF(2, 4, 20, 16), 2, 2)
        painter.drawLine(QPointF(6, 9), QPointF(9, 12))
        painter.drawLine(QPointF(9, 12), QPointF(6, 15))
        painter.drawLine(QPointF(12, 15), QPointF(17, 15))
        painter.end()
        fallback.addPixmap(pixmap)
    return QIcon.fromTheme('utilities-terminal', fallback)


# Bundled Papirus SVGs; see assets/papirus/LICENSE and SOURCES.json.
from remote_manager.icon_catalog import BUNDLED_ICONS, CONNECTION_ICONS


def connection_icon(name, palette):
    from pathlib import Path
    from PyQt6.QtSvg import QSvgRenderer
    if name not in CONNECTION_ICONS and name != 'folder':
        name = 'terminal'
    collection = 'network' if name in BUNDLED_ICONS else 'papirus'
    data = (Path(__file__).parent / 'assets' / collection / f'{name}.svg').read_bytes()
    renderer = QSvgRenderer(data)
    icon = QIcon()
    for size in (16, 24, 32, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def group_icon(widget, name='folder'):
    return connection_icon(name, widget.palette())
