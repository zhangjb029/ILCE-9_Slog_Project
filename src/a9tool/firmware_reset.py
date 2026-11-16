"""Force rollback: open the updater's version gate, then let Sony close it.

`/setting/updater/dat4` is a two-byte BCD record on nflasha2. It is the value
the body itself reports as "firmware version" — not a copy, the source. The
official updater refuses a package unless the body's version is lower than the
package's, so writing 5.00 there makes the stock 6.00 package installable
again. That reinstall replaces nflasha15/3/5/7 with factory code, which is the
only way to undo a partition-level change (the Creative Look build) without
shipping an image.

Two facts from hardware, not inference:

* 2026-10-25, on this project's camera: after dat4 was written to 5.00 the
  official 6.00 package re-flashed, and the body then refused every service
  connection with "Only ILCE-9 with firmware 6.00" — which proves dat4 is the
  reported value.
* 2026-11-17, same camera: the update ran to completion and dat4 was written
  back to 6.00 by the updater itself. So no manual close-out step is needed
  after a successful flash.

What the update also touches: the package ships a factory `/setting/Backup.bin`
(1,090,266 bytes, `0110_backup/.../CX79900_UC2.bin`) and `endupdate.sh` copies
it over the body's own before running `ud_keep_backup.elf`. So Fn slots, the
5 GHz byte and the 4:3 parameters are very likely reset too — but that has not
been checked property by property on a body, and it is not promised here.
"""
from __future__ import annotations

import io
import struct
from pathlib import Path

from . import journal

DAT4 = '/setting/updater/dat4'
# Read-only neighbours that let a user tell a stale dat4 from a failed one.
READ_EXTRA = frozenset({'/setting/updater/COMP'})
PFUNC_FILE_CONTROL = 0xFF01
FILE_WRITE = 1
FILE_READ = 2

V600 = b'\x00\x06'
V500 = b'\x00\x05'
LABELS = {V600: '6.00', V500: '5.00'}
SUPPORTED_MODEL = 'ILCE-9'


def describe(blob: bytes) -> str:
    """`00 06` -> '6.00'. Anything else is shown as the hex it actually is."""
    if len(blob) != 2:
        return f'长度异常（{len(blob)} 字节）'
    value, = struct.unpack('<H', bytes(blob))
    return LABELS.get(bytes(blob), f'{value:04x}')


def check_identity(identity: dict) -> None:
    """Model and serial only.

    This tab exists partly to get a body reporting 5.00 back to 6.00, so it
    cannot require 6.00 to connect — that would lock the tool out of the very
    state it creates. The model and the serial fingerprint still have to match.
    """
    if identity.get('model') != SUPPORTED_MODEL:
        raise ValueError('Only ILCE-9 is supported')
    serial = identity.get('serial_sha256', '')
    if len(serial) != 64 or any(c not in '0123456789abcdef' for c in serial):
        raise ValueError('Missing camera identity fingerprint')


class Dat4Guard:
    """FileControl only: reads from an allowlist, at most one 2-byte write.

    The write is armed with the exact two bytes the transaction decided on, so
    a sizing or argument bug cannot send a different version than the journal
    recorded.
    """

    def __init__(self, transport, allow_write=False):
        self.transport = transport
        self.allow_write = allow_write
        self.target: bytes | None = None
        self.writes = 0

    def arm(self, target: bytes) -> None:
        if not self.allow_write:
            raise ValueError('写入未解锁')
        if self.target is not None or self.writes:
            raise ValueError('本会话的写入额度已经用过')
        if len(target) != 2:
            raise ValueError('目标值必须恰好 2 字节')
        self.target = bytes(target)

    def sendSenserPacket(self, function, data, oData=None):
        if function == 0x10 and data == struct.pack('<HHB', 0, 0x1f, 0):
            return self.transport.sendSenserPacket(function, data)
        # oData is the sink PMCA hands over for FileControl reads. Dropping it
        # returns a zero-byte file and the caller would read "not 2 bytes".
        if function != PFUNC_FILE_CONTROL:
            raise ValueError('只允许文件控制通道')
        if len(data) < 4:
            raise ValueError('文件控制包长度异常')
        cmd, name_size = struct.unpack_from('<hh', data, 0)
        name = data[4:4 + name_size].rstrip(b'\0').decode('latin1')
        body = data[4 + name_size:]

        if cmd == FILE_READ:
            if name != DAT4 and name not in READ_EXTRA:
                raise ValueError(f'路径不在读取白名单内：{name!r}')
        elif cmd == FILE_WRITE:
            if not self.allow_write:
                raise ValueError('写入未解锁')
            if name != DAT4:
                raise ValueError(f'只允许写 {DAT4}，收到 {name!r}')
            if len(body) != 2:
                raise ValueError(f'写入必须恰好 2 字节，收到 {len(body)}')
            if self.target is None:
                raise ValueError('写入没有武装')
            if body != self.target:
                raise ValueError('写入内容与本次会话声明的目标不一致')
            self.writes += 1
            if self.writes > 1:
                raise ValueError('同一会话拒绝第二次写入')
        else:
            raise ValueError(f'文件控制命令 {cmd} 被拒绝')
        return self.transport.sendSenserPacket(function, data, oData)


