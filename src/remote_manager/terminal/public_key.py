"""Derive and install the public half of a vault-managed OpenSSH key."""
import base64
import binascii
import hashlib
import re
import shlex
import struct


def public_key_from_private(private_key):
    # OpenSSH keeps the public blob outside the encrypted private payload.
    # Read only that blob. Passphrases and private material stay local.
    try:
        lines = private_key.strip().splitlines()
        if lines[0] != b'-----BEGIN OPENSSH PRIVATE KEY-----' or lines[-1] != b'-----END OPENSSH PRIVATE KEY-----':
            raise ValueError
        data = base64.b64decode(b''.join(lines[1:-1]), validate=True)
        magic = b'openssh-key-v1\x00'
        if not data.startswith(magic):
            raise ValueError
        data = data[len(magic):]
        for _ in range(3):  # Cipher, KDF and KDF options.
            _, data = ssh_string(data)
        if data[:4] != b'\x00\x00\x00\x01':
            raise ValueError
        blob, remainder = ssh_string(data[4:])
        payload, trailing = ssh_string(remainder)
        key_type, parameters = ssh_string(blob)
        if not payload or trailing or not parameters or not re.fullmatch(rb'(?:ssh|ecdsa|sk)-[a-zA-Z0-9@._-]+', key_type):
            raise ValueError
    except (ValueError, binascii.Error, IndexError, struct.error):
        raise ValueError('Unable to derive the public key from the imported OpenSSH key.') from None
    fingerprint = base64.b64encode(hashlib.sha256(blob).digest()).rstrip(b'=')
    return key_type + b' ' + base64.b64encode(blob) + b'\n', 'SHA256:' + fingerprint.decode('ascii')


def ssh_string(data):
    size, = struct.unpack_from('>I', data)
    end = 4 + size
    if end > len(data):
        raise ValueError
    return data[4:end], data[end:]


INSTALL_SCRIPT = r'''
set -eu
umask 077
IFS=' ' read -r type blob
test -n "$type" && test -n "$blob" || exit 1
cd "${HOME:?}"
test ! -L .ssh || exit 1
mkdir -p .ssh
chmod 700 .ssh
cd .ssh
mkdir .unircm-authorized-keys.lock
trap 'rmdir .unircm-authorized-keys.lock' EXIT
trap 'exit 1' HUP INT TERM
file=authorized_keys
test ! -L "$file" || exit 1
if test -e "$file"; then
    test -f "$file" || exit 1
    # Also detect keys preceded by authorized_keys options. Preserve restrictions.
    existing=$(awk -v type="$type" -v blob="$blob" '
        /^[[:space:]]*#/ { next }
        $1==type && $2==blob { print "yes"; exit }
        {
            line=$0
            sub(/^[[:space:]]+/, "", line)
            quoted=0
            for (i=1; i<=length(line); i++) {
                char=substr(line,i,1)
                if (quoted && char=="\\") { i++; continue }
                if (char=="\"") quoted=!quoted
                if (!quoted && char ~ /[[:space:]]/) {
                    rest=substr(line,i)
                    sub(/^[[:space:]]+/, "", rest)
                    split(rest, fields, /[[:space:]]+/)
                    if (fields[1]==type && fields[2]==blob) { print "yes"; exit }
                    break
                }
            }
        }
    ' "$file")
    if test "$existing" = yes; then
        printf 'UNIRCM_KEY_ALREADY_PRESENT\n'
        exit 0
    fi
fi
temp=$(mktemp .unircm-authorized-keys.XXXXXXXX)
trap 'rm -f "$temp"; rmdir .unircm-authorized-keys.lock' EXIT
if test -s "$file"; then
    cat "$file" >> "$temp"
    if test "$(tail -c 1 "$file" | wc -l)" -eq 0; then printf '\n' >> "$temp"; fi
fi
printf '%s %s\n' "$type" "$blob" >> "$temp"
chmod 600 "$temp"
mv -f "$temp" "$file"
printf 'UNIRCM_KEY_INSTALLED\n'
'''


def install_arguments(socket_path, host):
    return ['-F', '/dev/null', '-S', socket_path, '-o', 'ControlMaster=no',
            '-o', 'ProxyCommand=false', '-o', 'BatchMode=yes',
            '-o', 'ForwardAgent=no', '-T', '--', host,
            'sh -c ' + shlex.quote(INSTALL_SCRIPT)]
