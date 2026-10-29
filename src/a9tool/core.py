"""The transaction engine: read the camera, write one property, verify, save.

Every writing function here follows the same shape — snapshot, persist, write,
read back, confirm nothing else moved, then SAVE(0) — because that is the shape
that was proven on hardware before this tool existed.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import fnmap, journal, usbdev

READ_PIDS = (fnmap.OVERRIDE, usbdev.FEATURE_SELECTOR, usbdev.MENU_SELECTOR, *fnmap.SLOT_PIDS)

STATUS_ENABLED = 'enabled'
STATUS_DISABLED = 'disabled'
STATUS_MIXED = 'mixed'


@dataclass
class CameraState:
    snapshot: bytes
    override: bytes
    slots: dict[int, int]


def read_state(camera) -> CameraState:
    """Read the whole backup once, then the live value of each property we model.

    The snapshot is kept as the on-disk evidence of the pre-write state; the
    per-property reads are what the transaction actually compares against.
    """
    snapshot = camera.getBackupPresetData(True)
    override = bytes(camera.readBackup(fnmap.OVERRIDE))
    slots = {number: camera.readBackup(pid)[0] for number, pid in fnmap.FN_SLOTS.items()}
    return CameraState(snapshot, override, slots)


def override_status(state: CameraState) -> str:
    values = {state.override[offset] for offset in fnmap.OVERRIDE_OFFSETS}
    if values == {2}:
        return STATUS_ENABLED
    if 2 not in values:
        return STATUS_DISABLED
    return STATUS_MIXED


def _perform_many(camera, session, targets: dict[int, bytes], state: CameraState,
                  say) -> journal.Session:
    """Write the given properties, confirm nothing else moved, then SAVE(0).

    Shared by every write path. On any failure the session is left in
    FAILED_REVIEW_REQUIRED with the error recorded, never silently retried.
    """
    try:
        live = {p: bytes(camera.readBackup(p)) for p in READ_PIDS}
        if live[fnmap.OVERRIDE] != state.override:
            raise ValueError('机身参数在读取之后发生变化，已停止，没有写入')
        for number, prop in fnmap.FN_SLOTS.items():
            if live[prop] != bytes([state.slots[number]]):
                raise ValueError('机身参数在读取之后发生变化，已停止，没有写入')

        pending = {pid: target for pid, target in targets.items() if live.get(pid) != target}
        others = {p: value for p, value in live.items() if p not in targets}
        if not pending:
            session.journal['state'] = 'ALREADY_AT_TARGET_NO_SAVE'
            return journal.save(session)

        say('正在写入…')
        session.journal['state'] = 'WRITE_PENDING'
        journal.save(session)
        for pid, target in pending.items():
            camera.writeBackup(pid, target)
            if bytes(camera.readBackup(pid)) != target:
                raise ValueError(f'写入后立即回读不一致（{pid:#010x}）')
        session.journal['state'] = 'WRITE_VERIFIED'
        journal.save(session)

        for other, expected in others.items():
            if bytes(camera.readBackup(other)) != expected:
                raise ValueError(f'一个不相关的参数被改动了（{other:#010x}），未保存')

        say('正在保存…')
        session.journal['state'] = 'SAVE_PENDING'
        journal.save(session)
        camera.saveBackup(0)

        for pid, target in pending.items():
            if bytes(camera.readBackup(pid)) != target:
                raise ValueError(f'保存后回读与写入值不一致（{pid:#010x}）')
        for other, expected in others.items():
            if bytes(camera.readBackup(other)) != expected:
                raise ValueError(f'保存后一个不相关的参数发生了变化（{other:#010x}）')

        session.journal['state'] = 'SAVED_AND_READBACK_VERIFIED'
        return journal.save(session)
    except BaseException as error:
        session.journal['state'] = 'FAILED_REVIEW_REQUIRED'
        session.journal['error'] = str(error)
        journal.save(session)
        raise


def _perform(camera, session, pid: int, target: bytes, state: CameraState, say) -> journal.Session:
    return _perform_many(camera, session, {pid: target}, state, say)


def enable_override(camera, state: CameraState, root: Path, progress=None) -> journal.Session:
    """Turn on the five PP feature-override bytes. No Fn slot is touched."""
    say = progress or (lambda _message: None)
    status = override_status(state)
    if status == STATUS_MIXED:
        raise ValueError('放行位状态不一致：五个字节里只有一部分是 02，没有对应的安全写法')

    target_bytes = bytearray(state.override)
    for offset in fnmap.OVERRIDE_OFFSETS:
        target_bytes[offset] = 2
    target = bytes(target_bytes)

    payload = dict(original=state.override.hex(), target=target.hex(),
                   changed_offsets=list(fnmap.OVERRIDE_OFFSETS), written_by=None)
    session = journal.create(root, 'enable_override', payload, state.snapshot)

    if status == STATUS_ENABLED:
        session.journal['state'] = 'ALREADY_AT_TARGET_NO_SAVE'
        return journal.save(session)

    return _perform(camera, session, fnmap.OVERRIDE, target, state, say)


PIXEL_SHIFT_CONFIRMATION = (
    '像素转换多重拍摄实测会在拍摄第一张后卡死，需要拔电池才能恢复。\n'
    '确定继续吗？'
)


def _lookup(value: int) -> fnmap.FunctionItem:
    for item in fnmap.load_functions():
        if item.value == value:
            return item
    raise ValueError(f'{value:#04x} 不是相机 Fn 列表里的功能')


def write_slot(camera, state: CameraState, slot: int, value: int, root: Path,
               progress=None) -> journal.Session:
    """Put one saved value into one Fn slot. Requires the override already on."""
    say = progress or (lambda _message: None)
    if slot not in fnmap.FN_SLOTS:
        raise ValueError(f'Fn 槽位必须是 1-{max(fnmap.FN_SLOTS)}')
    item = _lookup(value)
    if override_status(state) != STATUS_ENABLED:
        raise ValueError('请先开启 PP 放行，再写入功能槽位')

    pid = fnmap.FN_SLOTS[slot]
    original = state.slots[slot]
    written_by = None
    for prior in journal.list_sessions(root):
        if prior.action == 'write_slot' and prior.payload.get('slot') == slot:
            written_by = prior.directory.name
            break

    payload = dict(
        slot=slot,
        property=hex(pid),
        original=f'{original:02x}',
        target=f'{value:02x}',
        symbol=item.symbol,
        status=item.status,
        confirmation_text=PIXEL_SHIFT_CONFIRMATION if item.status == fnmap.STATUS_KNOWN_BAD else '',
        written_by=written_by,
    )
    session = journal.create(root, 'write_slot', payload, state.snapshot)
    return _perform(camera, session, pid, bytes([value]), state, say)


# --------------------------------------------------------------------------
# restore
# --------------------------------------------------------------------------

def _restore_target(session: journal.Session, state: CameraState):
    """(property id, the value to write back, the value that must be there now)."""
    payload = session.payload
    if session.action == 'write_slot':
        slot = payload['slot']
        pid = fnmap.FN_SLOTS[slot]
        return pid, bytes.fromhex(payload['original']), bytes([state.slots[slot]]), bytes.fromhex(payload['target'])
    if session.action == 'enable_override':
        return fnmap.OVERRIDE, bytes.fromhex(payload['original']), state.override, bytes.fromhex(payload['target'])
    raise ValueError('这条记录没有可以恢复的内容')


def restore_session(camera, session: journal.Session, root: Path, progress=None) -> journal.Session:
    """Put back exactly what one earlier write changed."""
    say = progress or (lambda _message: None)
    journal.load(session.directory / 'journal.json')  # re-verifies the snapshot hash
    state = read_state(camera)
    pid, original, current, written = _restore_target(session, state)
    if current not in (original, written):
        raise ValueError('恢复冲突：这个槽位的当前值既不是记录的原值、也不是写入的值。'
                         '可能你在相机上手动改过它，恢复已停止。')

    payload = dict(original=current.hex(), target=original.hex(),
                   property=hex(pid), restored_from=session.directory.name)
    restored = journal.create(root, 'restore', payload, state.snapshot)
    return _perform(camera, restored, pid, original, state, say)


def save_baseline(state: CameraState, root=None) -> Path:
    """Record the pre-first-write state once. Never overwritten afterwards."""
    base = Path(root) if root is not None else journal.baseline_root()
    record_path = base / 'baseline.json'
    if record_path.exists():
        return record_path
    base.mkdir(parents=True, exist_ok=True)
    (base / 'Backup-baseline.bin').write_bytes(state.snapshot)
    record = dict(
        schema='a9tool-baseline-v1',
        created=datetime.now(timezone.utc).isoformat(timespec='seconds'),
        snapshot_sha256=journal.digest(state.snapshot),
        override=state.override.hex(),
        slots={str(number): value for number, value in state.slots.items()},
    )
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return record_path


def restore_baseline(camera, root: Path, progress=None, baseline_dir=None) -> journal.Session:
    """Put the whole camera back to the state recorded before this tool was first used."""
    say = progress or (lambda _message: None)
    base = Path(baseline_dir) if baseline_dir is not None else journal.baseline_root()
    record_path = base / 'baseline.json'
    if not record_path.exists():
        raise ValueError('还没有原厂基线记录，无法恢复全部原厂')
    record = json.loads(record_path.read_text(encoding='utf-8'))
    snapshot = base / 'Backup-baseline.bin'
    if not snapshot.exists() or journal.digest(snapshot.read_bytes()) != record.get('snapshot_sha256'):
        raise ValueError('原厂基线文件缺失或已损坏，恢复已停止')

    state = read_state(camera)
    targets = {}
    override = bytes.fromhex(record['override'])
    if state.override != override:
        targets[fnmap.OVERRIDE] = override
    for number, prop in fnmap.FN_SLOTS.items():
        wanted = record['slots'][str(number)]
        if state.slots[number] != wanted:
            targets[prop] = bytes([wanted])

    payload = dict(restored_from='baseline', properties=[hex(pid) for pid in targets])
    session = journal.create(root, 'restore_baseline', payload, state.snapshot)
    return _perform_many(camera, session, targets, state, say)
