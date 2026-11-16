"""Name the build a partition dump contains, ignoring what the camera rewrites.

A whole-partition hash cannot answer this once the camera has booted: ext2's
mount counter and timestamps change at every start, so the same build hashes
differently on every body. Comparing the handful of files that actually differ
between releases does answer it, and it still works for a dump taken long after
the flash.
"""
from __future__ import annotations

import hashlib
import mmap
from functools import lru_cache
from pathlib import Path

from . import data
from .ext2 import Ext2Image

FINGERPRINT_FILE = 'version_fingerprints.json'


@lru_cache(maxsize=1)
def table() -> dict:
    return data.resource_json(FINGERPRINT_FILE)


def _digest(content) -> str | None:
    return None if content is None else hashlib.sha256(content).hexdigest()


def identify(blob) -> dict:
    """Match a dump against the known builds.

    ``blob`` may be bytes or an mmap; only the compared files are read.
    ``matched`` means every compared file agreed, so the label is exact.
    """
    known = table()
    # Identification is a diagnostic: a partition that cannot be parsed must
    # never turn a completed backup into a failed one.
    try:
        image = Ext2Image(blob)
        actual = {name: _digest(image.read_file(name)) for name in known['files']}
    except Exception as error:
        return dict(readable=False, matched=False, label=None,
                    note=f'{type(error).__name__}: {error}', mismatch=[])
    best_label, best_note, best_missing = None, '', None
    for version in known['versions']:
        missing = [name for name, expected in version['files'].items()
                   if actual.get(name) != expected]
        if best_missing is None or len(missing) < len(best_missing):
            best_label, best_note, best_missing = version['label'], version['note'], missing
        if not missing:
            break
    return dict(readable=True, matched=not best_missing, label=best_label,
                note=best_note, mismatch=best_missing or [])


def identify_file(path: Path) -> dict:
    """Identify without loading the whole partition into memory."""
    with Path(path).open('rb') as stream:
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            return identify(mapped)
