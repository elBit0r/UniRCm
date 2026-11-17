"""Terminal presets inspired by classic systems, not exact OS defaults."""


def default_profiles():
    themes = [
        ('green-black', 'Green on black', '#00ff00', '#000000'),
        ('amber-black', 'Amber on black', '#ffb000', '#000000'),
        ('white-black', 'White on black', '#eeeeee', '#000000'),
        ('solaris', 'Solaris CDE', '#000000', '#fff8dc'),
        ('openvms', 'OpenVMS VT', '#80ff80', '#101810'),
        ('unix', 'Classic Unix', '#000000', '#ffffff'),
        ('linux', 'Linux console', '#aaaaaa', '#000000'),
        ('ubuntu', 'Ubuntu', '#eeeeec', '#300a24'),
        ('freebsd', 'FreeBSD console', '#c0c0c0', '#000020'),
        ('macos', 'macOS Basic', '#000000', '#ffffff'),
        ('aix', 'AIX green', '#00cc66', '#001008'),
        ('ocean', 'Ocean blue', '#b8e8ff', '#001b33'),
    ]
    return [dict(id=key, name=name, options=dict(foreground=fg, background=bg,
                 cursor_color=fg, cursor_shape='block', cursor_blink=True,
                 font_family='monospace', font_size=12)) for key, name, fg, bg in themes]
