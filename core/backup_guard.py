import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Tuple


def measure_tree(path: str) -> Tuple[int, int]:
    total_count = 0
    total_bytes = 0
    for p in Path(path).rglob('*'):
        if p.is_file():
            total_count += 1
            total_bytes += p.stat().st_size
    return total_count, total_bytes


def verify_backup(src_dir: str, dst_dir: str) -> bool:
    src_count, src_bytes = measure_tree(src_dir)
    dst_count, dst_bytes = measure_tree(dst_dir)
    return (src_count, src_bytes) == (dst_count, dst_bytes)


def write_manifest(dst_dir: str, output_name: str = 'backup_manifest.txt') -> str:
    dst = Path(dst_dir)
    manifest = dst / output_name
    lines = []
    for p in sorted(dst.rglob('*')):
        if p.is_file() and p.name != output_name:
            rel = p.relative_to(dst).as_posix()
            lines.append(f"{p.stat().st_size}\t{rel}")
    manifest.write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')
    return str(manifest)


def write_hashes(dst_dir: str, output_name: str = 'backup_hashes.sha256') -> str:
    dst = Path(dst_dir)
    out = dst / output_name
    lines = []
    for p in sorted(dst.rglob('*')):
        if p.is_file() and p.name not in {'backup_manifest.txt', output_name}:
            rel = p.relative_to(dst).as_posix()
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            lines.append(f"{h} *{rel}")
    out.write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')
    return str(out)


def run_pre_refactor_backup(
    src_dir: str,
    dst_parent: str,
    prefix: str = 'navernews-tabsearch_pre_refactor_',
    verify_fn: Callable[[str, str], bool] = verify_backup,
) -> str:
    src = Path(src_dir)
    parent = Path(dst_parent)
    parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    dst = parent / f"{prefix}{ts}"

    if dst.exists():
        raise RuntimeError(f'backup target already exists: {dst}')

    shutil.copytree(src, dst)

    if not verify_fn(str(src), str(dst)):
        shutil.rmtree(dst, ignore_errors=True)
        raise RuntimeError('backup verification mismatch')

    write_manifest(str(dst))
    write_hashes(str(dst))
    return str(dst)
