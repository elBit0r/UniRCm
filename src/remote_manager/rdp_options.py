"""Validated, non-secret RDP connection settings stored inside SQLCipher."""
DEFAULTS = dict(connection_speed=7, color_depth=32, resolution='automatic', width=1280,
                height=720, display='workspace', timeout=15, compression=True,
                wallpaper=False, font_smoothing=True, themes=True,
                full_window_drag=False, menu_animations=False, admin_session=False,
                smooth_scaling=True, clipboard=False, authentication='configured')


def validate_options(options):
    if not isinstance(options, dict) or options.keys() - DEFAULTS.keys():
        raise ValueError('Invalid RDP options.')
    choices = dict(connection_speed=range(1, 8), color_depth=(15, 16, 24, 32),
                   resolution=('automatic', 'fixed'), display=('workspace', 'detached'),
                   authentication=('configured', 'prompt_password', 'prompt_both'))
    for key, value in options.items():
        if key in choices:
            if type(value) is not type(DEFAULTS[key]) or value not in choices[key]:
                raise ValueError('Invalid RDP option: ' + key)
        elif key in ('width', 'height', 'timeout'):
            low, high = (1, 600) if key == 'timeout' else (320, 8192)
            if type(value) is not int or not low <= value <= high:
                raise ValueError('Invalid RDP option: ' + key)
        elif type(value) is not bool:
            raise ValueError('Invalid RDP option: ' + key)


def effective_options(options):
    validate_options(options)
    return dict(DEFAULTS, **options)


def native_flags(options):
    keys = ('compression', 'wallpaper', 'font_smoothing', 'themes',
            'full_window_drag', 'menu_animations', 'admin_session', 'clipboard')
    return sum(1 << bit for bit, key in enumerate(keys) if options[key])


def desktop_size(options, width, height):
    if options['resolution'] == 'fixed':
        return options['width'], options['height']
    # Display-control widths must be even. Use logical pixels to avoid HiDPI oversizing.
    width = max(320, min(8192, width))
    return width - width % 2, max(320, min(8192, height))
