"""Turn exceptions into one sentence the user can act on.

The user is not a developer: an exception type and a stack trace tell them
nothing. Every message here answers "what do I do next".
"""

# Matched against "<ExceptionType>: <message>". First hit wins.
FAILURE_HINTS = (
    (
        'Service device not found',
        '相机已经切到服务模式，但 Windows 还没给这个新设备装驱动。\n'
        '请打开 Zadig → Options → List All Devices，选新出现的 Sony 设备 → 安装 libusb-win32，'
        '装好后点「重试」。相机不要拔线。',
    ),
    (
        'Camera busy during identity request',
        '读相机信息超时（相机一直回「忙」）。常见原因有三种：相机还停在上一次的服务模式、'
        'USB 驱动被换过、或者有别的软件（Imaging Edge 之类）正占用相机。\n'
        '处理：关机再开机 → 拔掉 USB 重插 → 关掉其他占用相机的软件 → 再点「连接并检查」。',
    ),
    (
        '没找到相机',
        '没有找到相机。请确认三件事：\n'
        '① 相机已开机，USB 连接模式选的是「大容量存储」；\n'
        '② 已经用 Zadig 给这台相机装过 libusb-win32 驱动；\n'
        '③ 换一根数据线或换一个 USB 口再试。',
    ),
    (
        '找到多台相机',
        '现在连接了不止一台相机。请只连接一台 ILCE-9，拔掉其他相机和读卡器，再点「连接并检查」。',
    ),
    (
        'already in service mode',
        '相机停在服务模式，Windows 里没有它的存储设备。请把相机拔掉重插，回到「大容量存储」模式，再点「连接并检查」。',
    ),
    (
        'Only ILCE-9 with firmware 6.00',
        '这个工具只支持 ILCE-9 固件 6.00。你连接的机型或版本不符，已经停止，没有写入任何东西。\n'
        '其他机型的参数地址不同，强行写入可能损坏相机配置。',
    ),
    (
        'Pipe error',
        'USB 传输出错，通常是线缆或 USB 口不稳。请换一个 USB 口、重新插好线，再点「连接并检查」。',
    ),
    (
        'Multiple service devices',
        '同时出现了多台服务模式设备。请只连接一台相机，拔掉其它相机，再试一次。',
    ),
    (
        '放行位状态不一致',
        'PP 放行位的五个字节处于混合状态（一部分已开、一部分没开）。这个状态没有对应的安全写法，'
        '已停止。请先用「恢复全部原厂」，或者从备份恢复一次。',
    ),
    (
        '恢复冲突',
        '这个槽位的当前值既不是当初的原值、也不是写入的值——你可能在相机上手动改过它。'
        '为避免覆盖你后来的改动，恢复已停止。请先在相机上确认当前值。',
    ),
)

FALLBACK = (
    '遇到未预期的问题。请把窗口下方日志整段复制下来。\n'
    '相机可能已经发生了部分改动，请保留 sessions 目录，并在相机上确认功能是否正常。'
)


def user_message(error: BaseException) -> str:
    text = f'{type(error).__name__}: {error}'
    for needle, hint in FAILURE_HINTS:
        if needle in text:
            return hint
    return FALLBACK
