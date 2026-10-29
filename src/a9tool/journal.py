"""Session directories: one per write, snapshot first, journal second.

Every write lands its pre-write snapshot and its transaction record on disk
before a single byte goes to the camera, so a power cut, a USB drop or a bug
still leaves the user with the original values to restore from.
"""
import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 'a9tool-session-v1'


def _base_dir() -> Path:
    """Where sessions/ and baseline/ live.

    Frozen (onefile exe): next to the exe, never inside _MEIPASS, which is a
    temporary directory that disappears when the process exits.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def sessions_root() -> Path:
    return _base_dir() / 'sessions'


def baseline_root() -> Path:
    return _base_dir() / 'baseline'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Session:
    directory: Path
    journal: dict

    @property
    def state(self) -> str:
        return self.journal.get('state', '')

    @property
    def action(self) -> str:
        return self.journal.get('action', '')

    @property
    def created(self) -> str:
        return self.journal.get('created', '')

    @property
    def payload(self) -> dict:
        return self.journal.get('payload', {})


def _write_record(path: Path, record: dict, exclusive: bool) -> None:
    mode = 'x' if exclusive else 'w'
    with path.open(mode, encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def _write_snapshot(path: Path, snapshot: bytes) -> None:
    with path.open('xb') as stream:
        stream.write(snapshot)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != snapshot:
        raise IOError('Local snapshot verification failed; no write performed')


def create(root: Path, action: str, payload: dict, snapshot: bytes) -> Session:
    """Allocate a session directory and persist the pre-write state.

    Snapshot first, journal second: a half-created session must never look
    like a journal whose snapshot is missing.
    """
    root.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S%f-') + uuid.uuid4().hex[:8]
    directory = root / name
    directory.mkdir(parents=False, exist_ok=False)
    _write_snapshot(directory / 'Backup-original.bin', snapshot)
    record = dict(
        schema=SCHEMA,
        action=action,
        payload=payload,
        snapshot_sha256=digest(snapshot),
        state='ORIGINAL_SAVED',
        created=datetime.now(timezone.utc).isoformat(timespec='seconds'),
    )
    _write_record(directory / 'journal.json', record, exclusive=True)
    return Session(directory, record)


def save(session: Session) -> Session:
    _write_record(session.directory / 'journal.json', session.journal, exclusive=False)
    return session


def load(path: Path) -> Session:
    path = Path(path)
    record = json.loads(path.read_text(encoding='utf-8'))
    if record.get('schema') != SCHEMA:
        raise ValueError('Not a session journal of this tool')
    snapshot = path.parent / 'Backup-original.bin'
    if not snapshot.exists() or digest(snapshot.read_bytes()) != record.get('snapshot_sha256'):
        raise ValueError('Original snapshot is missing or changed')
    return Session(path.parent, record)


def list_sessions(root: Path) -> list[Session]:
    root = Path(root)
    if not root.exists():
        return []
    found = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name, reverse=True):
        record = entry / 'journal.json'
        if entry.is_dir() and record.exists():
            found.append(Session(entry, json.loads(record.read_text(encoding='utf-8'))))
    return found


def mark_chained(session: Session) -> bool:
    """True when this session's recorded original came from an earlier write."""
    written_by = session.payload.get('written_by')
    if not written_by:
        return False
    return Path(written_by).name != session.directory.name
