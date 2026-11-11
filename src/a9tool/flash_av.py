"""Experimental A9 6.00 AV eligibility configuration; default is read-only.

Requires the existing menu policy to be open before apply. Only 0003000B:AD
may change (0/1). No firmware, RAM, shooting commands or hardware-safety claim.
The attr8 callback may update runtime state before SAVE or power cycling.
"""
import argparse
import io
import struct
import sys
from pathlib import Path

from pmca.backup import BackupFile
from . import flash_config as menu_cfg
from . import journal, usbdev

PID, OFFSET, SIZE = 0x0003000B, 0xAD, 256


def parse(data: bytes) -> int:
    if len(data) != SIZE or data[OFFSET] not in (0, 1):
        raise ValueError('0003000B 必须为 256 字节，偏移 AD 必须为已研究的 0/1')
    return data[OFFSET]


def with_eligibility(data: bytes, value: int) -> bytes:
    parse(data)
    if value not in (0, 1):
        raise ValueError('AV 资格试验只接受 0/1')
    target = bytearray(data)
    target[OFFSET] = value
    return bytes(target)


def from_backup(snapshot: bytes) -> tuple[bytes, bytes]:
    menu = menu_cfg.from_backup(snapshot)
    try:
        backup = BackupFile(io.BytesIO(snapshot))
        prop = backup.getProperty(PID)
        if prop.attr != 8:
            raise ValueError(f'0003000B attr 应为 8，实际为 {prop.attr:#x}')
        data = bytes(prop.data)
        parse(data)
        return menu, data
    except Exception as error:
        raise ValueError(f'无法验证 AV 配置快照：{error}') from error


class AVGuard:
    """Two readable properties; one exact single-byte-difference write only."""
    def __init__(self, transport):
        self.transport = transport
        self.reads = {}
        self.menu = self.original = self.target = None
        self.write_attempted = self.write_ok = False
        self.save_allowed = self.save_attempted = False

    def arm(self, menu: bytes, original: bytes, target: bytes) -> None:
        if (self.target is not None or self.write_attempted
                or self.reads != {menu_cfg.PID: menu, PID: original}):
            raise ValueError('缺少匹配的两项现场读值，或本会话已使用写入额度')
        menu_cfg.parse(menu)
        value = parse(target)
        if target == original or with_eligibility(original, value) != target:
            raise ValueError('只允许改变 0003000B 偏移 AD，其余 255 字节必须相同')
        self.menu, self.original, self.target = bytes(menu), bytes(original), bytes(target)

    def allow_save(self) -> None:
        if (not self.write_ok or self.save_attempted
                or self.reads != {menu_cfg.PID: self.menu, PID: self.target}):
            raise ValueError('两项写后回读尚未核对，不能保存')
        self.save_allowed = True

    def sendSenserPacket(self, function, data, oData=None):
        if oData is not None or not isinstance(data, bytes):
            raise ValueError('AV 试验不接受非标准传输')
        allowed = function == 0x10 and data == struct.pack('<HHB', 0, 0x1F, 0)
        operation, pid = None, None
        if not allowed and function == 0x40 and len(data) >= 4:
            category, command = struct.unpack_from('<HH', data)
            body = data[4:]
            if category == 0x603:
                if command == 5:
                    allowed = body == b'\x01'
                elif command == 1 and len(body) == 4:
                    pid, = struct.unpack('<I', body)
                    allowed = pid in (menu_cfg.PID, PID)
                    operation = 'read'
                elif command == 2:
                    allowed = (self.target is not None and not self.write_attempted
                               and self.reads == {menu_cfg.PID:self.menu, PID:self.original}
                               and body == struct.pack('<I', PID) + self.target)
                    operation = 'write'
                elif command == 3:
                    allowed = (self.save_allowed and not self.save_attempted
                               and self.reads == {menu_cfg.PID:self.menu, PID:self.target}
                               and body == b'\0\0')
                    operation = 'save'
        if not allowed:
            raise ValueError('AV 试验报文被独立白名单拒绝')
        if operation == 'read':
            self.reads.pop(pid, None)  # An exception must invalidate stale observations.
        elif operation == 'write':
            self.write_attempted = True
            self.reads.clear()
        elif operation == 'save':
            self.save_attempted = True
            self.save_allowed = False
        response, reply = self.transport.sendSenserPacket(function, data)
        if operation == 'read' and response == 0:
            self.reads[pid] = bytes(reply)
        elif operation == 'write':
            self.write_ok = response == 0
        return response, reply


