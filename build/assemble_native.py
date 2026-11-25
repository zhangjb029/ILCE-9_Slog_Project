"""Package the native release and source without copying device sessions."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def assemble(output):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('Choose a new release directory: '+str(output))
    check = (ROOT/'dist/selfcheck.txt').read_text(encoding='utf-8-sig')
    for token in ('version: 1.9.1', 'baseline: v1.8.2 / native Windows USB',
                  'R15NH: read -> identify -> patch -> write; FF01 full partition',
                  'V8: canonical and pinned RX extent variant; R15NH/CFG/LUT required',
                  'release assets:', 'gui: 77-row table, 6 tabs', 'SELFCHECK_OK'):
        if token not in check:
            raise ValueError('Final frozen selfcheck missing: '+token)
    output.mkdir(parents=True)
    folder = output/'A9Tool-1.9.1-Windows-native'
    folder.mkdir()
    for source, dest in (
        (ROOT/'dist/ILCE-9_Slog_Project.exe', folder/'ILCE-9_Slog_Project.exe'),
        (ROOT/'README.md', folder/'README.md'),
        (ROOT/'LICENSE', folder/'licenses/A9Tool-LICENSE.txt'),
        (ROOT/'NOTICE', folder/'licenses/NOTICE.txt'),
        (ROOT/'src/data/releases/NOTICE.md', folder/'licenses/Firmware-NOTICE.md'),
        (ROOT/'src/data/releases/LICENSE-PolyForm-Noncommercial.txt', folder/'licenses/PolyForm-Noncommercial.txt'),
        (ROOT/'dist/selfcheck.txt', folder/'verification/frozen-selfcheck.txt'),
    ):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    shutil.copytree(ROOT/'docs', folder/'docs')
    # The original check stays local; the public copy omits the operator path.
    check='\n'.join('sessions root: <application>/sessions' if line.startswith('sessions root:') else line
                    for line in check.splitlines())+'\n'
    (folder/'verification/frozen-selfcheck.txt').write_text(check,encoding='utf-8')
    (folder/'README.txt').write_text(
        'A9 Slog Project 1.9.1 — Windows native\n'
        'Based on released v1.8.2. Run ILCE-9_Slog_Project.exe.\n'
        'R15NH: read nflasha15, identify, patch locally, then write over FF01.\n'
        'No complete partition image is bundled. V8 requires R15NH.\n'
        'V8 accepts the canonical menu library and the exact known RX extent variant.\n'
        'Read README.md and the built-in operating instructions.\n'
        'Keep sessions beside the executable. This installer needs hardware acceptance.\n', encoding='utf-8')
    files = {p.relative_to(folder).as_posix(): dict(bytes=p.stat().st_size, sha256=sha(p))
             for p in sorted(folder.rglob('*')) if p.is_file()}
    manifest = dict(schema='a9-native-distribution-v1', version='1.9.1', baseline='v1.8.2',
        baseline_commit='975f21e76c28ed82905438d35b4a86c1a49bf4b0',
        native_windows_usb=True, wsl_required=False, hardware_verified=False, files=files)
    (folder/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    release_zip = output/(folder.name+'.zip')
    with zipfile.ZipFile(release_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob('*')):
            if path.is_file():
                archive.write(path, folder.name+'/'+path.relative_to(folder).as_posix())
    source_zip = output/'A9_Slog_Project-1.9.1-source.zip'
    with zipfile.ZipFile(source_zip, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in ('src', 'tests', 'docs', 'build', 'filters', '.github'):
            for path in sorted((ROOT/name).rglob('*')):
                if not path.is_file() or '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
                    continue
                relative = path.relative_to(ROOT)
                if name == 'build' and len(relative.parts) > 2 and relative.parts[1] != 'hooks':
                    continue
                archive.write(path, 'A9_Slog_Project-1.9.1/'+relative.as_posix())
        for name in ('README.md','README.en.md','README.zh-CN.md','pyproject.toml','LICENSE','NOTICE','.gitattributes','.gitignore'):
            if (ROOT/name).is_file():
                archive.write(ROOT/name, 'A9_Slog_Project-1.9.1/'+name)
    (output/'SHA256SUMS.txt').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in (release_zip, source_zip)), encoding='ascii')
    print(json.dumps(dict(distribution=str(folder), archive=str(release_zip), source=str(source_zip),
                         exe_sha256=sha(folder/'ILCE-9_Slog_Project.exe')), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    assemble(parser.parse_args().output)
