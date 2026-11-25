"""Generate V7.1 four-slot assets from frozen V7 three-slot assets (PC only)."""
import argparse
import hashlib
import json
from pathlib import Path
from make_burst_wps import decode_sds, encode_exact, write_wav
from pack_wps import build_package

def build(source, output):
    source, output = Path(source), Path(output)
    if output.exists():
        raise FileExistsError(output)
    slots = [(source / f'WPS{i}.pcm').read_bytes() for i in (1, 2, 3)]
    pcm = decode_sds(slots[0])[:1600] * 6
    if len(pcm) != 9600:
        raise ValueError('WPS1 is too short')
    slots.append(encode_exact(pcm, 310))
    package = build_package(slots)
    report = dict(version=2, package_bytes=len(package), source=str(source),
                  original_three_encoded_bytes_preserved=True, wps4_prefix_samples=1600,
                  wps4_repetitions=6, wps4_active_samples=9600, wps4_padding_samples=10,
                  wps4_app_id=0x32, repeat_interval_us=400000, camera_access=False,
                  acoustic_result='USER_TEST_PENDING', shared_native_resource='WiFi toggle off APP0x32', slots=[])
    card = output / 'CARD/PRIVATE/A9FL'
    card.mkdir(parents=True)
    (card / 'WPS.A9W').write_bytes(package)
    for i, raw in enumerate(slots, 1):
        (output / f'WPS{i}.pcm').write_bytes(raw)
        write_wav(output / f'WPS{i}_preview.wav', decode_sds(raw))
        report['slots'].append(dict(slot=i, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    (output / 'conversion.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    (output / 'README.md').write_text(
        'V7.1 four-slot package. WPS1/2/3 preserve frozen V7 encoded bytes. '
        'WPS4 repeats WPS1 decoded first1600 samples six times, pads10 to310 SDS frames; '
        '400000us scheduler interval. APP0x32 shares native WiFi-off sound via RAM bind only. '
        'Callback/padding latency and acoustic continuity require camera acceptance. '
        'WPS*.pcm contains encoded Sony SDS, previews decode final SDS. No device access.\n', encoding='utf-8')
    (output / 'SHA256SUMS').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(output).as_posix()+'\n'
        for p in sorted(output.rglob('*')) if p.is_file()), encoding='utf-8')
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.out)))