def _read(camera):
    snapshot = bytes(camera.getBackupPresetData(True))
    menu, data = from_backup(snapshot)
    if bytes(camera.readBackup(menu_cfg.PID)) != menu or bytes(camera.readBackup(PID)) != data:
        raise ValueError('现场属性与完整 Backup 快照不一致，停止')
    return snapshot, menu, data


def _record(root, action, state, identity, target=None, source=None):
    snapshot, menu, data = state
    payload = dict(property='0x0003000B', offset='0xAD', original=data.hex(),
                   menu_property='0x00020008', menu_original=menu.hex(),
                   menu_restriction=menu_cfg.parse(menu).value, av_eligibility=parse(data),
                   camera=dict(identity))
    if target is not None:
        payload['target'] = target.hex()
    if source is not None:
        payload['source_journal'] = str(Path(source).resolve())
    session = journal.create(Path(root), action, payload, snapshot)
    session.journal.update(write_attempted=False, save_attempted=False,
                           reboot_adoption_verified=False, physical_trigger_verified=False,
                           hardware_safety_verified=False)
    return journal.save(session)


def status(camera, identity, root):
    usbdev.check_identity(identity)
    session = _record(root, 'flash_av_status', _read(camera), identity)
    session.journal['state'] = 'READ_ONLY_COMPLETE'
    return journal.save(session)


def _check(camera, menu, data):
    if bytes(camera.readBackup(menu_cfg.PID)) != menu:
        raise ValueError('上层配置发生变化，停止')
    if bytes(camera.readBackup(PID)) != data:
        raise ValueError('AV 整项回读不一致，停止')


def _perform(camera, guard, identity, root, state, target, action, progress=None, source=None):
    if not isinstance(guard, AVGuard):
        raise ValueError('必须使用 AV 试验专用白名单')
    say = progress or (lambda _message: None)
    _, menu, original = state
    session = _record(root, action, state, identity, target, source)
    say(f'Journal: {session.directory / "journal.json"}')
    try:
        _check(camera, menu, original)
        if target == original:
            session.journal['state'] = 'ALREADY_AT_TARGET_NO_SAVE'
            return journal.save(session)
        guard.arm(menu, original, target)
        session.journal.update(state='WRITE_PENDING', write_attempted=True)
        journal.save(session)
        say(f'写入 0003000B：仅偏移 AD {parse(original)} → {parse(target)}；回调可能立即生效。')
        camera.writeBackup(PID, target)
        _check(camera, menu, target)
        session.journal.update(state='WRITE_VERIFIED', immediate_readback_verified=True)
        journal.save(session)
        guard.allow_save()
        session.journal.update(state='SAVE_PENDING', save_attempted=True)
        journal.save(session)
        camera.saveBackup(0)
        _check(camera, menu, target)
        session.journal.update(state='SAVED_AND_READBACK_VERIFIED', saved_readback_verified=True)
        return journal.save(session)
    except BaseException as error:
        session.journal.update(state='FAILED_REVIEW_REQUIRED', error=str(error), error_type=type(error).__name__)
        try:
            journal.save(session)
        except Exception as log_error:
            raise error from log_error
        raise


def apply(camera, guard, identity, root, progress=None):
    usbdev.check_identity(identity)
    state = _read(camera)
    if menu_cfg.parse(state[1]).value != 0:
        raise ValueError('索引 45 尚未开放；本入口只改第二处，不自动改变上层规则')
    return _perform(camera, guard, identity, root, state, with_eligibility(state[2], 1),
                    'flash_av_apply', progress)


def load_source(path):
    session = journal.load(Path(path))
    if session.action != 'flash_av_apply':
        raise ValueError('恢复需指定 flash_av_apply 日志')
    menu, original = from_backup((session.directory / 'Backup-original.bin').read_bytes())
    target = with_eligibility(original, 1)
    payload = session.payload
    if (menu_cfg.parse(menu).value != 0 or payload.get('property') != '0x0003000B'
            or payload.get('offset') != '0xAD' or payload.get('menu_property') != '0x00020008'
            or payload.get('menu_original') != menu.hex() or payload.get('menu_restriction') != 0
            or payload.get('av_eligibility') != parse(original)
            or payload.get('original') != original.hex() or payload.get('target') != target.hex()):
        raise ValueError('恢复日志与原始快照不符')
    usbdev.check_identity(payload.get('camera', {}))
    return session, original, target


