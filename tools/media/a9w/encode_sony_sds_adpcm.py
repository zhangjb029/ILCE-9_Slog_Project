#!/usr/bin/env python3
"""Convert an audio file (MP3/WAV/M4A) into Sony 24 kHz 32-byte SDS ADPCM (.pcm) for A6400/A6100."""
import argparse
import hashlib
import math
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

SAMPLE_RATE = 24000
SAMPLES_PER_FRAME = 31

SLOT_SPECS = {
    "shutter": ("a6400-charo-shutter.pcm", 930),  # 0x34 Dslr_Emnt_WPS_PBC.bin (29,760 B, ~1.20s)
    "connect": ("a6400-charo-connect.pcm", 774),  # 0x33 Dslr_Emnt_WPS_Connect.bin (24,768 B, ~1.00s)
    "push": ("a6400-charo-push.pcm", 580),        # 0x35 Dslr_Emnt_WPS_Push.bin (18,560 B, ~0.75s)
    "sd": ("CHARO.PCM", 930),                     # SD card override A:/A6400/CHARO.PCM (29,760 B)
}


def decode_to_24k_mono_pcm16(input_path):
    """Decode any audio file to 24 kHz mono 16-bit signed LE samples."""
    src = Path(input_path)
    if not src.is_file():
        raise FileNotFoundError(f"Audio file not found: {src}")

    if src.suffix.lower() == ".wav":
        try:
            with wave.open(str(src), "rb") as wf:
                if (wf.getnchannels(), wf.getsampwidth(), wf.getframerate()) == (1, 2, SAMPLE_RATE):
                    raw = wf.readframes(wf.getnframes())
                    return list(struct.unpack(f"<{len(raw) // 2}h", raw))
        except wave.Error:
            pass

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tmp_wav = Path(tf.name)
    try:
        ffmpeg = shutil.which("ffmpeg")
        afconvert = "/usr/bin/afconvert"
        if ffmpeg:
            subprocess.check_call(
                [ffmpeg, "-y", "-i", str(src), "-ac", "1", "-ar", str(SAMPLE_RATE), "-sample_fmt", "s16", str(tmp_wav)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif Path(afconvert).is_file():
            subprocess.check_call(
                [afconvert, "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", "-c", "1", str(src), str(tmp_wav)]
            )
        else:
            raise RuntimeError(
                "Need ffmpeg (or macOS afconvert) to convert non-24kHz-mono-WAV inputs. "
                "Install ffmpeg: Windows `winget install Gyan.FFmpeg`, Ubuntu/WSL2 `sudo apt install ffmpeg`, macOS `brew install ffmpeg`."
            )
        with wave.open(str(tmp_wav), "rb") as wf:
            if (wf.getnchannels(), wf.getsampwidth(), wf.getframerate()) != (1, 2, SAMPLE_RATE):
                raise RuntimeError("Decoded WAV did not match 24 kHz mono 16-bit PCM")
            raw = wf.readframes(wf.getnframes())
            return list(struct.unpack(f"<{len(raw) // 2}h", raw))
    finally:
        tmp_wav.unlink(missing_ok=True)


def encode_samples_to_sds(
    samples,
    total_frames,
    trim_lead=True,
    tail_fade_ms=10,
    truncate=False,
):
    """Trim, normalize, and encode 24 kHz mono s16 samples into Sony 32-byte SDS ADPCM."""
    total_samples = total_frames * SAMPLES_PER_FRAME
    work = list(samples)
    if trim_lead:
        for i, s in enumerate(work):
            if abs(s) > 150:
                work = work[max(0, i - int(0.005 * SAMPLE_RATE)):]
                break

    peak = max((abs(s) for s in work), default=0)
    gain = 29000.0 / peak if peak > 0 else 1.0
    work = [max(-32767, min(32767, int(round(s * gain)))) for s in work]

    end_idx = len(work)
    for i in range(len(work) - 1, -1, -1):
        if abs(work[i]) > 80:
            end_idx = min(len(work), i + int(0.025 * SAMPLE_RATE))
            break
    active = work[:end_idx]

    if len(active) > total_samples:
        if not truncate:
            raise ValueError(
                f"Active audio too long for slot: {len(active) / SAMPLE_RATE:.3f}s ({len(active)} samples) "
                f"> max {total_samples / SAMPLE_RATE:.3f}s ({total_samples} samples). "
                "Trim the MP3 shorter or pass --truncate."
            )
        active = active[:total_samples]

    fade_len = int((tail_fade_ms / 1000.0) * SAMPLE_RATE)
    for i in range(fade_len):
        idx = len(active) - fade_len + i
        if 0 <= idx < len(active):
            active[idx] = int(round(active[idx] * (1.0 - (i + 1) / fade_len)))

    padded = active + [0] * (total_samples - len(active))
    encoded = bytearray()
    prev = 0
    sq_err = 0.0
    sig_sq = 0.0

    for f in range(total_frames):
        chunk = padded[f * SAMPLES_PER_FRAME : (f + 1) * SAMPLES_PER_FRAME]
        if all(x == 0 for x in chunk) and prev == 0:
            encoded.append(0x00)
            encoded.extend(b"\x00" * SAMPLES_PER_FRAME)
            continue
        best = None
        for mode in (0, 1):
            for sh in range(9):
                p = prev
                err = 0
                fbytes = bytearray([((mode << 4) | sh)])
                fdec = []
                for target in chunk:
                    pred = 0 if mode == 0 else int((p * 15) / 16)
                    diff = target - pred
                    step = 1 << sh
                    q = max(-128, min(127, int(round(diff / float(step)))))
                    rec = max(-32768, min(32767, pred + (q << sh)))
                    d = target - rec
                    err += d * d
                    fbytes.append(q & 0xFF)
                    fdec.append(rec)
                    p = rec
                if best is None or err < best[0]:
                    best = (err, fbytes, fdec, p)
        encoded.extend(best[1])
        prev = best[3]
        for t, r in zip(chunk, best[2]):
            sq_err += (t - r) ** 2
            sig_sq += t * t

    snr = 10.0 * math.log10(sig_sq / max(1e-9, sq_err))
    return bytes(encoded), {
        "active_samples": len(active),
        "active_sec": len(active) / SAMPLE_RATE,
        "frames": total_frames,
        "bytes": len(encoded),
        "snr_db": snr,
    }


def verify_sds_bytes(raw):
    """Verify Sony 32-byte SDS ADPCM frame headers and decode stats."""
    if len(raw) <= 0 or len(raw) % 32 != 0:
        raise ValueError(f"Invalid SDS ADPCM length: {len(raw)} (must be non-empty multiple of 32)")
    out = []
    prev = 0
    bad_hdr = 0
    for i in range(0, len(raw), 32):
        hdr = raw[i]
        mode = (hdr >> 4) & 0xF
        sh = hdr & 0xF
        if mode not in (0, 1) or sh > 8:
            bad_hdr += 1
        for j in range(1, 32):
            v = struct.unpack("b", bytes([raw[i + j]]))[0]
            pred = 0 if mode == 0 else int((prev * 15) / 16)
            s = max(-32768, min(32767, pred + (v << sh)))
            out.append(s)
            prev = s
    if bad_hdr != 0:
        raise ValueError(f"Found {bad_hdr} invalid Sony SDS frame headers")
    peak = max((abs(x) for x in out), default=0)
    return {"bytes": len(raw), "frames": len(raw) // 32, "bad_hdr": bad_hdr, "peak": peak}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_audio", help="Path to source MP3 / WAV / M4A file")
    parser.add_argument(
        "--slot",
        choices=sorted(SLOT_SPECS.keys()),
        default="shutter",
        help="Target slot: shutter (<=29760B), connect (<=24768B), push (<=18560B), or sd (CHARO.PCM)",
    )
    parser.add_argument("-o", "--out", default="", help="Output .pcm path (defaults to assets/<slot_filename>)")
    parser.add_argument("--no-trim-lead", action="store_true", help="Do not trim leading silence")
    parser.add_argument("--tail-fade-ms", type=int, default=10, help="Fade-out length in ms (default: 10)")
    parser.add_argument("--truncate", action="store_true", help="Truncate audio if longer than slot max duration")
    args = parser.parse_args()

    default_name, frames = SLOT_SPECS[args.slot]
    if args.out:
        out_path = Path(args.out)
    elif args.slot == "sd":
        out_path = Path(default_name)
    else:
        out_path = Path(__file__).resolve().parent.parent / "assets" / default_name

    samples = decode_to_24k_mono_pcm16(args.input_audio)
    encoded, enc_info = encode_samples_to_sds(
        samples,
        frames,
        trim_lead=not args.no_trim_lead,
        tail_fade_ms=args.tail_fade_ms,
        truncate=args.truncate,
    )
    ver_info = verify_sds_bytes(encoded)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(encoded)
    sha = hashlib.sha256(encoded).hexdigest()
    print(
        f"ENCODE_SDS_OK slot={args.slot} out={out_path} active={enc_info['active_sec']:.3f}s "
        f"bytes={ver_info['bytes']} frames={ver_info['frames']} bad_hdr={ver_info['bad_hdr']} "
        f"snr={enc_info['snr_db']:.2f}dB sha256={sha}"
    )


if __name__ == "__main__":
    main()
