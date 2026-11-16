"""5 GHz access points: one Backup byte, 00A5000C 09 -> 03.

The A9 already carries an XR77 regulatory configuration with 24 usable 5 GHz
channels (36-64, 100-140 by 4, and 149/153/157/161/165). The stock C-index
selects XR83, whose 5 GHz set is empty, so the camera never offers those
channels to a normal access point. Writing one byte picks the configuration the
camera already ships with.

Nothing is downloaded or replaced: no partition, no driver, no menu library, no
diagnostic component. The change goes through Sony's own Backup service and is
persisted with a normal SAVE, which — like any save — may also update the
Backup's own counters and checksums. That is why the whole backup is captured
before the write and why restore replays the recorded value rather than
rewriting that file.

What this does not claim: the power values are untouched, and selecting a
configuration is not a certification that every channel is legal where you are.
"""
from __future__ import annotations

import io
import struct
from pathlib import Path

from . import journal, usbdev

PID = 0x00A5000C
ORIGINAL = b'\x09'
TARGET = b'\x03'

# (property id, expected attr, expected length, expected resetData). The service
# refuses to touch anything whose metadata does not match what the research
# recorded, so a different firmware layout stops here instead of writing blind.
SPEC = (
    (0x00A5000B, 0, 1, None),
    (PID, 0, 1, None),
    (0x00A50009, 0, 1, None),
    (0x00A5000A, 0, 1, None),
    (0x013E0061, 0x44, 2, b'\x00\x00'),
    (0x01071563, 0x44, 1, b'\x00'),
)
READ_IDS = tuple(pid for pid, *_ in SPEC)

# The values the one-byte change was researched against. apply refuses to run
# when any of these has moved, because the surrounding state would then be
# something nobody has tested.
COMPANIONS = {
    0x00A5000B: b'\x09',
    0x013E0061: b'\x00\x00',
    0x01071563: b'\x00',
    0x00A50009: b'\x00',
    0x00A5000A: b'\x00',
}

SNAPSHOT_LIMIT = 2 * 1024 * 1024


class WifiGuard:
    """One exact C-index write and one SAVE, each requiring the readback first."""

    def __init__(self, transport):
        self.transport = transport
        self.last_read = self.original = self.target = None
        self.write_attempted = self.write_ok = False
        self.save_allowed = self.save_attempted = False

    def arm(self, original: bytes, target: bytes) -> None:
        if (self.target is not None or self.write_attempted or self.last_read != original
                or (bytes(original), bytes(target)) not in ((ORIGINAL, TARGET), (TARGET, ORIGINAL))):
            raise ValueError('写入需要一个与 09↔03 匹配的现场原值，且本会话还没用过写入额度')
        self.original, self.target = bytes(original), bytes(target)

    def allow_save(self) -> None:
        if not self.write_ok or self.save_attempted or self.last_read != self.target:
            raise ValueError('必须先把值精确写下去并读回，才能请求保存')
        self.save_allowed = True

    def sendSenserPacket(self, function, data, oData=None):
        if oData is not None or not isinstance(data, bytes):
            raise ValueError('Wi-Fi 配置不接受非标准传输')
        allowed = function == 0x10 and data == struct.pack('<HHB', 0, 0x1f, 0)
        operation = None
        if not allowed and function == 0x40 and len(data) >= 4:
            category, command = struct.unpack_from('<HH', data)
            body = data[4:]
            if category == 0x603:
                if command == 5:
                    allowed = body == b'\x01'
                elif command == 1:
                    allowed = len(body) == 4 and struct.unpack('<I', body)[0] in READ_IDS
                    if allowed and struct.unpack('<I', body)[0] == PID:
                        operation = 'read'
                elif command == 2:
                    allowed = (self.target is not None and not self.write_attempted
                               and self.last_read == self.original
                               and body == struct.pack('<I', PID) + self.target)
                    operation = 'write'
                elif command == 3:
                    allowed = (self.save_allowed and not self.save_attempted
                               and self.last_read == self.target and body == b'\0\0')
                    operation = 'save'
        if not allowed:
            raise ValueError('Wi-Fi 配置报文被单字节白名单拒绝')
        if operation == 'write':
            # Consume the quota before sending: a failure may still have landed.
            self.write_attempted = True
            self.last_read = None
        elif operation == 'save':
            self.save_attempted = True
            self.save_allowed = False
        response, reply = self.transport.sendSenserPacket(function, data)
        if operation == 'read':
            self.last_read = bytes(reply) if response == 0 else None
        elif operation == 'write':
            self.write_ok = response == 0
        return response, reply


