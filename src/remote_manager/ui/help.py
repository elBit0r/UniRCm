"""Built-in user guide for the available SSH/Telnet workflows."""
from html import escape

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout
from .credentials import decorate_buttons


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr('Help'))
        self.resize(700, 580)
        layout = QVBoxLayout(self)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(False)
        sections = [
            ('Connections', [
                'Use File > New connection to create an SSH or Telnet connection. Select an existing connection and use Edit to change, move, duplicate or delete it.',
                'Double-click a connection or use Session > Connect to open its terminal. Each connection uses an independent tab.']),
            ('Groups and ordering', [
                'File > New group creates a group at the root; when a group or one of its connections is selected, New subgroup creates a subgroup there.',
                'Right-click the tree for group properties and Order. Drag above or below an item to reorder it, or onto a group to move it inside. Ctrl+Up/Down reorders only while the tree has focus.',
                'The icon bar below the tree provides Add, Delete, Move up/down, Cut, Copy and Paste. Copy duplicates a connection; Cut moves a group or connection. Select a destination before pasting. Escape in the tree cancels the pending transfer.',
                'Group properties control the group icon and name color, inherited credentials, SSH defaults and terminal appearance. Connections can override inherited settings.']),
            ('Sessions and terminal', [
                'Session > Disconnect stops the current session but keeps its terminal. Reconnect opens it again using the saved connection settings. Close tab disconnects and removes it.',
                'Ctrl+Shift+C copies selected text; Ctrl+Shift+V pastes. Hold Shift to select locally when a remote program captures the mouse. Ctrl+mouse wheel changes font size.',
                'Ctrl+N, Ctrl+O, Ctrl+F and F1 are local shortcuts only while the tree or search field has focus. Ordinary terminal control keys remain available to the remote program.']),
            ('Telnet login', [
                'Telnet is unencrypted. Manual login sends no stored credentials automatically. In the Telnet tab, explicitly choose password-only or username/password login to send stored credentials at their prompts.',
                'Username prompt and Password prompt accept literal text such as login: and password:. Matching ignores letter case. Leave blank for automatic detection; each field is sent once and retries remain manual.']),
            ('Database and settings', [
                'Changes are saved automatically to the encrypted database. File > Open database switches databases; File > New database creates a separate archive.',
                'Edit > Credentials manages shared credentials. Edit > Settings selects English/Italian, inactivity lock, archive description and master-password change. The archive description is public.',
                'File > Lock disconnects all sessions and requires the master password again. Exit asks for confirmation when sessions are active. A forgotten master password cannot be recovered.',
                'To back up a database, copy its .uni file elsewhere. Open that copy with Open database when needed.'])]
        blocks = ['<h1>UniRCm</h1>']
        for heading, paragraphs in sections:
            blocks.append(f'<h2>{escape(self.tr(heading))}</h2>')
            blocks.extend(f'<p>{escape(self.tr(paragraph))}</p>' for paragraph in paragraphs)
        self.browser.setHtml(''.join(blocks))
        layout.addWidget(self.browser)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        decorate_buttons(buttons)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
