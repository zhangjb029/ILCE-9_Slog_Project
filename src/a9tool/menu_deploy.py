"""Whole-partition menu deployment to /dev/nflasha15.

This is not a parameter write. It replaces a 300 MiB partition image in one
transfer, which is a strictly bigger hammer than everything else in this tool:
a previous attempt with a different layout left the camera cold-starting with
no menu at all. The guard therefore permits exactly one write, to exactly one
path, of exactly one size, in one session.

Nothing here is validated on hardware by the author of this module. The images
themselves were deployed by the user and confirmed working; this code is the
same transfer shape wrapped in the app's backup-first discipline.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import time
import uuid
from pathlib import Path

from . import journal

PARTITION = '/dev/nflasha15'
PARTITION_BYTES = 314572800
PFUNC_FILE_CONTROL = 0xFF01
FILE_WRITE = 1
FILE_READ = 2
READ_EXTRA = frozenset({'/setting/updater/dat4', '/setting/updater/COMP'})
TRANSFER_TIMEOUT_SECONDS = 900

# The single image the user deployed and confirmed working: creative-style menu
# plus the in-place PP / S-Log / four-aspect replacement. Nothing else is
# accepted, so an arbitrary 300 MiB file cannot be written by mistake.
KNOWN_IMAGES = {
    '4fa7bbe5c9cc21661c334fa5640af59a5d725f2214ee877112230c123f2eafa4': 'menu_inplace',
}
IMAGE_LABELS = {
    'menu_inplace': 'PP / S-Log / 四比例菜单 + 复古衣橱',
}


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


def inspect_image(path: Path) -> dict:
    """Identify an image without touching the camera."""
    path = Path(path)
    if not path.exists():
        raise ValueError(f'镜像文件不存在：{path}')
    size = path.stat().st_size
    if size != PARTITION_BYTES:
        raise ValueError(f'镜像大小 {size:,} 字节，应为 {PARTITION_BYTES:,}')
    sha = file_sha256(path)
    kind = KNOWN_IMAGES.get(sha)
    if kind is None:
        raise ValueError('这个镜像的 SHA256 不是已实机验证的那一版，拒绝使用')
    return dict(path=path, sha256=sha, kind=kind, label=IMAGE_LABELS[kind], bytes=size)


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


def _new_session(root: Path, label: str) -> Path:
    stamp = time.strftime('%Y%m%d_%H%M%S')
    folder = Path(root) / f'{label}_{stamp}_{uuid.uuid4().hex[:8]}'
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def _baseline_path(root: Path) -> Path:
    return Path(root) / 'baseline' / 'preimage.bin'


def _save_baseline_once(root: Path, session: Path) -> Path:
    """The first full preimage is what the restore button writes back."""
    target = _baseline_path(root)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        with (session / 'preimage.bin').open('rb') as source:
            while True:
                chunk = source.read(1 << 20)
                if not chunk:
                    break
                stream.write(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    _write_json(target.with_suffix('.json'), dict(sha256=file_sha256(target),
                                                  bytes=target.stat().st_size,
                                                  from_session=session.name))
    return target


def deploy(camera, identity: dict, image_path: Path, root: Path, progress=None) -> dict:
    """Back up the live partition completely, then write the image once."""
    say = progress or (lambda _message: None)
    image = inspect_image(image_path)
    target_sha = image['sha256']

    session = _new_session(root, 'deploy')
    _write_json(session / 'request.json', dict(
        partition=PARTITION, target_sha256=target_sha, kind=image['kind'],
        identity=identity, created_epoch=time.time()))

    say('正在完整读取当前分区（约 300 MB，需要一段时间）…')
    snapshot = read_partition(camera, session / 'preimage.bin')
    _write_json(session / 'preimage.json', snapshot)
    if snapshot['bytes'] != PARTITION_BYTES:
        _write_json(session / 'failure.json', dict(
            stage='read_preimage', write_attempted=False,
            error='分区读取不完整', preimage_bytes=snapshot['bytes']))
        raise ValueError(f'分区读取不完整（{snapshot["bytes"]:,} 字节），已停止，没有写入')

    _write_json(session / 'intent.json', dict(
        partition=PARTITION, preimage_sha256=snapshot['sha256'], target_sha256=target_sha,
        identity=identity, created_epoch=time.time()))
    _save_baseline_once(Path(root), session)
    say(f'原分区已保存：{session / "preimage.bin"}')

    if snapshot['sha256'] == target_sha:
        _write_json(session / 'result.json', dict(
            pass_=True, write_attempted=False, already_at_target=True,
            target_sha256=target_sha, completed_epoch=time.time()))
        return dict(directory=session, state='ALREADY_AT_TARGET_NO_WRITE', image=image)

    say('正在写入整分区…')
    _write_json(session / 'write_attempt.json', dict(
        target_sha256=target_sha, started_epoch=time.time()))
    camera.writeFile(PARTITION, Path(image_path).read_bytes())

    say('正在回读校验…')
    back = read_partition(camera, session / 'readback.bin')
    ok = back['bytes'] == PARTITION_BYTES and back['sha256'] == target_sha
    _write_json(session / 'result.json', dict(
        pass_=ok, write_attempted=True, target_sha256=target_sha,
        readback_sha256=back['sha256'], readback_bytes=back['bytes'],
        completed_epoch=time.time()))
    if not ok:
        raise ValueError('写入后回读与镜像不一致，已停止；请保留会话目录')
    return dict(directory=session, state='SAVED_AND_READBACK_VERIFIED', image=image)


def restore(camera, identity: dict, root: Path, progress=None) -> dict:
    """Write the first recorded preimage back. Requires a complete baseline."""
    say = progress or (lambda _message: None)
    baseline = _baseline_path(root)
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
    baseline = _baseline_path(root)
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
