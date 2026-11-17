"""Validated OpenSSH options shared by storage, editors and the SSH adapter."""
import re
import shlex

ADVANCED_DEFAULTS = dict(proxy_jump='', alive_interval=30, alive_count=3,
                         identities_only='config', address_family='config', compression='config', extra_options='', forwards=[])


def extra_arguments(text):
    """Parse -o options without a shell; allow only independent client settings."""
    if not isinstance(text, str) or len(text) > 8192 or any(c in text for c in ('\x00', '\r')):
        raise ValueError('Invalid additional SSH options.')
    try:
        tokens = shlex.split(text)
    except ValueError:
        raise ValueError('Invalid quoting in additional SSH options.') from None
    allowed = {'kexalgorithms', 'hostkeyalgorithms', 'pubkeyacceptedalgorithms',
               'ciphers', 'macs', 'rekeylimit', 'ipqos', 'tcpkeepalive',
               'numberofpasswordprompts', 'fingerprinthash'}
    args = []
    seen = set()
    while tokens:
        token = tokens.pop(0)
        if token == '-o' and tokens:
            option = tokens.pop(0)
        elif token.startswith('-o'):
            option = token[2:]
        else:
            raise ValueError('Use -o Name=value for additional SSH options.')
        name, separator, value = option.partition('=')
        if not separator or name.lower() not in allowed:
            raise ValueError('Unsupported additional SSH option. Use the dedicated fields for connection settings.')
        if name.lower() in seen:
            raise ValueError('Duplicate additional SSH option.')
        if not value or not re.fullmatch(r'[A-Za-z0-9_+^*,@./: -]+', value):
            raise ValueError('Invalid additional SSH option value.')
        seen.add(name.lower())
        args += ['-o', option]
    return args


def validate_forwards(rules):
    if not isinstance(rules, list) or len(rules) > 100:
        raise ValueError('Use at most 100 SSH forwarding rules.')
    listeners = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {'enabled', 'type', 'bind', 'port', 'host', 'target_port'}:
            raise ValueError('Invalid SSH forwarding rule.')
        if type(rule['enabled']) is not bool or rule['type'] not in ('L', 'R', 'D'):
            raise ValueError('Invalid SSH forwarding type or state.')
        for key in ('port', 'target_port'):
            if type(rule[key]) is not int or not (0 if key == 'target_port' and rule['type'] == 'D' else 1) <= rule[key] <= 65535:
                raise ValueError('SSH forwarding ports must be between 1 and 65535.')
        for key in ('bind', 'host'):
            value = rule[key]
            if not isinstance(value, str) or len(value) > 253:
                raise ValueError('Invalid SSH forwarding address.')
            if key == 'host' and rule['type'] == 'D' and value == '':
                continue
            if value == '*' and key == 'bind':
                continue
            if not value or value.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_.:-]+', value):
                raise ValueError('Use a hostname or IP address for SSH forwarding.')
            if ':' in value:
                import ipaddress
                try:
                    ipaddress.IPv6Address(value)
                except ValueError:
                    raise ValueError('Invalid IPv6 forwarding address.') from None
        if rule['enabled']:
            listener = ('remote' if rule['type'] == 'R' else 'local', rule['bind'].lower(), rule['port'])
            if listener in listeners:
                raise ValueError('Duplicate SSH forwarding listener.')
            listeners.add(listener)


def forwarding_arguments(rules):
    validate_forwards(rules)
    args = []
    def address(value):
        return f'[{value}]' if ':' in value else value
    for rule in rules:
        if not rule['enabled']:
            continue
        spec = f"{address(rule['bind'])}:{rule['port']}"
        if rule['type'] != 'D':
            spec += f":{address(rule['host'])}:{rule['target_port']}"
        args += ['-' + rule['type'], spec]
    if args:
        args += ['-o', 'ExitOnForwardFailure=yes', '-o', 'ControlMaster=no', '-o', 'ControlPath=none']
    return args


def validate_advanced(options):
    if not isinstance(options, dict) or set(options) - set(ADVANCED_DEFAULTS):
        raise ValueError('Invalid advanced SSH options.')
    for key, value in options.items():
        if key == 'forwards':
            validate_forwards(value)
        elif key == 'extra_options':
            extra_arguments(value)
        elif key == 'proxy_jump':
            if not isinstance(value, str) or len(value) > 1024:
                raise ValueError('Invalid jump host.')
            for jump in value.split(',') if value else []:
                match = re.fullmatch(r'(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?(?:[A-Za-z0-9_][A-Za-z0-9_.-]*|\[[0-9A-Fa-f:]+\])(?::([0-9]+))?', jump)
                if not match or (match[1] is not None and not 1 <= int(match[1]) <= 65535):
                    raise ValueError('Use jump hosts as [user@]host[:port], separated by commas.')
        elif key in ('alive_interval', 'alive_count'):
            if type(value) is not int or not (0 if key == 'alive_interval' else 1) <= value <= (3600 if key == 'alive_interval' else 100):
                raise ValueError('Invalid SSH keepalive value.')
        elif value not in (('config', 'any', 'inet', 'inet6') if key == 'address_family' else ('config', 'yes', 'no')):
            raise ValueError('Invalid advanced SSH choice.')


def advanced_arguments(options):
    validate_advanced(options)
    args = []
    names = dict(proxy_jump='ProxyJump', alive_interval='ServerAliveInterval', alive_count='ServerAliveCountMax',
                 identities_only='IdentitiesOnly', address_family='AddressFamily', compression='Compression')
    for key, value in options.items():
        if key == 'forwards':
            args += forwarding_arguments(value)
            continue
        if key == 'extra_options':
            args += extra_arguments(value)
            continue
        if value != '' and value != 'config':
            args += ['-o', f'{names[key]}={value}']
    return args
