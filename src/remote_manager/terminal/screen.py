"""pyte screens with xterm alternate-buffer switching and emoji presentation."""
import re

import pyte
from wcwidth import wcswidth


_PRESENTATION_SELECTORS = re.compile('([\ufe0e\ufe0f])')


class TerminalStream(pyte.ByteStream):
    def _parser_fsm(self):
        parser = super()._parser_fsm()
        ready = next(parser)
        while True:
            char = yield ready
            at_start = ready
            ready = parser.send(char)
            if not at_start:
                continue
            if self.use_utf8 and char in (pyte.control.SI, pyte.control.SO):
                # pyte skips G0/G1 shifts in UTF-8 mode. Remote applications
                # can still use them to select DEC line drawing.
                if char == pyte.control.SI:
                    self.listener.shift_in()
                else:
                    self.listener.shift_out()
                continue
            if char == pyte.control.ESC:
                char = yield ready
                ready = parser.send(char)
                if self.use_utf8 and char in ('(', ')'):
                    code = yield ready
                    ready = parser.send(code)
                    self.listener.define_charset(code, mode=char)
                    continue
                if char != '[':
                    continue
            elif char != pyte.control.CSI_C1:
                continue

            char = yield ready
            ready = parser.send(char)
            if char == '>':
                while not ready:
                    char = yield ready
                    if char == 'c':
                        # pyte drops '>' and would reply with primary DA.
                        # Mark secondary DA as private so pyte ignores it.
                        parser.send('?')
                    ready = parser.send(char)


class PresentationScreen:
    def draw(self, data):
        cursor = self.cursor
        charset = self.g1_charset if self.charset else self.g0_charset
        if (charset is pyte.charsets.LAT1_MAP and data.isascii() and data.isprintable()
                and pyte.modes.IRM not in self.mode and cursor.x + len(data) <= self.columns):
            # Printable ASCII in replace mode fits on this row without any
            # charset translation, width calculation or wrapping.
            row = self.buffer[cursor.y]
            with_glyph = cursor.attrs._replace
            for column, glyph in enumerate(data, cursor.x):
                row[column] = with_glyph(data=glyph)
            cursor.x += len(data)
            self.dirty.add(cursor.y)
            return
        if '\ufe0e' not in data and '\ufe0f' not in data:
            super().draw(data)
            return
        for index, text in enumerate(_PRESENTATION_SELECTORS.split(data)):
            if index % 2:
                self.apply_presentation_selector(text)
            elif text:
                super().draw(text)

    def apply_presentation_selector(self, selector):
        # pyte treats these zero-width characters as a reason to stop drawing.
        # Keep the selector with its glyph, even across separate stream feeds.
        if not self.cursor.x:
            return
        line = self.buffer[self.cursor.y]
        column = self.cursor.x - 1
        if column and line[column].data == '':
            column -= 1
        char = line[column]
        if len(char.data) != 1 or char.data == ' ':
            return
        glyph = char.data + selector
        if wcswidth(glyph) == 2 and self.cursor.x == column + 1 and self.cursor.x < self.columns:
            if pyte.modes.IRM in self.mode:
                self.insert_characters(1)
            line[self.cursor.x] = char._replace(data='')
            self.cursor.x += 1
        line[column] = char._replace(data=glyph)
        self.dirty.add(self.cursor.y)


class NormalScreen(PresentationScreen, pyte.HistoryScreen):
    pass


class AlternateScreen(PresentationScreen, pyte.Screen):
    pass


class TerminalScreen:
    def __init__(self, columns, lines, write_process_input=lambda data: None, bell=lambda: None):
        self.bell = bell
        self.normal = NormalScreen(columns, lines, history=2000)
        self.alternate = AlternateScreen(columns, lines)
        self.active = self.normal
        for screen in (self.normal, self.alternate):
            screen.write_process_input = write_process_input

    @property
    def is_alternate(self):
        return self.active is self.alternate

    @property
    def history(self):
        return self.normal.history

    @property
    def display(self):
        # The continuation cell is empty, including for glyphs whose width
        # changes with a presentation selector.
        return [''.join(self.buffer[y][x].data for x in range(self.columns))
                for y in range(self.lines)]

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

    def report_device_status(self, mode, *extra, private=False):
        if extra:
            return
        if not private:
            self.active.report_device_status(mode)
        elif mode == 6:
            # DECXCPR uses the private marker in the cursor position reply.
            screen = self.active
            row = screen.cursor.y + 1
            if pyte.modes.DECOM in screen.mode and screen.margins is not None:
                row -= screen.margins.top
            screen.write_process_input(f'\x1b[?{row};{screen.cursor.x + 1}R')

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
