"""Shared application defaults for terminal rendering and appearance editors."""
from PyQt6.QtGui import QFontDatabase


DEFAULT_OPTIONS = dict(background='#000000', foreground='#00ff00',
                       cursor_color='#00ff00', cursor_shape='block', cursor_blink=True)


def default_font():
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    families = {family.casefold(): family for family in QFontDatabase.families()}
    for preferred in ('Inconsolata', 'Hack'):
        if preferred.casefold() in families:
            font.setFamily(families[preferred.casefold()])
            break
    return font
