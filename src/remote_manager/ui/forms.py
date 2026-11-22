"""Shared form spacing, sections and field-level validation feedback."""
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtWidgets import (QComboBox, QDialogButtonBox, QFormLayout, QLabel,
                            QLineEdit, QPushButton, QScrollArea, QTabWidget,
                            QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy)
from .icons import connection_icon
from .visuals import title_label


def icon_label(widget, title, icon, field):
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    image = QLabel()
    image.setPixmap(connection_icon(icon, widget.palette()).pixmap(16, 16))
    label = QLabel(title)
    label.setBuddy(field)
    field.setAccessibleName(title)
    layout.addWidget(image)
    layout.addWidget(label)
    layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
    return row


class NamedButtonBox(QDialogButtonBox):
    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            for button in self.buttons():
                source = button.property('unircmText')
                if source:
                    button.setText(QCoreApplication.translate('Forms', source))


def primary_action(buttons, title):
    for button in buttons.buttons():
        if buttons.buttonRole(button) == QDialogButtonBox.ButtonRole.AcceptRole:
            button.setText(buttons.tr(title))
            button.setProperty('unircmText', title)
            button.setProperty('primary', True)
            button.setToolTip(buttons.tr(title))
            button.setDefault(True)
            break


def section(form, title, hint=None):
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 8, 0, 4)
    layout.setSpacing(4)
    heading = title_label(form.parentWidget().tr(title), size=11)
    heading.setObjectName('formSection')
    layout.addWidget(heading)
    if hint:
        label = QLabel(form.parentWidget().tr(hint))
        label.setWordWrap(True)
        layout.addWidget(label)
    form.addRow(widget)


def polish_dialog(dialog):
    dialog.setSizeGripEnabled(True)
    dialog.setObjectName('formDialog')
    dialog.setStyleSheet('''
        QDialog#formDialog QLineEdit, QDialog#formDialog QSpinBox,
        QDialog#formDialog QComboBox { min-height: 24px; }
        QDialog#formDialog QPushButton { padding: 5px 10px; }
        QDialog#formDialog QLabel#formSection {
            padding-bottom: 5px; border-bottom: 1px solid palette(mid);
        }
        QDialog#formDialog QPushButton[primary="true"] {
            background: palette(highlight); color: palette(highlighted-text);
            border: 1px solid palette(highlight); border-radius: 4px;
        }
        QDialog#formDialog QPushButton[primary="true"]:focus {
            border: 2px solid palette(text);
        }
        QDialog#formDialog QLineEdit[invalid="true"],
        QDialog#formDialog QComboBox[invalid="true"] {
            border: 2px solid palette(highlight); border-radius: 3px;
        }
        QDialog#formDialog QLabel[effectiveValue="true"] {
            background: palette(alternate-base); padding: 7px;
            border-left: 2px solid palette(mid);
        }
        QDialog#formDialog QLabel[fieldError="true"] {
            padding: 3px 0; font-weight: 600;
        }
    ''')
    layout = dialog.layout()
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(12)
    for form in dialog.findChildren(QFormLayout):
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        for row in range(form.rowCount()):
            item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item and isinstance(item.widget(), QLabel):
                item.widget().setWordWrap(True)
                item.widget().setMinimumWidth(150)
                item.widget().setMaximumWidth(210)
    for combo in dialog.findChildren(QComboBox):
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(16)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    for button in dialog.findChildren(QPushButton):
        if button.icon().isNull():
            from .icons import action_icon
            button.setIcon(action_icon(button, 'Edit'))
        if not button.toolTip():
            button.setToolTip(button.text().replace('&', ''))


def validated_field(dialog, field):
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    layout.addWidget(field)
    error = QLabel()
    error.setTextFormat(Qt.TextFormat.PlainText)
    error.setWordWrap(True)
    error.setProperty('fieldError', True)
    error.hide()
    layout.addWidget(error)
    if not hasattr(dialog, '_field_errors'):
        dialog._field_errors = {}
    dialog._field_errors[field] = error
    changed = field.textChanged if isinstance(field, QLineEdit) else field.currentTextChanged
    changed.connect(lambda: clear_field(dialog, field))
    return widget


def clear_field(dialog, field):
    dialog._field_errors[field].clear()
    dialog._field_errors[field].hide()
    field.setProperty('invalid', False)
    field.style().unpolish(field)
    field.style().polish(field)


def field_error(dialog, field, message):
    dialog._field_errors[field].setText(message)
    dialog._field_errors[field].show()
    field.setProperty('invalid', True)
    field.style().unpolish(field)
    field.style().polish(field)
    root = dialog.window()
    for tabs in root.findChildren(QTabWidget):
        for index in range(tabs.count()):
            if tabs.widget(index).isAncestorOf(field):
                tabs.setCurrentIndex(index)
                break
    field.setFocus()
    if isinstance(field, QLineEdit):
        field.selectAll()
    for scroll in root.findChildren(QScrollArea):
        if scroll.widget() and scroll.widget().isAncestorOf(field):
            scroll.ensureWidgetVisible(field)


def require_fields(dialog, fields):
    for field, message in fields:
        value = field.text() if field.property('secret') else field.text().strip()
        if not value:
            field_error(dialog, field, dialog.tr(message))
            return False
    return True
