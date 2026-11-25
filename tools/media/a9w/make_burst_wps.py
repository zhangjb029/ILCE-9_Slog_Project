"""Make V6.1 burst WPS assets from an already encoded WPS1 (PC only).

SINGLE preserves WPS1. LOOPL repeats its first 0.2 s six times; LOOPH
repeats its first 0.1 s seven times. The fixed Sony slots require padding.
This tool never runs ffmpeg, accesses a camera, or changes an existing output.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import wave

from pack_wps import build_package, SLOT_BYTES

SAMPLE_RATE = 24000
SAMPLES_PER_FRAME = 31
SLOT_FRAMES = tuple(size // 32 for size in SLOT_BYTES[:3])


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode_sds(raw):
    """Decode Sony mode0/mode1 32-byte SDS frames, preserving predictor state."""
    if not raw or len(raw) % 32:
        raise ValueError('SDS must be a nonempty multiple of 32 bytes')
    samples = []
    previous = 0
    for at in range(0, len(raw), 32):
        mode, shift = raw[at] >> 4, raw[at] & 15
        if mode not in (0, 1) or shift > 8:
            raise ValueError(f'Invalid Sony SDS frame header at byte {at}')
        for value in raw[at+1:at+32]:
            quantized = value if value < 128 else value - 256
            predictor = 0 if mode == 0 else int(previous * 15 / 16)
            previous = max(-32768, min(32767, predictor + (quantized << shift)))
            samples.append(previous)
    return samples


def repeat_prefix(samples, prefix_samples, repetitions):
    if prefix_samples <= 0 or repetitions <= 0 or len(samples) < prefix_samples:
        raise ValueError('Source is too short or repeat dimensions are invalid')
    return list(samples[:prefix_samples]) * repetitions


def encode_exact(samples, total_frames):
    """Encode without trim, normalization or fade; zero-pad the fixed slot.

    The frame search and quantization are adapted from the pinned upstream
    tools/encode_sony_sds_adpcm.py. Its public encoder always normalizes and
    trims trailing silence, so its preprocessing cannot be used here.
    """
    work = list(samples)
    if total_frames <= 0 or len(work) > total_frames * SAMPLES_PER_FRAME:
        raise ValueError('PCM samples exceed the fixed SDS slot')
    if any(not isinstance(value, int) or value < -32768 or value > 32767 for value in work):
        raise ValueError('PCM samples must be signed 16-bit integers')
    work += [0] * (total_frames * SAMPLES_PER_FRAME - len(work))
    encoded = bytearray()
    previous = 0
    for frame in range(total_frames):
        chunk = work[frame*SAMPLES_PER_FRAME:(frame+1)*SAMPLES_PER_FRAME]
        if not any(chunk) and previous == 0:
            encoded.extend(bytes(32))
            continue
        best = None
        for mode in (0, 1):
            for shift in range(9):
                p = previous
                error = 0
                candidate = bytearray([(mode << 4) | shift])
                for target in chunk:
                    predictor = 0 if mode == 0 else int(p * 15 / 16)
                    delta = target - predictor
                    quantized = max(-128, min(127, int(round(delta / float(1 << shift)))))
                    reconstructed = max(-32768, min(32767, predictor + (quantized << shift)))
                    error += (target - reconstructed) ** 2
                    candidate.append(quantized & 255)
                    p = reconstructed
                if best is None or error < best[0]:
                    best = (error, candidate, p)
        encoded.extend(best[1])
        previous = best[2]
    return bytes(encoded)


def write_wav(path, samples):
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, SAMPLE_RATE, 0, 'NONE', 'not compressed'))
        output.writeframes(struct.pack(f'<{len(samples)}h', *samples))


def build(wps1, output):
    """Create an exclusive folder with card package, SDS files and previews."""
    source, folder = Path(wps1), Path(output)
    if folder.exists() or folder.is_symlink():
        raise FileExistsError(f'Refusing to overwrite {folder}')
    raw = source.read_bytes()
    if len(raw) != SLOT_BYTES[0]:
        raise ValueError(f'WPS1 requires exactly {SLOT_BYTES[0]} Sony SDS bytes')
    original = decode_sds(raw)
    low = repeat_prefix(original, 4800, 6)
    high = repeat_prefix(original, 2400, 7)
    slots = (raw, encode_exact(low, SLOT_FRAMES[1]), encode_exact(high, SLOT_FRAMES[2]))
    package = build_package(slots)
    report = dict(
        source_name=source.name, wps1_sha256=sha(raw), package_version=1,
        package_bytes=len(package), package_sha256=sha(package), mask=7,
        sample_rate=SAMPLE_RATE, channels=1, trim=False, normalize=False,
        fade=False, wps1_unchanged=True, camera_access=False,
        acoustic_result='USER_TEST_PENDING',
        limitation='UI callback cadence and native request latency can expose padding or shift a restart; acoustic continuity requires camera testing.',
        slots=[],
    )
    for index, (encoded, pcm, repetitions, prefix, interval) in enumerate((
        (slots[0], original, 1, len(original), None),
        (slots[1], low, 6, 4800, 1200000),
        (slots[2], high, 7, 2400, 700000),
    )):
        physical_samples = len(encoded) // 32 * SAMPLES_PER_FRAME
        report['slots'].append(dict(
            slot=index+1, app_id=0x33+index, bytes=len(encoded), sha256=sha(encoded),
            prefix_samples=prefix, repetitions=repetitions, active_samples=len(pcm),
            padded_samples=physical_samples-len(pcm), physical_samples=physical_samples,
            active_seconds=len(pcm)/SAMPLE_RATE, physical_seconds=physical_samples/SAMPLE_RATE,
            repeat_interval_us=interval,
            pcm_target_sha256=sha(struct.pack(f'<{len(pcm)}h', *pcm)),
        ))
    # All source validation and encoding finish before creating the output.
    folder.mkdir(parents=True, exist_ok=False)
    card = folder / 'CARD/PRIVATE/A9FL'
    card.mkdir(parents=True)
    (card / 'WPS.A9W').write_bytes(package)
    for index, encoded in enumerate(slots, 1):
        (folder / f'WPS{index}.pcm').write_bytes(encoded)
        write_wav(folder / f'WPS{index}_preview.wav', decode_sds(encoded))
    (folder / 'conversion.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    (folder / 'README.md').write_text(
        'V6.1 连拍音资源。WPS1 保持输入编码字节；WPS2 为其前0.2秒重复6次（1.2秒），'
        'WPS3 为其前0.1秒重复7次（0.7秒）。两者均从解码PCM重新编码，没有裁前导、归一化或淡出。'
        '原固定槽另需补30样本（1.25ms）和1180样本（49.1667ms）静音目标。'
        'WPS*_preview.wav是最终SDS反解，含实际填充；调度器应分别于1.2/0.7秒重播，回调延迟仍可能暴露填充。'
        'WPS*.pcm是Sony SDS编码，不是裸PCM。写卡使用CARD/PRIVATE/A9FL/WPS.A9W，'
        '在浮层OFF时导入并完整重启。音频信号设为开：除电子快门以外。听感与接缝待实机。\n',
        encoding='utf-8',
    )
    (folder / 'SHA256SUMS').write_text(''.join(
        sha(path.read_bytes())+'  '+path.relative_to(folder).as_posix()+'\n'
        for path in sorted(folder.rglob('*')) if path.is_file()
    ), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wps1', type=Path, required=True, help='Existing 24768-byte Sony SDS WPS1')
    parser.add_argument('--out', type=Path, required=True, help='New output folder (must not exist)')
    args = parser.parse_args()
    try:
        report = build(args.wps1, args.out)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(dict(state='BURST_WPS_READY', output=str(args.out), **report), ensure_ascii=False))


if __name__ == '__main__':
    main()
