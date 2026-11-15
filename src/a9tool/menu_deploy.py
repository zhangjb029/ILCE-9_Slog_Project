"""Whole-partition deployment of the Creative Look (LUT) build.

No image is shipped. The tool reads the camera's own /dev/nflasha15, checks it
is byte-identical to the factory build, applies the R11 patch, verifies the
result against the hash the author accepted on hardware, and only then writes.
Both ends of the change are pinned by SHA256, so a partition in any other state
is refused rather than overwritten.

This is still not a parameter write. It replaces a 300 MiB partition in one
transfer; a previous attempt with a different layout left the camera
cold-starting with no menu at all.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import time
import uuid
import lzma
from functools import lru_cache
from pathlib import Path

from . import data, journal

PARTITION = '/dev/nflasha15'
PARTITION_BYTES = 314572800
PFUNC_FILE_CONTROL = 0xFF01
FILE_WRITE = 1
FILE_READ = 2
READ_EXTRA = frozenset({'/setting/updater/dat4', '/setting/updater/COMP'})
TRANSFER_TIMEOUT_SECONDS = 900

# The state every ILCE-9 at 6.00 leaves the factory in. Verified on hardware:
# the live partition was byte-identical to the official firmware's nflasha15
# padded with zeros to the full partition size, and this hash is what the
# successful deployment recorded as its preimage.
FACTORY_SHA = 'ed835ff938e5d9d816b611263d1e124c08eb907a883d08587170bdbd7c32f9d2'
# R11: 20 Creative Looks, plus PP and Gamma Display Assist moved onto page 14
# of Shooting Assist, with 照片效果 and 演示模式 restored to their own places.
LUT_SHA = '0676e29917bf3ef555df9c876eecc46e8e781d9a7e8f1c4b06c5ab225ef06a35'
PATCH_FILE = 'r11_patch.bin'

# Superseded builds this tool no longer produces. Recognising them lets the
# error message say what to do instead of only that the partition is unknown.
LEGACY_SHAS = {
    '4fa7bbe5c9cc21661c334fa5640af59a5d725f2214ee877112230c123f2eafa4':
        '旧版「菜单修改」（PP/S-Log/四比例 + 复古衣橱）',
    'cba78da44df413058f56db74b62305bda7d1de756d65ffd96b93d4e2659ef22e':
        '旧版「创意外观 FL」（实验）',
}

TARGETS = {
    'lut': (LUT_SHA, '创意外观 LUT（20 款 + 图片配置文件 + 伽玛显示辅助）'),
}

LABEL = TARGETS['lut'][1]


@lru_cache(maxsize=1)
def load_patch() -> tuple:
    """The 51,005 runs between the factory partition and the R11 build.

    Each run stores the replacement bytes and the distance from the previous
    run's offset. The input partition is pinned by SHA256, so the bytes being
    replaced never have to be carried in the program.
    """
    raw = lzma.decompress((data.data_root() / PATCH_FILE).read_bytes())
    if raw[:4] != b'R11P':
        raise ValueError('内置补丁格式不正确')
    count, = struct.unpack_from('<I', raw, 4)
    pos, offset, runs = 8, 0, []
    for _ in range(count):
        delta, length = struct.unpack_from('<II', raw, pos)
        pos += 8
        offset += delta
        runs.append((offset, raw[pos:pos + length]))
        pos += length
    if pos != len(raw):
        raise ValueError('内置补丁长度与声明不符')
    return tuple(runs)


def _apply(blob: bytes, patches) -> bytes:
    out = bytearray(blob)
    for offset, after in patches:
        out[offset:offset + len(after)] = after
    return bytes(out)


class PartitionGuard:
    """Reads from an allowlist; one whole-partition write, armed by the caller."""

    def __init__(self, transport, allow_write=False):
        self.transport = transport
        self.allow_write = allow_write
        self.writes = 0

    def sendSenserPacket(self, function, data, oData=None):
        if function == 0x10 and data == struct.pack('<HHB', 0, 0x1f, 0):
            return self.transport.sendSenserPacket(function, data)
        if function != PFUNC_FILE_CONTROL:
            raise ValueError('只允许文件控制通道')
        if len(data) < 4:
            raise ValueError('文件控制包长度异常')
        cmd, name_size = struct.unpack_from('<hh', data, 0)
        name = data[4:4 + name_size].rstrip(b'\0').decode('latin1')
        body = data[4 + name_size:]

        if cmd == FILE_READ:
            if name != PARTITION and name not in READ_EXTRA:
                raise ValueError(f'路径不在读取白名单内：{name!r}')
        elif cmd == FILE_WRITE:
            if not self.allow_write:
                raise ValueError('写入未解锁')
            if name != PARTITION:
                raise ValueError(f'只允许写 {PARTITION}，收到 {name!r}')
            if len(body) != PARTITION_BYTES:
                raise ValueError(f'写入必须恰好 {PARTITION_BYTES:,} 字节，收到 {len(body):,}')
            self.writes += 1
            if self.writes > 1:
                raise ValueError('同一会话拒绝第二次写入')
        else:
            raise ValueError(f'文件控制命令 {cmd} 被拒绝')
        return self.transport.sendSenserPacket(function, data)


def file_sha256(path: Path) -> str:
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sanity(blob: bytes) -> None:
    """Cheap structural checks: this must look like the /usr ext2 image."""
    if len(blob) != PARTITION_BYTES:
        raise ValueError(f'镜像长度 {len(blob):,} 不等于 {PARTITION_BYTES:,}')
    if blob[1080:1082] != b'\x53\xef':
        raise ValueError('偏移 1080 不是 ext2 超级块 magic')
    if any(blob[:1024]):
        raise ValueError('ext2 引导块非零，这可能不是预期分区')


def build_candidate(dump: bytes, target: str = 'lut') -> bytes:
    """Turn a factory partition into the requested build, in memory.

    The only accepted input is the untouched factory partition. Anything else
    is refused by hash, so an unexpected partition never reaches the camera.
    """
    sanity(dump)
    if target not in TARGETS:
        raise ValueError('未知的目标版本')
    want_sha = TARGETS[target][0]
    actual = hashlib.sha256(dump).hexdigest()
    if actual == want_sha:
        raise ValueError('分区已经是目标版本，不需要修改')
    if actual in LEGACY_SHAS:
        raise ValueError(
            f'相机上是{LEGACY_SHAS[actual]}，这个版本本工具不再生成。'
            '请先用「⑤ 回退」把初始备份写回相机（恢复原厂），再重新修补。')
    if actual != FACTORY_SHA:
        raise ValueError(
            '相机上的分区既不是原厂 6.00 状态、也不是本工具生成过的版本'
            '（SHA256 %s…），本工具只处理原厂状态，已停止' % actual[:16])

    blob = _apply(dump, load_patch())
    if hashlib.sha256(blob).hexdigest() != want_sha:
        raise ValueError('打补丁后的哈希与已验证镜像不符，已停止')
    return blob


def read_partition(camera, path: Path) -> dict:
    """Stream the whole partition to disk; a failed read keeps its partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        try:
            camera.readFile(PARTITION, stream)
        finally:
            stream.flush()
            os.fsync(stream.fileno())
    return dict(sha256=file_sha256(path), bytes=path.stat().st_size)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def record_path_for(path: Path) -> Path:
    return path.with_suffix('.json')


