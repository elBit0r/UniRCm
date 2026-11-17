"""Real Telnet transport with telnetlib3 negotiation, isolated from the Qt loop."""
import asyncio
import codecs
import logging
import re
import threading

import telnetlib3
from telnetlib3.telopt import NAWS
from PyQt6.QtCore import QThread, pyqtSignal

from remote_manager.storage.vault import validate_connect_timeout

ENCODINGS = ('utf-8', 'latin-1', 'cp437', 'ascii')
LOGIN_MODES = ('manual', 'password', 'username_password')


def validate_options(options):
    if not isinstance(options, dict) or set(options) - {'term', 'encoding', 'login_mode', 'username_prompt', 'password_prompt'}:
        raise ValueError('Invalid Telnet settings.')
    if not re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}', options.get('term', 'xterm-256color')):
        raise ValueError('Invalid Telnet terminal type.')
    if options.get('encoding', 'utf-8') not in ENCODINGS:
        raise ValueError('Unsupported Telnet encoding.')
    if options.get('login_mode', 'manual') not in LOGIN_MODES:
        raise ValueError('Invalid Telnet login mode.')
    for key in ('username_prompt', 'password_prompt'):
        prompt = options.get(key, '')
        if not isinstance(prompt, str) or len(prompt) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in prompt):
            raise ValueError('Telnet prompts must contain at most 256 characters without control characters.')


def validate_profile(profile):
    if not re.fullmatch(r'[A-Za-z0-9_.:%\[\]-]+', profile.get('host', '')) or profile['host'].startswith('-'):
        raise ValueError('Enter a hostname or IP address without spaces.')
    if type(profile.get('port')) is not int or not 1 <= profile['port'] <= 65535:
        raise ValueError('Invalid Telnet port.')
    validate_connect_timeout(profile.get('connect_timeout', 15))
    validate_options(profile.get('telnet_options', {}))


class PromptLogin:
    """Opt-in, one attempt per field. Unknown prompts always remain manual."""
    def __init__(self, mode, username='', password='', username_prompt='', password_prompt=''):
        self.username = username if mode == 'username_password' else ''
        self.password = password if mode != 'manual' else ''
        self.buffer = ''
        self.username_prompt = username_prompt.strip()
        self.password_prompt = password_prompt.strip()

    @staticmethod
    def matches(prompt, configured, automatic):
        return prompt.casefold().endswith(configured.casefold()) if configured else bool(re.fullmatch(automatic, prompt))

    def feed(self, text):
        # Strip complete ANSI control sequences and retain fragmented sequences.
        self.buffer = (self.buffer + text)[-2048:]
        plain = re.sub(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*\x07)', '', self.buffer)
        prompt = re.split(r'[\r\n]', plain)[-1].strip()
        if self.username and self.matches(prompt, self.username_prompt, r'(?i)(?:[\w .@/()\[\]-]*\s)?(?:login|user\s*name|username)\s*:'):
            value, self.username = self.username, ''
        elif self.password and self.matches(prompt, self.password_prompt, r'(?i)(?:[\w .@/()\[\]-]*\s)?password\s*:'):
            value, self.password = self.password, ''
            self.username = ''
        else:
            return None
        self.buffer = ''
        return value

    def clear(self):
        self.username = self.password = self.buffer = ''