def parse_snapshot(snapshot: bytes) -> dict:
    """Pull the six properties out of a full Backup, checking each metadata field."""
    from pmca.backup import BackupFile
    backup = BackupFile(io.BytesIO(snapshot))
    if backup.revision != 4 or not 0x100 <= backup.size <= len(snapshot) <= SNAPSHOT_LIMIT:
        raise ValueError('完整备份的版本或大小不符合预期，没有写入')
    values = {}
    for pid, attr, length, reset in SPEC:
        entry = backup.getProperty(pid)
        if entry.attr != attr or len(entry.data) != length or entry.resetData != reset:
            raise ValueError(f'属性 {pid:#010x} 的元数据与记录不符，没有写入')
        values[pid] = bytes(entry.data)
    return values


def _read(camera):
    """Full snapshot plus a live read of each of the six properties."""
    snapshot = bytes(camera.getBackupPresetData(True))
    values = parse_snapshot(snapshot)
    for pid in READ_IDS:
        if bytes(camera.readBackup(pid)) != values[pid]:
            raise ValueError(f'现场属性 {pid:#010x} 与完整备份快照不一致，停止')
    return snapshot, values


def _recheck(camera, values: dict, target: bytes) -> None:
    # PID last: that exact final read is what arms WRITE (or SAVE) in the guard.
    for pid in READ_IDS:
        expected = target if pid == PID else values[pid]
        if bytes(camera.readBackup(pid)) != expected:
            raise ValueError(f'现场 {pid:#010x} 与期望值不符，停止')


def _prepare(root: Path, action: str, snapshot: bytes, values: dict, identity: dict,
             target: bytes, source: Path | None = None) -> journal.Session:
    """Create the session with the full Backup as its snapshot."""
    payload = dict(
        property='00A5000C',
        original_hex=values[PID].hex(),
        target_hex=target.hex(),
        values={f'{pid:08X}': value.hex() for pid, value in values.items()},
        camera=dict(identity),
        rf_verified=False,
        reboot_persistence_observed=False,
    )
    if source is not None:
        payload['source_journal'] = str(Path(source).resolve())
    session = journal.create(Path(root), action, payload, snapshot)
    session.journal.update(write_attempted=False, save_attempted=False)
    return journal.save(session)


def status(camera, identity: dict, root: Path) -> journal.Session:
    """Read the six properties and keep the full backup. Writes nothing."""
    usbdev.check_identity(identity)
    snapshot, values = _read(camera)
    session = _prepare(root, 'wifi_status', snapshot, values, identity, TARGET)
    session.journal['state'] = 'READ_ONLY_COMPLETE'
    return journal.save(session)


def _perform(camera, guard, identity, root, snapshot, values, target, action,
             progress, source=None) -> journal.Session:
    if not isinstance(guard, WifiGuard):
        raise ValueError('必须使用 5 GHz 配置专用报文白名单')
    say = progress or (lambda _message: None)
    session = _prepare(root, action, snapshot, values, identity, target, source)
    say(f'日志：{session.directory / "journal.json"}')
    current = values[PID]
    try:
        # Recheck after the backup and journal reached disk, even for a no-op.
        _recheck(camera, values, current)
        if current == target:
            session.journal['state'] = ('ALREADY_AT_ORIGINAL_NO_SAVE' if action == 'wifi_restore'
                                        else 'ALREADY_AT_TARGET_NO_SAVE')
            return journal.save(session)

        guard.arm(current, target)
        session.journal.update(state='WRITE_PENDING', write_attempted=True)
        journal.save(session)
        say(f'写入 00A5000C：{current.hex()} → {target.hex()}')
        camera.writeBackup(PID, target)
        _recheck(camera, values, target)
        session.journal.update(state='WRITE_VERIFIED', immediate_readback_verified=True)
        journal.save(session)
        guard.allow_save()
        session.journal.update(state='SAVE_PENDING', save_attempted=True)
        journal.save(session)
        say('正在保存…')
        camera.saveBackup(0)
        _recheck(camera, values, target)
        session.journal.update(state='SAVED_AND_READBACK_VERIFIED', saved_readback_verified=True)
        return journal.save(session)
    except BaseException as error:
        session.journal.update(state='FAILED_REVIEW_REQUIRED', error=str(error),
                               error_type=type(error).__name__)
        try:
            journal.save(session)
        except Exception as log_error:
            raise error from log_error
        raise


