"""Shared validation for desktop connection profiles, independent of backends."""
import re


def validate_profile(profile):
    host = profile['host'].strip()
    if not re.fullmatch(r'[A-Za-z0-9_.:\[\]-]+', host) or host.startswith('-'):
        raise ValueError('Enter a hostname or IP address without spaces.')
    if not isinstance(profile['port'], int) or not 1 <= profile['port'] <= 65535:
        raise ValueError('Invalid desktop port.')
    if any(c in profile.get('username', '') for c in '\r\n\x00'):
        raise ValueError('Invalid username.')
