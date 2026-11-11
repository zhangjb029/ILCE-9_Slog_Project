"""One native Backup policy candidate, with a separate one-shot packet guard.

No firmware, arbitrary RAM, whole-Backup writes or protection commands are
allowed. Saved readback verifies configuration bytes, not physical triggering.
"""
import struct
from dataclasses import dataclass
from pathlib import Path

from . import flash_config as cfg
from . import journal, usbdev


class FlashGuard:
    """Permit reads and one exact, armed write; SAVE needs verified readback."""
    def __init__(self, transport):
        self.transport = transport
        self.last_read = None
        self.original = self.target = None
        self.write_attempted = self.write_ok = False
        self.save_allowed = self.save_attempted = False

    def arm(self, original: bytes, target: bytes) -> None:
        if self.target is not None or self.write_attempted or self.last_read != original:
            raise ValueError('写入尚无匹配的现场原值，或本次服务会话已经使用过写入额度')
        value = cfg.parse(target).value
        if target == original or cfg.with_policy(original, value) != target:
            raise ValueError('只允许改变索引 45 的 0/1 值，其余字节必须保持一致')
        self.original, self.target = bytes(original), bytes(target)

    def allow_save(self) -> None:
        if not self.write_ok or self.save_attempted or self.last_read != self.target:
            raise ValueError('尚未确认精确写后回读，不能保存')
        self.save_allowed = True

    def sendSenserPacket(self, function, data, oData=None):
        if oData is not None or not isinstance(data, bytes):
            raise ValueError('闪光配置不接受非标准传输')
        allowed = function == 0x10 and data == struct.pack('<HHB', 0, 0x1f, 0)
        operation = None
        if not allowed and function == 0x40 and len(data) >= 4:
            category, command = struct.unpack_from('<HH', data)
            body = data[4:]
            if category == 0x603:
                if command == 5:
                    allowed = body == b'\x01'
                elif command == 1:
                    allowed = body == struct.pack('<I', cfg.PID)
                    operation = 'read'
                elif command == 2:
                    allowed = (self.target is not None and not self.write_attempted
                               and self.last_read == self.original
                               and body == struct.pack('<I', cfg.PID) + self.target)
                    operation = 'write'
                elif command == 3:
                    allowed = (self.save_allowed and not self.save_attempted
                               and self.last_read == self.target and body == b'\0\0')
                    operation = 'save'
        if not allowed:
            raise ValueError('闪光配置报文被独立白名单拒绝')
        if operation == 'write':
            # Consume before sending: an exception may mean a partially completed write.
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


@dataclass(frozen=True)
class FlashState:
    snapshot: bytes
    data: bytes


def _read(camera) -> FlashState:
    snapshot = bytes(camera.getBackupPresetData(True))
    data = cfg.from_backup(snapshot)
    if bytes(camera.readBackup(cfg.PID)) != data:
        raise ValueError('现场属性与完整 Backup 快照不一致，停止')
    return FlashState(snapshot, data)


def _record(root, action, state, identity, target=None, source=None):
    payload = dict(property='0x00020008', index='0x45', restriction=cfg.parse(state.data).value,
                   original=state.data.hex(), camera=dict(identity))
    if target is not None:
        payload['target'] = target.hex()
    if source is not None:
        payload['source_journal'] = str(Path(source).resolve())
    session = journal.create(Path(root), action, payload, state.snapshot)
    session.journal.update(write_attempted=False, save_attempted=False,
                           reboot_adoption_verified=False, physical_trigger_verified=False)
    return journal.save(session)


def status(camera, identity: dict, root: Path) -> journal.Session:
    usbdev.check_identity(identity)
    state = _read(camera)
    session = _record(root, 'flash_status', state, identity)
    session.journal['state'] = 'READ_ONLY_COMPLETE'
    return journal.save(session)


def _perform(camera, guard, identity, root, state, target, action, progress, source=None):
    if not isinstance(guard, FlashGuard):
        raise ValueError('必须使用闪光配置专用报文白名单')
    say = progress or (lambda _message: None)
    session = _record(root, action, state, identity, target, source)
    say(f'Journal: {session.directory / "journal.json"}')
    try:
        # Recheck after backup and journal have reached disk, even for a no-op.
        if bytes(camera.readBackup(cfg.PID)) != state.data:
            raise ValueError('保存备份后机身配置发生变化，停止，没有写入')
        if target == state.data:
            session.journal['state'] = 'ALREADY_AT_TARGET_NO_SAVE'
            return journal.save(session)
        guard.arm(state.data, target)
        session.journal.update(state='WRITE_PENDING', write_attempted=True)
        journal.save(session)
        say('写入 00020008：只改变索引 45 的值…')
        camera.writeBackup(cfg.PID, target)
        if bytes(camera.readBackup(cfg.PID)) != target:
            raise ValueError('写后立即回读不一致，未请求保存')
        session.journal.update(state='WRITE_VERIFIED', immediate_readback_verified=True)
        journal.save(session)
        session.journal.update(state='SAVE_PENDING', save_attempted=True)
        journal.save(session)
        guard.allow_save()
        camera.saveBackup(0)
        if bytes(camera.readBackup(cfg.PID)) != target:
            raise ValueError('保存后回读不一致，停止')
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


def apply(camera, guard: FlashGuard, identity: dict, root: Path, progress=None) -> journal.Session:
    """Select native NOT_RESTRICTED; do not promise adopted state or flash output."""
    usbdev.check_identity(identity)
    state = _read(camera)
    return _perform(camera, guard, identity, root, state, cfg.with_policy(state.data, 0),
                    'flash_apply', progress)


def load_source(path: Path):
    """Validate restoration material before any camera access."""
    session = journal.load(Path(path))
    if session.action != 'flash_apply':
        raise ValueError('恢复必须指定本工具 flash_apply 操作的 journal.json')
    original = cfg.from_backup((session.directory / 'Backup-original.bin').read_bytes())
    target = cfg.with_policy(original, 0)
    payload = session.payload
    if (payload.get('property') != '0x00020008' or payload.get('index') != '0x45'
            or payload.get('original') != original.hex() or payload.get('target') != target.hex()):
        raise ValueError('恢复日志与经过 SHA256 校验的原始快照不符')
    usbdev.check_identity(payload.get('camera', {}))
    return session, original, target


def restore(camera, guard: FlashGuard, identity: dict, root: Path, source: Path,
            progress=None) -> journal.Session:
    usbdev.check_identity(identity)
    prior, original, target = load_source(source)
    if prior.payload['camera'] != identity:
        raise ValueError('恢复日志属于另一台相机或固件版本，停止')
    state = _read(camera)
    if state.data not in (original, target):
        raise ValueError('恢复冲突：当前完整属性既非记录原值也非记录目标，不覆盖其他配置变化')
    return _perform(camera, guard, identity, root, state, original, 'flash_restore', progress, source)


def current(camera) -> int:
    """The upper-layer restriction as it is now (0 = not applied)."""
    return cfg.parse(_read(camera).data).value


def restore_baseline(camera, guard: FlashGuard, identity: dict, root: Path, original: bytes,
                     progress=None) -> journal.Session:
    """Write back the value captured at first read. No journal to choose from."""
    usbdev.check_identity(identity)
    if not isinstance(guard, FlashGuard):
        raise ValueError('必须使用闪光配置专用报文白名单')
    cfg.parse(original)
    state = _read(camera)
    return _perform(camera, guard, identity, root, state, bytes(original),
                    'flash_restore_baseline', progress)
