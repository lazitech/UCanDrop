#!/usr/bin/python3
"""Inspect a UCanDrop source tree or native package without installing it."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import pwd
import re
import socket
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'.git', '__pycache__', 'build', 'dist', '.venv'}
PRIVATE_NAMES = {
    'RESTORE-MANIFEST.json', 'previous.json', 'validation_record.cms',
    'certificate.self-signed.pem', 'key.self-signed.pem',
    'certificate.pem', 'key.pem', 'network-session.json',
}
FORBIDDEN_SUFFIXES = {'.pcap', '.pcapng', '.key', '.pyc', '.pyo'}
HOME_PATH = re.compile(rb'/(?:home|Users)/[A-Za-z0-9_.-]+(?:/|\b)')
PHYSICAL_IFACE = re.compile(rb'\bwlp[0-9]+s[0-9]+(?:f[0-9]+)?\b')
PRIVATE_KEY = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----')


def private_tokens() -> list[bytes]:
    """Use the inspecting account's identifiers without embedding them in code."""
    account = pwd.getpwuid(os.getuid())
    candidates = {account.pw_name, socket.gethostname().split('.')[0]}
    generic = {'root', 'user', 'ubuntu', 'localhost', 'linux', 'test',
               'ucandrop', 'omdrop'}
    return [value.encode() for value in candidates
            if len(value) >= 4 and value.lower() not in generic]


def inspect_tree(root: Path, *, package: bool = False) -> list[str]:
    errors = []
    tokens = private_tokens()
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if any(part in IGNORED for part in relative.parts):
            continue
        if path.is_symlink():
            target = os.readlink(path)
            if not package:
                resolved = path.resolve()
                if os.path.isabs(target) or not resolved.is_relative_to(root.resolve()):
                    errors.append(f'{relative}: external source symlink')
            continue
        if not path.is_file():
            continue
        if path.name in PRIVATE_NAMES or path.suffix in FORBIDDEN_SUFFIXES:
            errors.append(f'{relative}: private/generated artifact name')
        data = path.read_bytes()
        if not package and data.startswith(b'\x7fELF'):
            errors.append(f'{relative}: prebuilt executable in source tree')
        if HOME_PATH.search(data):
            errors.append(f'{relative}: embedded account home path')
        if PHYSICAL_IFACE.search(data):
            errors.append(f'{relative}: embedded physical interface name')
        if PRIVATE_KEY.search(data):
            errors.append(f'{relative}: embedded private key')
        for token in tokens:
            if re.search(rb'(?<![A-Za-z0-9_])' + re.escape(token)
                         + rb'(?![A-Za-z0-9_])', data, re.IGNORECASE):
                errors.append(f'{relative}: inspecting account/device identifier')
                break
    return errors


def inspect_package(path: Path) -> list[str]:
    fields = subprocess.check_output(
        ['dpkg-deb', '-f', str(path), 'Package', 'Version', 'Architecture', 'Depends'],
        text=True)
    errors = []
    if not re.search(r'^Package: ucandrop$', fields, re.MULTILINE):
        errors.append('package: incorrect package name')
    if not re.search(r'^Version: 1\.2\.1(?:-[0-9]+)?$', fields, re.MULTILINE):
        errors.append('package: incorrect release version')
    for dependency in ('python3-gi', 'python3-libarchive-c', 'network-manager',
                       'pkexec', 'libnl-3', 'libpcap', 'libev', 'xdg-user-dirs'):
        if dependency not in fields:
            errors.append(f'package: missing dependency {dependency}')
    with tempfile.TemporaryDirectory(prefix='ucandrop-package-audit-') as temporary:
        extracted = Path(temporary)
        subprocess.run(['dpkg-deb', '-x', str(path), temporary], check=True)
        errors.extend(inspect_tree(extracted, package=True))
        for name in ('usr/bin/ucandrop',
                     'usr/lib/ucandrop/client/bin/airdrop-serve.py',
                     'usr/lib/ucandrop/client/bin/airdrop_notify.py',
                     'usr/lib/ucandrop/client/bin/receive_notify.py',
                     'usr/lib/ucandrop/client/bin/apple-ca/apple-aai-ca.pem',
                     'usr/lib/ucandrop/client/bin/apple-ca/apple-aai2-ca.pem',
                     'usr/lib/ucandrop/client/share/certs/apple_root_ca.pem',
                     'usr/lib/ucandrop/client/share/ucandrop-receiver.service',
                     'usr/lib/ucandrop/receiver/local_upload_completion.py',
                     'usr/lib/ucandrop/receiver/local_link_receiving.py',
                     'usr/lib/ucandrop/radio/owl',
                     'usr/lib/ucandrop/radio/omdrop-discoverable',
                     'usr/lib/ucandrop/radio/ucandrop-exec-reset.py',
                     'usr/share/polkit-1/actions/ucandrop-radio.policy',
                     'usr/lib/NetworkManager/conf.d/ucandrop-networkmanager.conf',
                     'usr/share/doc/ucandrop/THIRD_PARTY_NOTICES.md'):
            if not (extracted / name).exists():
                errors.append(f'package: required file missing: {name}')
        if (extracted / 'home').exists() or (extracted / 'root').exists():
            errors.append('package: contains a user home directory')
    # File extraction runs as the ordinary inspecting user. Check declared
    # archive ownership, not that temporary directory's ownership.
    listing = subprocess.check_output(['dpkg-deb', '-c', str(path)], text=True)
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] != 'root/root':
            errors.append('package: non-root archive ownership')
            break
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--package', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    errors = inspect_tree(root)
    if args.package is not None:
        errors.extend(inspect_package(args.package.resolve()))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print('Release audit passed: no private identities, account paths, physical '
          'interface names, captures or prebuilt source executables.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