class TelnetTransport(QThread):
    output = pyqtSignal(bytes)
    activity = pyqtSignal(str)
    connected = pyqtSignal()
    ended = pyqtSignal(int)
    failed = pyqtSignal(str)

    def __init__(self, profile):
        # No widget parent: stop can cancel a pending DNS lookup without keeping
        # a QThread child attached to a closing terminal widget.
        super().__init__()
        validate_profile(profile)
        self.host, self.port = profile['host'].strip('[]'), profile['port']
        self.timeout = profile.get('connect_timeout', 15)
        self.options = dict(profile.get('telnet_options', {}))
        self.login = PromptLogin(self.options.get('login_mode', 'manual'),
                                 profile.get('username', ''), profile.get('password', ''),
                                 self.options.get('username_prompt', ''), self.options.get('password_prompt', ''))
        self.size = (80, 24)
        self._guard = threading.Lock()
        self._stopped = threading.Event()
        self.loop = self.task = self.writer = None
        self._queued_bytes = 0
        self._code = 0

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # Never let library exception contexts print transport buffers/secrets.
        loop.set_exception_handler(lambda *_: None)
        with self._guard:
            self.loop = loop
            self.queue = asyncio.Queue()
            self.ack = asyncio.Event()
            self.task = loop.create_task(self.session())
            if self._stopped.is_set():
                self.task.cancel()
        try:
            loop.run_until_complete(self.task)
        except asyncio.CancelledError:
            pass
        except Exception:
            self._code = 1
            self.failed.emit('Telnet connection failed or was interrupted.')
        finally:
            self.login.clear()
            if self.writer is not None:
                self.writer.close()
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            with self._guard:
                self.loop = self.task = self.writer = None
            loop.close()
            self.ended.emit(self._code)

    async def session(self):
        owner = self
        silent = logging.Logger('unircm.telnet.private')
        silent.disabled = True

        class Client(telnetlib3.TelnetClient):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.log = silent

            def connection_made(self, transport):
                super().connection_made(transport)
                owner.writer = self.writer
                self.writer.log = silent
                for option in (self.writer.local_option, self.writer.remote_option, self.writer.pending_option):
                    option.log = silent
                self.writer.set_ext_send_callback(NAWS, lambda: (owner.size[1], owner.size[0]))

        reader, writer = await asyncio.wait_for(telnetlib3.open_connection(
            self.host, self.port, client_factory=Client, encoding=False,
            term=self.options.get('term', 'xterm-256color'), cols=self.size[0], rows=self.size[1],
            connect_maxwait=0.5, connect_timeout=self.timeout, compression=False,
            send_environ=('TERM', 'COLUMNS', 'LINES')), timeout=self.timeout + 1)
        self.connected.emit()  # TCP session established; no inferred authentication.
        codec = self.options.get('encoding', 'utf-8')
        decoder = codecs.getincrementaldecoder(codec)(errors='replace')
        input_decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')

        async def transmit():
            while True:
                data = await self.queue.get()
                text = input_decoder.decode(data)
                wire = text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r\n')
                writer.write(wire.encode(codec, errors='replace'))
                await writer.drain()
                if wire:
                    self.activity.emit('tx')
                self._queued_bytes -= len(data)

        sender = asyncio.create_task(transmit())
        expiry = asyncio.get_running_loop().call_later(60, self.login.clear)
        pending_cr = False
        try:
            while True:
                data = await reader.read(8192)
                if not data:
                    break
                self.activity.emit('rx')
                # NVT CR NUL denotes CR. Keep CR LF as a terminal newline.
                cooked = bytearray()
                for byte in data:
                    if pending_cr:
                        pending_cr = False
                        if byte == 0:
                            continue
                    cooked.append(byte)
                    pending_cr = byte == 13
                text = decoder.decode(cooked)
                if text:
                    self.ack.clear()
                    self.output.emit(text.encode('utf-8'))
                    await self.ack.wait()  # Bound cross-thread output buffering.
                    secret = self.login.feed(text)
                    if secret is not None:
                        try:
                            wire_secret = (secret + '\r\n').encode(codec)
                        except UnicodeEncodeError:
                            self.failed.emit('Stored credentials cannot be encoded with the selected Telnet encoding; use manual login.')
                            self.login.clear()
                        else:
                            writer.write(wire_secret)
                            await writer.drain()
                            self.activity.emit('tx')
                            wire_secret = None
                        secret = None
        finally:
            expiry.cancel()
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            writer.close()

    def schedule(self, callback, *args):
        with self._guard:
            if self.loop is not None and not self._stopped.is_set():
                self.loop.call_soon_threadsafe(callback, *args)

    def acknowledge(self):
        self.schedule(lambda: self.ack.set())

    def send(self, data):
        def enqueue():
            if self._queued_bytes + len(data) > 1024 * 1024:
                self._code = 1
                self.failed.emit('Telnet input buffer is full; connection closed.')
                self.task.cancel()
                return
            self._queued_bytes += len(data)
            self.queue.put_nowait(data)
        self.schedule(enqueue)

    def resize(self, columns, rows):
        self.size = (columns, rows)
        def update():
            if self.writer is not None and self.writer.local_option.enabled(NAWS):
                # telnetlib3 5.0.2 has no public method for unsolicited NAWS.
                self.writer._send_naws()
        self.schedule(update)

    def stop(self):
        self._stopped.set()
        with self._guard:
            if self.loop is not None and self.task is not None:
                self.loop.call_soon_threadsafe(self.task.cancel)
        self.wait(1000)
        self.login.clear()
