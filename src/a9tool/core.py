"""The transaction engine: read the camera, write one property, verify, save.

Every writing function here follows the same shape — snapshot, persist, write,
read back, confirm nothing else moved, then SAVE(0) — because that is the shape
that was proven on hardware before this tool existed.
"""
from dataclasses import dataclass
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


def _perform(camera, session, pid: int, target: bytes, state: CameraState, say) -> journal.Session:
    """Write one property, confirm nothing else moved, then SAVE(0).

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

        others = {p: value for p, value in live.items() if p != pid}
        say('正在写入…')
        session.journal['state'] = 'WRITE_PENDING'
        journal.save(session)
        camera.writeBackup(pid, target)
        if bytes(camera.readBackup(pid)) != target:
            raise ValueError('写入后立即回读不一致')
        session.journal['state'] = 'WRITE_VERIFIED'
        journal.save(session)

        for other, expected in others.items():
            if bytes(camera.readBackup(other)) != expected:
                raise ValueError(f'一个不相关的参数被改动了（{other:#010x}），未保存')

        say('正在保存…')
        session.journal['state'] = 'SAVE_PENDING'
        journal.save(session)
        camera.saveBackup(0)

        if bytes(camera.readBackup(pid)) != target:
            raise ValueError('保存后回读与写入值不一致')
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
