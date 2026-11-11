"""The first-read snapshot the flash tab restores to.

Written once, on the first successful read, before any write is permitted. The
restore path deliberately does not offer a journal picker: the user gets "put
it back the way it was", not a list of transactions to reason about. The CLI
still restores from a named journal, because there the operator asked for it.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from . import flash_av, flash_config as menu_cfg, journal

SCHEMA = 'a9tool-flash-baseline-v1'
MENU_FILE = '00020008.bin'
AV_FILE = '0003000B.bin'


def root() -> Path:
    return journal.sessions_root() / 'flash_baseline'


def record_path() -> Path:
    return root() / 'baseline.json'


def save(snapshot: bytes, identity: dict) -> Path:
    """Persist both flash properties as first read. Never overwrites an existing one."""
    path = record_path()
    if path.exists():
        return path
    menu = menu_cfg.from_backup(snapshot)
    _menu, av = flash_av.from_backup(snapshot)
    folder = root()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / MENU_FILE).write_bytes(menu)
    (folder / AV_FILE).write_bytes(av)
    record = dict(
        schema=SCHEMA,
        created=datetime.now(timezone.utc).isoformat(timespec='seconds'),
        snapshot_sha256=journal.digest(snapshot),
        identity={key: identity.get(key) for key in ('model', 'firmware', 'serial_sha256')},
        menu_sha256=journal.digest(menu),
        av_sha256=journal.digest(av),
        menu_value=menu_cfg.parse(menu).value,
        av_value=flash_av.parse(av),
    )
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def load() -> dict | None:
    """Return the baseline, or None when it is absent, damaged, or unreadable."""
    path = record_path()
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if record.get('schema') != SCHEMA:
        return None
    folder = root()
    try:
        menu = (folder / MENU_FILE).read_bytes()
        av = (folder / AV_FILE).read_bytes()
    except OSError:
        return None
    if journal.digest(menu) != record.get('menu_sha256') or journal.digest(av) != record.get('av_sha256'):
        return None
    return dict(record=record, menu=menu, av=av)


def belongs_to(baseline: dict, identity: dict) -> bool:
    """A baseline recorded on another body must not be written to this one."""
    recorded = baseline['record'].get('identity') or {}
    return recorded.get('serial_sha256') == identity.get('serial_sha256')