def _new_session(root: Path, label: str) -> Path:
    stamp = time.strftime('%Y%m%d_%H%M%S')
    folder = Path(root) / f'{label}_{stamp}_{uuid.uuid4().hex[:8]}'
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def baseline_path(root: Path) -> Path:
    return Path(root) / 'baseline' / 'preimage.bin'


def pending_dir(root: Path) -> Path:
    return Path(root) / 'pending'


def _move(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)


def backup(camera, identity: dict, root: Path, progress=None) -> dict:
    """Step 1: read the whole partition once and keep it as the baseline.

    Refuses to overwrite an existing baseline: everything else (patch, write,
    restore) is defined relative to this one capture.
    """
    say = progress or (lambda _message: None)
    target = baseline_path(root)
    if target.exists():
        raise ValueError('已经存在初始备份，不会覆盖')

    session = _new_session(root, 'backup')
    _write_json(session / 'request.json', dict(
        partition=PARTITION, identity=identity, created_epoch=time.time()))
    say('正在完整读取当前分区（约 300 MB，需要几分钟）…')
    snapshot = read_partition(camera, session / 'preimage.bin')
    _write_json(session / 'preimage.json', snapshot)
    if snapshot['bytes'] != PARTITION_BYTES:
        _write_json(session / 'failure.json', dict(
            stage='read_preimage', error='分区读取不完整', bytes=snapshot['bytes']))
        raise ValueError(f'分区读取不完整（{snapshot["bytes"]:,} 字节），已停止')

    _move(session / 'preimage.bin', target)
    meta = dict(sha256=snapshot['sha256'], bytes=snapshot['bytes'],
                from_session=session.name, identity=identity,
                created=time.strftime('%Y-%m-%dT%H:%M:%S'))
    _write_json(record_path_for(target), meta)
    return meta


def patch_from_baseline(root: Path, target: str = 'lut', progress=None) -> dict:
    """Step 2: build the target image from the baseline, locally. No camera."""
    say = progress or (lambda _message: None)
    baseline = baseline_path(root)
    if not baseline.exists():
        raise ValueError('还没有初始备份，请先执行初始备份')
    if target not in TARGETS:
        raise ValueError('未知的目标版本')

    say(f'正在本地生成：{TARGETS[target][1]}…')
    candidate = build_candidate(baseline.read_bytes(), target)
    out = pending_dir(root) / 'candidate.bin'
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('wb') as stream:
        stream.write(candidate)
        stream.flush()
        os.fsync(stream.fileno())
    meta = dict(target=target, label=TARGETS[target][1],
                sha256=hashlib.sha256(candidate).hexdigest(),
                bytes=len(candidate),
                baseline_sha256=file_sha256(baseline),
                created=time.strftime('%Y-%m-%dT%H:%M:%S'))
    _write_json(out.with_suffix('.json'), meta)
    return meta


