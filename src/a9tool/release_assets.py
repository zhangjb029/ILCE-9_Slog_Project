"""Pinned, standalone released artifacts; importing this module never imports USB."""
import hashlib
import json
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'data' / 'releases'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def asset(name):
    path = (ROOT / name).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise ValueError('Release asset path escaped package')
    meta = json.loads((ROOT / 'assets.json').read_text(encoding='utf-8'))
    row = meta['files'].get(path.relative_to(ROOT.resolve()).as_posix())
    raw = path.read_bytes()
    if not row or len(raw) != row['bytes'] or sha(raw) != row['sha256']:
        raise ValueError('Release asset checksum differs: ' + name)
    return raw


def verify():
    meta = json.loads((ROOT / 'assets.json').read_text(encoding='utf-8'))
    for name in meta['files']:
        asset(name)
    return dict(state='RELEASE_ASSETS_VERIFIED', files=len(meta['files']),
                bytes=sum(x['bytes'] for x in meta['files'].values()))


def r15(manifest=None):
    raw = asset('r15/manifest.json')
    if manifest is not None and Path(manifest).read_bytes() != raw:
        raise ValueError('Unsupported R15 release manifest')
    return json.loads(raw)


def v7():
    # The released installer is pure Python and imports USB only in its CLI
    # connect_runtime function; actions below use the application's shared handle.
    raw=asset('v7/deploy.py')
    module=types.ModuleType('a9_released_v7')
    module.__file__=str(ROOT/'v7/deploy.py')
    exec(compile(raw,module.__file__,'exec'),module.__dict__)
    return module
