"""pyte screens with xterm alternate-buffer switching for full-screen programs."""
import pyte


class TerminalScreen:
    def __init__(self, columns, lines, write_process_input=lambda data: None, bell=lambda: None):
        self.bell = bell
        self.normal = pyte.HistoryScreen(columns, lines, history=2000)
        self.alternate = pyte.Screen(columns, lines)
        self.active = self.normal
        for screen in (self.normal, self.alternate):
            screen.write_process_input = write_process_input

    @property
    def is_alternate(self):
        return self.active is self.alternate

    @property
    def history(self):
        return self.normal.history

    def __getattr__(self, name):
        value = getattr(self.active, name)
        if callable(value):
            # pyte caches event handlers when attaching the stream. Resolve the
            # active buffer at invocation time, rather than binding the old one.
            return lambda *args, **kwargs: getattr(self.active, name)(*args, **kwargs)
        return value

    def set_mode(self, *modes, **kwargs):
        if kwargs.get('private'):
            if any(mode in modes for mode in (47, 1047, 1049)) and not self.is_alternate:
                while self.normal.history.bottom:
                    self.normal.next_page()
                if 1047 in modes or 1049 in modes:
                    self.alternate.reset()
                self.alternate.mode = self.normal.mode.copy()
                self.alternate.cursor.hidden = pyte.modes.DECTCEM not in self.alternate.mode
                self.active = self.alternate
            if 1048 in modes:
                self.active.save_cursor()
        self.active.set_mode(*modes, **kwargs)

    def reset_mode(self, *modes, **kwargs):
        if kwargs.get('private'):
            if 1048 in modes:
                self.active.restore_cursor()
            if any(mode in modes for mode in (47, 1047, 1049)):
                self.active = self.normal
        self.active.reset_mode(*modes, **kwargs)

    def select_graphic_rendition(self, *attrs, private=False):
        # xterm private CSI ? ... m controls keyboard extensions, not colors.
        # pyte does not implement that extension; do not treat it as SGR.
        if not private:
            self.active.select_graphic_rendition(*attrs)

    def set_margins(self, *args, private=False):
        # CSI ? ... r restores xterm private modes (emitted by mc on exit).
        # It is not DECSTBM; pyte has no saved-private-mode implementation.
        if not private:
            self.active.set_margins(*args)

    def reset(self):
        self.normal.reset()
        self.alternate.reset()
        self.active = self.normal

    def resize(self, lines=None, columns=None):
        self.normal.resize(lines, columns)
        self.alternate.resize(lines, columns)

    def prev_page(self):
        if not self.is_alternate:
            self.normal.prev_page()

    def next_page(self):
        if not self.is_alternate:
            self.normal.next_page()