def apply(camera, guard: WifiGuard, identity: dict, root: Path, progress=None) -> journal.Session:
    """Select the 5 GHz-capable configuration: 00A5000C 09 -> 03."""
    usbdev.check_identity(identity)
    snapshot, values = _read(camera)
    if values[PID] not in (ORIGINAL, TARGET):
        raise ValueError(
            f'当前 00A5000C 是 {values[PID].hex()}，既不是原厂 09 也不是已解锁的 03，'
            '这个工具不处理这种状态，没有写入')
    if values[PID] == ORIGINAL:
        moved = [f'{pid:#010x}={value.hex()}' for pid, value in COMPANIONS.items()
                 if values[pid] != value]
        if moved:
            raise ValueError(
                '这项修改要求以下设置保持原厂值，而它们现在不是：'
                + '，'.join(moved)
                + '。请先在相机上恢复这些设置，或改用与当前状态相符的方案。没有写入。')
    return _perform(camera, guard, identity, root, snapshot, values, TARGET,
                    'wifi_apply', progress)


def load_source(path: Path):
    """Validate the journal a restore is about to rely on. No camera access."""
    session = journal.load(Path(path))
    if session.action not in ('wifi_apply', 'wifi_restore'):
        raise ValueError('恢复必须指定本工具 wifi_apply 操作的 journal.json')
    payload = session.payload
    if payload.get('property') != '00A5000C':
        raise ValueError('这份日志不是 5 GHz 配置写入的记录')
    recorded = payload.get('values', {}).get('00A5000C')
    if recorded not in ('09', '03'):
        raise ValueError('日志里记录的 00A5000C 值不是 09 或 03')
    usbdev.check_identity(payload.get('camera', {}))
    return session, bytes.fromhex(recorded)


def restore(camera, guard: WifiGuard, identity: dict, root: Path, source: Path,
            progress=None) -> journal.Session:
    """Put the recorded C-index back. Other properties are left as they are."""
    usbdev.check_identity(identity)
    prior, original = load_source(source)
    if prior.payload['camera'] != identity:
        raise ValueError('这份日志属于另一台相机或固件版本，恢复已停止')
    snapshot, values = _read(camera)
    current = values[PID]
    if current not in (ORIGINAL, TARGET):
        raise ValueError(
            f'恢复冲突：当前 00A5000C 是 {current.hex()}，既不是记录的 {original.hex()} '
            '也不是 03。为避免覆盖别的改动，已停止')
    return _perform(camera, guard, identity, root, snapshot, values, original,
                    'wifi_restore', progress, source)


def restore_to_original(camera, guard: WifiGuard, identity: dict, root: Path,
                        progress=None) -> journal.Session:
    """Put the stock C-index back without asking for a journal.

    There is only one original value and only one thing this module ever
    changes, so the value is known: 03 -> 09. A journal would add nothing but a
    file the user has to find.
    """
    usbdev.check_identity(identity)
    snapshot, values = _read(camera)
    current_value = values[PID]
    if current_value not in (ORIGINAL, TARGET):
        raise ValueError(
            f'恢复冲突：当前 00A5000C 是 {current_value.hex()}，既不是原厂 09 也不是解锁后的 03。'
            '为避免覆盖别的改动，已停止')
    return _perform(camera, guard, identity, root, snapshot, values, ORIGINAL,
                    'wifi_restore', progress)


def current(camera) -> bytes:
    """The C-index as it is right now."""
    _, values = _read(camera)
    return values[PID]
