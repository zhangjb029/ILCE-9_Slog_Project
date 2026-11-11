"""Source entry: python -m a9tool.flash [status|apply|restore]."""
import argparse
import sys
from pathlib import Path

from . import flash_service as service
from . import journal, usbdev


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='A9 6.00 电子快门禁闪原生配置候选；默认只读')
    parser.add_argument('action', nargs='?', choices=('status', 'apply', 'restore'), default='status',
                        help='status 只读；apply 选择不限制；restore 从指定日志恢复')
    parser.add_argument('--journal', type=Path, help='restore 对应的 flash_apply journal.json')
    parser.add_argument('--sessions-root', type=Path, default=journal.sessions_root() / 'flash',
                        help='备份和日志保存目录（默认 sessions/flash）')
    parser.add_argument('--receipt', type=Path, help='服务模式切换失败后继续使用的身份凭据')
    args = parser.parse_args(argv)
    if (args.action == 'restore') != (args.journal is not None):
        parser.error('restore 必须提供 --journal；其他操作不接受 --journal')
    handle = None
    try:
        if args.action == 'restore':
            service.load_source(args.journal)
        print('实验配置工具：重启采用及物理引闪尚未实机验证。')
        handle = usbdev.connect(args.receipt or usbdev.load_current_receipt(),
                               progress=print, guard_factory=service.FlashGuard)
        if args.action == 'status':
            result = service.status(handle.camera, handle.identity, args.sessions_root)
            value = result.payload['restriction']
            print(f'索引 0x45 = {value}：' + ('强制禁闪' if value else '不施加这条禁闪限制'))
            print(f'只读备份：{result.directory / "journal.json"}')
        elif args.action == 'apply':
            result = service.apply(handle.camera, handle.guard, handle.identity, args.sessions_root,
                                   progress=print)
        else:
            result = service.restore(handle.camera, handle.guard, handle.identity, args.sessions_root,
                                     args.journal, progress=print)
        print(f'事务结果：{result.state}')
        if result.state == 'SAVED_AND_READBACK_VERIFIED':
            print('仅确认配置保存及精确回读。请正常关机再开机核查配置采用情况；实际引闪未验证。')
        elif result.state == 'ALREADY_AT_TARGET_NO_SAVE':
            print('配置已经等于目标，没有写入或保存。')
        return 0
    except KeyboardInterrupt:
        print('操作已中止，不自动重试或恢复。请保留备份和日志。', file=sys.stderr)
        return 130
    except Exception as error:
        print(f'已停止：{error}\n没有自动重试或恢复；请保留备份和日志。', file=sys.stderr)
        return 1
    finally:
        if handle is not None:
            handle.close()


if __name__ == '__main__':
    sys.exit(main())