def pending_info(root: Path) -> dict | None:
    out = pending_dir(root) / 'candidate.bin'
    meta_path = out.with_suffix('.json')
    if not out.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if file_sha256(out) != meta.get('sha256'):
        return None
    return meta


def write_candidate(camera, identity: dict, root: Path, progress=None) -> dict:
    """Step 3: write the image prepared in step 2, once, and verify the readback."""
    say = progress or (lambda _message: None)
    info = pending_info(root)
    if info is None:
        raise ValueError('还没有生成目标镜像，请先执行修补')
    candidate_path = pending_dir(root) / 'candidate.bin'
    want_sha = info['sha256']

    session = _new_session(root, 'write')
    _write_json(session / 'request.json', dict(
        partition=PARTITION, target=info['target'], candidate_sha256=want_sha,
        identity=identity, created_epoch=time.time()))

    say('正在完整读取当前分区（写入前留一份现场）…')
    snapshot = read_partition(camera, session / 'preimage.bin')
    if snapshot['bytes'] != PARTITION_BYTES:
        raise ValueError(f'分区读取不完整（{snapshot["bytes"]:,} 字节），已停止，没有写入')
    _write_json(session / 'intent.json', dict(
        partition=PARTITION, preimage_sha256=snapshot['sha256'], target=info['target'],
        target_sha256=want_sha, identity=identity, created_epoch=time.time()))

    if snapshot['sha256'] == want_sha:
        _write_json(session / 'result.json', dict(
            pass_=True, write_attempted=False, already_at_target=True,
            target_sha256=want_sha))
        return dict(directory=session, state='ALREADY_AT_TARGET_NO_WRITE')

    say('正在写入整分区…')
    _write_json(session / 'write_attempt.json', dict(
        target_sha256=want_sha, started_epoch=time.time()))
    camera.writeFile(PARTITION, candidate_path.read_bytes())

    say('正在回读校验…')
    back = read_partition(camera, session / 'readback.bin')
    ok = back['bytes'] == PARTITION_BYTES and back['sha256'] == want_sha
    _write_json(session / 'result.json', dict(
        pass_=ok, write_attempted=True, target_sha256=want_sha,
        readback_sha256=back['sha256'], readback_bytes=back['bytes']))
    if not ok:
        raise ValueError('写入后回读与目标镜像不一致，已停止；请保留会话目录')
    return dict(directory=session, state='SAVED_AND_READBACK_VERIFIED')


def restore(camera, identity: dict, root: Path, progress=None) -> dict:
    """Write the first recorded preimage back. Requires a complete baseline."""
    say = progress or (lambda _message: None)
    baseline = baseline_path(root)
    record = baseline.with_suffix('.json')
    if not baseline.exists() or not record.exists():
        raise ValueError('还没有初始备份，无法恢复。请先完成一次部署。')
    meta = json.loads(record.read_text(encoding='utf-8'))
    if file_sha256(baseline) != meta.get('sha256'):
        raise ValueError('初始备份文件已损坏，恢复已停止')
    blob = baseline.read_bytes()
    sanity(blob)

    session = _new_session(root, 'restore')
    _write_json(session / 'request.json', dict(
        partition=PARTITION, target_sha256=meta['sha256'], identity=identity,
        source=meta.get('from_session'), created_epoch=time.time()))

    say('正在完整读取当前分区（回滚前也会留一份）…')
    snapshot = read_partition(camera, session / 'preimage.bin')
    if snapshot['bytes'] != PARTITION_BYTES:
        raise ValueError('当前分区读取不完整，已停止，没有写入')
    _write_json(session / 'intent.json', dict(
        partition=PARTITION, preimage_sha256=snapshot['sha256'],
        target_sha256=meta['sha256'], identity=identity, created_epoch=time.time()))

    if snapshot['sha256'] == meta['sha256']:
        _write_json(session / 'result.json', dict(
            pass_=True, write_attempted=False, already_at_target=True,
            target_sha256=meta['sha256']))
        return dict(directory=session, state='ALREADY_AT_TARGET_NO_WRITE')

    say('正在写回初始备份…')
    _write_json(session / 'write_attempt.json', dict(target_sha256=meta['sha256'],
                                                     started_epoch=time.time()))
    camera.writeFile(PARTITION, blob)
    back = read_partition(camera, session / 'readback.bin')
    ok = back['bytes'] == PARTITION_BYTES and back['sha256'] == meta['sha256']
    _write_json(session / 'result.json', dict(
        pass_=ok, write_attempted=True, target_sha256=meta['sha256'],
        readback_sha256=back['sha256'], readback_bytes=back['bytes']))
    if not ok:
        raise ValueError('恢复后回读与备份不一致，已停止；请保留会话目录')
    return dict(directory=session, state='SAVED_AND_READBACK_VERIFIED')


def baseline_info(root: Path) -> dict | None:
    baseline = baseline_path(root)
    record = baseline.with_suffix('.json')
    if not baseline.exists() or not record.exists():
        return None
    try:
        meta = json.loads(record.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if file_sha256(baseline) != meta.get('sha256'):
        return None
    return meta
