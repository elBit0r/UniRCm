"""Short-lived OpenSSH ASKPASS channel; secrets travel only over private IPC."""
import json
import os
from pathlib import Path
import re
import shlex
import socket
import struct
import sys
import tempfile

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtNetwork import QLocalServer
from PyQt6.QtWidgets import QInputDialog, QLineEdit


# This helper contains no credentials. OpenSSH supplies only its prompt in argv.
HELPER = '''import json, os, socket, sys
with socket.socket(socket.AF_UNIX) as connection:
    connection.settimeout(120)
    connection.connect(os.environ['UNIRCM_ASKPASS_SOCKET'])
    connection.sendall(json.dumps(sys.argv[1]).encode('utf-8') + b'\\n')
    chunks = []
    while True:
        data = connection.recv(4096)
        if not data:
            break
        chunks.append(data)
    sys.stdout.buffer.write(b''.join(chunks))
'''


class AskpassBridge(QObject):
    def __init__(self, password, parent, key_passphrase='', identity_file=''):
        super().__init__(parent)
        self.password = password
        self.key_passphrase = key_passphrase
        self.identity_file = os.path.realpath(os.path.expanduser(identity_file)) if identity_file else None
        self.directory = tempfile.TemporaryDirectory(prefix='unircm-auth-')
        self.server = QLocalServer(self)
        self.connections = set()
        self.address = str(Path(self.directory.name) / 'socket')
        if not self.server.listen(self.address):
            self.close()
            raise RuntimeError('Unable to create private SSH authentication channel.')
        helper = Path(self.directory.name) / 'askpass'
        helper.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -c ' + shlex.quote(HELPER) + ' "$@"\n')
        helper.chmod(0o700)
        self.helper = str(helper)
        self.server.newConnection.connect(self.accept)
        # Discard an unused saved secret after the initial authentication period.
        self.expiry = QTimer(self)
        self.expiry.setSingleShot(True)
        self.expiry.timeout.connect(self.clear_password)
        self.expiry.start(60000)

    def environment(self):
        return dict(SSH_ASKPASS=self.helper, SSH_ASKPASS_REQUIRE='force',
                    UNIRCM_ASKPASS_SOCKET=self.address)

    def clear_password(self):
        self.password = ''
        self.key_passphrase = ''

    def accept(self):
        while self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            # Fail closed if the local client's UID cannot be verified.
            with socket.socket(fileno=os.dup(int(connection.socketDescriptor()))) as peer:
                if hasattr(socket, 'SO_PEERCRED'):
                    uid = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
                elif hasattr(peer, 'getpeereid'):
                    uid = peer.getpeereid()[0]
                else:
                    uid = None
            if uid != os.getuid():
                connection.abort()
                connection.deleteLater()
                continue
            self.connections.add(connection)
            buffer = bytearray()
            connection.readyRead.connect(lambda c=connection, b=buffer: self.respond(c, b))
            connection.disconnected.connect(lambda c=connection: self.remove(c))
            self.respond(connection, buffer)

    def remove(self, connection):
        self.connections.discard(connection)
        connection.deleteLater()

    def respond(self, connection, buffer):
        buffer.extend(bytes(connection.readAll()))
        if len(buffer) > 32768:
            connection.abort()
            return
        if b'\n' not in buffer:
            return
        try:
            prompt = json.loads(bytes(buffer).split(b'\n', 1)[0])
            if not isinstance(prompt, str):
                raise ValueError()
        except (ValueError, UnicodeError):
            connection.abort()
            return
        buffer.clear()
        key_prompt = re.fullmatch(r"Enter passphrase for key ['\"](.+)['\"]:\s*", prompt)
        if self.key_passphrase and self.identity_file and key_prompt and os.path.realpath(os.path.expanduser(key_prompt[1])) == self.identity_file:
            answer, accepted = self.key_passphrase, True
            self.key_passphrase = ''
        elif self.password and re.fullmatch(r"[^\r\n]+(?:'s)? password:\s*", prompt, re.IGNORECASE):
            answer, accepted = self.password, True
            self.password = ''
        else:
            # Host-key confirmations and other challenges always require user input.
            echo = QLineEdit.EchoMode.Normal if 'yes/no' in prompt else QLineEdit.EchoMode.Password
            answer, accepted = QInputDialog.getText(self.parent(), self.tr('SSH authentication'), prompt, echo)
        if accepted:
            connection.write((answer + '\n').encode('utf-8'))
        connection.disconnectFromServer()

    def close(self):
        self.clear_password()
        if hasattr(self, 'expiry'):
            self.expiry.stop()
        self.server.close()
        for connection in tuple(self.connections):
            connection.abort()
        self.directory.cleanup()
