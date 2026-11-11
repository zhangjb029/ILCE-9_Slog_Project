"""Validate the A9 6.00 native electronic-shutter flash policy, offline.

Index 0x45 is a key inside a table, never a byte offset or a separate PID.
These checks describe the known A9 table format; they do not certify hardware
behavior or that a changed configuration will be adopted on the next boot.
"""
import io
import struct
from dataclasses import dataclass

from pmca.backup import BackupFile

PID = 0x00020008
INDEX = 0x45
SIZE = 1024
TAG = 20160707
COUNT = 104


@dataclass(frozen=True)
class Configuration:
    value: int
    value_offset: int


def parse(data: bytes) -> Configuration:
    if len(data) != SIZE or data[:4] != b'BIN!':
        raise ValueError('00020008 必须是 1024 字节的 BIN! 配置表')
    enabled, used, tag, count = struct.unpack_from('<IIII', data, 4)
    if (enabled, used, tag, count) != (1, 856, TAG, COUNT):
        raise ValueError('配置表启用标志、版本、长度或记录数与已研究的 A9 6.00 格式不符')
    end = 20 + count * 8
    if data[end:end+4] != b'FIN!':
        raise ValueError('配置表 FIN! 结束标记无效')
    found = None
    indices = set()
    for i in range(count):
        index, value = struct.unpack_from('<II', data, 20 + i*8)
        if index in indices or index > 0x6a:
            raise ValueError('配置表含重复或超出已知范围的索引')
        indices.add(index)
        if index == INDEX:
            found = Configuration(value, 24 + i*8)
    if found is None or found.value not in (0, 1):
        raise ValueError('找不到唯一的闪光限制索引 45，或其值不是已知的 0/1')
    return found


def with_policy(data: bytes, value: int) -> bytes:
    config = parse(data)
    if value not in (0, 1):
        raise ValueError('闪光限制只接受已研究的 0/1 值')
    target = bytearray(data)
    struct.pack_into('<I', target, config.value_offset, value)
    return bytes(target)


def from_backup(snapshot: bytes) -> bytes:
    """Verify the complete Backup checksum and this property's exact metadata."""
    try:
        backup = BackupFile(io.BytesIO(snapshot))
        if backup.revision != 4 or not 0x100 <= backup.size <= len(snapshot):
            raise ValueError('Backup 长度或修订版本不符')
        prop = backup.getProperty(PID)
        if prop.attr != 0:
            raise ValueError(f'00020008 属性标志不是已核验的 0（实际 {prop.attr:#x}），停止')
        data = bytes(prop.data)
        parse(data)
        return data
    except Exception as error:
        raise ValueError(f'无法验证原始 Backup 中的闪光限制配置：{error}') from error
