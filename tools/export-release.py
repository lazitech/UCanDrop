#!/usr/bin/python3
"""Create a checked source archive with stable, non-personal file metadata."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
EPOCH = 1791936000
spec = importlib.util.spec_from_file_location('verify_release', ROOT / 'tools/verify-release.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def exported_paths(root):
    return [path for path in sorted(root.rglob('*'))
            if not any(part in audit.IGNORED for part in path.relative_to(root).parts)]


def export(root: Path, destination: Path) -> Path:
    problems = audit.inspect_tree(root)
    if problems:
        raise RuntimeError('source release audit failed:\n' + '\n'.join(problems))
    version = (root / 'VERSION').read_text().strip()
    prefix = f'ucandrop-{version}'
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f'{prefix}-source.tar.gz'
    with archive.open('wb') as raw, gzip.GzipFile(filename='', mode='wb',
                                                fileobj=raw, mtime=EPOCH) as zipped:
        with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as output:
            base = tarfile.TarInfo(prefix)
            base.type = tarfile.DIRTYPE
            base.mode = 0o755
            base.mtime = EPOCH
            output.addfile(base)
            for path in exported_paths(root):
                relative = path.relative_to(root)
                info = tarfile.TarInfo(str(Path(prefix) / relative))
                info.mtime = EPOCH
                # Deliberately do not copy the exporting account, group or
                # host filesystem timestamps into distribution metadata.
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                if path.is_symlink():
                    info.type = tarfile.SYMTYPE
                    info.linkname = os.readlink(path)
                    info.mode = 0o777
                    output.addfile(info)
                elif path.is_dir():
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    output.addfile(info)
                elif path.is_file():
                    data = path.read_bytes()
                    info.size = len(data)
                    info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                    output.addfile(info, io.BytesIO(data))
    return archive


def checksums(directory: Path):
    lines = []
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.name != 'SHA256SUMS':
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            lines.append(f'{digest}  {path.name}\n')
    (directory / 'SHA256SUMS').write_text(''.join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    archive = export(ROOT, args.out.resolve())
    checksums(args.out.resolve())
    print(f'Exported {archive.name}; SHA256SUMS contains relative artifact names.')


if __name__ == '__main__':
    main()
