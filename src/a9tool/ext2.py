"""Just enough ext2 to read named files out of a partition dump.

The camera's /usr partition is ext2, so identifying what a dump contains means
reading the few files that differ between builds. That is all this does — no
allocation, no writing, no repair. A malformed image raises rather than
returning half-guessed bytes.
"""
from __future__ import annotations

import struct

EXT2_MAGIC = 0xEF53
SUPERBLOCK = 1024
MAX_FILE_BYTES = 64 * 1024 * 1024


class Ext2Image:
    def __init__(self, data: bytes):
        if len(data) < SUPERBLOCK + 2048:
            raise ValueError('分区数据太短，不是 ext2 镜像')
        superblock = data[SUPERBLOCK:SUPERBLOCK + 1024]
        magic, = struct.unpack_from('<H', superblock, 56)
        if magic != EXT2_MAGIC:
            raise ValueError('偏移 1080 不是 ext2 超级块 magic')
        self.data = data
        self.block_size = 1024 << struct.unpack_from('<I', superblock, 24)[0]
        self.inode_count = struct.unpack_from('<I', superblock, 0)[0]
        self.first_data_block = struct.unpack_from('<I', superblock, 20)[0]
        self.inodes_per_group = struct.unpack_from('<I', superblock, 40)[0]
        self.inode_size = struct.unpack_from('<H', superblock, 88)[0] or 128
        groups = (self.inode_count + self.inodes_per_group - 1) // self.inodes_per_group
        table_start = (self.first_data_block + 1) * self.block_size
        self.inode_tables = [
            struct.unpack_from('<I', data, table_start + index * 32 + 8)[0]
            for index in range(groups)
        ]

    # -- blocks and inodes -------------------------------------------------
    def _block(self, number: int) -> bytes:
        start = number * self.block_size
        return self.data[start:start + self.block_size]

    def _pointers(self, block_number: int) -> list:
        raw = self._block(block_number)
        return list(struct.unpack_from('<%dI' % (self.block_size // 4), raw))

    def _inode(self, number: int) -> dict:
        if not 1 <= number <= self.inode_count:
            raise ValueError('inode 编号超出范围')
        group = (number - 1) // self.inodes_per_group
        index = (number - 1) % self.inodes_per_group
        offset = self.inode_tables[group] * self.block_size + index * self.inode_size
        raw = self.data[offset:offset + self.inode_size]
        if len(raw) < 128:
            raise ValueError('inode 表超出分区范围')
        return dict(size=struct.unpack_from('<I', raw, 4)[0],
                    blocks=list(struct.unpack_from('<15I', raw, 40)))

    def inode_data(self, number: int) -> bytes:
        node = self._inode(number)
        if node['size'] > MAX_FILE_BYTES:
            raise ValueError('文件过大，不是预期的 ext2 内容')
        chunks, remaining = [], node['size']
        for block in node['blocks'][:12]:
            if remaining <= 0:
                break
            chunks.append(self._block(block))
            remaining -= self.block_size
        for level, block in ((1, node['blocks'][12]), (2, node['blocks'][13])):
            if remaining <= 0 or not block:
                continue
            for pointer in self._pointers(block):
                if remaining <= 0:
                    break
                if not pointer:
                    continue
                if level == 1:
                    chunks.append(self._block(pointer))
                    remaining -= self.block_size
                else:
                    for deep in self._pointers(pointer):
                        if remaining <= 0:
                            break
                        if deep:
                            chunks.append(self._block(deep))
                            remaining -= self.block_size
        return b''.join(chunks)[:node['size']]

    # -- paths -------------------------------------------------------------
    def lookup(self, path: str) -> int | None:
        inode = 2                       # the root directory is always inode 2
        for part in path.split('/'):
            if not part:
                continue
            inode = self._entry(inode, part)
            if inode is None:
                return None
        return inode

    def _entry(self, directory: int, want: str) -> int | None:
        data = self.inode_data(directory)
        position = 0
        while position + 8 <= len(data):
            child, record, name_length = struct.unpack_from('<IHB', data, position)
            name = data[position + 8:position + 8 + name_length].decode('latin1')
            if child and name == want:
                return child
            if not record:
                break
            position += record
        return None

    def read_file(self, path: str) -> bytes | None:
        inode = self.lookup(path)
        return None if inode is None else self.inode_data(inode)
