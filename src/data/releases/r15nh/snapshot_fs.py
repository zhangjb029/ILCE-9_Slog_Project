"""Read-only ext2 snapshot helpers adapted from the A9 ext2 locator and build verifiers."""
import hashlib
from pathlib import Path
import struct


class Ext2:
    def __init__(self, path: Path):
        self._parse(path.read_bytes())

    @classmethod
    def from_bytes(cls, data):
        fs = cls.__new__(cls)
        fs._parse(data)
        return fs

    def _parse(self, data):
        self.data = data
        sb = self.data[1024:2048]
        assert struct.unpack_from('<H', sb, 56)[0] == 0xEF53, 'not ext2'
        self.log_block = struct.unpack_from('<I', sb, 24)[0]
        self.block_size = 1024 << self.log_block
        self.blocks = struct.unpack_from('<I', sb, 4)[0]
        self.inodes = struct.unpack_from('<I', sb, 0)[0]
        self.first_data = struct.unpack_from('<I', sb, 20)[0]
        self.blocks_per_group = struct.unpack_from('<I', sb, 32)[0]
        self.inodes_per_group = struct.unpack_from('<I', sb, 40)[0]
        self.inode_size = struct.unpack_from('<H', sb, 88)[0] or 128
        self.groups = (self.inodes + self.inodes_per_group - 1) // self.inodes_per_group
        gd_block = self.first_data + 1
        self.gd = []
        for i in range(self.groups):
            off = gd_block * self.block_size + i * 32
            bitmap, imap, itable = struct.unpack_from('<III', self.data, off)
            self.gd.append(dict(inode_table=itable))

    def inode(self, ino: int):
        grp = (ino - 1) // self.inodes_per_group
        idx = (ino - 1) % self.inodes_per_group
        off = self.gd[grp]['inode_table'] * self.block_size + idx * self.inode_size
        raw = self.data[off:off + self.inode_size]
        mode, size = struct.unpack_from('<HI', raw, 0)[0], struct.unpack_from('<I', raw, 4)[0]
        blocks = list(struct.unpack_from('<15I', raw, 40))
        return dict(mode=mode, size=size, blocks=blocks)

    def read_block(self, b: int) -> bytes:
        return self.data[b * self.block_size:(b + 1) * self.block_size]

    def inode_data(self, ino: int) -> bytes:
        n = self.inode(ino)
        bs = self.block_size
        out = bytearray()
        for b in n['blocks'][:12]:
            out += self.read_block(b)
        # single indirect
        b = n['blocks'][12]
        if b:
            for x in struct.unpack('<%dI' % (bs // 4), self.read_block(b)):
                if x:
                    out += self.read_block(x)
        # double indirect
        b = n['blocks'][13]
        if b:
            for x in struct.unpack('<%dI' % (bs // 4), self.read_block(b)):
                if x:
                    for y in struct.unpack('<%dI' % (bs // 4), self.read_block(x)):
                        if y:
                            out += self.read_block(y)
        return bytes(out[:n['size']])

    def lookup(self, path: str) -> int:
        ino = 2
        for part in path.split('/'):
            if not part:
                continue
            data = self.inode_data(ino)
            pos, found = 0, None
            while pos + 8 <= len(data):
                i, rec, name_len = struct.unpack_from('<IHB', data, pos)
                name = data[pos + 8:pos + 8 + name_len].decode('latin1')
                if i and name == part:
                    found = i
                    break
                if rec == 0:
                    break
                pos += rec
            if found is None:
                raise FileNotFoundError(path)
            ino = found
        return ino

    def extents(self, ino: int):
        """返回 [(镜像字节偏移, 长度)]，按文件逻辑顺序。"""
        n = self.inode(ino)
        bs = self.block_size
        out, remain = [], n['size']
        for b in n['blocks'][:12]:
            if remain <= 0:
                break
            take = min(bs, remain)
            out.append((b * bs, take))
            remain -= take
        if remain > 0 and n['blocks'][12]:
            for x in struct.unpack('<%dI' % (bs // 4), self.read_block(n['blocks'][12])):
                if remain <= 0:
                    break
                if x:
                    take = min(bs, remain)
                    out.append((x * bs, take))
                    remain -= take
        if remain > 0 and n['blocks'][13]:
            for x in struct.unpack('<%dI' % (bs // 4), self.read_block(n['blocks'][13])):
                if remain <= 0:
                    break
                if not x:
                    continue
                for y in struct.unpack('<%dI' % (bs // 4), self.read_block(x)):
                    if remain <= 0:
                        break
                    if y:
                        take = min(bs, remain)
                        out.append((y * bs, take))
                        remain -= take
        return out


def tree(fs):
    result={}
    def walk(ino,path):
        node=fs.inode(ino);kind=node['mode']&0xf000
        if kind==0x4000:
            data=fs.inode_data(ino);pos=0
            while pos+8<=len(data):
                child,rec,n=struct.unpack_from('<IHB',data,pos)
                assert rec>=8 and pos+rec<=len(data)
                name=data[pos+8:pos+8+n].decode('utf-8')
                if child and name not in ('.','..'):walk(child,path+'/'+name)
                pos+=rec
            content=None
        elif kind==0xa000 and node['size']<=60:
            group,index=divmod(ino-1,fs.inodes_per_group)
            at=fs.gd[group]['inode_table']*fs.block_size+index*fs.inode_size+40
            content=fs.data[at:at+node['size']]
        else:content=fs.inode_data(ino)
        result[path]=dict(inode=ino,mode=node['mode'],size=node['size'],
                          sha256=sha(content) if content is not None else None)
    walk(2,'')
    return result


def sha(data):return hashlib.sha256(data).hexdigest()


def raw_inode(fs,n):
 group,index=divmod(n-1,fs.inodes_per_group)
 offset=fs.gd[group]['inode_table']*fs.block_size+index*fs.inode_size
 return fs.data[offset:offset+fs.inode_size]


def metadata(fs,n):
 raw=raw_inode(fs,n)
 return dict(mode=struct.unpack_from('<H',raw,0)[0],uid=struct.unpack_from('<H',raw,2)[0],gid=struct.unpack_from('<H',raw,24)[0],links=struct.unpack_from('<H',raw,26)[0],flags=struct.unpack_from('<I',raw,32)[0])


def allocation_summary(fs):
    """Check primary ext2 free counters against the actual allocation bitmaps."""
    sb = fs.data[1024:2048]
    incompat, ro_compat = struct.unpack_from('<II', sb, 96)
    if (incompat & ~0x2 or ro_compat & ~0x7 or
            fs.blocks * fs.block_size > len(fs.data) or
            not 0 < fs.blocks_per_group <= fs.block_size * 8 or
            not 0 < fs.inodes_per_group <= fs.block_size * 8):
        raise ValueError('Unsupported ext2 allocation layout')
    groups = (fs.blocks-fs.first_data+fs.blocks_per_group-1)//fs.blocks_per_group
    if len(fs.gd) != groups:
        raise ValueError('Ext2 inode and block group geometry disagree')

    def free(bitmap, nbits):
        if not fs.first_data <= bitmap < fs.blocks or not 0 < nbits <= fs.block_size*8:
            raise ValueError('Invalid ext2 bitmap location or size')
        whole, rem = divmod(nbits, 8)
        data = fs.read_block(bitmap)
        used = int.from_bytes(data[:whole], 'little').bit_count()
        if rem:
            used += (data[whole] & ((1 << rem) - 1)).bit_count()
        return nbits-used

    mismatches = []
    free_blocks = free_inodes = 0
    for g in range(groups):
        offset = (fs.first_data+1)*fs.block_size + g*32
        bb, ib, _, stated_b, stated_i = struct.unpack_from('<IIIHH', fs.data, offset)
        actual_b = free(bb, min(fs.blocks_per_group, fs.blocks-fs.first_data-g*fs.blocks_per_group))
        actual_i = free(ib, min(fs.inodes_per_group, fs.inodes-g*fs.inodes_per_group))
        free_blocks += actual_b
        free_inodes += actual_i
        if (stated_b, stated_i) != (actual_b, actual_i):
            mismatches.append(dict(group=g, reported=[stated_b, stated_i], bitmap=[actual_b, actual_i]))
    reported = list(struct.unpack_from('<II', sb, 12))
    bitmap = [free_blocks, free_inodes]
    return dict(match=reported == bitmap and not mismatches, fields=['free_blocks','free_inodes'],
                superblock=reported, bitmap_totals=bitmap, groups_with_mismatch=mismatches,
                scope='primary ext2 summaries vs allocation bitmaps; not a full filesystem check')


def runtime_metadata_regions(fs):
    """Only observed ext2 lifecycle fields; all maps and file bytes stay protected.

    R14's normal SD import remounts /usr and writes the preallocated a9fl.so
    tail. This changes s_mtime/s_mnt_count and that inode's atime/ctime/mtime,
    without changing its size, permissions, block map or fixed code prefix.
    Other inode timestamps and all allocation bitmaps remain byte-exact.
    """
    sb = fs.data[1024:2048]
    log = struct.unpack_from('<I', sb, 24)[0]
    blocks, first, per_group = (struct.unpack_from('<I', sb, n)[0] for n in (4,20,32))
    incompat, ro_compat = struct.unpack_from('<II', sb, 96)
    if (len(sb)!=1024 or struct.unpack_from('<H', sb, 56)[0]!=0xef53 or log>2 or
            incompat & ~0x2 or ro_compat & ~0x7 or not 0<per_group<=(1024<<log)*8 or
            not first<blocks or blocks*(1024<<log)>len(fs.data)):
        raise ValueError('Unsupported ext2 comparison layout')
    groups = (blocks-first+per_group-1)//per_group
    group_table = (first+1)*(1024<<log)
    # Superblock: free counts, mount time, write time, mount count.
    # s_max_mnt_count, s_state, geometry, UUID and feature flags are excluded.
    allowed = [(1024+12,1024+20),(1024+44,1024+54)]
    allowed.extend((group_table+32*g+12,group_table+32*g+16) for g in range(groups))
    try:
        ino = fs.lookup('lib/a9fl.so')
    except FileNotFoundError:
        pass
    else:
        node = fs.inode(ino)
        if node['mode'] & 0xf000 != 0x8000:
            raise ValueError('a9fl.so is not a regular file')
        group,index = divmod(ino-1,fs.inodes_per_group)
        offset = fs.gd[group]['inode_table']*fs.block_size+index*fs.inode_size
        allowed.append((offset+8,offset+20))
    return sorted(allowed)


def metadata_only_delta(reference, actual):
    """Compare every byte except the explicitly named runtime metadata fields."""
    if len(reference) != len(actual):
        raise ValueError('Partition lengths differ')
    allowed = runtime_metadata_regions(Ext2.from_bytes(reference))
    a,b = memoryview(reference),memoryview(actual)
    pos=0; changed=[]
    for start,end in (*allowed,(len(a),len(a))):
        if start<pos or end>len(a) or a[pos:start]!=b[pos:start]:
            raise ValueError('Partition bytes differ outside known ext2 lifecycle metadata')
        changed.extend(i for i in range(start,end) if a[i]!=b[i])
        pos=end
    return changed