def restore(camera, guard, identity, root, source, progress=None):
    usbdev.check_identity(identity)
    prior, original, target = load_source(source)
    if prior.payload['camera'] != identity:
        raise ValueError('恢复日志属于另一台相机或固件版本')
    state = _read(camera)
    if state[2] not in (original, target):
        raise ValueError('恢复冲突：AV 整项既非原值也非目标，不覆盖其他改变')
    return _perform(camera, guard, identity, root, state, original, 'flash_av_restore', progress, source)


def current(camera) -> tuple[int, int]:
    """(upper-layer restriction, AV eligibility) as read now."""
    _snapshot, menu, data = _read(camera)
    return menu_cfg.parse(menu).value, parse(data)


def restore_baseline(camera, guard, identity, root, original, progress=None):
    """Write back the value captured at first read. No journal to choose from."""
    usbdev.check_identity(identity)
    if not isinstance(guard, AVGuard):
        raise ValueError('必须使用 AV 试验专用白名单')
    parse(original)
    state = _read(camera)
    return _perform(camera, guard, identity, root, state, bytes(original),
                    'flash_av_restore_baseline', progress)


def main(argv=None):
    parser = argparse.ArgumentParser(description='A9 6.00 第二处 AV 闪光资格试验；硬件安全未验证；默认只读')
    parser.add_argument('action', nargs='?', default='status', choices=('status', 'apply', 'restore'))
    parser.add_argument('--journal', type=Path, help='restore 使用的 flash_av_apply 日志')
    parser.add_argument('--sessions-root', type=Path, default=journal.sessions_root() / 'flash_av')
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--flash-detached', action='store_true',
                        help='操作者确认热靴附件已拆下；软件不自动检测。apply/restore 必填')
    args = parser.parse_args(argv)
    if (args.action == 'restore') != (args.journal is not None):
        parser.error('restore 必须提供 --journal；其他操作不接受 --journal')
    if args.action in ('apply', 'restore') and not args.flash_detached:
        parser.error('写入可能立即生效；拆下热靴附件后使用 --flash-detached 确认')
    handle = None
    try:
        if args.action == 'restore':
            load_source(args.journal)
        print('实验配置：可能立即刷新运行状态。请在相机与闪光灯均关机时拆下热靴附件，再连接操作。')
        print('硬件安全、完整拍摄和物理引闪尚未验证；恢复需要服务接口仍能连接。')
        handle = usbdev.connect(args.receipt or usbdev.load_current_receipt(),
                               progress=print, guard_factory=AVGuard)
        if args.action == 'status':
            result = status(handle.camera, handle.identity, args.sessions_root)
            print(f'上层索引 45 = {result.payload["menu_restriction"]}（0 为不施加此限制）')
            print(f'AV 偏移 AD = {result.payload["av_eligibility"]}（0 保留电子资格否决，1 通过此项检查）')
            print(f'只读备份：{result.directory / "journal.json"}')
        elif args.action == 'apply':
            result = apply(handle.camera, handle.guard, handle.identity, args.sessions_root, print)
        else:
            result = restore(handle.camera, handle.guard, handle.identity, args.sessions_root, args.journal, print)
        print(f'事务结果：{result.state}')
        if result.state == 'SAVED_AND_READBACK_VERIFIED':
            print('仅确认配置保存及回读。先保持热靴空置，结束服务会话后正常关机再开机；见 docs/FLASH_AV_TRIAL.zh-CN.md。')
        elif result.state == 'ALREADY_AT_TARGET_NO_SAVE':
            print('已是目标，无写入或保存；本次日志不代表更早的原厂基线。')
        return 0
    except KeyboardInterrupt:
        print('已中止；没有自动重试或回滚，请保留日志。', file=sys.stderr)
        return 130
    except Exception as error:
        print(f'已停止：{error}\n没有自动重试或回滚；请保留日志。', file=sys.stderr)
        return 1
    finally:
        if handle is not None:
            handle.close()


if __name__ == '__main__':
    sys.exit(main())
