"""Human-readable observations; file identity never proves runtime activation."""


def r15_text(record, *, runtime_note=True):
    record = record or {}
    state, label = record.get('state'), record.get('label')
    if state == 'current' and label == 'R15 NAME HELP' and record.get('state_validated') is True:
        text = 'R15NH：已安装（文件与配置校验通过）'
        if runtime_note:
            text += '；运行生效未验证，请冷重启后实机核对。'
        return text
    if state == 'stock' and label == 'stock':
        return 'R15NH：未安装；当前为原厂 6.00。'
    if state == 'legacy' and label:
        return 'R15NH：未安装；当前版本 ' + str(label) + '。'
    if state == 'conflict':
        text = 'R15NH：校验冲突，无法确认完整安装状态'
        if label:
            text += '（检测到 ' + str(label) + '）'
    else:
        text = 'R15NH：当前状态无法确认（未知、混合或未完成校验）'
    if record.get('reason'):
        text += '；原因：' + str(record['reason'])
    return text


def v8_text(result):
    result = result or {}
    r15 = result.get('r15') or ({'state': 'current', 'label': 'R15 NAME HELP', 'state_validated': True}
                              if result.get('r15nh_current') is True else {})
    lines = [r15_text(r15, runtime_note=False)]
    menu = result.get('menu') or {}
    state = menu.get('state')
    payload = menu.get('payload_state')
    preload = menu.get('preload_state')
    count = str(menu.get('payloads_present', '?')) + '/' + str(menu.get('payloads_expected', 3))
    if state == 'conflict' or payload == 'different':
        text = 'V8：校验冲突，不能确认完整部署'
    elif state == 'current' and menu.get('label') == 'V8':
        text = 'V8：已部署；载荷完整（' + count + '），预加载入口已启用'
    elif state == 'legacy' and menu.get('label'):
        text = 'V8：未部署；当前悬浮菜单为 ' + str(menu['label'])
    elif preload == 'v8':
        text = 'V8：部署不完整；入口已指向 V8，载荷 ' + count
    elif payload == 'complete':
        text = 'V8：文件完整（' + count + '），预加载入口未启用'
    elif payload == 'partial':
        text = 'V8：存在部分载荷（' + count + '），预加载入口未启用'
    elif payload == 'absent' and preload == 'inactive':
        text = 'V8：未部署（未发现 V8 载荷或预加载入口）'
    else:
        text = 'V8：当前状态无法确认（读取或校验未完成）'
    if menu.get('reason'):
        text += '；原因：' + str(menu['reason'])
    lines.append(text)
    if result.get('r15nh_current') is not True:
        lines.append('前置条件未满足：暂不允许部署 V8，须先部署并核对 R15NH。')
    elif menu.get('installable') is False:
        lines.append('当前菜单来源校验未通过，暂不允许部署 V8。')
    lines.append('以上为文件与入口状态；运行生效未验证。')
    return '\n'.join(lines)
