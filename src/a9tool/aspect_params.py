"""4:3 save parameters, which live in /setting/Backup.bin on nflasha2.

The four-aspect menu entry ships inside the nflasha15 image, but selecting 4:3
and actually saving needs these 51 backup properties: output sizes, pixel
counts and JPEG capacity pairs that the stock A9 never filled in for that slot.
Without them the entry appears, then saving hangs or reports zero frames.

This is a parameter write, not a partition replacement: per body, small, and
reversible from the recorded preimage.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import time
import uuid
from pathlib import Path

from . import journal

PFUNC_ADJUST = 0x40
CATEGORY = 0x603

ASPECT_PARAMS = (
    (0x50018, 'fc5d0000'),
    (0x50019, '233f0000'),
    (0x5001a, 'fc2d0000'),
    (0x5001b, 'b2200000'),
    (0x5001c, 'e0220000'),
    (0x5001d, 'cc150000'),
    (0x5002a, '88340000'),
    (0x5002b, 'd5200000'),
    (0x5002c, '681b0000'),
    (0x5002d, '21110000'),
    (0x5002e, '8a120000'),
    (0x5002f, '960b0000'),
    (0x5003c, 'a6260000'),
    (0x5003d, '28180000'),
    (0x5003e, '53130000'),
    (0x5003f, '140c0000'),
    (0x50040, '990d0000'),
    (0x50041, '7f080000'),
    (0x50088, 'd75c0000'),
    (0x500a6, '3f050000'),
    (0x500a7, '54030000'),
    (0x5011a, '792b0000'),
    (0x5011b, '2b1b0000'),
    (0x5011c, '83160000'),
    (0x5011d, '120e0000'),
    (0x5011e, '020f0000'),
    (0x5011f, '61090000'),
    (0x50138, '991e0000'),
    (0x50139, '1f130000'),
    (0x5013a, 'f60f0000'),
    (0x5013b, 'fa090000'),
    (0x5013c, 'cc0a0000'),
    (0x5013d, 'bf060000'),
    (0x50156, '96100000'),
    (0x50157, '5e0a0000'),
    (0x50158, '4b080000'),
    (0x50159, '2f050000'),
    (0x5015a, 'd6050000'),
    (0x5015b, 'a5030000'),
    (0x501bc, '15280000'),
    (0x50290, 'b00d400a004c8c00'),
    (0x50295, '700ad007008b5100'),
    (0x5029a, 'd006200500ea2200'),
    (0x502bd, 'd014a00f00324501'),
    (0x502c2, 'b00d400a004c8c00'),
    (0x502c7, '700ad007008b5100'),
    (0x502d2, 'b00d400a'),
    (0x502d7, '700ad007'),
    (0x502dc, 'd014a00f'),
    (0x50304, 'aeb90000'),
    (0x50305, '2a500000'),
)

PIDS = tuple(pid for pid, _ in ASPECT_PARAMS)
TARGETS = {pid: bytes.fromhex(value) for pid, value in ASPECT_PARAMS}


class AspectGuard:
    """Only the 51 aspect properties may be read or written, once per session for SAVE."""

    def __init__(self, transport):
        self.transport = transport
        self.wrote = False

    def sendSenserPacket(self, function, data, oData=None):
        if oData is not None or not isinstance(data, bytes):
            raise ValueError('不接受的传输方式')
        allowed = function == 0x10 and data == struct.pack('<HHB', 0, 0x1f, 0)
        if not allowed and function == PFUNC_ADJUST and len(data) >= 4:
            category, command = struct.unpack_from('<HH', data)
            body = data[4:]
            if category == CATEGORY:
                if command == 5:
                    allowed = body == b'\x01'
                elif command == 1:
                    allowed = len(body) == 4 and struct.unpack('<I', body)[0] in TARGETS
                elif command == 2 and len(body) >= 5:
                    pid = struct.unpack_from('<I', body)[0]
                    expected = TARGETS.get(pid)
                    allowed = expected is not None and len(body) - 4 == len(expected)
                    if allowed:
                        self.wrote = True
                elif command == 3:
                    allowed = self.wrote and body == b'\0\0'
                    if allowed:
                        self.wrote = False
        if not allowed:
            raise ValueError('参数报文被 4:3 白名单拒绝')
        return self.transport.sendSenserPacket(function, data)


def _read_all(camera) -> dict:
    return {pid: bytes(camera.readBackup(pid)) for pid in PIDS}


def _session(root: Path, label: str) -> Path:
    stamp = time.strftime('%Y%m%d_%H%M%S')
    folder = Path(root) / f'{label}_{stamp}_{uuid.uuid4().hex[:8]}'
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def status(camera, identity: dict, root: Path) -> dict:
    """Read the 51 values; writes nothing."""
    session = _session(root, 'aspect_status')
    current = _read_all(camera)
    pending = [hex(pid) for pid in PIDS if current[pid] != TARGETS[pid]]
    _write(session / 'status.json', dict(
        identity=identity, created_epoch=time.time(),
        differ=pending, total=len(PIDS),
        values={hex(pid): current[pid].hex() for pid in PIDS}))
    return dict(directory=session, differ=len(pending), total=len(PIDS))


def apply(camera, identity: dict, root: Path, progress=None) -> dict:
    """Write the 4:3 parameters, verify every one, then SAVE once."""
    say = progress or (lambda _message: None)
    session = _session(root, 'aspect_apply')
    say('正在读取当前的 4:3 参数…')
    before = _read_all(camera)
    _write(session / 'preimage.json', dict(
        identity=identity, created_epoch=time.time(),
        partition='/dev/nflasha2', file='/setting/Backup.bin',
        values={hex(pid): before[pid].hex() for pid in PIDS}))
    say(f'当前值快照：{session / "preimage.json"}')

    changed = [pid for pid in PIDS if before[pid] != TARGETS[pid]]
    if not changed:
        _write(session / 'result.json', dict(pass_=True, changed=0, already_at_target=True))
        return dict(directory=session, state='ALREADY_AT_TARGET_NO_SAVE', changed=0)

    say(f'正在写入 {len(changed)} 项参数…')
    for pid in changed:
        camera.writeBackup(pid, TARGETS[pid])
        if bytes(camera.readBackup(pid)) != TARGETS[pid]:
            _write(session / 'failure.json', dict(
                stage='write', property=hex(pid), write_attempted=True))
            raise ValueError(f'属性 {pid:#07x} 写入后回读不一致，已停止，未保存')

    say('正在保存…')
    camera.saveBackup(0)
    after = _read_all(camera)
    mismatch = [hex(pid) for pid in PIDS if after[pid] != TARGETS[pid]]
    ok = not mismatch
    _write(session / 'result.json', dict(
        pass_=ok, changed=len(changed), mismatch=mismatch, write_attempted=True))
    if not ok:
        raise ValueError('保存后仍有权重不符：' + ', '.join(mismatch))
    return dict(directory=session, state='SAVED_AND_READBACK_VERIFIED', changed=len(changed))


def restore(camera, identity: dict, root: Path, source: Path, progress=None) -> dict:
    """Put back the values recorded by one apply session."""
    say = progress or (lambda _message: None)
    record = json.loads((Path(source) / 'preimage.json').read_text(encoding='utf-8'))
    if record.get('identity', {}).get('serial_sha256') != identity.get('serial_sha256'):
        raise ValueError('这份参数备份属于另一台相机')

    session = _session(root, 'aspect_restore')
    say('正在写回参数备份…')
    changed = 0
    for pid in PIDS:
        value = bytes.fromhex(record['values'][hex(pid)])
        if bytes(camera.readBackup(pid)) != value:
            camera.writeBackup(pid, value)
            changed += 1
    if changed:
        camera.saveBackup(0)
    mismatch = [hex(pid) for pid in PIDS
                if bytes(camera.readBackup(pid)) != bytes.fromhex(record['values'][hex(pid)])]
    _write(session / 'result.json', dict(pass_=not mismatch, changed=changed, mismatch=mismatch))
    if mismatch:
        raise ValueError('恢复后仍有权重不符：' + ', '.join(mismatch))
    return dict(directory=session, state='SAVED_AND_READBACK_VERIFIED' if changed
                else 'ALREADY_AT_TARGET_NO_SAVE', changed=changed)