def _read(camera, path: str = DAT4) -> bytes:
    buffer = io.BytesIO()
    camera.readFile(path, buffer)
    return buffer.getvalue()


def _require_two_bytes(blob: bytes, where: str) -> bytes:
    if len(blob) != 2:
        raise ValueError(f'{where} 读出 {len(blob)} 字节，不是预期的 2 字节，没有写入')
    return bytes(blob)


def status(camera, identity: dict, root: Path, progress=None) -> journal.Session:
    """Read dat4 and keep the two bytes. Writes nothing."""
    check_identity(identity)
    say = progress or (lambda _message: None)
    say('正在读取相机自报的版本号…')
    blob = _require_two_bytes(_read(camera), DAT4)
    session = journal.create(root, 'firmware_status', dict(
        dat4=blob.hex(), version=describe(blob), camera=dict(identity)), blob)
    session.journal['state'] = 'READ_ONLY_COMPLETE'
    return journal.save(session)


def _perform(camera, guard, identity, root, current: bytes, target: bytes,
             action: str, progress=None) -> journal.Session:
    if not isinstance(guard, Dat4Guard):
        raise ValueError('必须使用 dat4 专用报文白名单')
    say = progress or (lambda _message: None)
    session = journal.create(root, action, dict(
        dat4=current.hex(), version=describe(current),
        target=target.hex(), target_version=describe(target),
        camera=dict(identity)), current)
    session.journal.update(write_attempted=False)
    journal.save(session)
    say(f'日志：{session.directory / "journal.json"}')
    try:
        # The two bytes reached disk before this read, so a value that moved in
        # between is somebody else's change and not ours to overwrite.
        if _read(camera) != current:
            raise ValueError('再次读到的 dat4 与刚才不一致，可能有人在同时改动，已停止')
        if current == target:
            session.journal['state'] = 'ALREADY_AT_TARGET_NO_WRITE'
            return journal.save(session)

        guard.arm(target)
        session.journal.update(state='WRITE_PENDING', write_attempted=True)
        journal.save(session)
        say(f'写入 dat4：{current.hex()} → {target.hex()}（{describe(target)}）')
        camera.writeFile(DAT4, target)

        back = _read(camera)
        ok = back == target
        session.journal.update(
            state='WRITE_VERIFIED' if ok else 'READBACK_MISMATCH',
            readback=back.hex(), readback_version=describe(back))
        journal.save(session)
        if not ok:
            raise ValueError(
                f'写入后回读是 {back.hex()}（{describe(back)}），不是 {target.hex()}，'
                '已停止；请保留会话目录')
        return session
    except BaseException as error:
        session.journal.update(state='FAILED_REVIEW_REQUIRED', error=str(error),
                               error_type=type(error).__name__)
        try:
            journal.save(session)
        except Exception as log_error:
            raise error from log_error
        raise


def open_gate(camera, guard: Dat4Guard, identity: dict, root: Path,
              progress=None) -> journal.Session:
    """Write 5.00 so the stock 6.00 package will install over this body."""
    check_identity(identity)
    current = _require_two_bytes(_read(camera), DAT4)
    if current not in (V600, V500):
        raise ValueError(
            f'当前 dat4 是 {current.hex()}（版本 {describe(current)}），'
            '既不是原厂 6.00 也不是已打开的 5.00，这个工具不处理这种状态，没有写入')
    return _perform(camera, guard, identity, root, current, V500,
                    'firmware_open_gate', progress)


def close_gate(camera, guard: Dat4Guard, identity: dict, root: Path,
               progress=None) -> journal.Session:
    """Put 6.00 back without running the updater.

    Only for a body that was opened and then not updated, or whose update keeps
    failing. A successful update writes 6.00 itself.
    """
    check_identity(identity)
    current = _require_two_bytes(_read(camera), DAT4)
    if current not in (V600, V500):
        raise ValueError(
            f'当前 dat4 是 {current.hex()}（版本 {describe(current)}），'
            '既不是原厂 6.00 也不是已打开的 5.00，这个工具不处理这种状态，没有写入')
    return _perform(camera, guard, identity, root, current, V600,
                    'firmware_close_gate', progress)
