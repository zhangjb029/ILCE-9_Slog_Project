"""Whole-partition menu deployment: dump the live partition, patch it in memory, write it back.

No image is shipped. The tool reads the camera's own /dev/nflasha15, checks it
is byte-identical to the factory build, applies the 677 bytes that were
confirmed working on hardware, verifies the result against the known candidate
hash, and only then writes. Both ends of the change are pinned by SHA256, so a
partition in any other state is refused rather than overwritten.

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
from pathlib import Path

from . import journal

PARTITION = '/dev/nflasha15'
PARTITION_BYTES = 314572800
PFUNC_FILE_CONTROL = 0xFF01
FILE_WRITE = 1
FILE_READ = 2
READ_EXTRA = frozenset({'/setting/updater/dat4', '/setting/updater/COMP'})
TRANSFER_TIMEOUT_SECONDS = 900

# The state every ILCE-9 at 6.00 leaves the factory in. Verified on hardware:
# the live partition was byte-identical to the official firmware's nflasha15,
# and this hash is what the successful deployment recorded as its preimage.
FACTORY_SHA = 'ed835ff938e5d9d816b611263d1e124c08eb907a883d08587170bdbd7c32f9d2'
# The result the user deployed and confirmed: creative-style entry, PP, S-Log
# Display Assist, four aspect ratios.
CANDIDATE_SHA = '4fa7bbe5c9cc21661c334fa5640af59a5d725f2214ee877112230c123f2eafa4'

# (offset, factory bytes, candidate bytes) — 29 runs, 677 bytes total.
PATCHES = (
    (36611128, '87e0', '56fc'),
    (70594444, 'f7f71afd', '38f01cf7'),
    (75038752, '80b500af', '622909d0'),
    (75038758, '00f24281dfe811f0610063006500670069006b006d006f0071007300750077', '0ad80ff2180303eb410318785b78136070470320106070471420704700bf01'),
    (75038790, '79', '02'),
    (75038792, '7b', '03'),
    (75038794, '97', '04'),
    (75038796, 'b3', '05'),
    (75038798, 'cf', '06'),
    (75038800, 'eb', '07'),
    (75038802, '09017d', '080009'),
    (75038806, '7f', '0a'),
    (75038808, '81', '0b'),
    (75038810, '83', '0c'),
    (75038812, '85', '0d'),
    (75038814, '870089008b008d008f009100930095009b009d009f00a100a300a500a700a900ab00ad00af00b1009900b900bb00bd00bf00c100c300c500c700c900cb00cd00b500b700dd00df00e100e300e500e700e900d100d300d500d700d900db00fd00ff000101030105010701ed00ef00f100f300f500f700fb0038013c010d011101150119011d012101240128012c01300134010023aae00023ace00023aee00023b0e00023b2e000238ae00023b5e00023b7e00023b9e00023bbe00023bde00023bfe00023c1e001238ce00120a2e0012390e0012392e0012394e0012396e001236ee0012399e001239be001239de001239fe00123a1e00123a3e00123a5e0022370e0022372e0022084e0022376e0022378e002237ae0022352e002237de002237fe0022381e0022383e0022385e0022387', '0001000200030004000500060101020103010401050106010701080109010a010b010c010d01020203020402050206020702080209020a020b020c020d02010203030403050306030703080309030a030b030c030d03010302030704080409040a040b040c040d04010402040304040405040604080509050a050b050c050d0501050205030504050505060507050c060d060106020603060406050606060706080609060a060b0600bf2de9ff50164696b3706813282fd1b06861282cd1306850b3c02700204ff48051032222234ff0ff34002500df10f5805f1dd2e0b105463168be2251f8043b40f8043b013af9d1316850310a2251f8043b40f8043b013af9d16221c5f800130649c5f804133560bff35b8f14217160bde8ff50c5f5a7ba00bf56fc04022de90f50d4f8580105f796'),
    (75039120, '022389e0032354e0032356e0032358e0032066e003235ce003235ee0', '622805d10120b8604ff0ff3078603860bde80f50bb68214600f0abba'),
    (75039149, '2336e0', '2909d1'),
    (75039153, '2361e0032363e0032365e0032367e0032369e003236be003236de0042338e004233ae004233ce004233ee0042048e0042342e004231ae0042345e0042347e0042349e004234be004234de004234fe0042351e005231ce005231ee0052320e0052322e0052324e005202ae005231360062080bd052327e0052329e005232be005232de005232fe0052331e0052333e0062313', '2a07d108b5d0f85801612104f736e2622008bd00f076b8f0b581b0bef7faf5054600a41e4be41a1e4b1b199d4240f03380bef741f578b30746d7f8f063d7f8d4744eb347b369680a685268d36a5b681869b04240f00f8008694068806840680068b84240f007801068406800698068042800f011801e610b695b689b685b681f60126852681269074be35845f26c601b1853'),
    (75039300, '002080bd06231360012080bd06231360022080bd06231360032080bd06231360042080bd06231360052080bd0620106080bd06231360072080bd06231360082080bd06231360092080bd062313600a2080bd062313600b2080bd062313600c2080bd062313600d2080bd142080bd', '04239360284601b0f0bd00bfd42965001c1da700ac3b950000bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf00bf'),
    (75039411, '00', 'bf'),
    (75040510, 'bb682146', 'fff741bd'),
    (75045076, 'ef', '6b'),
    (75045292, '01', 'fe'),
    (75045294, '44e7', 'acfb'),
    (75047248, 'b1', '2d'),
    (141296518, 'ffff0000', '0180f93d'),
    (141625620, '00000000000000000000000000000000', '56fc041ee5a48de58fa4e8a1a3e6a9b1'),
    (192980996, '14', '28'),
)

LABEL = 'PP / S-Log / 四比例菜单 + 复古衣橱'


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


def build_candidate(dump: bytes) -> bytes:
    """Turn a factory partition into the confirmed candidate, in memory.

    Both the input and the output are pinned by SHA256, so an unexpected
    partition never reaches the camera.
    """
    sanity(dump)
    actual = hashlib.sha256(dump).hexdigest()
    if actual == CANDIDATE_SHA:
        raise ValueError('分区已经是目标版本，不需要修改')
    if actual != FACTORY_SHA:
        raise ValueError(
            '相机上的分区不是原厂状态（SHA256 %s…），本工具只处理原厂分区，已停止' % actual[:16])
    patched = bytearray(dump)
    for offset, before_hex, after_hex in PATCHES:
        before, after = bytes.fromhex(before_hex), bytes.fromhex(after_hex)
        if len(before) != len(after):
            raise ValueError('内置补丁长度不一致')
        if patched[offset:offset + len(before)] != before:
            raise ValueError(f'偏移 {offset} 的原始字节与预期不符，补丁不适用')
        patched[offset:offset + len(after)] = after
    result = bytes(patched)
    if hashlib.sha256(result).hexdigest() != CANDIDATE_SHA:
        raise ValueError('打补丁后的哈希与已验证的候选镜像不符，已停止')
    return result


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


def deploy(camera, identity: dict, root: Path, progress=None) -> dict:
    """Back up completely, derive the candidate from it, write once, verify."""
    say = progress or (lambda _message: None)

    session = _new_session(root, 'deploy')
    _write_json(session / 'request.json', dict(
        partition=PARTITION, factory_sha256=FACTORY_SHA, candidate_sha256=CANDIDATE_SHA,
        identity=identity, created_epoch=time.time()))

    say('正在完整读取当前分区（约 300 MB，需要几分钟）…')
    snapshot = read_partition(camera, session / 'preimage.bin')
    _write_json(session / 'preimage.json', snapshot)
    if snapshot['bytes'] != PARTITION_BYTES:
        _write_json(session / 'failure.json', dict(
            stage='read_preimage', write_attempted=False,
            error='分区读取不完整', preimage_bytes=snapshot['bytes']))
        raise ValueError(f'分区读取不完整（{snapshot["bytes"]:,} 字节），已停止，没有写入')

    _write_json(session / 'intent.json', dict(
        partition=PARTITION, preimage_sha256=snapshot['sha256'],
        target_sha256=CANDIDATE_SHA, identity=identity, created_epoch=time.time()))
    _save_baseline_once(Path(root), session)
    say(f'原分区已保存：{session / "preimage.bin"}')

    if snapshot['sha256'] == CANDIDATE_SHA:
        _write_json(session / 'result.json', dict(
            pass_=True, write_attempted=False, already_at_target=True,
            target_sha256=CANDIDATE_SHA, completed_epoch=time.time()))
        return dict(directory=session, state='ALREADY_AT_TARGET_NO_WRITE')

    say('正在本地打补丁并校验…')
    candidate = build_candidate((session / 'preimage.bin').read_bytes())
    _write_json(session / 'candidate.json', dict(
        sha256=hashlib.sha256(candidate).hexdigest(), patches=len(PATCHES)))

    say('正在写入整分区…')
    _write_json(session / 'write_attempt.json', dict(
        target_sha256=CANDIDATE_SHA, started_epoch=time.time()))
    camera.writeFile(PARTITION, candidate)
    del candidate

    say('正在回读校验…')
    back = read_partition(camera, session / 'readback.bin')
    ok = back['bytes'] == PARTITION_BYTES and back['sha256'] == CANDIDATE_SHA
    _write_json(session / 'result.json', dict(
        pass_=ok, write_attempted=True, target_sha256=CANDIDATE_SHA,
        readback_sha256=back['sha256'], readback_bytes=back['bytes'],
        completed_epoch=time.time()))
    if not ok:
        raise ValueError('写入后回读与候选镜像不一致，已停止；请保留会话目录')
    return dict(directory=session, state='SAVED_AND_READBACK_VERIFIED')


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
